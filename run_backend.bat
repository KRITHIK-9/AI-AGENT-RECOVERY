@echo off
REM Starts the FastAPI backend on http://127.0.0.1:8000 (API docs at /docs). Keep this window open.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
pause
