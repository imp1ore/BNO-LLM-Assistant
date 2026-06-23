@echo off
REM Start the BNO LLM Assistant (single API + RAG process on port 9000).
echo Starting BNO LLM Assistant...
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH ^(need 3.10+^)
    pause
    exit /b 1
)

REM Install dependencies if needed
pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r "%~dp0..\requirements.txt"
)

REM Run the app (RAG runs in-process; no separate model server)
cd /d %~dp0..
echo Open http://127.0.0.1:9000 once it starts. Press Ctrl+C to stop.
python -m backend.api_server.main

pause
