@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    where py >nul 2>nul
    if not errorlevel 1 set "PY=py -3.14"
)
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo Install Python 3.14 and dependencies as described in README.md.
    pause
    exit /b 1
)
%PY% scripts\serve.py --open-browser
if errorlevel 1 pause
endlocal
