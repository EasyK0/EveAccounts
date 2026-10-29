"""UI language: English by default, Polish as the second language.

Texts are written in English in the code and wrapped in tr(). Polish
translations live in PL, keyed by the English text.
"""

from __future__ import annotations

DEFAULT_LANGUAGE = "en"
LANGUAGES = {"en": "English", "pl": "Polski"}

_language = DEFAULT_LANGUAGE


def set_language(code: str) -> None:
    global _language
    _language = code if code in LANGUAGES else DEFAULT_LANGUAGE


def get_language() -> str:
    return _language


def tr(text: str, /, **values) -> str:
    """Returns text in the current language, with {placeholders} filled from values."""
    if _language == "pl":
        text = PL.get(text, text)
    return text.format(**values) if values else text


# Polish texts, keyed by the English original
PL: dict[str, str] = {
    # --- crypto, csv
    "Unknown encrypted data format": "Nieznany format zaszyfrowanych danych",
    "Damaged data or wrong master password": "Dane uszkodzone albo złe hasło główne",
    "Cannot decrypt (different Windows account or wrong master password)":
        "Nie da się odszyfrować (inne konto Windows albo złe hasło główne)",
    "Wrong master password": "Złe hasło główne",
    "DPAPI: encryption failed": "DPAPI: nie udało się zaszyfrować",
    "The file needs a header row with a 'login' or 'email' column":
        "Plik musi mieć nagłówek z kolumną 'login' albo 'email'",
    # --- master password
    "EveKonta – first start": "EveKonta – pierwsze uruchomienie",
    "Set a master password. It encrypts account passwords and character tokens.\n\n"
    "Remember it: without it the saved passwords cannot be read.":
        "Ustaw hasło główne. Szyfruje ono hasła do kont i tokeny postaci.\n\n"
        "Zapamiętaj je: bez niego nie da się odczytać zapisanych haseł.",
    "Master password": "Hasło główne",
    "Master password:": "Hasło główne:",
    "Current master password:": "Obecne hasło główne:",
    "New master password (min. 8 characters):": "Nowe hasło główne (min. 8 znaków):",
    "Repeat the master password:": "Powtórz hasło główne:",
    "Repeat the new password:": "Powtórz nowe hasło:",
    "The password needs at least 8 characters.": "Hasło musi mieć co najmniej 8 znaków.",
    "The passwords do not match.": "Hasła się różnią.",
    "Wrong master password.": "Złe hasło główne.",
    "Wrong password.": "Złe hasło.",
    "Master password changed.": "Hasło główne zmienione.",
    "Wait until the fetch finishes.": "Poczekaj, aż skończy się pobieranie.",
    # --- account dialog
    "New account": "Nowe konto",
    "Edit account": "Edycja konta",
    "Account": "Konto",
    "Name (anything)": "Nazwa (dowolna)",
    "EVE login": "Login EVE",
    "EVE password": "Hasło EVE",
    "E-mail": "E-mail",
    "E-mail password": "Hasło do maila",
    "Omega until (YYYY-MM-DD)": "Omega do (RRRR-MM-DD)",
    "Notes": "Notatki",
    "Show passwords": "Pokaż hasła",
    "Save": "Zapisz",
    "Cancel": "Anuluj",
    "Close": "Zamknij",
    "Enter at least a login, e-mail or name.": "Wpisz przynajmniej login, e-mail albo nazwę.",
    "Omega date as YYYY-MM-DD (e.g. 2026-11-30).": "Data Omegi w formacie RRRR-MM-DD (np. 2026-11-30).",
    # --- paste accounts
    "Paste accounts": "Wklej konta",
    "Paste a list of accounts, one per line. Separate fields any way: ; : | , tab or space.\n"
    "Examples:   login;password;mail@wp.pl     login:password     mail@wp.pl password     login;mail@wp.pl\n"
    "The field with @ is the e-mail, the first other one is the login, then the password, the rest goes to notes.":
        "Wklej listę kont, jedno konto w linii. Pola rozdziel dowolnie: ; : | , tabulatorem albo spacją.\n"
        "Przykłady:   login;hasło;mail@wp.pl     login:hasło     mail@wp.pl hasło     login;mail@wp.pl\n"
        "Pole z @ to e-mail, pierwsze inne to login, potem hasło, reszta trafia do notatek.",
    "List without passwords (login + e-mail, I will add passwords later)":
        "Lista bez haseł (login + e-mail, hasła dopiszę później)",
    "Shared password for accounts without one (optional):": "Wspólne hasło dla kont bez hasła (opcjonalnie):",
    "The preview appears after pasting.": "Podgląd pojawi się po wklejeniu.",
    "Login": "Login",
    "Password": "Hasło",
    "(none)": "(brak)",
    "Add accounts": "Dodaj konta",
    "Recognized {n} accounts": "Rozpoznano {n} kont",
    ", without password: {n}": ", bez hasła: {n}",
    "Nothing recognized.": "Nic nie rozpoznano.",
    "Added: {added}\nSkipped (login already there): {skipped}":
        "Dodano: {added}\nPominięto (login już był): {skipped}",
    # --- add character
    "Add character (EVE SSO)": "Dodaj postać (EVE SSO)",
    "(no assigned account)": "(bez przypisanego konta)",
    "Account: {label}": "Konto: {label}",
    "1. Click \"Open login\" (or copy the link into a private/incognito window when the browser is logged in to "
    "another account).\n2. Log in to this account and pick the character.\n"
    "3. Back here you can add the next character of this account right away.":
        "1. Kliknij „Otwórz logowanie” (albo skopiuj link do okna prywatnego/incognito, gdy przeglądarka jest "
        "zalogowana na inne konto).\n2. Zaloguj się na to konto i wybierz postać.\n"
        "3. Po powrocie możesz od razu dodać kolejną postać z tego konta.",
    "Copy login": "Kopiuj login",
    "Copy password": "Kopiuj hasło",
    "Open login": "Otwórz logowanie",
    "Copy link (incognito)": "Kopiuj link (incognito)",
    "First enter the Client ID on the Settings tab.": "Najpierw wpisz Client ID w zakładce Ustawienia.",
    "Port {port} is in use. Change it in Settings (and in the app on developers.eveonline.com).":
        "Port {port} jest zajęty. Zmień go w Ustawieniach (i w aplikacji na developers.eveonline.com).",
    "Waiting for the login in the browser…": "Czekam na zalogowanie w przeglądarce…",
    "Link copied. Paste it into a private browser window and log in…":
        "Link skopiowany. Wklej go w okno prywatne przeglądarki i zaloguj się…",
    "Added: {name}. Fetching data… You can add another character.":
        "Dodano: {name}. Pobieram dane… Możesz dodać kolejną postać.",
    "Added and fetched: {name}. You can add another character.":
        "Dodano i pobrano: {name}. Możesz dodać kolejną postać.",
    "Failed: {msg}": "Nie udało się: {msg}",
    "Error: {msg}": "Błąd: {msg}",
    # --- main window
    "Empty field – nothing copied.": "Puste pole – nic nie skopiowano.",
    "Clipboard cleared.": "Schowek wyczyszczony.",
    "Copied. The clipboard will be cleared in {s} s.": "Skopiowano. Schowek wyczyszczę za {s} s.",
    "Copied.": "Skopiowano.",
    "⟳ Refresh all characters": "⟳ Odśwież wszystkie postacie",
    "Stop": "Przerwij",
    "Database: {path}": "Baza: {path}",
    "Alerts": "Uwagi",
    "Characters": "Postacie",
    "Wealth": "Majątek",
    "Accounts": "Konta",
    "Settings": "Ustawienia",
    "Severity": "Ważność",
    "Character": "Postać",
    "What": "Co",
    "When": "Kiedy",
    "Add character…": "Dodaj postać…",
    "Assign to account…": "Przypisz do konta…",
    "Refresh selected": "Odśwież zaznaczone",
    "Log in again": "Zaloguj ponownie",
    "Remove character": "Usuń postać",
    "Search:": "Szukaj:",
    "Search": "Szukaj",
    "Queue ends": "Kolejka kończy się",
    "Training": "Trenuje",
    "Wallet": "Portfel",
    "Assets": "Assety",
    "Jobs ready/all": "Joby gotowe/wszystkie",
    "PI (next)": "PI (najbliższy)",
    "System": "System",
    "Status": "Status",
    "Where is… (item/ship name):": "Gdzie jest… (nazwa przedmiotu/statku):",
    "Item": "Przedmiot",
    "Qty": "Ilość",
    "Value": "Wartość",
    "Location": "Lokacja",
    "Value from ESI average prices (/markets/prices). Blueprint copies count as 0.":
        "Wartość wg średnich cen z ESI (/markets/prices). Kopie blueprintów liczone jako 0.",
    "Edit": "Edytuj",
    "Delete": "Usuń",
    "Set password for selected…": "Ustaw hasło zaznaczonym…",
    "Copy e-mail": "Kopiuj e-mail",
    "Copy e-mail password": "Kopiuj hasło maila",
    "Add character to account…": "Dodaj postać do konta…",
    "Search (name, login, e-mail, character, notes):": "Szukaj (nazwa, login, e-mail, postać, notatki):",
    "Export CSV…": "Eksport CSV…",
    "Import CSV…": "Import CSV…",
    "Paste accounts…": "Wklej konta…",
    "Name": "Nazwa",
    "Omega until": "Omega do",
    "EVE app Client ID": "Client ID aplikacji EVE",
    "Secret Key (optional)": "Secret Key (opcjonalnie)",
    "Callback port": "Port callbacku",
    "Auto refresh every (min, 0 = off)": "Auto-odświeżanie co (min, 0 = wył.)",
    "Parallel downloads (1–10)": "Równoległe pobieranie (1–10)",
    "Save settings": "Zapisz ustawienia",
    "Change master password…": "Zmień hasło główne…",
    "Check EVE app": "Sprawdź aplikację EVE",
    "How to set up character login (once):\n"
    "1. Go to {portal} and create an app (Create New Application).\n"
    "2. Connection Type: Authentication & API Access. Tick the scopes from the list below.\n"
    "3. Callback URL: http://localhost:<port>/callback (default http://localhost:8765/callback).\n"
    "4. Copy the Client ID here and save. Enter the Secret Key only if you want to (PKCE works without it).\n\n"
    "The game password is not needed to fetch data: each character logs in once and the app\n"
    "keeps an encrypted token. Everything is stored only on this computer:\n"
    "{path}\n\nRequired scopes:\n":
        "Jak przygotować logowanie postaci (raz):\n"
        "1. Wejdź na {portal} i utwórz aplikację (Create New Application).\n"
        "2. Connection Type: Authentication & API Access. Zaznacz uprawnienia z listy poniżej.\n"
        "3. Callback URL: http://localhost:<port>/callback (domyślnie http://localhost:8765/callback).\n"
        "4. Skopiuj Client ID tutaj i zapisz. Secret Key wpisz tylko, jeśli chcesz (PKCE działa bez niego).\n\n"
        "Hasło do gry nie jest potrzebne do pobierania danych: każdą postać logujesz raz, a aplikacja\n"
        "trzyma zaszyfrowany token. Wszystko jest zapisane tylko na tym komputerze:\n"
        "{path}\n\nWymagane uprawnienia (scopes):\n",
    "Open developers.eveonline.com": "Otwórz developers.eveonline.com",
    "Copy scope list": "Kopiuj listę uprawnień",
    "Copy callback URL": "Kopiuj callback URL",
    "Last fetch: {time}": "Ostatnie pobranie: {time}",
    "Nothing fetched yet": "Jeszcze nic nie pobrano",
    "Urgent: {urgent}   Soon: {soon}": "Pilne: {urgent}   Wkrótce: {soon}",
    "No alerts. All good.": "Brak uwag. Wszystko gra.",
    "Accounts: {accounts}    Characters: {chars}    Total SP: {sp}\n"
    "Wallets: {wallet} ISK    Assets: {assets} ISK    Total: {total} ISK":
        "Konta: {accounts}    Postacie: {chars}    SP razem: {sp}\n"
        "Portfele: {wallet} ISK    Assety: {assets} ISK    Razem: {total} ISK",
    "{n} accounts": "{n} kont",
    "{n} results, {total} ISK in total": "{n} wyników, razem {total} ISK",
    "No results": "Brak wyników",
    "Select an account in the list.": "Zaznacz konto na liście.",
    "Select the accounts to delete (Ctrl/Shift = several, Ctrl+A = all).":
        "Zaznacz konta do usunięcia (Ctrl/Shift = kilka, Ctrl+A = wszystkie).",
    "Delete accounts": "Usuń konta",
    "Delete {label}?\nThe characters stay, but without an assigned account.":
        "Usunąć {label}?\nPostacie zostaną, ale bez przypisanego konta.",
    "Select accounts (Ctrl+A = all, Ctrl/Shift = several).": "Zaznacz konta (Ctrl+A = wszystkie, Ctrl/Shift = kilka).",
    "Set password": "Ustaw hasło",
    "New EVE password for {n} accounts:": "Nowe hasło EVE dla {n} kont:",
    "Password set for {n} accounts.": "Ustawiono hasło dla {n} kont.",
    "First enter the Client ID and save the settings.": "Najpierw wpisz Client ID i zapisz ustawienia.",
    "Checking the EVE app…": "Sprawdzam aplikację EVE…",
    "No connection to the EVE login server: {error}": "Brak połączenia z serwerem logowania EVE: {error}",
    "EVE app check": "Sprawdzenie aplikacji EVE",
    "EVE app check finished.": "Sprawdzenie aplikacji EVE zakończone.",
    "\n\nBest tick them on the EVE site. Log characters in WITHOUT them for now? "
    "(data from these scopes will not be fetched)":
        "\n\nNajlepiej zaznaczyć je na stronie EVE. Czy na razie logować postacie BEZ nich? "
        "(dane z tych uprawnień nie będą pobierane)",
    "Import CSV": "Import CSV",
    "A CSV file (e.g. saved from Excel) with a header in the first row.\n"
    "Recognized columns: name, login, password, email, email_password, omega, notes (Polish names work too).\n"
    "Accounts whose login is already in the database are skipped.\n\n"
    "Delete the CSV file after importing – the passwords in it are plain text.":
        "Plik CSV (np. zapisany z Excela) z nagłówkiem w pierwszym wierszu.\n"
        "Rozpoznawane kolumny: nazwa, login, haslo, email, haslo_email, omega, notatki "
        "(angielskie nazwy też działają).\n"
        "Konta z loginem, który już jest w bazie, zostaną pominięte.\n\n"
        "Po imporcie usuń plik CSV z dysku – hasła są w nim jawne.",
    "All files": "Wszystkie",
    "Added: {added}\nSkipped (duplicates): {skipped}": "Dodano: {added}\nPominięto (duplikaty): {skipped}",
    "Export CSV": "Eksport CSV",
    "Include passwords?\n\nYes = file with plain-text passwords (keep it safe!)\nNo = without passwords":
        "Dołączyć hasła?\n\nTak = plik z jawnymi hasłami (trzymaj go bezpiecznie!)\nNie = bez haseł",
    "eve-accounts.csv": "konta-eve.csv",
    "Saved {n} accounts to {path}": "Zapisano {n} kont do {path}",
    "Which account does the character belong to?": "Do którego konta należy postać?",
    "(no account)": "(bez konta)",
    "Choose account": "Wybierz konto",
    "Select a character (Ctrl/Shift = several).": "Zaznacz postać (Ctrl/Shift = kilka).",
    "Assign {n} character(s) to account:": "Przypisz {n} postać/postacie do konta:",
    "Remove": "Usuń",
    "Remove {n} character(s) from the app?": "Usunąć {n} postać/postacie z aplikacji?",
    "First enter the Client ID in Settings.": "Najpierw wpisz Client ID w Ustawieniach.",
    "Fetching {done}/{total}: {name}": "Pobieram {done}/{total}: {name}",
    "Done in {s} s.": "Gotowe w {s} s.",
    " Problems: {n} (details in the Status column).": " Problemy: {n} (szczegóły w kolumnie Status).",
    "Fetch error: {error}": "Błąd pobierania: {error}",
    "The port must be a number 1024–65535.": "Port musi być liczbą 1024–65535.",
    "Settings saved.": "Ustawienia zapisane.",
    # --- reports
    "URGENT": "PILNE",
    "SOON": "WKRÓTCE",
    "INFO": "INFO",
    "{text} ago": "{text} temu",
    "in {text}": "za {text}",
    "Login expired: log the character in again": "Token nieważny: zaloguj postać ponownie",
    "Skill queue paused": "Kolejka skilli wstrzymana",
    "Skill queue empty": "Kolejka skilli pusta",
    "Skill queue ends soon": "Kolejka skilli się kończy",
    "Unallocated SP: {sp}": "Nieprzydzielone SP: {sp}",
    "Manufacturing": "Produkcja",
    "TE research": "Badanie TE",
    "ME research": "Badanie ME",
    "Copying": "Kopiowanie",
    "Invention": "Inwencja",
    "Reaction": "Reakcja",
    "Job": "Job",
    "{activity} ready: {product}": "{activity} gotowa: {product}",
    "PI extractor stopped: {where}": "Ekstraktor PI stoi: {where}",
    "PI extractor ending: {where}": "Ekstraktor PI kończy się: {where}",
    "Omega expired (by your date)": "Omega wygasła (wg Twojej daty)",
    "Omega ending": "Omega kończy się",
    " (in space)": " (w kosmosie)",
    "Structure {id}": "Struktura {id}",
    "Location {id}": "Lokacja {id}",
    " (BP copy)": " (kopia BP)",
    "paused": "wstrzymana",
    "EMPTY": "PUSTA",
    "{n} pl., ": "{n} pl., ",
    "stopped": "stoi",
    "LOG IN AGAIN": "ZALOGUJ PONOWNIE",
    "error: ": "błąd: ",
    # --- sso
    "The EVE app is set up correctly. You can add characters.":
        "Aplikacja EVE jest ustawiona poprawnie. Możesz dodawać postacie.",
    "EVE rejects these scopes (they are not ticked in the app with THIS Client ID):\n{lines}\n\n"
    "On developers.eveonline.com open the app with exactly the Client ID from Settings, tick them and save.":
        "EVE odrzuca te uprawnienia (nie są zaznaczone w aplikacji z TYM Client ID):\n{lines}\n\n"
        "Na developers.eveonline.com otwórz aplikację o dokładnie takim Client ID jak w Ustawieniach, "
        "zaznacz je i zapisz.",
    "EVE does not know this Client ID. Copy it again from the app page (no spaces at the start or end) "
    "and save the settings.":
        "EVE nie zna tego Client ID. Skopiuj go jeszcze raz ze strony aplikacji (bez spacji na początku i końcu) "
        "i zapisz ustawienia.",
    "The Callback URL in the EVE app must be exactly: {url}\n(EVE says: {detail})":
        "Callback URL w aplikacji EVE musi być dokładnie: {url}\n(EVE zgłasza: {detail})",
    "EVE returns an error: {error}": "EVE zwraca błąd: {error}",
    "Invalid token from SSO": "Nieprawidłowy token z SSO",
    "The token does not belong to a character": "Token nie należy do postaci",
    "Token revoked, log the character in again": "Token unieważniony, zaloguj postać ponownie",
    "SSO rejected the request ({status} {error})": "SSO odrzuciło żądanie ({status} {error})",
    "SSO error {status}": "SSO błąd {status}",
    "You can close this tab and go back to EveKonta.": "Możesz zamknąć tę kartę i wrócić do EveKonta.",
    "Wrong state parameter (old login window?)": "Zły parametr state (stare okno logowania?)",
    "Login failed": "Błąd logowania",
    "No code": "Brak kodu",
    "Login cancelled": "Logowanie anulowane",
    "Character added": "Postać dodana",
    "Login timed out": "Minął czas na zalogowanie",
    # --- sync
    "No token": "Brak tokena",
    "skills": "skille",
    "queue": "kolejka",
    "wallet": "portfel",
    "location": "lokacja",
    "assets": "assety",
    "prices and names…": "ceny i nazwy…",
    "prices": "ceny",
    "names": "nazwy",
    "unexpected error: {name}": "nieoczekiwany błąd: {name}",
    "Structure {id} (no access)": "Struktura {id} (brak dostępu)",
}
