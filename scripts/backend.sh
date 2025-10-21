#!/bin/bash

# Whombat Backend Control Script
# This script controls the backend server independently

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

# Load environment variables from .env file
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Configuration
WHOMBAT_PORT=${WHOMBAT_PORT:-5000}
WHOMBAT_HOST=${WHOMBAT_HOST:-0.0.0.0}
WHOMBAT_DOMAIN=${WHOMBAT_DOMAIN:-localhost}
WHOMBAT_PROTOCOL=${WHOMBAT_PROTOCOL:-http}
WHOMBAT_DEV=${WHOMBAT_DEV:-true}

LOG_DIR="$PROJECT_ROOT/logs"
BACKEND_LOG="$LOG_DIR/backend.log"

# Create logs directory
mkdir -p "$LOG_DIR"

# Function to check if backend is running
is_running() {
    # Use ss instead of lsof for better compatibility
    ss -tlnp 2>/dev/null | grep -q ":${WHOMBAT_PORT} "
}

# Function to get backend PID
get_pid() {
    # Extract PID from ss output
    ss -tlnp 2>/dev/null | grep ":${WHOMBAT_PORT} " | grep -oP 'pid=\K[0-9]+' | head -n 1
}

# Function to start backend
start_backend() {
    if is_running; then
        echo -e "${YELLOW}Backend is already running on port $WHOMBAT_PORT${NC}"
        PID=$(get_pid)
        echo -e "${YELLOW}PID: $PID${NC}"
        return 0
    fi

    echo -e "${BLUE}"
    echo "======================================"
    echo "   Starting Backend Server"
    echo "======================================"
    echo -e "${NC}"

    BACKEND_URL="${WHOMBAT_PROTOCOL}://${WHOMBAT_DOMAIN}:${WHOMBAT_PORT}"
    echo -e "${YELLOW}Configuration:${NC}"
    echo -e "  Directory: $BACK_DIR"
    echo -e "  URL:       $BACKEND_URL"
    echo -e "  Log:       $BACKEND_LOG"
    echo ""

    # Check virtual environment
    if [ ! -d "$BACK_DIR/.venv" ]; then
        echo -e "${RED}Error: Virtual environment not found in $BACK_DIR${NC}"
        echo -e "${YELLOW}Please run './scripts/setup.sh' first${NC}"
        exit 1
    fi

    # Start backend
    cd "$BACK_DIR"
    uv run python -m whombat > "$BACKEND_LOG" 2>&1 &
    BACKEND_PID=$!

    # Wait for startup
    echo -e "${YELLOW}Waiting for backend to start...${NC}"
    for i in {1..30}; do
        if is_running; then
            ACTUAL_PID=$(get_pid)
            echo -e "${GREEN}✓ Backend started successfully (PID: ${ACTUAL_PID:-$BACKEND_PID})${NC}"
            echo -e "${BLUE}Access at: $BACKEND_URL${NC}"
            echo -e "${BLUE}API Docs:  $BACKEND_URL/docs${NC}"
            return 0
        fi
        if [ $i -eq 30 ]; then
            echo -e "${RED}✗ Backend failed to start after 30 seconds${NC}"
            echo -e "${YELLOW}Check logs: tail -f $BACKEND_LOG${NC}"
            echo -e "${YELLOW}Last 10 lines of log:${NC}"
            tail -n 10 "$BACKEND_LOG"
            exit 1
        fi
        sleep 1
    done
}

# Function to stop backend
stop_backend() {
    if ! is_running; then
        echo -e "${YELLOW}Backend is not running${NC}"
        return 0
    fi

    echo -e "${YELLOW}Stopping backend...${NC}"

    PID=$(get_pid)

    # Try graceful shutdown
    kill $PID 2>/dev/null || true
    sleep 2

    # Force kill if still running
    if is_running; then
        echo -e "${YELLOW}Force killing backend...${NC}"
        kill -9 $PID 2>/dev/null || true
        sleep 1
    fi

    if ! is_running; then
        echo -e "${GREEN}✓ Backend stopped${NC}"
    else
        echo -e "${RED}✗ Failed to stop backend${NC}"
        exit 1
    fi
}

# Function to restart backend
restart_backend() {
    echo -e "${BLUE}"
    echo "======================================"
    echo "   Restarting Backend Server"
    echo "======================================"
    echo -e "${NC}"

    stop_backend
    sleep 2
    start_backend
}

# Function to show backend logs
show_logs() {
    if [ ! -f "$BACKEND_LOG" ]; then
        echo -e "${RED}Log file not found: $BACKEND_LOG${NC}"
        exit 1
    fi

    echo -e "${BLUE}Backend logs (Ctrl+C to exit):${NC}"
    tail -f "$BACKEND_LOG"
}

# Function to show status
show_status() {
    echo -e "${BLUE}"
    echo "======================================"
    echo "   Backend Server Status"
    echo "======================================"
    echo -e "${NC}"

    BACKEND_URL="${WHOMBAT_PROTOCOL}://${WHOMBAT_DOMAIN}:${WHOMBAT_PORT}"

    echo -e "${YELLOW}Configuration:${NC}"
    echo -e "  Port:   $WHOMBAT_PORT"
    echo -e "  Domain: $WHOMBAT_DOMAIN"
    echo -e "  URL:    $BACKEND_URL"
    echo ""

    if is_running; then
        PID=$(get_pid)
        echo -e "${GREEN}✓ Backend is running${NC}"
        echo -e "  PID: $PID"

        # Check if responding
        if command -v curl >/dev/null 2>&1; then
            if curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 "http://localhost:${WHOMBAT_PORT}/docs" | grep -q "200"; then
                echo -e "  Health: ${GREEN}Responding${NC}"
            else
                echo -e "  Health: ${YELLOW}Not responding${NC}"
            fi
        fi
    else
        echo -e "${RED}✗ Backend is not running${NC}"
    fi
    echo ""
}

# Main script
COMMAND=${1:-start}

case "$COMMAND" in
    start)
        start_backend
        ;;
    stop)
        stop_backend
        ;;
    restart)
        restart_backend
        ;;
    logs)
        show_logs
        ;;
    status)
        show_status
        ;;
    *)
        echo -e "${YELLOW}Usage: $0 {start|stop|restart|logs|status}${NC}"
        echo ""
        echo -e "${BLUE}Commands:${NC}"
        echo -e "  start   - Start backend server"
        echo -e "  stop    - Stop backend server"
        echo -e "  restart - Restart backend server"
        echo -e "  logs    - Show backend logs (tail -f)"
        echo -e "  status  - Show backend status"
        echo ""
        exit 1
        ;;
esac
