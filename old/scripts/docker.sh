#!/bin/bash
# Echoroo Docker Management Script
#
# Usage:
#   ./scripts/docker.sh dev [command]   - Development environment
#   ./scripts/docker.sh prod [command]  - Production environment
#
# Commands:
#   start (default) - Start containers
#   stop            - Stop containers
#   restart         - Restart containers
#   logs [service]  - Show logs
#   status          - Show container status
#   shell [service] - Open shell in container
#   db              - Connect to PostgreSQL
#   clean           - Stop and remove containers
#   clean-all       - Remove everything including volumes (DATA LOSS!)
#   build           - Rebuild images
#   watch           - Start with hot reload (dev only)

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
info() { echo -e "${BLUE}ℹ${NC} $1"; }
success() { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; }

header() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

# Check .env file
check_env() {
    if [ ! -f .env ]; then
        warn ".env file not found"
        info "Creating .env from .env.example..."
        cp .env.example .env
        success ".env file created"
        warn "Please edit .env to set required values:"
        echo "  - POSTGRES_PASSWORD (required)"
        echo "  - ECHOROO_AUDIO_DIR (required)"
        echo ""
        read -p "Press Enter to continue or Ctrl+C to edit .env first..."
    fi

    # Source .env to check required variables
    set -a
    source .env
    set +a

    local missing=()
    [ -z "$POSTGRES_PASSWORD" ] && missing+=("POSTGRES_PASSWORD")
    [ -z "$ECHOROO_AUDIO_DIR" ] && missing+=("ECHOROO_AUDIO_DIR")

    if [ ${#missing[@]} -gt 0 ]; then
        error "Missing required environment variables:"
        for var in "${missing[@]}"; do
            echo "  - $var"
        done
        echo ""
        info "Please edit .env and set the required values"
        exit 1
    fi
}

# Get compose file
get_compose_file() {
    case $1 in
        dev)  echo "compose.dev.yaml" ;;
        prod) echo "compose.prod.yaml" ;;
        *)    echo "" ;;
    esac
}

# Commands
cmd_start() {
    local env=$1
    local compose_file=$(get_compose_file "$env")

    header "Starting Echoroo ($env)"
    check_env

    info "Using: $compose_file"
    docker compose -f "$compose_file" up -d

    success "Echoroo started!"
    echo ""
    if [ "$env" = "dev" ]; then
        info "Frontend: http://localhost:${ECHOROO_FRONTEND_PORT:-3000}"
        info "Backend:  http://localhost:${ECHOROO_PORT:-5000}"
        info "API Docs: http://localhost:${ECHOROO_PORT:-5000}/docs"
        info "Database: localhost:${POSTGRES_PORT:-5432}"
    else
        info "Access: http://${DOMAIN:-localhost}"
        info "Traefik: http://localhost:8080"
    fi
    echo ""
    info "View logs: $0 $env logs"
    info "Stop:      $0 $env stop"
}

cmd_stop() {
    local env=$1
    local compose_file=$(get_compose_file "$env")

    header "Stopping Echoroo ($env)"
    docker compose -f "$compose_file" down
    success "Echoroo stopped"
}

cmd_restart() {
    local env=$1
    header "Restarting Echoroo ($env)"
    cmd_stop "$env"
    sleep 2
    cmd_start "$env"
}

cmd_logs() {
    local env=$1
    local service=$2
    local compose_file=$(get_compose_file "$env")

    if [ -n "$service" ]; then
        docker compose -f "$compose_file" logs -f "$service"
    else
        docker compose -f "$compose_file" logs -f
    fi
}

cmd_status() {
    local env=$1
    local compose_file=$(get_compose_file "$env")

    header "Echoroo Status ($env)"
    docker compose -f "$compose_file" ps
}

cmd_shell() {
    local env=$1
    local service=${2:-backend}
    local compose_file=$(get_compose_file "$env")

    info "Opening shell in $service..."
    docker compose -f "$compose_file" exec "$service" /bin/bash
}

cmd_db() {
    local env=$1
    local compose_file=$(get_compose_file "$env")

    info "Connecting to PostgreSQL..."
    docker compose -f "$compose_file" exec db psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-echoroo}"
}

cmd_clean() {
    local env=$1
    local compose_file=$(get_compose_file "$env")

    header "Cleaning Echoroo ($env)"
    warn "This will stop and remove containers and networks"
    read -p "Continue? (y/N) " -n 1 -r
    echo
    [[ ! $REPLY =~ ^[Yy]$ ]] && { info "Cancelled"; exit 0; }

    docker compose -f "$compose_file" down
    success "Cleanup complete"
}

cmd_clean_all() {
    local env=$1
    local compose_file=$(get_compose_file "$env")

    header "Cleaning ALL Data ($env)"
    error "WARNING: This will delete ALL data including database!"
    warn "This action cannot be undone!"
    read -p "Type 'yes' to confirm: " -r
    echo
    [[ ! $REPLY == "yes" ]] && { info "Cancelled"; exit 0; }

    docker compose -f "$compose_file" down -v
    success "All data removed"
}

cmd_build() {
    local env=$1
    local compose_file=$(get_compose_file "$env")

    header "Building Echoroo ($env)"
    docker compose -f "$compose_file" build --no-cache
    success "Build complete"
}

cmd_watch() {
    local env=$1
    local compose_file=$(get_compose_file "$env")

    if [ "$env" != "dev" ]; then
        error "Watch mode is only available for dev environment"
        exit 1
    fi

    header "Starting Echoroo with Watch Mode"
    check_env

    info "Starting with hot reload..."
    docker compose -f "$compose_file" watch
}

cmd_help() {
    cat << 'EOF'
Echoroo Docker Management Script

Usage: ./scripts/docker.sh <env> [command] [options]

Environments:
  dev     Development (PostgreSQL exposed, hot reload)
  prod    Production (Traefik proxy, scalable)

Commands:
  start (default)  Start containers
  stop             Stop containers
  restart          Restart containers
  logs [service]   Show logs (optionally for specific service)
  status           Show container status
  shell [service]  Open shell in container (default: backend)
  db               Connect to PostgreSQL CLI
  build            Rebuild Docker images
  watch            Start with hot reload (dev only)
  clean            Stop and remove containers
  clean-all        Remove everything including volumes (DATA LOSS!)
  help             Show this help

Examples:
  ./scripts/docker.sh dev              # Start development environment
  ./scripts/docker.sh dev logs         # View all logs
  ./scripts/docker.sh dev logs backend # View backend logs only
  ./scripts/docker.sh dev db           # Connect to database
  ./scripts/docker.sh dev watch        # Start with hot reload
  ./scripts/docker.sh prod             # Start production environment
  ./scripts/docker.sh prod stop        # Stop production
  ./scripts/docker.sh dev clean-all    # Remove all dev data

Required Environment Variables (.env):
  POSTGRES_PASSWORD   Database password
  ECHOROO_AUDIO_DIR   Path to audio files directory

Optional Environment Variables:
  POSTGRES_DB         Database name (default: echoroo)
  POSTGRES_USER       Database user (default: postgres)
  POSTGRES_PORT       Database port (default: 5432, dev only)
  ECHOROO_PORT        Backend port (default: 5000)
  ECHOROO_FRONTEND_PORT  Frontend port (default: 3000, dev only)
  DOMAIN              Domain name (required for prod)
  BACKEND_REPLICAS    Number of backend replicas (prod only)
EOF
}

# Main
main() {
    local env=${1:-help}
    local command=${2:-start}
    shift 2 2>/dev/null || true

    # Handle help
    if [ "$env" = "help" ] || [ "$env" = "--help" ] || [ "$env" = "-h" ]; then
        cmd_help
        exit 0
    fi

    # Validate environment
    local compose_file=$(get_compose_file "$env")
    if [ -z "$compose_file" ]; then
        error "Invalid environment: $env"
        echo "Use 'dev' or 'prod'"
        echo ""
        cmd_help
        exit 1
    fi

    if [ ! -f "$compose_file" ]; then
        error "Compose file not found: $compose_file"
        exit 1
    fi

    # Execute command
    case $command in
        start)     cmd_start "$env" ;;
        stop)      cmd_stop "$env" ;;
        restart)   cmd_restart "$env" ;;
        logs)      cmd_logs "$env" "$@" ;;
        status)    cmd_status "$env" ;;
        shell)     cmd_shell "$env" "$@" ;;
        db)        cmd_db "$env" ;;
        build)     cmd_build "$env" ;;
        watch)     cmd_watch "$env" ;;
        clean)     cmd_clean "$env" ;;
        clean-all) cmd_clean_all "$env" ;;
        help)      cmd_help ;;
        *)
            error "Unknown command: $command"
            echo ""
            cmd_help
            exit 1
            ;;
    esac
}

main "$@"
