"""Import/eksport listy kont z pliku CSV (np. z Excela)."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from .crypto import Vault
from .storage import Db

COLUMNS = {
    "name": ("nazwa", "name", "konto", "account"),
    "login": ("login", "username", "user", "uzytkownik", "użytkownik"),
    "password": ("haslo", "hasło", "password", "pass"),
    "email": ("email", "e-mail", "mail"),
    "email_password": ("haslo_email", "hasło_email", "haslo email", "hasło email", "email_password",
                       "haslo do maila", "hasło do maila"),
    "omega_until": ("omega", "omega_do", "omega do", "omega_until"),
    "notes": ("notatki", "notes", "uwagi"),
}


class _Semicolon(csv.excel):
    delimiter = ";"


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1250"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _map_header(header: list[str]) -> dict[str, int]:
    norm = [h.strip().lower() for h in header]
    mapping = {}
    for field, names in COLUMNS.items():
        for i, h in enumerate(norm):
            if h in names:
                mapping[field] = i
                break
    return mapping


def import_accounts(db: Db, vault: Vault, path: Path) -> tuple[int, int]:
    """Zwraca (dodane, pominięte). Konto z istniejącym loginem jest pomijane."""
    text = _read_text(Path(path))
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
    except csv.Error:
        dialect = _Semicolon
    rows = list(csv.reader(io.StringIO(text), dialect))
    if not rows:
        return 0, 0
    mapping = _map_header(rows[0])
    if "login" not in mapping and "email" not in mapping:
        raise ValueError("Plik musi mieć nagłówek z kolumną 'login' albo 'email'")
    existing = {r["login"].lower() for r in db.query("SELECT login FROM accounts") if r["login"]}
    added = skipped = 0

    def get(row, field):
        i = mapping.get(field)
        return row[i].strip() if i is not None and i < len(row) else ""

    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        login = get(row, "login")
        if login and login.lower() in existing:
            skipped += 1
            continue
        db.add_account(
            name=get(row, "name"), login=login, email=get(row, "email"),
            password_enc=vault.encrypt(get(row, "password")),
            email_password_enc=vault.encrypt(get(row, "email_password")),
            omega_until=get(row, "omega_until"), notes=get(row, "notes"),
        )
        if login:
            existing.add(login.lower())
        added += 1
    return added, skipped


def export_accounts(db: Db, vault: Vault, path: Path, include_passwords: bool) -> int:
    rows = db.list_accounts()
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh, delimiter=";")
        header = ["nazwa", "login", "email", "omega", "notatki", "postacie"]
        if include_passwords:
            header[2:2] = ["haslo"]
            header.insert(4, "haslo_email")
        writer.writerow(header)
        for r in rows:
            line = [r["name"], r["login"], r["email"], r["omega_until"], r["notes"], r["characters"]]
            if include_passwords:
                line[2:2] = [vault.decrypt(r["password_enc"])]
                line.insert(4, vault.decrypt(r["email_password_enc"]))
            writer.writerow(line)
    return len(rows)


# --- wklejanie listy kont (dowolny format, jedno konto w linii) --------------

_SEPARATORS = ["\t", ";", "|", ":", ","]
_HEADER_WORDS = {"login", "haslo", "hasło", "password", "email", "e-mail", "mail", "nazwa"}


def _is_email(text: str) -> bool:
    text = text.strip()
    return "@" in text and "." in text.split("@")[-1] and " " not in text


def _pick_separator(lines: list[str]) -> str | None:
    best, best_count = None, 0
    for sep in _SEPARATORS:
        count = sum(1 for line in lines if sep in line)
        if count > best_count:
            best, best_count = sep, count
    # separator musi występować w większości linii, inaczej dzielimy po spacjach
    return best if best and best_count >= max(1, len(lines) // 2) else None


def parse_pasted(text: str, with_passwords: bool = True) -> list[dict]:
    """Rozpoznaje listy typu `login:haslo`, `login;haslo;mail`, `mail haslo`,
    `login | haslo | mail | notatka`. Pole z @ to e-mail, pierwsze inne to
    login, kolejne to hasło, reszta trafia do notatek."""
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("#")]
    if not lines:
        return []
    sep = _pick_separator(lines)
    accounts = []
    header: dict[str, int] = {}
    for index, line in enumerate(lines):
        parts = [p.strip() for p in (line.split(sep) if sep and sep in line else line.split())]
        if not header:
            parts = [p for p in parts if p]
        if not parts:
            continue
        if index == 0 and sum(1 for p in parts if p.lower() in _HEADER_WORDS) >= 2:
            header = _map_header(parts)  # nagłówek mówi, która kolumna jest czym
            continue
        if header:
            def col(field):
                i = header.get(field)
                return parts[i] if i is not None and i < len(parts) else ""
            row = {"login": col("login") or col("email"), "password": col("password"),
                   "email": col("email"),
                   "notes": " ".join(x for x in [col("notes")] + [p for i, p in enumerate(parts)
                                     if i not in header.values() and p] if x)}
            if col("name"):
                row["name"] = col("name")
            if any(row.values()):
                accounts.append(row)
            continue
        email = ""
        rest = []
        for p in parts:
            if not email and _is_email(p):
                email = p
            else:
                rest.append(p)
        if not with_passwords:
            login = rest[0] if rest else email
            password, notes = "", " ".join(rest[1:])
        elif email and len(rest) == 1:
            login, password, notes = email, rest[0], ""
        else:
            login = rest[0] if rest else email
            password = rest[1] if len(rest) > 1 else ""
            notes = " ".join(rest[2:])
        accounts.append({"login": login, "password": password, "email": email, "notes": notes})
    return accounts


def add_parsed(db: Db, vault: Vault, accounts: list[dict]) -> tuple[int, int]:
    existing = {r["login"].lower() for r in db.query("SELECT login FROM accounts") if r["login"]}
    added = skipped = 0
    for acc in accounts:
        login = acc["login"]
        if login and login.lower() in existing:
            skipped += 1
            continue
        db.add_account(name=acc.get("name") or login, login=login, email=acc.get("email", ""),
                       password_enc=vault.encrypt(acc.get("password", "")), notes=acc.get("notes", ""))
        if login:
            existing.add(login.lower())
        added += 1
    return added, skipped
