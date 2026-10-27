"""Uwagi (alerty), podsumowania i wyszukiwanie przedmiotów."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .storage import Db
from .sync import parse_ts

QUEUE_WARN = timedelta(hours=24)
PI_WARN = timedelta(hours=6)
OMEGA_WARN = timedelta(days=3)

ACTIVITIES = {1: "Produkcja", 3: "Badanie TE", 4: "Badanie ME", 5: "Kopiowanie", 8: "Inwencja", 9: "Reakcja",
              11: "Reakcja"}

LEVELS = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}


@dataclass
class Alert:
    severity: int  # 0 = pilne, 1 = wkrótce, 2 = informacja
    character: str
    account: str
    what: str
    when: datetime | None

    @property
    def severity_label(self) -> str:
        return ("PILNE", "WKRÓTCE", "INFO")[self.severity]


def fmt_isk(value: float | None) -> str:
    if value is None:
        return "–"
    for limit, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(value) >= limit:
            return f"{value / limit:.2f}{suffix}"
    return f"{value:.0f}"


def fmt_sp(value: int | None) -> str:
    return "–" if value is None else f"{value / 1e6:.1f}M"


def fmt_delta(when: datetime | None, now: datetime) -> str:
    if when is None:
        return "–"
    seconds = int((when - now).total_seconds())
    past = seconds < 0
    seconds = abs(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        text = f"{days}d {hours}h"
    elif hours:
        text = f"{hours}h {minutes}m"
    else:
        text = f"{minutes}m"
    return f"{text} temu" if past else f"za {text}"


def _account_label(row) -> str:
    return row["account_name"] or row["account_login"] or "(bez konta)"


def parse_omega(value: str) -> datetime | None:
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def build_alerts(db: Db, now: datetime | None = None) -> list[Alert]:
    now = now or datetime.now(timezone.utc)
    alerts: list[Alert] = []
    chars = db.list_characters()
    by_id = {r["character_id"]: r for r in chars}

    for c in chars:
        acc = _account_label(c)
        if not c["token_ok"]:
            alerts.append(Alert(0, c["name"], acc, "Token nieważny: zaloguj postać ponownie", None))
            continue
        if not c["last_sync"]:
            continue
        if c["queue_len"] is not None:
            end = parse_ts(c["queue_end"])
            if c["queue_paused"]:
                alerts.append(Alert(0, c["name"], acc, "Kolejka skilli wstrzymana", None))
            elif c["queue_len"] == 0:
                alerts.append(Alert(0, c["name"], acc, "Kolejka skilli pusta", None))
            elif end and end - now < QUEUE_WARN:
                alerts.append(Alert(1, c["name"], acc, "Kolejka skilli się kończy", end))
        if c["unallocated_sp"]:
            alerts.append(Alert(2, c["name"], acc, f"Nieprzydzielone SP: {c['unallocated_sp']:,}".replace(",", " "),
                                None))

    for j in db.query("SELECT * FROM industry_jobs"):
        c = by_id.get(j["character_id"])
        if not c:
            continue
        end = parse_ts(j["end_date"])
        product = db.name_of(j["product_type_id"] or j["blueprint_type_id"], "?")
        activity = ACTIVITIES.get(j["activity_id"], "Job")
        if j["status"] == "ready" or (j["status"] == "active" and end and end <= now):
            alerts.append(Alert(0, c["name"], _account_label(c), f"{activity} gotowa: {product}", end))

    for p in db.query("SELECT * FROM planets WHERE extractors > 0"):
        c = by_id.get(p["character_id"])
        if not c:
            continue
        exp = parse_ts(p["expiry"])
        where = f"{db.name_of(p['solar_system_id'], '?')} ({p['planet_type']})"
        if exp is None or exp <= now:
            alerts.append(Alert(0, c["name"], _account_label(c), f"Ekstraktor PI stoi: {where}", exp))
        elif exp - now < PI_WARN:
            alerts.append(Alert(1, c["name"], _account_label(c), f"Ekstraktor PI kończy się: {where}", exp))

    for a in db.list_accounts():
        omega = parse_omega(a["omega_until"])
        if omega is None:
            continue
        label = a["name"] or a["login"]
        if omega <= now:
            alerts.append(Alert(1, a["characters"] or "–", label, "Omega wygasła (wg Twojej daty)", omega))
        elif omega - now < OMEGA_WARN:
            alerts.append(Alert(1, a["characters"] or "–", label, "Omega kończy się", omega))

    far = datetime.max.replace(tzinfo=timezone.utc)
    alerts.sort(key=lambda a: (a.severity, a.when or far, a.account.lower(), a.character.lower()))
    return alerts


def totals(db: Db) -> dict:
    row = db.query("""SELECT COUNT(*) AS chars, COALESCE(SUM(wallet),0) AS wallet,
                             COALESCE(SUM(assets_value),0) AS assets, COALESCE(SUM(total_sp),0) AS sp
                      FROM characters""")[0]
    accounts = db.query("SELECT COUNT(*) FROM accounts")[0][0]
    return {"accounts": accounts, "chars": row["chars"], "wallet": row["wallet"], "assets": row["assets"],
            "sp": row["sp"], "total": row["wallet"] + row["assets"]}


def location_name(db: Db, location_id, location_type) -> str:
    if location_id is None:
        return "?"
    name = db.name_of(location_id, "")
    if name and name != str(location_id):
        return name + (" (w kosmosie)" if location_type == "solar_system" else "")
    return {"structure": f"Struktura {location_id}"}.get(location_type, f"Lokacja {location_id}")


def find_items(db: Db, text: str, limit: int = 500) -> list[dict]:
    """Szuka przedmiotów po nazwie we wszystkich postaciach ("gdzie jest mój Sabre?")."""
    text = text.strip()
    if not text:
        return []
    rows = db.query(
        """SELECT n.name AS item, c.name AS character, COALESCE(acc.name, acc.login, '') AS account,
                  a.root_location_id, a.root_location_type, SUM(a.quantity) AS qty,
                  COALESCE(p.price, 0) AS price, MAX(a.is_bpc) AS bpc
           FROM assets a
           JOIN names n ON n.id = a.type_id
           JOIN characters c ON c.character_id = a.character_id
           LEFT JOIN accounts acc ON acc.id = c.account_id
           LEFT JOIN prices p ON p.type_id = a.type_id
           WHERE lower(n.name) LIKE ?
           GROUP BY a.type_id, a.character_id, a.root_location_id
           ORDER BY lower(n.name), lower(c.name)
           LIMIT ?""",
        (f"%{text.lower()}%", limit),
    )
    out = []
    for r in rows:
        value = 0 if r["bpc"] else r["qty"] * r["price"]
        out.append({
            "item": r["item"] + (" (kopia BP)" if r["bpc"] else ""),
            "character": r["character"],
            "account": r["account"],
            "location": location_name(db, r["root_location_id"], r["root_location_type"]),
            "qty": r["qty"],
            "value": value,
        })
    return out


def character_rows(db: Db, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    jobs = {r[0]: (r[1], r[2]) for r in db.query(
        """SELECT character_id, COUNT(*),
                  SUM(CASE WHEN status='ready' OR (status='active' AND end_date <= ?) THEN 1 ELSE 0 END)
           FROM industry_jobs GROUP BY character_id""", (now.strftime("%Y-%m-%dT%H:%M:%SZ"),))}
    pi = {r[0]: (r[1], r[2]) for r in db.query(
        "SELECT character_id, COUNT(*), MIN(COALESCE(expiry, '0')) FROM planets GROUP BY character_id")}
    rows = []
    for c in db.list_characters():
        if c["queue_paused"]:
            queue = "wstrzymana"
        elif c["queue_len"] == 0:
            queue = "PUSTA"
        else:
            queue = fmt_delta(parse_ts(c["queue_end"]), now) if c["queue_end"] else "–"
        training = ""
        if c["training_type_id"]:
            training = f"{db.name_of(c['training_type_id'])} {LEVELS.get(c['training_level'], '')}".strip()
        job_count, ready = jobs.get(c["character_id"], (0, 0))
        planet_count, first_exp = pi.get(c["character_id"], (0, None))
        if planet_count:
            pi_text = f"{planet_count} pl., " + ("stoi" if first_exp == "0" else fmt_delta(parse_ts(first_exp), now))
        else:
            pi_text = "–"
        rows.append({
            "character_id": c["character_id"],
            "account": _account_label(c),
            "character": c["name"],
            "sp": fmt_sp(c["total_sp"]),
            "queue": queue,
            "training": training,
            "wallet": fmt_isk(c["wallet"]),
            "assets": fmt_isk(c["assets_value"]),
            "jobs": f"{ready}/{job_count}" if job_count else "–",
            "pi": pi_text,
            "system": db.name_of(c["solar_system_id"], "–") if c["solar_system_id"] else "–",
            "status": "OK" if c["token_ok"] and not c["last_error"] else (
                "ZALOGUJ PONOWNIE" if not c["token_ok"] else "błąd: " + c["last_error"][:80]),
            "_sort": {"wallet": c["wallet"] or 0, "assets": c["assets_value"] or 0, "sp": c["total_sp"] or 0,
                      "queue": c["queue_end"] or ("" if c["queue_len"] == 0 else "~")},
        })
    return rows
