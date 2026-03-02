#!/bin/bash
# Echoroo Docker Management Script
#
# Usage:
#   ./scripts/docker.sh dev [command]   - Development environment
#
# Commands:
#   start (default) - Start containers
#   stop            - Stop containers
#   restart [svc]   - Restart containers or specific service
#   logs [service]  - Show logs
#   status          - Show container status
#   shell [service] - Open shell in container
#   db              - Connect to PostgreSQL
#   clean           - Stop and remove containers
#   clean-all       - Remove everything including volumes (DATA LOSS!)
#   build           - Rebuild images

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Helper functions
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check .env file
check_env() {
    if [ ! -f .env ]; then
        warn ".env file not found"
        if [ -f .env.example ]; then
            info "Creating .env from .env.example..."
            cp .env.example .env
            warn "Please edit .env and set required values (POSTGRES_PASSWORD, etc.)"
            exit 1
        else
            error "No .env or .env.example found"
            exit 1
        fi
    fi
}

# Get compose file based on environment
get_compose_file() {
    local env=$1
    case $env in
        dev|development)
            echo "compose.dev.yaml"
            ;;
        prod|production)
            echo "compose.prod.yaml"
            ;;
        *)
            error "Unknown environment: $env"
            echo "Usage: $0 {dev|prod} [command]"
            exit 1
            ;;
    esac
}

# Main logic
ENV=${1:-dev}
COMMAND=${2:-start}
SERVICE=${3:-}

COMPOSE_FILE=$(get_compose_file "$ENV")

if [ ! -f "$COMPOSE_FILE" ]; then
    error "Compose file not found: $COMPOSE_FILE"
    exit 1
fi

COMPOSE="docker compose -f $COMPOSE_FILE"

case $COMMAND in
    start)
        check_env
        info "Starting $ENV environment..."
        $COMPOSE up -d --build
        success "Environment started"
        info "Frontend: http://localhost:${ECHOROO_FRONTEND_PORT:-5173}"
        info "Backend:  http://localhost:${ECHOROO_API_PORT:-8002}"
        ;;
    stop)
        info "Stopping $ENV environment..."
        $COMPOSE down
        success "Environment stopped"
        ;;
    restart)
        if [ -n "$SERVICE" ]; then
            info "Restarting $SERVICE..."
            $COMPOSE restart "$SERVICE"
        else
            info "Restarting $ENV environment..."
            $COMPOSE down
            check_env
            $COMPOSE up -d --build
        fi
        success "Restart complete"
        ;;
    logs)
        if [ -n "$SERVICE" ]; then
            $COMPOSE logs -f "$SERVICE"
        else
            $COMPOSE logs -f
        fi
        ;;
    status)
        $COMPOSE ps
        ;;
    shell)
        SERVICE=${SERVICE:-backend}
        info "Opening shell in $SERVICE..."
        $COMPOSE exec "$SERVICE" /bin/sh
        ;;
    db)
        info "Connecting to PostgreSQL..."
        $COMPOSE exec db psql -U "${POSTGRES_USER:-postgres}" "${POSTGRES_DB:-echoroo}"
        ;;
    clean)
        info "Cleaning up containers..."
        $COMPOSE down --remove-orphans
        success "Cleanup complete"
        ;;
    clean-all)
        warn "This will remove ALL containers AND volumes (DATA LOSS!)"
        read -p "Are you sure? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            $COMPOSE down -v --remove-orphans
            success "Full cleanup complete"
        else
            info "Cancelled"
        fi
        ;;
    build)
        info "Rebuilding images..."
        $COMPOSE build --no-cache
        success "Build complete"
        ;;
    *)
        error "Unknown command: $COMMAND"
        echo "Usage: $0 {dev|prod} {start|stop|restart|logs|status|shell|db|clean|clean-all|build} [service]"
        exit 1
        ;;
esac
