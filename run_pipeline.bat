@echo off
REM Runs the whole pipeline from the command line (no servers needed) and writes ./reports
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python run_pipeline.py %*
pause
