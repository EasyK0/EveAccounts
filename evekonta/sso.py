"""Logowanie postaci przez EVE SSO (OAuth2 + PKCE).

Każdą postać logujesz raz. Aplikacja zapisuje (zaszyfrowany) refresh token
i potem sama odnawia dostęp, więc hasło do gry nie jest do tego potrzebne.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass

from .net import USER_AGENT, Transport, urllib_transport

AUTH_URL = "https://login.eveonline.com/v2/oauth/authorize"
TOKEN_URL = "https://login.eveonline.com/v2/oauth/token"

SCOPES = [
    "esi-skills.read_skills.v1",
    "esi-skills.read_skillqueue.v1",
    "esi-wallet.read_character_wallet.v1",
    "esi-assets.read_assets.v1",
    "esi-industry.read_character_jobs.v1",
    "esi-planets.manage_planets.v1",
    "esi-location.read_location.v1",
    "esi-universe.read_structures.v1",
]


class SsoError(Exception):
    pass


class InvalidToken(SsoError):
    """Refresh token odrzucony: postać trzeba zalogować ponownie."""


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str
    expires_at: float
    character_id: int
    character_name: str
    scopes: list[str]


def make_pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def redirect_uri(port: int) -> str:
    return f"http://localhost:{port}/callback"


def build_auth_url(client_id: str, port: int, state: str, challenge: str,
                   scopes: list[str] | None = None) -> str:
    query = {
        "response_type": "code",
        "redirect_uri": redirect_uri(port),
        "client_id": client_id,
        "scope": " ".join(SCOPES if scopes is None else scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(query)


@dataclass
class AppCheck:
    ok: bool
    error: str = ""            # kod błędu z SSO (invalid_client, invalid_scope, ...)
    description: str = ""
    rejected: list[str] | None = None  # uprawnienia odrzucone przez SSO


def _probe(client_id: str, port: int, scopes: list[str], transport: Transport) -> tuple[str, str]:
    """Pyta SSO o stronę logowania. Zwraca ("", "") gdy SSO akceptuje żądanie."""
    _, challenge = make_pkce()
    url = build_auth_url(client_id, port, "probe", challenge, scopes)
    resp = transport("GET", url, {"User-Agent": USER_AGENT, "Accept": "text/html,application/json"}, None)
    body = resp.body[:4000].decode("utf-8", "replace")
    data = None
    try:
        data = json.loads(body)
    except ValueError:
        pass
    if isinstance(data, dict) and data.get("error"):
        return str(data["error"]), str(data.get("error_description", ""))
    if resp.status >= 400:
        return f"http_{resp.status}", body[:200]
    return "", ""


def check_app(client_id: str, port: int, transport: Transport = urllib_transport) -> AppCheck:
    """Sprawdza konfigurację aplikacji na developers.eveonline.com bez logowania:
    poprawność Client ID, callback URL i które uprawnienia są włączone."""
    error, desc = _probe(client_id, port, SCOPES, transport)
    if not error:
        return AppCheck(True, rejected=[])
    if error != "invalid_scope":
        return AppCheck(False, error, desc)
    rejected = []
    for scope in SCOPES:
        err, d = _probe(client_id, port, [scope], transport)
        if err == "invalid_scope":
            rejected.append(scope)
        elif err:
            return AppCheck(False, err, d)
    return AppCheck(False, "invalid_scope", desc, rejected)


def explain_check(result: AppCheck, port: int) -> str:
    if result.ok:
        return "Aplikacja EVE jest ustawiona poprawnie. Możesz dodawać postacie."
    if result.error == "invalid_scope":
        lines = "\n".join(f"  • {s}" for s in result.rejected or [])
        return ("EVE odrzuca te uprawnienia (nie są zaznaczone w aplikacji z TYM Client ID):\n"
                f"{lines}\n\nNa developers.eveonline.com otwórz aplikację o dokładnie takim Client ID jak w "
                "Ustawieniach, zaznacz je i zapisz.")
    if result.error in ("invalid_client", "unauthorized_client"):
        return ("EVE nie zna tego Client ID. Skopiuj go jeszcze raz ze strony aplikacji "
                "(bez spacji na początku i końcu) i zapisz ustawienia.")
    if "redirect" in (result.error + result.description).lower():
        return (f"Callback URL w aplikacji EVE musi być dokładnie: {redirect_uri(port)}\n"
                f"(EVE zgłasza: {result.description or result.error})")
    return f"EVE zwraca błąd: {result.error} {result.description}".strip()


def decode_jwt(token: str) -> dict:
    """Odczyt danych z tokena (bez weryfikacji podpisu: token przychodzi
    bezpośrednio z serwera CCP po HTTPS)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError) as exc:
        raise SsoError("Nieprawidłowy token z SSO") from exc


def _token_set(data: dict, now: float) -> TokenSet:
    claims = decode_jwt(data["access_token"])
    sub = str(claims.get("sub", ""))
    if not sub.startswith("CHARACTER:EVE:"):
        raise SsoError("Token nie należy do postaci")
    scp = claims.get("scp", [])
    if isinstance(scp, str):
        scp = [scp]
    return TokenSet(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=now + float(data.get("expires_in", 1199)) - 60,
        character_id=int(sub.rsplit(":", 1)[1]),
        character_name=str(claims.get("name", "")),
        scopes=list(scp),
    )


def _post_token(form: dict, client_id: str, client_secret: str | None, transport: Transport) -> dict:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": USER_AGENT,
        "Host": "login.eveonline.com",
    }
    if client_secret:
        raw = f"{client_id}:{client_secret}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    else:
        form = {**form, "client_id": client_id}
    resp = transport("POST", TOKEN_URL, headers, urllib.parse.urlencode(form).encode())
    if resp.status == 400 or resp.status == 401:
        try:
            err = (resp.json() or {}).get("error", "")
        except ValueError:
            err = ""
        if err in ("invalid_grant", "invalid_token"):
            raise InvalidToken("Token unieważniony, zaloguj postać ponownie")
        raise SsoError(f"SSO odrzuciło żądanie ({resp.status} {err})")
    if resp.status >= 400:
        raise SsoError(f"SSO błąd {resp.status}")
    return resp.json()


def exchange_code(code: str, verifier: str, client_id: str, client_secret: str | None = None,
                  transport: Transport = urllib_transport, now: float | None = None) -> TokenSet:
    data = _post_token(
        {"grant_type": "authorization_code", "code": code, "code_verifier": verifier},
        client_id, client_secret, transport,
    )
    return _token_set(data, time.time() if now is None else now)


def refresh(refresh_token: str, client_id: str, client_secret: str | None = None,
            transport: Transport = urllib_transport, now: float | None = None) -> TokenSet:
    data = _post_token({"grant_type": "refresh_token", "refresh_token": refresh_token},
                       client_id, client_secret, transport)
    return _token_set(data, time.time() if now is None else now)


_DONE_PAGE = """<!doctype html><meta charset="utf-8"><title>EveKonta</title>
<body style="font-family:sans-serif;background:#111;color:#eee;padding:40px">
<h2>{msg}</h2><p>Możesz zamknąć tę kartę i wrócić do EveKonta.</p></body>"""


class CallbackServer:
    """Jednorazowy serwer na localhost, który odbiera kod z EVE SSO."""

    def __init__(self, port: int, state: str):
        self.state = state
        self.code: str | None = None
        self.error: str | None = None
        self._done = threading.Event()
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                qs = urllib.parse.parse_qs(parsed.query)
                if qs.get("state", [""])[0] != outer.state:
                    outer.error = "Zły parametr state (stare okno logowania?)"
                    msg = "Błąd logowania"
                elif "code" not in qs:
                    outer.error = qs.get("error", ["Brak kodu"])[0]
                    msg = "Logowanie anulowane"
                else:
                    outer.code = qs["code"][0]
                    msg = "Postać dodana"
                body = _DONE_PAGE.format(msg=msg).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                outer._done.set()

            def log_message(self, *args):
                pass

        self._server = http.server.HTTPServer(("127.0.0.1", port), Handler)
        self._server.timeout = 0.5
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._done.is_set():
            try:
                self._server.handle_request()
            except (OSError, ValueError):
                break

    def wait(self, timeout: float) -> str:
        finished = self._done.wait(timeout)
        self.close()
        if not finished:
            raise SsoError("Minął czas na zalogowanie")
        if self.error:
            raise SsoError(self.error)
        return self.code

    def close(self):
        self._done.set()
        try:
            self._server.server_close()
        except OSError:
            pass
