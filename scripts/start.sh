#!/bin/bash

echo "Starting BNO LLM Assistant..."
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed"
    echo "Please install Python 3.8 or higher"
    exit 1
fi

# Check if dependencies are installed
echo "Checking dependencies..."
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "Installing dependencies..."
    pip3 install -r requirements.txt
fi

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Start LLM Server in background
echo "Starting LLM Server on port 8000..."
cd "$PROJECT_DIR"
python3 -m backend.llm_server.main &
LLM_PID=$!

# Wait for LLM server to start
sleep 3

# Start API Server
echo "Starting API Server on port 9000..."
python3 -m backend.api_server.main &
API_PID=$!

echo ""
echo "Both servers are running!"
echo "LLM Server PID: $LLM_PID"
echo "API Server PID: $API_PID"
echo ""
echo "Open http://127.0.0.1:9000 in your browser"
echo ""
echo "Press Ctrl+C to stop both servers"

# Wait for user interrupt
trap "kill $LLM_PID $API_PID 2>/dev/null; exit" INT TERM
wait

