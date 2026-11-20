#!/usr/bin/env bash
# Starts backend (port 8000) and dashboard (port 8501). Ctrl+C stops both.
cd "$(dirname "$0")"
source .venv/bin/activate
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 &
BACK=$!
trap "kill $BACK" EXIT
sleep 3
streamlit run frontend/app.py
