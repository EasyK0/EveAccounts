import base64
import json
import urllib.parse
from datetime import datetime, timezone

import pytest

from evekonta import csvio, reports, sso
from evekonta.crypto import Vault, WrongPassword, derive_key, new_salt, verifier_for
from evekonta.net import EsiClient, EsiError, Response
from evekonta.storage import Db
from evekonta.sync import Syncer, resolve_asset_roots, summarize_queue

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
NOW_TS = NOW.timestamp()


def jwt_for(cid, name):
    payload = base64.urlsafe_b64encode(json.dumps(
        {"sub": f"CHARACTER:EVE:{cid}", "name": name, "scp": sso.SCOPES}).encode()).rstrip(b"=").decode()
    return f"x.{payload}.y"


def ok(data, headers=None):
    return Response(200, headers or {}, json.dumps(data).encode())


@pytest.fixture
def vault():
    salt = new_salt()
    key = derive_key("tajne", salt)
    return Vault(key, use_dpapi=False)


@pytest.fixture
def db():
    d = Db(":memory:")
    yield d
    d.close()


def test_vault_roundtrip_and_wrong_password():
    salt = new_salt()
    key = derive_key("haslo-glowne", salt)
    v = Vault(key, use_dpapi=False)
    blob = v.encrypt("MojeHaslo!ąę")
    assert blob and b"MojeHaslo" not in blob
    assert v.decrypt(blob) == "MojeHaslo!ąę"
    assert v.encrypt("") is None and v.decrypt(None) == ""
    with pytest.raises(WrongPassword):
        Vault.unlock("zle", salt, verifier_for(key))
    other = Vault(derive_key("inne", salt), use_dpapi=False)
    with pytest.raises(WrongPassword):
        other.decrypt(blob)


def test_queue_summary():
    q = [
        {"skill_id": 3300, "finished_level": 5, "queue_position": 0,
         "start_date": "2026-10-10T00:00:00Z", "finish_date": "2026-10-11T18:00:00Z"},
        {"skill_id": 3301, "finished_level": 4, "queue_position": 1,
         "start_date": "2026-10-11T18:00:00Z", "finish_date": "2026-10-13T00:00:00Z"},
        {"skill_id": 1, "finished_level": 1, "queue_position": -1, "finish_date": "2026-10-01T00:00:00Z"},
    ]
    s = summarize_queue(q, NOW)
    assert s["queue_len"] == 2 and s["queue_end"] == "2026-10-13T00:00:00Z"
    assert s["training_type_id"] == 3300 and not s["queue_paused"]
    assert summarize_queue([], NOW)["queue_len"] == 0
    paused = summarize_queue([{"skill_id": 5, "finished_level": 1, "queue_position": 0}], NOW)
    assert paused["queue_paused"] and paused["queue_end"] is None


def test_asset_roots():
    assets = [
        {"item_id": 1, "type_id": 11, "location_id": 60003760, "location_type": "station"},
        {"item_id": 2, "type_id": 12, "location_id": 1, "location_type": "item"},
        {"item_id": 3, "type_id": 13, "location_id": 2, "location_type": "item"},
        {"item_id": 4, "type_id": 14, "location_id": 1035466617946, "location_type": "item"},
        {"item_id": 5, "type_id": 15, "location_id": 30000142, "location_type": "solar_system"},
    ]
    resolve_asset_roots(assets)
    assert assets[2]["root_location_id"] == 60003760 and assets[2]["root_location_type"] == "station"
    assert assets[3]["root_location_type"] == "structure"
    assert assets[4]["root_location_type"] == "solar_system"


class FakeEve:
    """Udaje SSO i ESI dla jednej postaci."""

    def __init__(self):
        self.refresh_calls = 0
        self.invalid = False
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url))
        if url == sso.TOKEN_URL:
            form = urllib.parse.parse_qs(body.decode())
            assert form["client_id"] == ["cid"]
            if self.invalid:
                return Response(400, {}, b'{"error":"invalid_grant"}')
            self.refresh_calls += 1
            return ok({"access_token": jwt_for(90000001, "Alt Jeden"), "expires_in": 1199,
                       "refresh_token": f"rt{self.refresh_calls}"})
        path = urllib.parse.urlparse(url).path
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        if method == "GET" and path != "/markets/prices" and not path.startswith("/universe"):
            assert headers["Authorization"].startswith("Bearer ")
        base = "/characters/90000001"
        routes = {
            base + "/skills": {"total_sp": 25_000_000, "unallocated_sp": 0},
            base + "/skillqueue": [],
            base + "/wallet": 1_500_000_000.5,
            base + "/location": {"solar_system_id": 30000142},
            base + "/industry/jobs": [{"job_id": 7, "activity_id": 1, "blueprint_type_id": 999,
                                       "product_type_id": 587, "runs": 1, "status": "active",
                                       "end_date": "2026-10-11T10:00:00Z"}],
            base + "/planets": [{"planet_id": 40000001, "planet_type": "barren", "solar_system_id": 30000142}],
            base + "/planets/40000001": {"pins": [
                {"pin_id": 1, "extractor_details": {"heads": []}, "expiry_time": "2026-10-11T14:00:00Z"},
                {"pin_id": 2}]},
            "/markets/prices": [{"type_id": 587, "average_price": 400_000}, {"type_id": 34, "average_price": 5}],
            "/universe/structures/1035466617946": {"name": "Perimeter - Tranquility Trading Tower"},
        }
        if path == base + "/assets":
            page = int(query["page"][0])
            items = {
                1: [{"item_id": 100, "type_id": 587, "location_id": 60003760, "location_type": "station",
                     "location_flag": "Hangar", "quantity": 1, "is_singleton": True}],
                2: [{"item_id": 101, "type_id": 34, "location_id": 100, "location_type": "item",
                     "location_flag": "Cargo", "quantity": 1000, "is_singleton": False},
                    {"item_id": 102, "type_id": 587, "location_id": 1035466617946, "location_type": "item",
                     "location_flag": "Hangar", "quantity": 2, "is_singleton": False},
                    {"item_id": 103, "type_id": 999, "location_id": 60003760, "location_type": "station",
                     "location_flag": "Hangar", "quantity": 1, "is_singleton": True,
                     "is_blueprint_copy": True}],
            }[page]
            return ok(items, {"x-pages": "2"})
        if path == "/universe/names":
            ids = json.loads(body)
            known = {587: ("Rifter", "inventory_type"), 34: ("Tritanium", "inventory_type"),
                     999: ("Rifter Blueprint", "inventory_type"),
                     30000142: ("Jita", "solar_system"), 60003760: ("Jita IV - Moon 4 - CNAP", "station")}
            if any(i not in known for i in ids):
                return Response(404, {}, b'{"error":"Ensure all IDs are valid"}')
            return ok([{"id": i, "name": known[i][0], "category": known[i][1]} for i in ids])
        if path in routes:
            return ok(routes[path])
        return Response(404, {}, b'{"error":"not found"}')


def make_syncer(db, vault, fake):
    return Syncer(db, vault, "cid", transport=fake, esi=EsiClient(fake, sleep=lambda s: None),
                  clock=lambda: NOW_TS)


def test_full_sync_flow(db, vault):
    fake = FakeEve()
    acc = db.add_account(name="Konto 1", login="dawid1", email="a@b.pl", password_enc=vault.encrypt("pw1"))
    syncer = make_syncer(db, vault, fake)
    tokens = sso.refresh("start", "cid", transport=fake, now=NOW_TS)
    syncer.add_token(tokens, acc)

    errors = syncer.sync_all(workers=2)
    assert errors == {}
    c = db.list_characters()[0]
    assert c["name"] == "Alt Jeden" and c["account_name"] == "Konto 1"
    assert c["total_sp"] == 25_000_000 and c["wallet"] == pytest.approx(1_500_000_000.5)
    assert c["queue_len"] == 0
    # 3 Riftery * 400k; kopia BP i Tritanium (5 ISK * 1000) wg cen
    assert c["assets_value"] == pytest.approx(3 * 400_000 + 5000)
    # token z cache (bez nowego refresh), refresh token zapisany zaszyfrowany
    assert fake.refresh_calls == 1
    assert vault.decrypt(c["refresh_enc"]) == "rt1"

    found = reports.find_items(db, "rift")
    locations = {(r["item"], r["location"]) for r in found}
    assert ("Rifter", "Jita IV - Moon 4 - CNAP") in locations
    assert ("Rifter", "Perimeter - Tranquility Trading Tower") in locations
    assert any(r["item"] == "Rifter Blueprint (kopia BP)" and r["value"] == 0 for r in found)
    trit = reports.find_items(db, "trit")[0]
    assert trit["location"] == "Jita IV - Moon 4 - CNAP" and trit["qty"] == 1000

    alerts = reports.build_alerts(db, NOW)
    whats = [a.what for a in alerts]
    assert "Kolejka skilli pusta" in whats
    assert any(w.startswith("Produkcja gotowa: Rifter") for w in whats)
    assert any(w.startswith("Ekstraktor PI kończy się: Jita") for w in whats)
    assert alerts[0].severity == 0

    rows = reports.character_rows(db, NOW)
    assert rows[0]["queue"] == "PUSTA" and rows[0]["jobs"] == "1/1" and rows[0]["system"] == "Jita"
    assert rows[0]["wallet"] == "1.50B"

    t = reports.totals(db)
    assert t["accounts"] == 1 and t["chars"] == 1


def test_invalid_token_marks_character(db, vault):
    fake = FakeEve()
    syncer = make_syncer(db, vault, fake)
    syncer.add_token(sso.refresh("start", "cid", transport=fake, now=NOW_TS), None)
    syncer._tokens.clear()
    fake.invalid = True
    assert "zaloguj" in syncer.sync_character(90000001).lower()
    assert db.list_characters()[0]["token_ok"] == 0
    alerts = reports.build_alerts(db, NOW)
    assert alerts[0].what.startswith("Token nieważny")
    # sync_all pomija postacie z nieważnym tokenem
    assert syncer.sync_all() == {}


def test_names_bisect_skips_unknown_ids(db, vault):
    fake = FakeEve()
    syncer = make_syncer(db, vault, fake)
    db.execute("INSERT INTO characters(character_id, name, solar_system_id) VALUES(1, 'x', 30000142)")
    db.execute("INSERT INTO planets VALUES(1, 5, 'gas', 31999999, 1, NULL)")
    syncer.resolve_names()
    assert db.name_of(30000142) == "Jita"
    assert db.name_of(31999999) == "31999999"


def test_esi_retries_then_raises():
    calls = []

    def transport(method, url, headers, body):
        calls.append(url)
        return Response(502, {}, b"")

    client = EsiClient(transport, sleep=lambda s: None)
    with pytest.raises(EsiError) as exc:
        client.get("/status")
    assert exc.value.status == 502 and len(calls) == 4


def test_account_search_and_csv(db, vault, tmp_path):
    src = tmp_path / "konta.csv"
    src.write_text("nazwa;login;hasło;email;haslo_email;omega;notatki\n"
                   "Main;dawid_main;Pw1;main@x.pl;mailpw;2026-10-12;\n"
                   "Alt 2;alt2;Pw2;alt2@y.pl;;;farma\n"
                   "Dup;DAWID_MAIN;x;;;;\n", encoding="utf-8")
    added, skipped = csvio.import_accounts(db, vault, src)
    assert (added, skipped) == (2, 1)
    acc = db.list_accounts("y.pl")
    assert len(acc) == 1 and acc[0]["login"] == "alt2"
    assert vault.decrypt(acc[0]["password_enc"]) == "Pw2"
    main = db.list_accounts("dawid_main")[0]
    assert vault.decrypt(main["email_password_enc"]) == "mailpw"

    db.execute("INSERT INTO characters(character_id, name, account_id) VALUES(5, 'Pochven Pilot', ?)", (main["id"],))
    assert db.list_accounts("pochven")[0]["login"] == "dawid_main"

    alerts = reports.build_alerts(db, NOW)
    assert any(a.what == "Omega kończy się" and a.account == "Main" for a in alerts)

    out = tmp_path / "out.csv"
    assert csvio.export_accounts(db, vault, out, include_passwords=True) == 2
    text = out.read_text(encoding="utf-8-sig")
    assert "Pw1" in text and "mailpw" in text
    csvio.export_accounts(db, vault, out, include_passwords=False)
    assert "Pw1" not in out.read_text(encoding="utf-8-sig")

    db.delete_account(main["id"])
    assert db.list_characters()[0]["account_id"] is None


def test_auth_url_and_callback_server():
    import threading
    import urllib.request

    verifier, challenge = sso.make_pkce()
    url = sso.build_auth_url("cid", 8799, "st4te", challenge)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["redirect_uri"] == ["http://localhost:8799/callback"] and q["code_challenge_method"] == ["S256"]

    server = sso.CallbackServer(8799, "st4te")
    threading.Thread(target=lambda: urllib.request.urlopen(
        "http://127.0.0.1:8799/callback?code=abc&state=st4te").read(), daemon=True).start()
    assert server.wait(5) == "abc"


def test_parse_pasted_formats(db, vault):
    rows = csvio.parse_pasted("login;haslo;email\nalt1;Pw:1;a1@wp.pl\n\nalt2;Pw2;a2@wp.pl;farma PI\n")
    assert rows == [
        {"login": "alt1", "password": "Pw:1", "email": "a1@wp.pl", "notes": ""},
        {"login": "alt2", "password": "Pw2", "email": "a2@wp.pl", "notes": "farma PI"},
    ]
    rows = csvio.parse_pasted("alt3:Haslo3\nalt4:Haslo4:alt4@gmail.com\n")
    assert rows[0] == {"login": "alt3", "password": "Haslo3", "email": "", "notes": ""}
    assert rows[1]["email"] == "alt4@gmail.com" and rows[1]["password"] == "Haslo4"
    rows = csvio.parse_pasted("mail5@o2.pl Haslo5\n")
    assert rows[0] == {"login": "mail5@o2.pl", "password": "Haslo5", "email": "mail5@o2.pl", "notes": ""}
    rows = csvio.parse_pasted("alt6;alt6@wp.pl\nalt7 alt7@wp.pl Pochven\n", with_passwords=False)
    assert rows == [{"login": "alt6", "password": "", "email": "alt6@wp.pl", "notes": ""},
                    {"login": "alt7", "password": "", "email": "alt7@wp.pl", "notes": "Pochven"}]
    # nagłówek decyduje o kolumnach, także bez zaznaczonej opcji "bez haseł"
    rows = csvio.parse_pasted("login;email\nPochvenCrab1;sole@gmail.com\nPochvenCrab2;sole@gmail.com\n")
    assert rows[0]["login"] == "PochvenCrab1" and rows[0]["email"] == "sole@gmail.com"
    assert rows[0]["password"] == "" and len(rows) == 2
    added, skipped = csvio.add_parsed(db, vault, csvio.parse_pasted("a:1\nb:2\nA:3"))
    assert (added, skipped) == (2, 1)
    assert vault.decrypt(db.list_accounts("b")[0]["password_enc"]) == "2"


def test_check_app_finds_rejected_scope():
    enabled = set(sso.SCOPES) - {"esi-assets.read_assets.v1"}

    def transport(method, url, headers, body):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        if q["client_id"] != ["good"]:
            return Response(400, {}, b'{"error":"invalid_client","error_description":"Unknown client"}')
        bad = [s for s in q["scope"][0].split() if s not in enabled]
        if bad:
            return Response(400, {}, json.dumps({"error": "invalid_scope",
                                                 "error_description": f"The requested '{bad[0]}' scope is not valid."}).encode())
        return Response(200, {}, b"<html>login</html>")

    r = sso.check_app("good", 8765, transport)
    assert not r.ok and r.rejected == ["esi-assets.read_assets.v1"]
    assert "esi-assets.read_assets.v1" in sso.explain_check(r, 8765)
    r = sso.check_app("bad", 8765, transport)
    assert r.error == "invalid_client" and "Client ID" in sso.explain_check(r, 8765)
    enabled.add("esi-assets.read_assets.v1")
    assert sso.check_app("good", 8765, transport).ok
