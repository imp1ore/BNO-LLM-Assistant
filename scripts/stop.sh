#!/bin/bash
# Stop the BNO LLM Assistant (the single API + RAG process on port 9000).

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${YELLOW}Stopping BNO LLM Assistant...${NC}"

API_PID=$(lsof -ti:9000 2>/dev/null)
if [ -n "$API_PID" ]; then
    kill $API_PID 2>/dev/null
    echo -e "${GREEN}✓ Stopped process on port 9000 (PID: $API_PID)${NC}"
else
    echo -e "${YELLOW}Nothing running on port 9000${NC}"
fi

# Fallback: kill by module name in case the port changed
pkill -f "backend.api_server.main" 2>/dev/null

echo -e "${GREEN}Done.${NC}"
