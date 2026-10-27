@echo off
rem To samo co start.bat, ale z oknem konsoli (widac bledy).
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m evekonta
) else (
    python -m evekonta
)
pause
