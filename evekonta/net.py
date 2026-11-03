"""HTTP client for ESI and EVE SSO (standard library only)."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from . import __version__

ESI_BASE = "https://esi.evetech.net"
ESI_COMPAT_DATE = "2025-09-30"
USER_AGENT = f"EveKonta/{__version__} (private multibox tool)"


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self):
        return json.loads(self.body.decode("utf-8")) if self.body else None


# transport(method, url, headers, body) -> Response
Transport = Callable[[str, str, dict, bytes | None], Response]


def urllib_transport(method: str, url: str, headers: dict, body: bytes | None) -> Response:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return Response(resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read())
    except urllib.error.HTTPError as exc:
        return Response(exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read())


class EsiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"ESI {status}: {message}")
        self.status = status


class EsiClient:
    """ESI calls with retries and error-limit tracking."""

    def __init__(self, transport: Transport = urllib_transport, *, sleep=time.sleep, base: str = ESI_BASE):
        self._transport = transport
        self._sleep = sleep
        self._base = base
        self._lock = threading.Lock()
        self._pause_until = 0.0

    def _wait_for_error_budget(self) -> None:
        with self._lock:
            delay = self._pause_until - time.monotonic()
        if delay > 0:
            self._sleep(delay)

    def request(self, method: str, path: str, *, token: str | None = None, params: dict | None = None,
                body=None) -> Response:
        url = self._base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "X-Compatibility-Date": ESI_COMPAT_DATE,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        last = None
        for attempt in range(4):
            self._wait_for_error_budget()
            resp = self._transport(method, url, headers, data)
            last = resp
            self._track_error_limit(resp)
            if resp.status < 400:
                return resp
            if resp.status in (420, 429) or resp.status >= 500:
                retry_after = _to_float(resp.headers.get("retry-after"), 2.0 * (attempt + 1))
                self._sleep(min(retry_after, 60.0))
                continue
            break
        raise EsiError(last.status, _error_text(last))

    def _track_error_limit(self, resp: Response) -> None:
        remain = resp.headers.get("x-esi-error-limit-remain")
        reset = resp.headers.get("x-esi-error-limit-reset")
        if remain is not None and reset is not None and _to_float(remain, 100) < 10:
            with self._lock:
                self._pause_until = max(self._pause_until, time.monotonic() + _to_float(reset, 10) + 1)

    def get(self, path: str, *, token: str | None = None, params: dict | None = None):
        return self.request("GET", path, token=token, params=params).json()

    def get_paged(self, path: str, *, token: str | None = None) -> list:
        first = self.request("GET", path, token=token, params={"page": 1})
        items = list(first.json() or [])
        pages = int(first.headers.get("x-pages", "1") or 1)
        for page in range(2, pages + 1):
            items.extend(self.request("GET", path, token=token, params={"page": page}).json() or [])
        return items

    def post(self, path: str, body, *, token: str | None = None):
        return self.request("POST", path, token=token, body=body).json()


def _to_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _error_text(resp: Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            return str(data["error"])[:200]
    except (ValueError, UnicodeDecodeError):
        pass
    return resp.body[:200].decode("utf-8", "replace")
