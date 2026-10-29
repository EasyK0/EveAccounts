# Changelog

All notable changes to EveKonta. Adding a new version at the top publishes a GitHub release for it.

## [1.1.0] - 2026-10-28

- The app is now in English by default, with Polish as a second language (Settings → Language / Język). The window switches language right away.
- Alerts, table columns, dialogs, error messages and the SSO login page follow the chosen language.
- CSV export uses English column names (Polish ones in Polish mode); import accepts both.
- New tests check that every text has a Polish translation with the same placeholders.

## [1.0.0] - 2026-10-11

- Encrypted account vault (Windows DPAPI + master password) with CSV import and export.
- EVE SSO login per character; one table with skills, wallet, assets, industry jobs, PI and location for all characters.
- Alerts for empty skill queues, finished jobs, PI extractors, Omega expiry and expired logins.
- "Where is my item" search across all characters.
