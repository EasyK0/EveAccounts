@echo off
rem Same as start.bat, but with a console window (shows errors).
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m evekonta
) else (
    python -m evekonta
)
pause
