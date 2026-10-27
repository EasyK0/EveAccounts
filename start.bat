@echo off
rem Uruchamia EveKonta bez okna konsoli.
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 -m evekonta
) else (
    start "" pythonw -m evekonta
)
