#!/bin/bash

# Whombat Application Restart Script
# This script restarts both the backend and frontend servers

# Color codes for output
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo -e "${BLUE}"
echo "======================================"
echo "   Restarting Whombat Application"
echo "======================================"
echo -e "${NC}"

# Stop services
echo "Step 1: Stopping services..."
"$SCRIPT_DIR/stop.sh"

echo ""
echo "Waiting 3 seconds..."
sleep 3
echo ""

# Start services
echo "Step 2: Starting services..."
"$SCRIPT_DIR/start.sh"
