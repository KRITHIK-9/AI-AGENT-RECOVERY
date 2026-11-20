@echo off
REM Starts the Streamlit dashboard on http://localhost:8501. Start run_backend.bat first.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
streamlit run frontend\app.py
pause
