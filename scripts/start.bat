@echo off
echo Starting BNO LLM Assistant...
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8 or higher
    pause
    exit /b 1
)

REM Check if dependencies are installed
echo Checking dependencies...
pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
)

REM Start LLM Server in new window
echo Starting LLM Server on port 8000...
start "BNO LLM Server" cmd /k "cd /d %~dp0.. && python -m backend.llm_server.main"

REM Wait a bit for LLM server to start
timeout /t 3 /nobreak >nul

REM Start API Server
echo Starting API Server on port 9000...
cd /d %~dp0..
python -m backend.api_server.main

pause

