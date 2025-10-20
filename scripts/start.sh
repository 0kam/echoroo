#!/bin/bash

# Whombat Application Startup Script
# This script starts both the backend (FastAPI) and frontend (Next.js) servers

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

BACK_DIR="$PROJECT_ROOT/back"
FRONT_DIR="$PROJECT_ROOT/front"

# Default ports
BACKEND_PORT=${WHOMBAT_BACKEND_PORT:-5000}
FRONTEND_PORT=${WHOMBAT_FRONTEND_PORT:-3000}

# Log files
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

echo -e "${BLUE}"
echo "======================================"
echo "   Starting Whombat Application"
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

# Function to cleanup on exit
cleanup() {
    echo -e "\n${YELLOW}Stopping servers...${NC}"

    # Kill background processes
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null || true
    fi
    if [ ! -z "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null || true
    fi

    # Also kill by port
    lsof -ti:$BACKEND_PORT | xargs kill -9 2>/dev/null || true
    lsof -ti:$FRONTEND_PORT | xargs kill -9 2>/dev/null || true

    echo -e "${GREEN}Servers stopped${NC}"
    exit 0
}

# Set trap to cleanup on script exit
trap cleanup EXIT INT TERM

# Check if ports are already in use
echo -e "${YELLOW}Checking ports...${NC}"

if check_port $BACKEND_PORT; then
    echo -e "${RED}Error: Backend port $BACKEND_PORT is already in use${NC}"
    echo -e "${YELLOW}Stopping existing process...${NC}"
    lsof -ti:$BACKEND_PORT | xargs kill -9 2>/dev/null || true
    sleep 2
fi

if check_port $FRONTEND_PORT; then
    echo -e "${RED}Error: Frontend port $FRONTEND_PORT is already in use${NC}"
    echo -e "${YELLOW}Stopping existing process...${NC}"
    lsof -ti:$FRONTEND_PORT | xargs kill -9 2>/dev/null || true
    sleep 2
fi

# Start Backend
echo -e "\n${YELLOW}[1/2] Starting Backend Server...${NC}"
echo -e "  📁 Directory: $BACK_DIR"
echo -e "  🌐 URL: http://localhost:$BACKEND_PORT"
echo -e "  📝 Log: $BACKEND_LOG"

cd "$BACK_DIR"

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${RED}Error: Virtual environment not found in $BACK_DIR${NC}"
    echo -e "${YELLOW}Please run 'cd back && uv sync' first${NC}"
    exit 1
fi

# Start backend in background
WHOMBAT_DEV=true uv run python -m whombat > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

# Wait for backend to start
echo -e "${YELLOW}Waiting for backend to start...${NC}"
for i in {1..30}; do
    if check_port $BACKEND_PORT; then
        echo -e "${GREEN}✓ Backend started successfully (PID: $BACKEND_PID)${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}✗ Backend failed to start${NC}"
        echo -e "${YELLOW}Check logs at: $BACKEND_LOG${NC}"
        tail -n 20 "$BACKEND_LOG"
        exit 1
    fi
    sleep 1
done

# Start Frontend
echo -e "\n${YELLOW}[2/2] Starting Frontend Server...${NC}"
echo -e "  📁 Directory: $FRONT_DIR"
echo -e "  🌐 URL: http://localhost:$FRONTEND_PORT"
echo -e "  📝 Log: $FRONTEND_LOG"

cd "$FRONT_DIR"

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo -e "${RED}Error: node_modules not found in $FRONT_DIR${NC}"
    echo -e "${YELLOW}Please run 'cd front && npm install' first${NC}"
    exit 1
fi

# Start frontend in background
PORT=$FRONTEND_PORT npm run dev > "$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

# Wait for frontend to start
echo -e "${YELLOW}Waiting for frontend to start...${NC}"
for i in {1..30}; do
    if check_port $FRONTEND_PORT; then
        echo -e "${GREEN}✓ Frontend started successfully (PID: $FRONTEND_PID)${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}✗ Frontend failed to start${NC}"
        echo -e "${YELLOW}Check logs at: $FRONTEND_LOG${NC}"
        tail -n 20 "$FRONTEND_LOG"
        exit 1
    fi
    sleep 1
done

# Success message
echo -e "\n${GREEN}"
echo "======================================"
echo "   🚀 Whombat is now running!"
echo "======================================"
echo -e "${NC}"
echo -e "${BLUE}Frontend:${NC}  http://localhost:$FRONTEND_PORT"
echo -e "${BLUE}Backend:${NC}   http://localhost:$BACKEND_PORT"
echo -e "${BLUE}API Docs:${NC}  http://localhost:$BACKEND_PORT/docs"
echo ""
echo -e "${YELLOW}Logs:${NC}"
echo -e "  Backend:  tail -f $BACKEND_LOG"
echo -e "  Frontend: tail -f $FRONTEND_LOG"
echo ""
echo -e "${YELLOW}To stop:${NC} Press Ctrl+C or run ./scripts/stop.sh"
echo ""

# Keep script running and tail logs
tail -f "$BACKEND_LOG" "$FRONTEND_LOG"
