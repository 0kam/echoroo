#!/bin/bash

# Whombat Frontend Control Script
# This script controls the frontend server independently

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
FRONT_DIR="$PROJECT_ROOT/front"

# Load environment variables from .env file
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Configuration
WHOMBAT_PORT=${WHOMBAT_PORT:-5000}
WHOMBAT_FRONTEND_PORT=${WHOMBAT_FRONTEND_PORT:-3000}
WHOMBAT_DOMAIN=${WHOMBAT_DOMAIN:-localhost}
WHOMBAT_PROTOCOL=${WHOMBAT_PROTOCOL:-http}

LOG_DIR="$PROJECT_ROOT/logs"
FRONTEND_LOG="$LOG_DIR/frontend.log"

# Create logs directory
mkdir -p "$LOG_DIR"

# Function to check if frontend is running
is_running() {
    # Use ss instead of lsof for better compatibility
    ss -tlnp 2>/dev/null | grep -q ":${WHOMBAT_FRONTEND_PORT} "
}

# Function to get frontend PID
get_pid() {
    # Extract PID from ss output
    ss -tlnp 2>/dev/null | grep ":${WHOMBAT_FRONTEND_PORT} " | grep -oP 'pid=\K[0-9]+' | head -n 1
}

# Function to generate frontend .env
generate_frontend_env() {
    BACKEND_URL="${WHOMBAT_PROTOCOL}://${WHOMBAT_DOMAIN}:${WHOMBAT_PORT}"
    cat > "$FRONT_DIR/.env" <<EOF
# Auto-generated from root .env - DO NOT EDIT MANUALLY
# Backend API endpoint
NEXT_PUBLIC_BACKEND_HOST=${BACKEND_URL}

# Frontend port
PORT=${WHOMBAT_FRONTEND_PORT}
EOF
}

# Function to start frontend
start_frontend() {
    if is_running; then
        echo -e "${YELLOW}Frontend is already running on port $WHOMBAT_FRONTEND_PORT${NC}"
        PID=$(get_pid)
        echo -e "${YELLOW}PID: $PID${NC}"
        return 0
    fi

    echo -e "${BLUE}"
    echo "======================================"
    echo "   Starting Frontend Server"
    echo "======================================"
    echo -e "${NC}"

    # Generate frontend .env
    echo -e "${YELLOW}Generating frontend configuration...${NC}"
    generate_frontend_env
    echo -e "${GREEN}✓ Frontend .env generated${NC}"

    FRONTEND_URL="${WHOMBAT_PROTOCOL}://${WHOMBAT_DOMAIN}:${WHOMBAT_FRONTEND_PORT}"
    echo -e "${YELLOW}Configuration:${NC}"
    echo -e "  Directory: $FRONT_DIR"
    echo -e "  URL:       $FRONTEND_URL"
    echo -e "  Log:       $FRONTEND_LOG"
    echo ""

    # Check node_modules
    if [ ! -d "$FRONT_DIR/node_modules" ]; then
        echo -e "${RED}Error: node_modules not found in $FRONT_DIR${NC}"
        echo -e "${YELLOW}Please run './scripts/setup.sh' first${NC}"
        exit 1
    fi

    # Start frontend
    cd "$FRONT_DIR"
    PORT=$WHOMBAT_FRONTEND_PORT npm run dev > "$FRONTEND_LOG" 2>&1 &
    FRONTEND_PID=$!

    # Wait for startup (Next.js can take a while to start)
    echo -e "${YELLOW}Waiting for frontend to start...${NC}"
    for i in {1..60}; do
        if is_running; then
            ACTUAL_PID=$(get_pid)
            echo -e "${GREEN}✓ Frontend started successfully (PID: ${ACTUAL_PID:-$FRONTEND_PID})${NC}"
            echo -e "${BLUE}Access at: $FRONTEND_URL${NC}"
            return 0
        fi
        if [ $i -eq 60 ]; then
            echo -e "${RED}✗ Frontend failed to start after 60 seconds${NC}"
            echo -e "${YELLOW}Check logs: tail -f $FRONTEND_LOG${NC}"
            echo -e "${YELLOW}Last 10 lines of log:${NC}"
            tail -n 10 "$FRONTEND_LOG"
            exit 1
        fi
        sleep 1
    done
}

# Function to stop frontend
stop_frontend() {
    if ! is_running; then
        echo -e "${YELLOW}Frontend is not running${NC}"
        return 0
    fi

    echo -e "${YELLOW}Stopping frontend...${NC}"

    PID=$(get_pid)

    # Try graceful shutdown
    kill $PID 2>/dev/null || true
    sleep 2

    # Force kill if still running
    if is_running; then
        echo -e "${YELLOW}Force killing frontend...${NC}"
        kill -9 $PID 2>/dev/null || true
        sleep 1
    fi

    if ! is_running; then
        echo -e "${GREEN}✓ Frontend stopped${NC}"
    else
        echo -e "${RED}✗ Failed to stop frontend${NC}"
        exit 1
    fi
}

# Function to restart frontend
restart_frontend() {
    echo -e "${BLUE}"
    echo "======================================"
    echo "   Restarting Frontend Server"
    echo "======================================"
    echo -e "${NC}"

    stop_frontend
    sleep 2
    start_frontend
}

# Function to show frontend logs
show_logs() {
    if [ ! -f "$FRONTEND_LOG" ]; then
        echo -e "${RED}Log file not found: $FRONTEND_LOG${NC}"
        exit 1
    fi

    echo -e "${BLUE}Frontend logs (Ctrl+C to exit):${NC}"
    tail -f "$FRONTEND_LOG"
}

# Function to show status
show_status() {
    echo -e "${BLUE}"
    echo "======================================"
    echo "   Frontend Server Status"
    echo "======================================"
    echo -e "${NC}"

    FRONTEND_URL="${WHOMBAT_PROTOCOL}://${WHOMBAT_DOMAIN}:${WHOMBAT_FRONTEND_PORT}"

    echo -e "${YELLOW}Configuration:${NC}"
    echo -e "  Port:   $WHOMBAT_FRONTEND_PORT"
    echo -e "  Domain: $WHOMBAT_DOMAIN"
    echo -e "  URL:    $FRONTEND_URL"
    echo ""

    if is_running; then
        PID=$(get_pid)
        echo -e "${GREEN}✓ Frontend is running${NC}"
        echo -e "  PID: $PID"

        # Check if responding
        if command -v curl >/dev/null 2>&1; then
            if curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 "http://localhost:${WHOMBAT_FRONTEND_PORT}" | grep -q "200\|304"; then
                echo -e "  Health: ${GREEN}Responding${NC}"
            else
                echo -e "  Health: ${YELLOW}Not responding${NC}"
            fi
        fi
    else
        echo -e "${RED}✗ Frontend is not running${NC}"
    fi
    echo ""
}

# Main script
COMMAND=${1:-start}

case "$COMMAND" in
    start)
        start_frontend
        ;;
    stop)
        stop_frontend
        ;;
    restart)
        restart_frontend
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
        echo -e "  start   - Start frontend server"
        echo -e "  stop    - Stop frontend server"
        echo -e "  restart - Restart frontend server"
        echo -e "  logs    - Show frontend logs (tail -f)"
        echo -e "  status  - Show frontend status"
        echo ""
        exit 1
        ;;
esac
