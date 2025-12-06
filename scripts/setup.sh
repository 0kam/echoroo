#!/bin/bash

# Echoroo Setup Script
# This script sets up the development environment for Echoroo (without Docker)

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

echo -e "${BLUE}"
echo "======================================"
echo "   Echoroo Setup"
echo "======================================"
echo -e "${NC}"

# Check system requirements
echo -e "\n${YELLOW}[1/5] Checking system requirements...${NC}"

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is not installed${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
echo -e "${GREEN}✓ Python ${PYTHON_VERSION} found${NC}"

# Check uv
if ! command -v uv &> /dev/null; then
    echo -e "${RED}Error: uv is not installed${NC}"
    echo -e "${YELLOW}Please install uv: https://docs.astral.sh/uv/getting-started/installation/${NC}"
    exit 1
fi
echo -e "${GREEN}✓ uv found${NC}"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo -e "${RED}Error: Node.js is not installed${NC}"
    exit 1
fi

NODE_VERSION=$(node --version)
echo -e "${GREEN}✓ Node.js ${NODE_VERSION} found${NC}"

# Check npm
if ! command -v npm &> /dev/null; then
    echo -e "${RED}Error: npm is not installed${NC}"
    exit 1
fi

NPM_VERSION=$(npm --version)
echo -e "${GREEN}✓ npm ${NPM_VERSION} found${NC}"

# Setup backend
echo -e "\n${YELLOW}[2/5] Setting up backend...${NC}"
cd "$PROJECT_ROOT/back"

if [ -d ".venv" ]; then
    echo -e "${YELLOW}Virtual environment already exists, skipping...${NC}"
else
    echo -e "${GREEN}Creating virtual environment and installing dependencies...${NC}"
    uv sync
fi

echo -e "${GREEN}✓ Backend setup complete${NC}"

# Setup frontend
echo -e "\n${YELLOW}[3/5] Setting up frontend...${NC}"
cd "$PROJECT_ROOT/front"

if [ -d "node_modules" ]; then
    echo -e "${YELLOW}node_modules already exists, skipping...${NC}"
else
    echo -e "${GREEN}Installing dependencies...${NC}"
    npm install
fi

echo -e "${GREEN}✓ Frontend setup complete${NC}"

# Setup environment file
echo -e "\n${YELLOW}[4/5] Setting up environment configuration...${NC}"
cd "$PROJECT_ROOT"

if [ -f ".env" ]; then
    echo -e "${YELLOW}.env file already exists${NC}"
    echo -e "${YELLOW}To reconfigure, edit .env manually or delete it and run setup again${NC}"
else
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "${GREEN}✓ Created .env from .env.example${NC}"
        echo -e "${YELLOW}Please edit .env to configure:${NC}"
        echo -e "  ${BLUE}vim .env${NC}"
    else
        echo -e "${RED}Warning: .env.example not found${NC}"
    fi
fi

# Create logs directory
echo -e "\n${YELLOW}[5/5] Creating logs directory...${NC}"
mkdir -p "$PROJECT_ROOT/logs"
echo -e "${GREEN}✓ Logs directory created${NC}"

# Success message
echo -e "\n${GREEN}"
echo "======================================"
echo "   ✓ Setup Complete!"
echo "======================================"
echo -e "${NC}"

echo -e "${BLUE}Next steps:${NC}"
echo ""
echo -e "1. ${YELLOW}Configure your environment:${NC}"
echo -e "   ${BLUE}vim .env${NC}"
echo -e "   Set ECHOROO_AUDIO_DIR to your audio files directory"
echo ""
echo -e "2. ${YELLOW}Start with Docker (recommended):${NC}"
echo -e "   ${BLUE}./scripts/docker.sh dev${NC}"
echo ""
echo -e "   ${YELLOW}Or start manually:${NC}"
echo -e "   ${BLUE}# Terminal 1: Backend${NC}"
echo -e "   ${BLUE}cd back && uv run python -m echoroo${NC}"
echo ""
echo -e "   ${BLUE}# Terminal 2: Frontend${NC}"
echo -e "   ${BLUE}cd front && npm run dev${NC}"
echo ""
echo -e "${YELLOW}For more information, see:${NC}"
echo -e "  ${BLUE}DOCKER.md${NC}          - Docker deployment"
echo -e "  ${BLUE}CONFIGURATION.md${NC}   - Configuration guide"
echo ""
