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

# Load environment variables from .env file
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a  # automatically export all variables
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Network configuration with defaults
WHOMBAT_DOMAIN=${WHOMBAT_DOMAIN:-localhost}
WHOMBAT_HOST=${WHOMBAT_HOST:-localhost}
WHOMBAT_PORT=${WHOMBAT_PORT:-5000}
WHOMBAT_FRONTEND_PORT=${WHOMBAT_FRONTEND_PORT:-3000}
WHOMBAT_PROTOCOL=${WHOMBAT_PROTOCOL:-http}
WHOMBAT_DEV=${WHOMBAT_DEV:-false}

# Ports
BACKEND_PORT=$WHOMBAT_PORT
FRONTEND_PORT=$WHOMBAT_FRONTEND_PORT

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
    # Use ss instead of lsof for better compatibility
    ss -tlnp 2>/dev/null | grep -q ":${port} "
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

    # Also kill by port using ss
    BACKEND_PIDS=$(ss -tlnp 2>/dev/null | grep ":${BACKEND_PORT} " | grep -oP 'pid=\K[0-9]+')
    FRONTEND_PIDS=$(ss -tlnp 2>/dev/null | grep ":${FRONTEND_PORT} " | grep -oP 'pid=\K[0-9]+')

    [ ! -z "$BACKEND_PIDS" ] && echo "$BACKEND_PIDS" | xargs kill -9 2>/dev/null || true
    [ ! -z "$FRONTEND_PIDS" ] && echo "$FRONTEND_PIDS" | xargs kill -9 2>/dev/null || true

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
    PIDS=$(ss -tlnp 2>/dev/null | grep ":${BACKEND_PORT} " | grep -oP 'pid=\K[0-9]+')
    [ ! -z "$PIDS" ] && echo "$PIDS" | xargs kill -9 2>/dev/null || true
    sleep 2
fi

if check_port $FRONTEND_PORT; then
    echo -e "${RED}Error: Frontend port $FRONTEND_PORT is already in use${NC}"
    echo -e "${YELLOW}Stopping existing process...${NC}"
    PIDS=$(ss -tlnp 2>/dev/null | grep ":${FRONTEND_PORT} " | grep -oP 'pid=\K[0-9]+')
    [ ! -z "$PIDS" ] && echo "$PIDS" | xargs kill -9 2>/dev/null || true
    sleep 2
fi

# Generate frontend .env file
echo -e "\n${YELLOW}Generating frontend configuration...${NC}"
BACKEND_URL="${WHOMBAT_PROTOCOL}://${WHOMBAT_DOMAIN}:${BACKEND_PORT}"
cat > "$FRONT_DIR/.env" <<EOF
# Auto-generated from root .env - DO NOT EDIT MANUALLY
# Backend API endpoint
NEXT_PUBLIC_BACKEND_HOST=${BACKEND_URL}

# Frontend port
PORT=${FRONTEND_PORT}
EOF
echo -e "${GREEN}✓ Frontend .env generated${NC}"

# Start Backend
echo -e "\n${YELLOW}[1/2] Starting Backend Server...${NC}"
echo -e "  📁 Directory: $BACK_DIR"
echo -e "  🌐 URL: ${BACKEND_URL}"
echo -e "  📝 Log: $BACKEND_LOG"

cd "$BACK_DIR"

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${RED}Error: Virtual environment not found in $BACK_DIR${NC}"
    echo -e "${YELLOW}Please run 'cd back && uv sync' first${NC}"
    exit 1
fi

# Start backend in background with network settings from environment
uv run python -m whombat > "$BACKEND_LOG" 2>&1 &
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
FRONTEND_URL="${WHOMBAT_PROTOCOL}://${WHOMBAT_DOMAIN}:${FRONTEND_PORT}"
echo -e "\n${YELLOW}[2/2] Starting Frontend Server...${NC}"
echo -e "  📁 Directory: $FRONT_DIR"
echo -e "  🌐 URL: ${FRONTEND_URL}"
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
echo -e "${BLUE}Frontend:${NC}  ${FRONTEND_URL}"
echo -e "${BLUE}Backend:${NC}   ${BACKEND_URL}"
echo -e "${BLUE}API Docs:${NC}  ${BACKEND_URL}/docs"
echo ""
echo -e "${YELLOW}Network Configuration:${NC}"
echo -e "  Domain:   ${WHOMBAT_DOMAIN}"
echo -e "  Protocol: ${WHOMBAT_PROTOCOL}"
echo -e "  Backend:  ${WHOMBAT_HOST}:${BACKEND_PORT}"
echo -e "  Frontend: ${FRONTEND_PORT}"
echo ""
echo -e "${YELLOW}Logs:${NC}"
echo -e "  Backend:  tail -f $BACKEND_LOG"
echo -e "  Frontend: tail -f $FRONTEND_LOG"
echo ""
echo -e "${YELLOW}To stop:${NC} Press Ctrl+C or run ./scripts/stop.sh"
echo ""

# Keep script running and tail logs
tail -f "$BACKEND_LOG" "$FRONTEND_LOG"
