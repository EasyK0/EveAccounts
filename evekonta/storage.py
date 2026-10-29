"""Local SQLite database (%LOCALAPPDATA%\\EveKonta\\evekonta.sqlite3)."""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    login TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    password_enc BLOB,
    email_password_enc BLOB,
    omega_until TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS characters (
    character_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    refresh_enc BLOB,
    scopes TEXT NOT NULL DEFAULT '',
    token_ok INTEGER NOT NULL DEFAULT 1,
    last_error TEXT NOT NULL DEFAULT '',
    last_sync TEXT NOT NULL DEFAULT '',
    total_sp INTEGER,
    unallocated_sp INTEGER,
    wallet REAL,
    queue_len INTEGER,
    queue_end TEXT,
    queue_paused INTEGER NOT NULL DEFAULT 0,
    training_type_id INTEGER,
    training_level INTEGER,
    solar_system_id INTEGER,
    assets_value REAL
);
CREATE TABLE IF NOT EXISTS industry_jobs (
    character_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    activity_id INTEGER,
    blueprint_type_id INTEGER,
    product_type_id INTEGER,
    runs INTEGER,
    status TEXT,
    end_date TEXT,
    PRIMARY KEY (character_id, job_id)
);
CREATE TABLE IF NOT EXISTS planets (
    character_id INTEGER NOT NULL,
    planet_id INTEGER NOT NULL,
    planet_type TEXT,
    solar_system_id INTEGER,
    extractors INTEGER NOT NULL DEFAULT 0,
    expiry TEXT,
    PRIMARY KEY (character_id, planet_id)
);
CREATE TABLE IF NOT EXISTS assets (
    character_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    type_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    location_flag TEXT,
    root_location_id INTEGER,
    root_location_type TEXT,
    is_singleton INTEGER NOT NULL DEFAULT 0,
    is_bpc INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (character_id, item_id)
);
CREATE INDEX IF NOT EXISTS assets_type ON assets(type_id);
CREATE TABLE IF NOT EXISTS names (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS prices (
    type_id INTEGER PRIMARY KEY,
    price REAL NOT NULL
);
"""


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "EveKonta"
    return Path.home() / ".evekonta"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Db:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        if str(path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        with self.lock:
            self.conn.close()

    def query(self, sql: str, params=()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    # --- settings ----------------------------------------------------------

    def get_setting(self, key: str, default: str = "") -> str:
        rows = self.query("SELECT value FROM settings WHERE key=?", (key,))
        return rows[0]["value"] if rows and rows[0]["value"] is not None else default

    def set_setting(self, key: str, value: str) -> None:
        self.execute("INSERT INTO settings(key, value) VALUES(?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    # --- accounts ---------------------------------------------------------------

    def add_account(self, *, name="", login="", email="", password_enc=None, email_password_enc=None,
                    omega_until="", notes="") -> int:
        cur = self.execute(
            "INSERT INTO accounts(name, login, email, password_enc, email_password_enc, omega_until, notes,"
            " created_at) VALUES(?,?,?,?,?,?,?,?)",
            (name, login, email, password_enc, email_password_enc, omega_until, notes, utcnow_iso()),
        )
        return int(cur.lastrowid)

    def update_account(self, account_id: int, **fields) -> None:
        allowed = {"name", "login", "email", "password_enc", "email_password_enc", "omega_until", "notes"}
        keys = [k for k in fields if k in allowed]
        if not keys:
            return
        sql = "UPDATE accounts SET " + ", ".join(f"{k}=?" for k in keys) + " WHERE id=?"
        self.execute(sql, [fields[k] for k in keys] + [account_id])

    def delete_account(self, account_id: int) -> None:
        self.execute("DELETE FROM accounts WHERE id=?", (account_id,))

    def get_account(self, account_id: int):
        rows = self.query("SELECT * FROM accounts WHERE id=?", (account_id,))
        return rows[0] if rows else None

    def list_accounts(self, search: str = "") -> list[sqlite3.Row]:
        sql = """
            SELECT a.*, COALESCE(group_concat(c.name, ', '), '') AS characters,
                   COUNT(c.character_id) AS char_count
            FROM accounts a LEFT JOIN characters c ON c.account_id = a.id
            GROUP BY a.id
        """
        sql = f"SELECT * FROM ({sql})"
        params: list = []
        if search:
            like = f"%{search.lower()}%"
            sql += " WHERE lower(name) LIKE ? OR lower(login) LIKE ? " \
                   "OR lower(email) LIKE ? OR lower(characters) LIKE ? OR lower(notes) LIKE ?"
            params = [like] * 5
        sql += " ORDER BY lower(name), lower(login)"
        return self.query(sql, params)

    # --- characters ------------------------------------------------------------

    def upsert_character(self, character_id: int, name: str, refresh_enc: bytes, scopes: str,
                         account_id: int | None) -> None:
        self.execute(
            """INSERT INTO characters(character_id, name, refresh_enc, scopes, account_id, token_ok, last_error)
               VALUES(?,?,?,?,?,1,'')
               ON CONFLICT(character_id) DO UPDATE SET name=excluded.name, refresh_enc=excluded.refresh_enc,
                 scopes=excluded.scopes, token_ok=1, last_error='',
                 account_id=COALESCE(excluded.account_id, characters.account_id)""",
            (character_id, name, refresh_enc, scopes, account_id),
        )

    def set_character_account(self, character_id: int, account_id: int | None) -> None:
        self.execute("UPDATE characters SET account_id=? WHERE character_id=?", (account_id, character_id))

    def delete_character(self, character_id: int) -> None:
        with self.lock:
            for table in ("industry_jobs", "planets", "assets", "characters"):
                self.conn.execute(f"DELETE FROM {table} WHERE character_id=?", (character_id,))
            self.conn.commit()

    def store_refresh_token(self, character_id: int, refresh_enc: bytes) -> None:
        self.execute("UPDATE characters SET refresh_enc=? WHERE character_id=?", (refresh_enc, character_id))

    def mark_token(self, character_id: int, ok: bool, error: str = "") -> None:
        self.execute("UPDATE characters SET token_ok=?, last_error=? WHERE character_id=?",
                     (1 if ok else 0, error[:300], character_id))

    def list_characters(self) -> list[sqlite3.Row]:
        return self.query(
            """SELECT c.*, a.name AS account_name, a.login AS account_login, a.omega_until AS omega_until
               FROM characters c LEFT JOIN accounts a ON a.id = c.account_id
               ORDER BY lower(COALESCE(a.name, a.login, '')), lower(c.name)"""
        )

    # --- names and prices --------------------------------------------------------

    def save_names(self, entries: dict[int, tuple[str, str]]) -> None:
        with self.lock:
            self.conn.executemany(
                "INSERT INTO names(id, name, category) VALUES(?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, category=excluded.category",
                [(i, n, c) for i, (n, c) in entries.items()],
            )
            self.conn.commit()

    def known_name_ids(self) -> set[int]:
        return {r[0] for r in self.query("SELECT id FROM names")}

    def name_of(self, entity_id: int | None, default: str = "") -> str:
        if entity_id is None:
            return default
        rows = self.query("SELECT name FROM names WHERE id=?", (entity_id,))
        return rows[0]["name"] if rows else (default or str(entity_id))

    def save_prices(self, prices: dict[int, float]) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM prices")
            self.conn.executemany("INSERT INTO prices(type_id, price) VALUES(?,?)", list(prices.items()))
            self.conn.commit()
