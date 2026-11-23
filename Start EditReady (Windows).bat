@echo off
rem EditReady launcher for Windows. Double-click this file to start EditReady.
rem First start: installs the free engine (about 100 MB) into %USERPROFILE%\.editready
setlocal
title EditReady
cd /d "%~dp0"
set "VENV=%USERPROFILE%\.editready\venv"
echo.
echo   EditReady
echo.

set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python"
if not defined PY goto nopython

set "FIRST="
if exist "%VENV%\Scripts\python.exe" goto update
set "FIRST=1"
echo   First start: setting up. This downloads about 100 MB, one time only.
if not exist "%USERPROFILE%\.editready" mkdir "%USERPROFILE%\.editready"
%PY% -m venv "%VENV%"
if errorlevel 1 goto venvfail

:update
echo   Checking for engine updates...
if defined FIRST (
  "%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -U -r requirements.txt
) else (
  "%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -q -U -r requirements.txt
)
if not errorlevel 1 goto run
if defined FIRST goto installfail
echo   Could not check for updates. Starting with the current engine.

:run
"%VENV%\Scripts\python.exe" app.py
echo.
pause
exit /b 0

:nopython
echo   EditReady needs Python 3.11 or newer. It is free.
echo   1. Download it from https://www.python.org/downloads/
echo   2. While installing, tick "Add python.exe to PATH".
echo   3. Double-click this file again.
start "" https://www.python.org/downloads/
pause
exit /b 1

:venvfail
echo   Could not create the app environment.
pause
exit /b 1

:installfail
rmdir /s /q "%VENV%"
echo   Setup failed. Check your internet connection and double-click this file again.
pause
exit /b 1
