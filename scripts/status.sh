#!/bin/bash

# Whombat Application Status Check Script
# This script checks the status of backend and frontend servers

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default ports
BACKEND_PORT=${WHOMBAT_BACKEND_PORT:-5000}
FRONTEND_PORT=${WHOMBAT_FRONTEND_PORT:-3000}

echo -e "${BLUE}"
echo "======================================"
echo "   Whombat Application Status"
echo "======================================"
echo -e "${NC}"

# Function to check if a port is in use
check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1 ; then
        return 0  # Port is in use
    else
        return 1  # Port is free
    fi
}

# Function to get PID on port
get_pid() {
    local port=$1
    lsof -ti:$port 2>/dev/null
}

# Function to check service status
check_service() {
    local port=$1
    local name=$2
    local url=$3

    echo -e "\n${YELLOW}$name:${NC}"
    echo -e "  Port: $port"
    echo -e "  URL:  $url"

    if check_port $port; then
        PID=$(get_pid $port)
        echo -e "  Status: ${GREEN}Running${NC} (PID: $PID)"

        # Try to get more info about the process
        PROCESS_INFO=$(ps -p $PID -o comm= 2>/dev/null)
        echo -e "  Process: $PROCESS_INFO"

        # Check if actually responding
        if command -v curl >/dev/null 2>&1; then
            if curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 "$url" | grep -q "200\|302\|404"; then
                echo -e "  Health: ${GREEN}Responding${NC}"
            else
                echo -e "  Health: ${YELLOW}Not responding${NC}"
            fi
        fi
    else
        echo -e "  Status: ${RED}Not running${NC}"
    fi
}

# Check Backend
check_service $BACKEND_PORT "Backend (FastAPI)" "http://localhost:$BACKEND_PORT/docs"

# Check Frontend
check_service $FRONTEND_PORT "Frontend (Next.js)" "http://localhost:$FRONTEND_PORT"

# Summary
echo -e "\n${BLUE}"
echo "======================================"
echo -e "${NC}"

BACKEND_RUNNING=false
FRONTEND_RUNNING=false

check_port $BACKEND_PORT && BACKEND_RUNNING=true
check_port $FRONTEND_PORT && FRONTEND_RUNNING=true

if $BACKEND_RUNNING && $FRONTEND_RUNNING; then
    echo -e "${GREEN}✓ All services are running${NC}"
    echo ""
    echo -e "${BLUE}Access the application at:${NC}"
    echo -e "  Frontend:  http://localhost:$FRONTEND_PORT"
    echo -e "  API Docs:  http://localhost:$BACKEND_PORT/docs"
elif $BACKEND_RUNNING || $FRONTEND_RUNNING; then
    echo -e "${YELLOW}⚠ Some services are not running${NC}"
    $BACKEND_RUNNING || echo -e "  ${RED}✗ Backend is not running${NC}"
    $FRONTEND_RUNNING || echo -e "  ${RED}✗ Frontend is not running${NC}"
    echo ""
    echo -e "${YELLOW}Run './scripts/start.sh' to start all services${NC}"
else
    echo -e "${RED}✗ All services are stopped${NC}"
    echo ""
    echo -e "${YELLOW}Run './scripts/start.sh' to start the application${NC}"
fi

echo ""
