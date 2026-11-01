@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
REM Optional C2PA support. Do not stop the app if the optional package is unavailable.
python -m pip install -r backend\requirements-optional.txt
if errorlevel 1 echo [start.bat] Optional C2PA package was not installed; continuing without it.
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
