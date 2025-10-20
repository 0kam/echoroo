#!/bin/bash

# Whombat Application Shutdown Script
# This script stops both the backend and frontend servers

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
echo "   Stopping Whombat Application"
echo "======================================"
echo -e "${NC}"

# Function to stop processes on a port
stop_port() {
    local port=$1
    local name=$2

    echo -e "${YELLOW}Stopping $name (port $port)...${NC}"

    # Find and kill processes
    PIDS=$(lsof -ti:$port 2>/dev/null)

    if [ -z "$PIDS" ]; then
        echo -e "${GREEN}✓ No $name process running on port $port${NC}"
        return 0
    fi

    # Try graceful shutdown first
    echo "$PIDS" | xargs kill 2>/dev/null
    sleep 2

    # Check if still running
    PIDS=$(lsof -ti:$port 2>/dev/null)
    if [ ! -z "$PIDS" ]; then
        echo -e "${YELLOW}Process still running, force killing...${NC}"
        echo "$PIDS" | xargs kill -9 2>/dev/null
        sleep 1
    fi

    # Final check
    PIDS=$(lsof -ti:$port 2>/dev/null)
    if [ -z "$PIDS" ]; then
        echo -e "${GREEN}✓ $name stopped successfully${NC}"
    else
        echo -e "${RED}✗ Failed to stop $name${NC}"
        return 1
    fi
}

# Stop both servers
stop_port $BACKEND_PORT "Backend"
stop_port $FRONTEND_PORT "Frontend"

# Also try to find and kill by process name
echo -e "\n${YELLOW}Cleaning up remaining processes...${NC}"

# Kill any remaining uvicorn processes
pkill -f "uvicorn.*whombat" 2>/dev/null && echo -e "${GREEN}✓ Stopped uvicorn processes${NC}" || true

# Kill any remaining next dev processes
pkill -f "next dev" 2>/dev/null && echo -e "${GREEN}✓ Stopped Next.js processes${NC}" || true

echo -e "\n${GREEN}"
echo "======================================"
echo "   ✓ Whombat stopped successfully"
echo "======================================"
echo -e "${NC}"
