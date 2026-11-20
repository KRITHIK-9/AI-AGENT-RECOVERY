@echo off
REM One-time setup for Windows: creates a virtual environment and installs dependencies.
cd /d "%~dp0"
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo Setup complete. Next: double-click run_backend.bat, then run_dashboard.bat
pause
