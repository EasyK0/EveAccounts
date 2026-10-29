@echo off
rem Starts EveKonta without a console window.
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 -m evekonta
) else (
    start "" pythonw -m evekonta
)
