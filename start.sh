#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
# Optional: C2PA provenance support. Safe to fail -- the app runs fine without it.
python -m pip install -r backend/requirements-optional.txt || echo "[start.sh] c2pa-python not installed -- continuing without C2PA support."
exec uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
