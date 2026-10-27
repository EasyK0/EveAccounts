"""Okno aplikacji EveKonta (Tkinter)."""

from __future__ import annotations

import queue
import secrets
import threading
import time
import tkinter as tk
import traceback
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import __version__, csvio, reports, sso
from .crypto import Vault, WrongPassword, derive_key, new_salt, verifier_for
from .storage import Db, default_data_dir
from .sync import Syncer

CLIPBOARD_CLEAR_SECONDS = 30
DEV_PORTAL = "https://developers.eveonline.com/applications"


# --- pomocnicze widgety -----------------------------------------------------


class Table(ttk.Frame):
    """Treeview z paskiem przewijania i sortowaniem po kliknięciu nagłówka."""

    def __init__(self, master, columns: list[tuple[str, str, int]], height=20):
        super().__init__(master)
        self.columns = [c[0] for c in columns]
        self.tree = ttk.Treeview(self, columns=self.columns, show="headings", height=height)
        for key, label, width in columns:
            self.tree.heading(key, text=label, command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=width, anchor="w", stretch=True)
        ys = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._rows: dict[str, dict] = {}
        self._sort_key: str | None = None
        self._sort_desc = False

    def set_rows(self, rows: list[dict], iid_key: str | None = None, tag_key: str | None = None):
        selected = self.selected_ids()
        self.tree.delete(*self.tree.get_children())
        self._rows = {}
        for i, row in enumerate(rows):
            iid = str(row[iid_key]) if iid_key else str(i)
            self._rows[iid] = row
            tags = (row[tag_key],) if tag_key and row.get(tag_key) else ()
            self.tree.insert("", "end", iid=iid, values=[row.get(c, "") for c in self.columns], tags=tags)
        if self._sort_key:
            self._apply_sort()
        keep = [s for s in selected if s in self._rows]
        if keep:
            self.tree.selection_set(keep)

    def selected_ids(self) -> list[str]:
        return list(self.tree.selection())

    def selected_rows(self) -> list[dict]:
        return [self._rows[i] for i in self.tree.selection() if i in self._rows]

    def sort_by(self, key: str):
        if self._sort_key == key:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_key, self._sort_desc = key, False
        self._apply_sort()

    def _apply_sort(self):
        key = self._sort_key

        def value(iid):
            row = self._rows[iid]
            special = row.get("_sort", {}).get(key)
            if special is not None:
                return (0, special)
            v = row.get(key, "")
            if isinstance(v, (int, float)):
                return (0, v)
            return (1, str(v).lower())

        ordered = sorted(self._rows, key=value, reverse=self._sort_desc)
        for index, iid in enumerate(ordered):
            self.tree.move(iid, "", index)


def labeled_entry(parent, row, label, show=None, width=40):
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=3)
    var = tk.StringVar()
    entry = ttk.Entry(parent, textvariable=var, width=width, show=show or "")
    entry.grid(row=row, column=1, sticky="ew", padx=6, pady=3)
    return var, entry


# --- hasło główne -----------------------------------------------------------


def ask_master_password(root: tk.Tk, db: Db) -> Vault | None:
    salt_hex = db.get_setting("master_salt")
    if not salt_hex:
        messagebox.showinfo(
            "EveKonta – pierwsze uruchomienie",
            "Ustaw hasło główne. Szyfruje ono hasła do kont i tokeny postaci.\n\n"
            "Zapamiętaj je: bez niego nie da się odczytać zapisanych haseł.",
            parent=root,
        )
        while True:
            first = simpledialog.askstring("Hasło główne", "Nowe hasło główne (min. 8 znaków):", show="*",
                                           parent=root)
            if first is None:
                return None
            if len(first) < 8:
                messagebox.showwarning("Hasło główne", "Hasło musi mieć co najmniej 8 znaków.", parent=root)
                continue
            second = simpledialog.askstring("Hasło główne", "Powtórz hasło główne:", show="*", parent=root)
            if second != first:
                messagebox.showwarning("Hasło główne", "Hasła się różnią.", parent=root)
                continue
            salt = new_salt()
            key = derive_key(first, salt)
            db.set_setting("master_salt", salt.hex())
            db.set_setting("master_verifier", verifier_for(key))
            return Vault(key)
    salt = bytes.fromhex(salt_hex)
    verifier = db.get_setting("master_verifier")
    for _ in range(5):
        pw = simpledialog.askstring("EveKonta", "Hasło główne:", show="*", parent=root)
        if pw is None:
            return None
        try:
            return Vault.unlock(pw, salt, verifier)
        except WrongPassword:
            messagebox.showerror("EveKonta", "Złe hasło główne.", parent=root)
    return None


# --- okno edycji konta ------------------------------------------------------


class AccountDialog(tk.Toplevel):
    def __init__(self, app: "App", account_id: int | None):
        super().__init__(app)
        self.app = app
        self.account_id = account_id
        self.title("Nowe konto" if account_id is None else "Edycja konta")
        self.transient(app)
        self.resizable(True, False)
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        self.name, _ = labeled_entry(frm, 0, "Nazwa (dowolna)")
        self.login, _ = labeled_entry(frm, 1, "Login EVE")
        self.password, self._pw_entry = labeled_entry(frm, 2, "Hasło EVE", show="•")
        self.email, _ = labeled_entry(frm, 3, "E-mail")
        self.email_password, self._epw_entry = labeled_entry(frm, 4, "Hasło do maila", show="•")
        self.omega, _ = labeled_entry(frm, 5, "Omega do (RRRR-MM-DD)")
        ttk.Label(frm, text="Notatki").grid(row=6, column=0, sticky="nw", padx=6, pady=3)
        self.notes = tk.Text(frm, height=4, width=40)
        self.notes.grid(row=6, column=1, sticky="ew", padx=6, pady=3)
        self.show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Pokaż hasła", variable=self.show_var, command=self._toggle).grid(
            row=7, column=1, sticky="w", padx=6)
        btns = ttk.Frame(frm)
        btns.grid(row=8, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Zapisz", command=self.save).pack(side="right", padx=4)
        ttk.Button(btns, text="Anuluj", command=self.destroy).pack(side="right")

        if account_id is not None:
            acc = app.db.get_account(account_id)
            self.name.set(acc["name"])
            self.login.set(acc["login"])
            self.password.set(app.vault.decrypt(acc["password_enc"]))
            self.email.set(acc["email"])
            self.email_password.set(app.vault.decrypt(acc["email_password_enc"]))
            self.omega.set(acc["omega_until"])
            self.notes.insert("1.0", acc["notes"])
        self.bind("<Return>", lambda e: self.save() if e.widget is not self.notes else None)
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()

    def _toggle(self):
        show = "" if self.show_var.get() else "•"
        self._pw_entry.configure(show=show)
        self._epw_entry.configure(show=show)

    def save(self):
        if not (self.login.get().strip() or self.email.get().strip() or self.name.get().strip()):
            messagebox.showwarning("Konto", "Wpisz przynajmniej login, e-mail albo nazwę.", parent=self)
            return
        omega = self.omega.get().strip()
        if omega and reports.parse_omega(omega) is None:
            messagebox.showwarning("Konto", "Data Omegi w formacie RRRR-MM-DD (np. 2026-11-30).", parent=self)
            return
        v = self.app.vault
        fields = dict(
            name=self.name.get().strip(), login=self.login.get().strip(), email=self.email.get().strip(),
            password_enc=v.encrypt(self.password.get()), email_password_enc=v.encrypt(self.email_password.get()),
            omega_until=omega, notes=self.notes.get("1.0", "end").strip(),
        )
        if self.account_id is None:
            self.app.db.add_account(**fields)
        else:
            self.app.db.update_account(self.account_id, **fields)
        self.app.refresh_views()
        self.destroy()


# --- wklejanie listy kont -------------------------------------------------


class PasteAccountsDialog(tk.Toplevel):
    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("Wklej konta")
        self.transient(app)
        self.geometry("820x600")
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, justify="left", text=(
            "Wklej listę kont, jedno konto w linii. Pola rozdziel dowolnie: ; : | , tabulatorem albo spacją.\n"
            "Przykłady:   login;hasło;mail@wp.pl     login:hasło     mail@wp.pl hasło     login;mail@wp.pl\n"
            "Pole z @ to e-mail, pierwsze inne to login, potem hasło, reszta trafia do notatek.")).pack(anchor="w")
        self.no_pw = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Lista bez haseł (login + e-mail, hasła dopiszę później)",
                        variable=self.no_pw, command=self.preview).pack(anchor="w", pady=4)
        pw_row = ttk.Frame(frm)
        pw_row.pack(anchor="w", pady=2)
        ttk.Label(pw_row, text="Wspólne hasło dla kont bez hasła (opcjonalnie):").pack(side="left")
        self.common_pw = tk.StringVar()
        ttk.Entry(pw_row, textvariable=self.common_pw, show="•", width=30).pack(side="left", padx=4)
        self.common_pw.trace_add("write", lambda *_: self.preview())
        self.text = tk.Text(frm, height=10, wrap="none")
        self.text.pack(fill="both", expand=True)
        self.text.bind("<<Modified>>", self._modified)
        self.summary = tk.StringVar(value="Podgląd pojawi się po wklejeniu.")
        ttk.Label(frm, textvariable=self.summary).pack(anchor="w", pady=4)
        self.table = Table(frm, [("login", "Login", 200), ("email", "E-mail", 220), ("password", "Hasło", 100),
                                 ("notes", "Notatki", 220)], height=8)
        self.table.pack(fill="both", expand=True)
        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Dodaj konta", command=self.add).pack(side="right")
        ttk.Button(btns, text="Anuluj", command=self.destroy).pack(side="right", padx=4)
        self.grab_set()

    def _modified(self, _event=None):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            self.preview()

    def parsed(self) -> list[dict]:
        rows = csvio.parse_pasted(self.text.get("1.0", "end"), with_passwords=not self.no_pw.get())
        common = self.common_pw.get()
        if common:
            for r in rows:
                if not r["password"]:
                    r["password"] = common
        return rows

    def preview(self):
        rows = self.parsed()
        shown = [{**r, "password": "•" * min(len(r["password"]), 8) if r["password"] else "(brak)"} for r in rows]
        self.table.set_rows(shown)
        missing_pw = sum(1 for r in rows if not r["password"])
        self.summary.set(f"Rozpoznano {len(rows)} kont" + (f", bez hasła: {missing_pw}" if missing_pw else ""))

    def add(self):
        rows = self.parsed()
        if not rows:
            messagebox.showinfo("Wklej konta", "Nic nie rozpoznano.", parent=self)
            return
        added, skipped = csvio.add_parsed(self.app.db, self.app.vault, rows)
        self.app.refresh_views()
        messagebox.showinfo("Wklej konta", f"Dodano: {added}\nPominięto (login już był): {skipped}", parent=self)
        self.destroy()


# --- dodawanie postaci przez SSO -------------------------------------------


class AddCharacterDialog(tk.Toplevel):
    def __init__(self, app: "App", account_id: int | None):
        super().__init__(app)
        self.app = app
        self.account_id = account_id
        self.server: sso.CallbackServer | None = None
        self.title("Dodaj postać (EVE SSO)")
        self.transient(app)
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)
        acc = app.db.get_account(account_id) if account_id else None
        label = (acc["name"] or acc["login"] or acc["email"]) if acc else "(bez przypisanego konta)"
        ttk.Label(frm, text=f"Konto: {label}", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(frm, justify="left", wraplength=460, text=(
            "1. Kliknij „Otwórz logowanie” (albo skopiuj link do okna prywatnego/incognito, "
            "gdy przeglądarka jest zalogowana na inne konto).\n"
            "2. Zaloguj się na to konto i wybierz postać.\n"
            "3. Po powrocie możesz od razu dodać kolejną postać z tego konta.")).pack(anchor="w", pady=6)
        row = ttk.Frame(frm)
        row.pack(anchor="w", pady=4)
        if acc:
            ttk.Button(row, text="Kopiuj login", command=lambda: app.copy_secret(acc["login"], False)).pack(
                side="left", padx=2)
            ttk.Button(row, text="Kopiuj hasło",
                       command=lambda: app.copy_secret(app.vault.decrypt(acc["password_enc"]), True)).pack(
                side="left", padx=2)
        row2 = ttk.Frame(frm)
        row2.pack(anchor="w", pady=4)
        self.open_btn = ttk.Button(row2, text="Otwórz logowanie", command=lambda: self.start(open_browser=True))
        self.open_btn.pack(side="left", padx=2)
        self.link_btn = ttk.Button(row2, text="Kopiuj link (incognito)", command=lambda: self.start(False))
        self.link_btn.pack(side="left", padx=2)
        self.status = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.status, wraplength=460, foreground="#1a5fb4").pack(anchor="w", pady=6)
        ttk.Button(frm, text="Zamknij", command=self.close).pack(anchor="e")
        self.protocol("WM_DELETE_WINDOW", self.close)

    def start(self, open_browser: bool):
        cfg = self.app.sso_config()
        if not cfg["client_id"]:
            messagebox.showwarning("EveKonta", "Najpierw wpisz Client ID w zakładce Ustawienia.", parent=self)
            return
        if self.server:
            self.server.close()
        state = secrets.token_urlsafe(16)
        verifier, challenge = sso.make_pkce()
        try:
            self.server = sso.CallbackServer(cfg["port"], state)
        except OSError:
            messagebox.showerror("EveKonta", f"Port {cfg['port']} jest zajęty. Zmień go w Ustawieniach "
                                             "(i w aplikacji na developers.eveonline.com).", parent=self)
            return
        url = sso.build_auth_url(cfg["client_id"], cfg["port"], state, challenge, self.app.enabled_scopes())
        if open_browser:
            webbrowser.open(url)
            self.status.set("Czekam na zalogowanie w przeglądarce…")
        else:
            self.app.copy_secret(url, False)
            self.status.set("Link skopiowany. Wklej go w okno prywatne przeglądarki i zaloguj się…")
        server = self.server

        def work():
            try:
                code = server.wait(300)
                tokens = sso.exchange_code(code, verifier, cfg["client_id"], cfg["client_secret"] or None)
                self.app.syncer.add_token(tokens, self.account_id)
                self.app.ui(lambda: self.status.set(
                    f"Dodano: {tokens.character_name}. Pobieram dane… Możesz dodać kolejną postać."))
                self.app.ui(self.app.refresh_views)
                self.app.syncer.sync_character(tokens.character_id)
                self.app.syncer.resolve_names()
                self.app.syncer.compute_values()
                self.app.ui(lambda: self.status.set(
                    f"Dodano i pobrano: {tokens.character_name}. Możesz dodać kolejną postać."))
                self.app.ui(self.app.refresh_views)
            except sso.SsoError as exc:
                msg = str(exc)
                if server is self.server:
                    self.app.ui(lambda: self.status.set(f"Nie udało się: {msg}"))
            except Exception as exc:  # noqa: BLE001
                msg = f"{type(exc).__name__}: {exc}"
                self.app.ui(lambda: self.status.set(f"Błąd: {msg}"))

        threading.Thread(target=work, daemon=True).start()

    def close(self):
        if self.server:
            self.server.close()
        self.destroy()


# --- główne okno ------------------------------------------------------------


class App(tk.Tk):
    def __init__(self, data_dir: Path | None = None):
        super().__init__()
        self.withdraw()
        self.title(f"EveKonta {__version__}")
        self.geometry("1280x760")
        self.minsize(900, 500)
        self.data_dir = data_dir or default_data_dir()
        self.db = Db(self.data_dir / "evekonta.sqlite3")
        self._ui_queue: queue.Queue = queue.Queue()
        self._sync_thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._clipboard_token = 0
        self._next_auto = 0.0

        vault = ask_master_password(self, self.db)
        if vault is None:
            self.destroy()
            raise SystemExit(0)
        self.vault = vault
        self.syncer = self._make_syncer()
        self._build()
        self.deiconify()
        self.refresh_views()
        self._schedule_auto()
        self.after(100, self._drain_ui_queue)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # --- infrastruktura ------------------------------------------------------

    def ui(self, fn):
        """Wywołanie fn w wątku okna (z dowolnego wątku)."""
        self._ui_queue.put(fn)

    def _drain_ui_queue(self):
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
        except queue.Empty:
            pass
        self.after(100, self._drain_ui_queue)

    def sso_config(self) -> dict:
        try:
            port = int(self.db.get_setting("callback_port", "8765"))
        except ValueError:
            port = 8765
        secret_enc = self.db.get_setting("client_secret_enc")
        return {
            "client_id": self.db.get_setting("client_id").strip(),
            "client_secret": self.vault.decrypt(bytes.fromhex(secret_enc)) if secret_enc else "",
            "port": port,
        }

    def _make_syncer(self) -> Syncer:
        cfg = self.sso_config()
        return Syncer(self.db, self.vault, cfg["client_id"], cfg["client_secret"])

    def copy_secret(self, text: str, sensitive: bool):
        if not text:
            self.set_status("Puste pole – nic nie skopiowano.")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        if sensitive:
            self._clipboard_token += 1
            token = self._clipboard_token

            def clear():
                if token != self._clipboard_token:
                    return
                try:
                    if self.clipboard_get() == text:
                        self.clipboard_clear()
                        self.clipboard_append("")
                        self.set_status("Schowek wyczyszczony.")
                except tk.TclError:
                    pass

            self.after(CLIPBOARD_CLEAR_SECONDS * 1000, clear)
            self.set_status(f"Skopiowano. Schowek wyczyszczę za {CLIPBOARD_CLEAR_SECONDS} s.")
        else:
            self.set_status("Skopiowano.")

    def set_status(self, text: str):
        self.status_var.set(text)

    # --- budowa okna ---------------------------------------------------------

    def _build(self):
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=22)

        top = ttk.Frame(self, padding=(8, 6))
        top.pack(fill="x")
        self.refresh_btn = ttk.Button(top, text="⟳ Odśwież wszystkie postacie", command=self.start_sync)
        self.refresh_btn.pack(side="left")
        self.cancel_btn = ttk.Button(top, text="Przerwij", command=self._cancel.set, state="disabled")
        self.cancel_btn.pack(side="left", padx=4)
        self.progress = ttk.Progressbar(top, length=260, mode="determinate")
        self.progress.pack(side="left", padx=8)
        self.last_sync_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.last_sync_var).pack(side="right")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=4)
        self._build_alerts_tab()
        self._build_chars_tab()
        self._build_wealth_tab()
        self._build_accounts_tab()
        self._build_settings_tab()

        self.status_var = tk.StringVar(value=f"Baza: {self.db.path}")
        ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w", padding=(6, 2)).pack(
            fill="x", side="bottom")

    def _build_alerts_tab(self):
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="Uwagi")
        self.alerts_summary = tk.StringVar()
        ttk.Label(tab, textvariable=self.alerts_summary, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=4)
        self.alerts_table = Table(tab, [("severity", "Ważność", 80), ("account", "Konto", 160),
                                        ("character", "Postać", 180), ("what", "Co", 420), ("when", "Kiedy", 140)])
        self.alerts_table.pack(fill="both", expand=True)
        self.alerts_table.tree.tag_configure("PILNE", background="#f8d7da")
        self.alerts_table.tree.tag_configure("WKRÓTCE", background="#fff3cd")

    def _build_chars_tab(self):
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="Postacie")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=4)
        ttk.Button(bar, text="Dodaj postać…", command=lambda: self.add_character(None)).pack(side="left")
        ttk.Button(bar, text="Przypisz do konta…", command=self.assign_character).pack(side="left", padx=4)
        ttk.Button(bar, text="Odśwież zaznaczone", command=self.sync_selected).pack(side="left")
        ttk.Button(bar, text="Zaloguj ponownie", command=self.relogin_selected).pack(side="left", padx=4)
        ttk.Button(bar, text="Usuń postać", command=self.delete_character).pack(side="left")
        self.char_filter = tk.StringVar()
        self.char_filter.trace_add("write", lambda *_: self.refresh_chars())
        ttk.Entry(bar, textvariable=self.char_filter, width=30).pack(side="right")
        ttk.Label(bar, text="Szukaj:").pack(side="right", padx=4)
        self.chars_table = Table(tab, [
            ("account", "Konto", 130), ("character", "Postać", 160), ("sp", "SP", 70),
            ("queue", "Kolejka kończy się", 120), ("training", "Trenuje", 190), ("wallet", "Portfel", 85),
            ("assets", "Assety", 85), ("jobs", "Joby gotowe/wszystkie", 80), ("pi", "PI (najbliższy)", 120),
            ("system", "System", 100), ("status", "Status", 160)])
        self.chars_table.pack(fill="both", expand=True)
        self.chars_table.tree.tag_configure("bad", background="#f8d7da")

    def _build_wealth_tab(self):
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="Majątek")
        self.totals_var = tk.StringVar()
        ttk.Label(tab, textvariable=self.totals_var, font=("Segoe UI", 11, "bold"), justify="left").pack(
            anchor="w", pady=6)
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=4)
        ttk.Label(bar, text="Gdzie jest… (nazwa przedmiotu/statku):").pack(side="left")
        self.item_query = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.item_query, width=40)
        entry.pack(side="left", padx=4)
        entry.bind("<Return>", lambda e: self.search_items())
        ttk.Button(bar, text="Szukaj", command=self.search_items).pack(side="left")
        self.items_summary = tk.StringVar()
        ttk.Label(bar, textvariable=self.items_summary).pack(side="left", padx=10)
        self.items_table = Table(tab, [("item", "Przedmiot", 240), ("qty", "Ilość", 70), ("value", "Wartość", 90),
                                       ("character", "Postać", 160), ("account", "Konto", 130),
                                       ("location", "Lokacja", 330)])
        self.items_table.pack(fill="both", expand=True)
        ttk.Label(tab, foreground="#666", text=(
            "Wartość wg średnich cen z ESI (/markets/prices). Kopie blueprintów liczone jako 0.")).pack(anchor="w")

    def _build_accounts_tab(self):
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="Konta")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=4)
        ttk.Button(bar, text="Nowe konto", command=lambda: AccountDialog(self, None)).pack(side="left")
        ttk.Button(bar, text="Edytuj", command=self.edit_account).pack(side="left", padx=4)
        ttk.Button(bar, text="Usuń", command=self.delete_account).pack(side="left")
        ttk.Button(bar, text="Ustaw hasło zaznaczonym…", command=self.set_password_selected).pack(side="left", padx=4)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(bar, text="Kopiuj login", command=lambda: self.copy_account_field("login")).pack(side="left")
        ttk.Button(bar, text="Kopiuj hasło", command=lambda: self.copy_account_field("password")).pack(
            side="left", padx=4)
        ttk.Button(bar, text="Kopiuj e-mail", command=lambda: self.copy_account_field("email")).pack(side="left")
        ttk.Button(bar, text="Kopiuj hasło maila",
                   command=lambda: self.copy_account_field("email_password")).pack(side="left", padx=4)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(bar, text="Dodaj postać do konta…", command=self.add_character_to_selected).pack(side="left")

        bar2 = ttk.Frame(tab)
        bar2.pack(fill="x", pady=4)
        ttk.Label(bar2, text="Szukaj (nazwa, login, e-mail, postać, notatki):").pack(side="left")
        self.account_filter = tk.StringVar()
        self.account_filter.trace_add("write", lambda *_: self.refresh_accounts())
        ttk.Entry(bar2, textvariable=self.account_filter, width=40).pack(side="left", padx=4)
        ttk.Button(bar2, text="Eksport CSV…", command=self.export_csv).pack(side="right")
        ttk.Button(bar2, text="Import CSV…", command=self.import_csv).pack(side="right", padx=4)
        ttk.Button(bar2, text="Wklej konta…", command=lambda: PasteAccountsDialog(self)).pack(side="right")
        self.accounts_count = tk.StringVar()
        ttk.Label(bar2, textvariable=self.accounts_count).pack(side="left", padx=10)

        self.accounts_table = Table(tab, [("name", "Nazwa", 150), ("login", "Login", 160), ("email", "E-mail", 220),
                                          ("characters", "Postacie", 330), ("omega_until", "Omega do", 90),
                                          ("notes", "Notatki", 200)])
        self.accounts_table.pack(fill="both", expand=True)
        self.accounts_table.tree.bind("<Double-1>", lambda e: self.edit_account())
        self.accounts_table.tree.bind(
            "<Control-a>", lambda e: self.accounts_table.tree.selection_set(self.accounts_table.tree.get_children()))

    def _build_settings_tab(self):
        tab = ttk.Frame(self.nb, padding=12)
        self.nb.add(tab, text="Ustawienia")
        tab.columnconfigure(1, weight=1)
        self.set_client_id, _ = labeled_entry(tab, 0, "Client ID aplikacji EVE", width=50)
        self.set_secret, _ = labeled_entry(tab, 1, "Secret Key (opcjonalnie)", show="•", width=50)
        self.set_port, _ = labeled_entry(tab, 2, "Port callbacku", width=10)
        self.set_auto, _ = labeled_entry(tab, 3, "Auto-odświeżanie co (min, 0 = wył.)", width=10)
        self.set_workers, _ = labeled_entry(tab, 4, "Równoległe pobieranie (1–10)", width=10)
        cfg = self.sso_config()
        self.set_client_id.set(cfg["client_id"])
        self.set_secret.set(cfg["client_secret"])
        self.set_port.set(str(cfg["port"]))
        self.set_auto.set(self.db.get_setting("auto_minutes", "30"))
        self.set_workers.set(self.db.get_setting("workers", "6"))
        btns = ttk.Frame(tab)
        btns.grid(row=5, column=1, sticky="w", padx=6, pady=8)
        ttk.Button(btns, text="Zapisz ustawienia", command=self.save_settings).pack(side="left")
        ttk.Button(btns, text="Zmień hasło główne…", command=self.change_master_password).pack(side="left", padx=6)
        ttk.Button(btns, text="Sprawdź aplikację EVE", command=self.check_eve_app).pack(side="left")

        help_text = (
            "Jak przygotować logowanie postaci (raz):\n"
            f"1. Wejdź na {DEV_PORTAL} i utwórz aplikację (Create New Application).\n"
            "2. Connection Type: Authentication & API Access. Zaznacz uprawnienia z listy poniżej.\n"
            "3. Callback URL: http://localhost:<port>/callback (domyślnie http://localhost:8765/callback).\n"
            "4. Skopiuj Client ID tutaj i zapisz. Secret Key wpisz tylko, jeśli chcesz (PKCE działa bez niego).\n\n"
            "Hasło do gry nie jest potrzebne do pobierania danych: każdą postać logujesz raz, a aplikacja\n"
            "trzyma zaszyfrowany token. Wszystko jest zapisane tylko na tym komputerze:\n"
            f"{self.db.path}\n\nWymagane uprawnienia (scopes):\n" + "\n".join(sso.SCOPES)
        )
        txt = tk.Text(tab, height=20, wrap="word", relief="flat", background=self.cget("background"),
                      font="TkDefaultFont")
        txt.insert("1.0", help_text)
        txt.configure(state="disabled")
        txt.grid(row=6, column=0, columnspan=2, sticky="nsew", padx=6)
        tab.rowconfigure(6, weight=1)
        links = ttk.Frame(tab)
        links.grid(row=7, column=0, columnspan=2, sticky="w", padx=6)
        ttk.Button(links, text="Otwórz developers.eveonline.com",
                   command=lambda: webbrowser.open(DEV_PORTAL)).pack(side="left")
        ttk.Button(links, text="Kopiuj listę uprawnień",
                   command=lambda: self.copy_secret(" ".join(sso.SCOPES), False)).pack(side="left", padx=6)
        ttk.Button(links, text="Kopiuj callback URL",
                   command=lambda: self.copy_secret(sso.redirect_uri(self.sso_config()["port"]), False)).pack(
            side="left")

    # --- odświeżanie widoków -------------------------------------------------

    def refresh_views(self):
        self.refresh_alerts()
        self.refresh_chars()
        self.refresh_wealth()
        self.refresh_accounts()
        last = self.db.query("SELECT MAX(last_sync) FROM characters")[0][0]
        self.last_sync_var.set(f"Ostatnie pobranie: {self._local_time(last)}" if last else "Jeszcze nic nie pobrano")

    @staticmethod
    def _local_time(iso: str) -> str:
        try:
            dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            return dt.astimezone().strftime("%d.%m %H:%M")
        except (TypeError, ValueError):
            return iso or ""

    def refresh_alerts(self):
        now = datetime.now().astimezone()
        alerts = reports.build_alerts(self.db)
        rows = [{"severity": a.severity_label, "account": a.account, "character": a.character, "what": a.what,
                 "when": reports.fmt_delta(a.when, now) if a.when else "", "_sort": {"severity": a.severity}}
                for a in alerts]
        self.alerts_table.set_rows(rows, tag_key="severity")
        urgent = sum(1 for a in alerts if a.severity == 0)
        soon = sum(1 for a in alerts if a.severity == 1)
        self.alerts_summary.set(f"Pilne: {urgent}   Wkrótce: {soon}" if alerts else "Brak uwag. Wszystko gra.")
        self.nb.tab(0, text=f"Uwagi ({urgent})" if urgent else "Uwagi")

    def refresh_chars(self):
        rows = reports.character_rows(self.db)
        text = self.char_filter.get().strip().lower() if hasattr(self, "char_filter") else ""
        if text:
            rows = [r for r in rows if text in r["character"].lower() or text in r["account"].lower()
                    or text in r["system"].lower()]
        for r in rows:
            r["_tag"] = "bad" if r["status"] != "OK" else ""
        self.chars_table.set_rows(rows, iid_key="character_id", tag_key="_tag")

    def refresh_wealth(self):
        t = reports.totals(self.db)
        self.totals_var.set(
            f"Konta: {t['accounts']}    Postacie: {t['chars']}    SP razem: {reports.fmt_sp(t['sp'])}\n"
            f"Portfele: {reports.fmt_isk(t['wallet'])} ISK    Assety: {reports.fmt_isk(t['assets'])} ISK    "
            f"Razem: {reports.fmt_isk(t['total'])} ISK")

    def refresh_accounts(self):
        rows = [dict(r) for r in self.db.list_accounts(self.account_filter.get().strip())]
        self.accounts_table.set_rows(rows, iid_key="id")
        self.accounts_count.set(f"{len(rows)} kont")

    def search_items(self):
        rows = reports.find_items(self.db, self.item_query.get())
        total = sum(r["value"] for r in rows)
        for r in rows:
            r["_sort"] = {"value": r["value"], "qty": r["qty"]}
            r["value"] = reports.fmt_isk(r["value"])
        self.items_table.set_rows(rows)
        self.items_summary.set(f"{len(rows)} wyników, razem {reports.fmt_isk(total)} ISK" if rows else "Brak wyników")

    # --- akcje: konta --------------------------------------------------------

    def _selected_account_id(self) -> int | None:
        rows = self.accounts_table.selected_rows()
        if not rows:
            messagebox.showinfo("Konta", "Zaznacz konto na liście.", parent=self)
            return None
        return int(rows[0]["id"])

    def edit_account(self):
        acc_id = self._selected_account_id()
        if acc_id is not None:
            AccountDialog(self, acc_id)

    def delete_account(self):
        rows = self.accounts_table.selected_rows()
        if not rows:
            messagebox.showinfo("Konta", "Zaznacz konta do usunięcia (Ctrl/Shift = kilka, Ctrl+A = wszystkie).",
                                parent=self)
            return
        label = (rows[0]["name"] or rows[0]["login"]) if len(rows) == 1 else f"{len(rows)} kont"
        if messagebox.askyesno("Usuń konta", f"Usunąć {label}?\n"
                               "Postacie zostaną, ale bez przypisanego konta.", parent=self):
            for r in rows:
                self.db.delete_account(int(r["id"]))
            self.refresh_views()

    def copy_account_field(self, field: str):
        acc_id = self._selected_account_id()
        if acc_id is None:
            return
        acc = self.db.get_account(acc_id)
        if field == "password":
            self.copy_secret(self.vault.decrypt(acc["password_enc"]), True)
        elif field == "email_password":
            self.copy_secret(self.vault.decrypt(acc["email_password_enc"]), True)
        else:
            self.copy_secret(acc[field], False)

    def add_character_to_selected(self):
        acc_id = self._selected_account_id()
        if acc_id is not None:
            self.add_character(acc_id)

    def set_password_selected(self):
        rows = self.accounts_table.selected_rows()
        if not rows:
            messagebox.showinfo("Konta", "Zaznacz konta (Ctrl+A = wszystkie, Ctrl/Shift = kilka).", parent=self)
            return
        pw = simpledialog.askstring("Ustaw hasło", f"Nowe hasło EVE dla {len(rows)} kont:", show="*", parent=self)
        if not pw:
            return
        enc = self.vault.encrypt(pw)
        for r in rows:
            self.db.update_account(int(r["id"]), password_enc=enc)
        self.refresh_views()
        self.set_status(f"Ustawiono hasło dla {len(rows)} kont.")

    def enabled_scopes(self) -> list[str]:
        disabled = set(self.db.get_setting("disabled_scopes").split())
        return [s for s in sso.SCOPES if s not in disabled]

    def check_eve_app(self):
        if self.set_client_id.get().strip() != self.sso_config()["client_id"]:
            self.save_settings()
        cfg = self.sso_config()
        if not cfg["client_id"]:
            messagebox.showwarning("EveKonta", "Najpierw wpisz Client ID i zapisz ustawienia.", parent=self)
            return
        self.set_status("Sprawdzam aplikację EVE…")

        def work():
            try:
                result = sso.check_app(cfg["client_id"], cfg["port"])
            except OSError as exc:
                msg = f"Brak połączenia z serwerem logowania EVE: {exc}"
                self.ui(lambda: messagebox.showerror("Sprawdzenie aplikacji EVE", msg, parent=self))
                return
            self.ui(lambda: self._show_app_check(result, cfg["port"]))

        threading.Thread(target=work, daemon=True).start()

    def _show_app_check(self, result: sso.AppCheck, port: int):
        text = sso.explain_check(result, port)
        self.set_status("Sprawdzenie aplikacji EVE zakończone.")
        if result.ok:
            self.db.set_setting("disabled_scopes", "")
            messagebox.showinfo("Sprawdzenie aplikacji EVE", text, parent=self)
        elif result.error == "invalid_scope" and result.rejected:
            if messagebox.askyesno("Sprawdzenie aplikacji EVE", text + (
                    "\n\nNajlepiej zaznaczyć je na stronie EVE. Czy na razie logować postacie BEZ nich? "
                    "(dane z tych uprawnień nie będą pobierane)"), parent=self):
                self.db.set_setting("disabled_scopes", " ".join(result.rejected))
        else:
            messagebox.showerror("Sprawdzenie aplikacji EVE", text, parent=self)

    def import_csv(self):
        messagebox.showinfo("Import CSV", (
            "Plik CSV (np. zapisany z Excela) z nagłówkiem w pierwszym wierszu.\n"
            "Rozpoznawane kolumny: nazwa, login, haslo, email, haslo_email, omega, notatki.\n"
            "Konta z loginem, który już jest w bazie, zostaną pominięte.\n\n"
            "Po imporcie usuń plik CSV z dysku – hasła są w nim jawne."), parent=self)
        path = filedialog.askopenfilename(parent=self, filetypes=[("CSV", "*.csv"), ("Wszystkie", "*.*")])
        if not path:
            return
        try:
            added, skipped = csvio.import_accounts(self.db, self.vault, Path(path))
        except (ValueError, OSError) as exc:
            messagebox.showerror("Import CSV", str(exc), parent=self)
            return
        self.refresh_views()
        messagebox.showinfo("Import CSV", f"Dodano: {added}\nPominięto (duplikaty): {skipped}", parent=self)

    def export_csv(self):
        with_pw = messagebox.askyesnocancel(
            "Eksport CSV", "Dołączyć hasła?\n\nTak = plik z jawnymi hasłami (trzymaj go bezpiecznie!)\n"
                           "Nie = bez haseł", parent=self)
        if with_pw is None:
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile="konta-eve.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            count = csvio.export_accounts(self.db, self.vault, Path(path), bool(with_pw))
            self.set_status(f"Zapisano {count} kont do {path}")

    # --- akcje: postacie -----------------------------------------------------

    def add_character(self, account_id: int | None):
        if account_id is None:
            account_id = self._pick_account("Do którego konta należy postać?")
            if account_id == -1:
                return
        AddCharacterDialog(self, account_id)

    def _pick_account(self, prompt: str) -> int | None:
        """Zwraca ID konta, None (bez konta) albo -1 (anulowano)."""
        accounts = self.db.list_accounts()
        labels = ["(bez konta)"] + [f"{a['name'] or a['login'] or a['email']}  [{a['login']}]" for a in accounts]
        ids = [None] + [a["id"] for a in accounts]
        win = tk.Toplevel(self)
        win.title("Wybierz konto")
        win.transient(self)
        ttk.Label(win, text=prompt, padding=8).pack(anchor="w")
        var = tk.StringVar(value=labels[0])
        combo = ttk.Combobox(win, values=labels, textvariable=var, width=50, state="readonly")
        combo.pack(padx=8, pady=4)
        result = {"value": -1}

        def ok():
            result["value"] = ids[labels.index(var.get())]
            win.destroy()

        ttk.Button(win, text="OK", command=ok).pack(pady=8)
        win.grab_set()
        self.wait_window(win)
        return result["value"]

    def _selected_char_ids(self) -> list[int]:
        rows = self.chars_table.selected_rows()
        if not rows:
            messagebox.showinfo("Postacie", "Zaznacz postać (Ctrl/Shift = kilka).", parent=self)
        return [int(r["character_id"]) for r in rows]

    def assign_character(self):
        ids = self._selected_char_ids()
        if not ids:
            return
        acc = self._pick_account(f"Przypisz {len(ids)} postać/postacie do konta:")
        if acc == -1:
            return
        for cid in ids:
            self.db.set_character_account(cid, acc)
        self.refresh_views()

    def delete_character(self):
        ids = self._selected_char_ids()
        if ids and messagebox.askyesno("Usuń", f"Usunąć {len(ids)} postać/postacie z aplikacji?", parent=self):
            for cid in ids:
                self.db.delete_character(cid)
            self.refresh_views()

    def relogin_selected(self):
        ids = self._selected_char_ids()
        if ids:
            acc = self.db.query("SELECT account_id FROM characters WHERE character_id=?", (ids[0],))[0][0]
            AddCharacterDialog(self, acc)

    def sync_selected(self):
        ids = self._selected_char_ids()
        if ids:
            self.start_sync(ids)

    # --- pobieranie ----------------------------------------------------------

    def start_sync(self, only: list[int] | None = None):
        if self._sync_thread and self._sync_thread.is_alive():
            return
        if not self.sso_config()["client_id"]:
            self.nb.select(4)
            messagebox.showinfo("EveKonta", "Najpierw wpisz Client ID w Ustawieniach.", parent=self)
            return
        self._cancel.clear()
        self.refresh_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.configure(value=0)
        workers = self._int_setting("workers", 6, 1, 10)

        def progress(done, total, name):
            self.ui(lambda: (self.progress.configure(maximum=max(total, 1), value=done),
                             self.set_status(f"Pobieram {done}/{total}: {name}")))

        def work():
            started = time.monotonic()
            try:
                if only:
                    errors = {}
                    for i, cid in enumerate(only, 1):
                        err = self.syncer.sync_character(cid)
                        if err:
                            errors[str(cid)] = err
                        progress(i, len(only), str(cid))
                    self.syncer.resolve_names()
                    self.syncer.compute_values()
                else:
                    errors = self.syncer.sync_all(progress, workers=workers, cancel=self._cancel)
                msg = f"Gotowe w {time.monotonic() - started:.0f} s."
                if errors:
                    msg += f" Problemy: {len(errors)} (szczegóły w kolumnie Status)."
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                msg = f"Błąd pobierania: {type(exc).__name__}: {exc}"
            self.ui(lambda: self._sync_finished(msg))

        self._sync_thread = threading.Thread(target=work, daemon=True)
        self._sync_thread.start()

    def _sync_finished(self, msg: str):
        self.refresh_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.set_status(msg)
        self.refresh_views()
        if self.item_query.get().strip():
            self.search_items()

    def _int_setting(self, key, default, lo, hi) -> int:
        try:
            return max(lo, min(hi, int(self.db.get_setting(key, str(default)))))
        except ValueError:
            return default

    def _schedule_auto(self):
        minutes = self._int_setting("auto_minutes", 30, 0, 1440)
        has_chars = self.db.query("SELECT COUNT(*) FROM characters WHERE token_ok=1")[0][0]
        if minutes and has_chars and time.monotonic() >= self._next_auto and self.sso_config()["client_id"]:
            if self._next_auto:  # nie od razu przy starcie, chyba że dane są stare
                self.start_sync()
            else:
                last = self.db.query("SELECT MIN(last_sync) FROM characters WHERE token_ok=1")[0][0]
                last_dt = datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if last else None
                if not last_dt or (datetime.now(timezone.utc) - last_dt).total_seconds() > minutes * 60:
                    self.start_sync()
            self._next_auto = time.monotonic() + minutes * 60
        elif not self._next_auto:
            self._next_auto = time.monotonic() + max(minutes, 1) * 60
        self.after(60_000, self._schedule_auto)

    # --- ustawienia ----------------------------------------------------------

    def save_settings(self):
        try:
            port = int(self.set_port.get())
            assert 1024 <= port <= 65535
        except (ValueError, AssertionError):
            messagebox.showwarning("Ustawienia", "Port musi być liczbą 1024–65535.", parent=self)
            return
        self.db.set_setting("client_id", self.set_client_id.get().strip())
        secret = self.set_secret.get().strip()
        self.db.set_setting("client_secret_enc", self.vault.encrypt(secret).hex() if secret else "")
        self.db.set_setting("callback_port", str(port))
        self.db.set_setting("auto_minutes", self.set_auto.get().strip() or "0")
        self.db.set_setting("workers", self.set_workers.get().strip() or "6")
        self.syncer = self._make_syncer()
        self.set_status("Ustawienia zapisane.")

    def change_master_password(self):
        if self._sync_thread and self._sync_thread.is_alive():
            messagebox.showinfo("Hasło główne", "Poczekaj, aż skończy się pobieranie.", parent=self)
            return
        old = simpledialog.askstring("Hasło główne", "Obecne hasło główne:", show="*", parent=self)
        if old is None:
            return
        try:
            Vault.unlock(old, bytes.fromhex(self.db.get_setting("master_salt")),
                         self.db.get_setting("master_verifier"))
        except WrongPassword:
            messagebox.showerror("Hasło główne", "Złe hasło.", parent=self)
            return
        new = simpledialog.askstring("Hasło główne", "Nowe hasło główne (min. 8 znaków):", show="*", parent=self)
        if not new or len(new) < 8:
            return
        if simpledialog.askstring("Hasło główne", "Powtórz nowe hasło:", show="*", parent=self) != new:
            messagebox.showwarning("Hasło główne", "Hasła się różnią.", parent=self)
            return
        salt = new_salt()
        key = derive_key(new, salt)
        new_vault = Vault(key)
        old_vault = self.vault
        db = self.db
        with db.lock:
            c = db.conn
            for row in c.execute("SELECT id, password_enc, email_password_enc FROM accounts").fetchall():
                c.execute("UPDATE accounts SET password_enc=?, email_password_enc=? WHERE id=?",
                          (new_vault.encrypt(old_vault.decrypt(row[1])),
                           new_vault.encrypt(old_vault.decrypt(row[2])), row[0]))
            for row in c.execute("SELECT character_id, refresh_enc FROM characters").fetchall():
                c.execute("UPDATE characters SET refresh_enc=? WHERE character_id=?",
                          (new_vault.encrypt(old_vault.decrypt(row[1])), row[0]))
            secret_hex = db.get_setting("client_secret_enc")
            if secret_hex:
                secret = old_vault.decrypt(bytes.fromhex(secret_hex))
                c.execute("UPDATE settings SET value=? WHERE key='client_secret_enc'",
                          (new_vault.encrypt(secret).hex(),))
            c.execute("UPDATE settings SET value=? WHERE key='master_salt'", (salt.hex(),))
            c.execute("UPDATE settings SET value=? WHERE key='master_verifier'", (verifier_for(key),))
            c.commit()
        self.vault = new_vault
        self.syncer = self._make_syncer()
        messagebox.showinfo("Hasło główne", "Hasło główne zmienione.", parent=self)

    def on_close(self):
        self._cancel.set()
        self.db.close()
        self.destroy()


def main():
    try:
        app = App()
    except SystemExit:
        return
    app.mainloop()
