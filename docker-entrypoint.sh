#!/bin/bash
set -e

# Wait for Ollama to be ready
echo "Waiting for Ollama to be ready..."
MAX_RETRIES=30
RETRY_COUNT=0
until curl -s http://ollama:11434/api/tags > /dev/null 2>&1; do
  RETRY_COUNT=$((RETRY_COUNT + 1))
  if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
    echo "ERROR: Ollama did not start after 60 seconds"
    exit 1
  fi
  echo "Waiting for Ollama... ($RETRY_COUNT/$MAX_RETRIES)"
  sleep 2
done

echo "Ollama is ready!"

# Initialize database
python3 -c "from backend.shared.database import init_db; init_db()"

# Start LLM server in background
echo "Starting LLM Server on port 8000..."
python3 -m backend.llm_server.main &
LLM_PID=$!

# Wait for LLM server
sleep 3

# Start API server in foreground
echo "Starting API Server on port 9000..."
python3 -m backend.api_server.main

