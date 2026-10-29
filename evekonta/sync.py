"""Fetches character data from ESI and stores it in the local database."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from . import sso
from .crypto import Vault
from .i18n import tr
from .net import EsiClient, EsiError, Transport, urllib_transport
from .storage import Db, utcnow_iso

STATION_MIN, STATION_MAX = 60_000_000, 64_000_000
STRUCTURE_MIN = 1_000_000_000_000


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@dataclass
class CharData:
    total_sp: int | None = None
    unallocated_sp: int | None = None
    wallet: float | None = None
    queue_len: int | None = None
    queue_end: str | None = None
    queue_paused: bool = False
    training_type_id: int | None = None
    training_level: int | None = None
    solar_system_id: int | None = None
    jobs: list[dict] | None = None
    planets: list[dict] | None = None
    assets: list[dict] | None = None
    errors: list[str] = field(default_factory=list)


def summarize_queue(queue: list[dict], now: datetime) -> dict:
    remaining = []
    paused = False
    for entry in queue or []:
        finish = parse_ts(entry.get("finish_date"))
        if finish is None:
            # no finish date = queue paused (or the skill needs Omega)
            if entry.get("start_date") is None:
                paused = True
            remaining.append((entry, None))
        elif finish > now:
            remaining.append((entry, finish))
    remaining.sort(key=lambda pair: pair[0].get("queue_position", 0))
    ends = [f for _, f in remaining if f is not None]
    first = remaining[0][0] if remaining else None
    return {
        "queue_len": len(remaining),
        "queue_end": max(ends).strftime("%Y-%m-%dT%H:%M:%SZ") if ends and not paused else None,
        "queue_paused": paused and bool(remaining),
        "training_type_id": first.get("skill_id") if first else None,
        "training_level": first.get("finished_level") if first else None,
    }


def resolve_asset_roots(assets: list[dict]) -> None:
    """Finds the station/structure/system each item is in
    (items inside ships and containers point at their parent's ID)."""
    by_id = {a["item_id"]: a for a in assets}
    for asset in assets:
        cur = asset
        for _ in range(12):
            parent = by_id.get(cur.get("location_id"))
            if parent is None or parent is cur:
                break
            cur = parent
        root_id = cur.get("location_id")
        root_type = cur.get("location_type", "other")
        if root_type != "station" and root_type != "solar_system":
            if root_id is not None and STATION_MIN <= root_id < STATION_MAX:
                root_type = "station"
            elif root_id is not None and root_id >= STRUCTURE_MIN:
                root_type = "structure"
        asset["root_location_id"] = root_id
        asset["root_location_type"] = root_type


class Syncer:
    def __init__(self, db: Db, vault: Vault, client_id: str, client_secret: str = "", *,
                 transport: Transport = urllib_transport, esi: EsiClient | None = None,
                 clock: Callable[[], float] = time.time):
        self.db = db
        self.vault = vault
        self.client_id = client_id
        self.client_secret = client_secret or None
        self.transport = transport
        self.esi = esi or EsiClient(transport)
        self.clock = clock
        self._tokens: dict[int, sso.TokenSet] = {}
        self._token_lock = threading.Lock()

    # --- tokens --------------------------------------------------------------

    def add_token(self, tokens: sso.TokenSet, account_id: int | None) -> None:
        self.db.upsert_character(tokens.character_id, tokens.character_name,
                                 self.vault.encrypt(tokens.refresh_token), " ".join(tokens.scopes), account_id)
        with self._token_lock:
            self._tokens[tokens.character_id] = tokens

    def access_token(self, character_id: int) -> str:
        with self._token_lock:
            cached = self._tokens.get(character_id)
            if cached and cached.expires_at > self.clock():
                return cached.access_token
        rows = self.db.query("SELECT refresh_enc FROM characters WHERE character_id=?", (character_id,))
        if not rows or not rows[0]["refresh_enc"]:
            raise sso.InvalidToken(tr("No token"))
        refresh_token = self.vault.decrypt(rows[0]["refresh_enc"])
        try:
            tokens = sso.refresh(refresh_token, self.client_id, self.client_secret, self.transport, self.clock())
        except sso.InvalidToken as exc:
            self.db.mark_token(character_id, False, str(exc))
            raise
        # CCP may hand out a new refresh token: store it right away
        if tokens.refresh_token != refresh_token:
            self.db.store_refresh_token(character_id, self.vault.encrypt(tokens.refresh_token))
        with self._token_lock:
            self._tokens[character_id] = tokens
        return tokens.access_token

    # --- fetching ----------------------------------------------------------

    def fetch(self, cid: int, token: str) -> CharData:
        data = CharData()
        now = datetime.fromtimestamp(self.clock(), timezone.utc)

        def part(label, fn):
            try:
                fn()
            except EsiError as exc:
                data.errors.append(f"{label}: {exc}")

        def skills():
            s = self.esi.get(f"/characters/{cid}/skills", token=token) or {}
            data.total_sp = s.get("total_sp")
            data.unallocated_sp = s.get("unallocated_sp", 0)

        def queue():
            q = summarize_queue(self.esi.get(f"/characters/{cid}/skillqueue", token=token) or [], now)
            data.queue_len = q["queue_len"]
            data.queue_end = q["queue_end"]
            data.queue_paused = q["queue_paused"]
            data.training_type_id = q["training_type_id"]
            data.training_level = q["training_level"]

        def wallet():
            data.wallet = float(self.esi.get(f"/characters/{cid}/wallet", token=token) or 0)

        def location():
            data.solar_system_id = (self.esi.get(f"/characters/{cid}/location", token=token) or {}).get(
                "solar_system_id")

        def jobs():
            data.jobs = self.esi.get(f"/characters/{cid}/industry/jobs", token=token) or []

        def planets():
            result = []
            for planet in self.esi.get(f"/characters/{cid}/planets", token=token) or []:
                detail = self.esi.get(f"/characters/{cid}/planets/{planet['planet_id']}", token=token) or {}
                extractors = [p for p in detail.get("pins", []) if p.get("extractor_details")]
                expiries = [p.get("expiry_time") for p in extractors]
                known = [e for e in expiries if e]
                result.append({
                    "planet_id": planet["planet_id"],
                    "planet_type": planet.get("planet_type", ""),
                    "solar_system_id": planet.get("solar_system_id"),
                    "extractors": len(extractors),
                    # extractor without expiry_time = no program running (stopped)
                    "expiry": None if (not known or len(known) < len(expiries)) else min(known),
                })
            data.planets = result

        def assets():
            items = self.esi.get_paged(f"/characters/{cid}/assets", token=token)
            resolve_asset_roots(items)
            data.assets = items

        for label, fn in ((tr("skills"), skills), (tr("queue"), queue), (tr("wallet"), wallet),
                          (tr("location"), location), ("industry", jobs), ("PI", planets), (tr("assets"), assets)):
            part(label, fn)
        return data

    def store(self, cid: int, data: CharData) -> None:
        db = self.db
        with db.lock:
            c = db.conn
            fields = {
                "total_sp": data.total_sp, "unallocated_sp": data.unallocated_sp, "wallet": data.wallet,
                "solar_system_id": data.solar_system_id,
            }
            if data.queue_len is not None:
                fields.update(queue_len=data.queue_len, queue_end=data.queue_end,
                              queue_paused=1 if data.queue_paused else 0,
                              training_type_id=data.training_type_id, training_level=data.training_level)
            fields = {k: v for k, v in fields.items() if v is not None or k.startswith(("queue", "training"))}
            fields["last_sync"] = utcnow_iso()
            fields["last_error"] = "; ".join(data.errors)[:300]
            fields["token_ok"] = 1
            c.execute("UPDATE characters SET " + ", ".join(f"{k}=?" for k in fields) + " WHERE character_id=?",
                      [*fields.values(), cid])
            if data.jobs is not None:
                c.execute("DELETE FROM industry_jobs WHERE character_id=?", (cid,))
                c.executemany(
                    "INSERT INTO industry_jobs VALUES(?,?,?,?,?,?,?,?)",
                    [(cid, j["job_id"], j.get("activity_id"), j.get("blueprint_type_id"), j.get("product_type_id"),
                      j.get("runs"), j.get("status"), j.get("end_date")) for j in data.jobs],
                )
            if data.planets is not None:
                c.execute("DELETE FROM planets WHERE character_id=?", (cid,))
                c.executemany(
                    "INSERT INTO planets VALUES(?,?,?,?,?,?)",
                    [(cid, p["planet_id"], p["planet_type"], p["solar_system_id"], p["extractors"], p["expiry"])
                     for p in data.planets],
                )
            if data.assets is not None:
                c.execute("DELETE FROM assets WHERE character_id=?", (cid,))
                c.executemany(
                    "INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?)",
                    [(cid, a["item_id"], a["type_id"], a.get("quantity", 1), a.get("location_flag"),
                      a.get("root_location_id"), a.get("root_location_type"), 1 if a.get("is_singleton") else 0,
                      1 if a.get("is_blueprint_copy") else 0) for a in data.assets],
                )
            c.commit()

    def sync_character(self, cid: int) -> str | None:
        try:
            token = self.access_token(cid)
        except sso.InvalidToken as exc:
            return str(exc)
        except (sso.SsoError, OSError) as exc:
            self.db.execute("UPDATE characters SET last_error=? WHERE character_id=?", (str(exc)[:300], cid))
            return str(exc)
        try:
            data = self.fetch(cid, token)
        except OSError as exc:  # no network etc.
            self.db.execute("UPDATE characters SET last_error=? WHERE character_id=?", (str(exc)[:300], cid))
            return str(exc)
        self.store(cid, data)
        return "; ".join(data.errors) or None

    def sync_all(self, progress: Callable[[int, int, str], None] | None = None, workers: int = 6,
                 cancel: threading.Event | None = None) -> dict:
        chars = self.db.query("SELECT character_id, name FROM characters WHERE token_ok=1 ORDER BY name")
        total = len(chars)
        errors: dict[str, str] = {}
        done = 0
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {}
            for row in chars:
                if cancel and cancel.is_set():
                    break
                futures[pool.submit(self._sync_guarded, row["character_id"], cancel)] = row["name"]
            for fut in as_completed(futures):
                done += 1
                name = futures[fut]
                err = fut.result()
                if err:
                    errors[name] = err
                if progress:
                    progress(done, total, name)
        if not (cancel and cancel.is_set()):
            if progress:
                progress(done, total, tr("prices and names…"))
            try:
                self.refresh_prices()
            except (EsiError, OSError) as exc:
                errors[tr("prices")] = str(exc)
            try:
                self.resolve_names()
            except (EsiError, OSError) as exc:
                errors[tr("names")] = str(exc)
            self.compute_values()
        return errors

    def _sync_guarded(self, cid: int, cancel: threading.Event | None) -> str | None:
        if cancel and cancel.is_set():
            return None
        try:
            return self.sync_character(cid)
        except Exception as exc:  # one character must not stop the rest
            return tr("unexpected error: {name}", name=type(exc).__name__)

    # --- shared data ----------------------------------------------------------

    def refresh_prices(self) -> None:
        prices = {}
        for row in self.esi.get("/markets/prices") or []:
            price = row.get("average_price") or row.get("adjusted_price")
            if price:
                prices[int(row["type_id"])] = float(price)
        if prices:
            self.db.save_prices(prices)

    def resolve_names(self) -> None:
        q = self.db.query
        wanted: set[int] = set()
        for sql in (
            "SELECT DISTINCT type_id FROM assets",
            "SELECT DISTINCT product_type_id FROM industry_jobs WHERE product_type_id IS NOT NULL",
            "SELECT DISTINCT blueprint_type_id FROM industry_jobs WHERE blueprint_type_id IS NOT NULL",
            "SELECT DISTINCT training_type_id FROM characters WHERE training_type_id IS NOT NULL",
            "SELECT DISTINCT solar_system_id FROM characters WHERE solar_system_id IS NOT NULL",
            "SELECT DISTINCT solar_system_id FROM planets WHERE solar_system_id IS NOT NULL",
            "SELECT DISTINCT root_location_id FROM assets WHERE root_location_type IN ('station','solar_system')",
        ):
            wanted.update(r[0] for r in q(sql))
        missing = sorted(i for i in wanted - self.db.known_name_ids() if i and i < STRUCTURE_MIN)
        for start in range(0, len(missing), 1000):
            chunk = missing[start:start + 1000]
            try:
                found = self.esi.post("/universe/names", chunk) or []
            except EsiError as exc:
                if exc.status != 404 or len(chunk) == 1:
                    if exc.status == 404:
                        continue
                    raise
                # the chunk holds an unknown ID: split it in half
                found = self._names_bisect(chunk)
            self.db.save_names({int(r["id"]): (r["name"], r.get("category", "")) for r in found})

        structures = q("""SELECT root_location_id AS sid, MIN(character_id) AS cid FROM assets
                          WHERE root_location_type='structure' GROUP BY root_location_id""")
        known = self.db.known_name_ids()
        for row in structures:
            sid = row["sid"]
            if sid in known:
                continue
            name = tr("Structure {id}", id=sid)
            try:
                info = self.esi.get(f"/universe/structures/{sid}", token=self.access_token(row["cid"])) or {}
                name = info.get("name") or name
            except (EsiError, sso.SsoError):
                name = tr("Structure {id} (no access)", id=sid)
            self.db.save_names({sid: (name, "structure")})

    def _names_bisect(self, ids: list[int]) -> list[dict]:
        if not ids:
            return []
        try:
            return self.esi.post("/universe/names", ids) or []
        except EsiError as exc:
            if exc.status != 404:
                raise
            if len(ids) == 1:
                return []
            mid = len(ids) // 2
            return self._names_bisect(ids[:mid]) + self._names_bisect(ids[mid:])

    def compute_values(self) -> None:
        self.db.execute(
            """UPDATE characters SET assets_value = (
                   SELECT COALESCE(SUM(a.quantity * p.price), 0) FROM assets a
                   JOIN prices p ON p.type_id = a.type_id
                   WHERE a.character_id = characters.character_id AND a.is_bpc = 0)
               WHERE character_id IN (SELECT DISTINCT character_id FROM assets)"""
        )
