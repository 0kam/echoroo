#!/bin/bash
# Whombat Docker Management Script
#
# This script helps you manage Whombat using Docker Compose
#
# Usage:
#   ./scripts/docker.sh [command] [options]
#
# Commands:
#   start [simple|postgres|dev|prod]  - Start Whombat
#   stop                              - Stop Whombat
#   restart                           - Restart Whombat
#   logs                              - Show logs
#   status                            - Show container status
#   clean                             - Stop and remove containers, networks
#   clean-all                         - Stop and remove everything including volumes
#   build                             - Rebuild Docker images

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Change to project directory
cd "$PROJECT_DIR"

# Helper functions
print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_header() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

# Check if .env file exists
check_env_file() {
    if [ ! -f .env ]; then
        print_warning ".env file not found"
        print_info "Creating .env from .env.example..."
        cp .env.example .env
        print_success ".env file created"
        print_warning "Please edit .env file to configure your settings"
        print_info "At minimum, set WHOMBAT_AUDIO_DIR to point to your audio files"
        echo ""
        read -p "Press Enter to continue or Ctrl+C to exit and edit .env..."
    fi
}

# Get compose file based on mode
get_compose_file() {
    local mode=$1
    case $mode in
        simple)
            echo "compose.simple.yaml"
            ;;
        postgres)
            echo "compose.postgres.yaml"
            ;;
        dev)
            echo "compose.dev.yaml"
            ;;
        prod)
            echo "compose.prod.yaml"
            ;;
        *)
            echo "compose.simple.yaml"
            ;;
    esac
}

# Start command
cmd_start() {
    local mode=${1:-simple}
    local compose_file=$(get_compose_file "$mode")

    print_header "Starting Whombat ($mode mode)"

    check_env_file

    if [ ! -f "$compose_file" ]; then
        print_error "Compose file not found: $compose_file"
        exit 1
    fi

    print_info "Using compose file: $compose_file"
    print_info "Starting containers..."

    docker compose -f "$compose_file" up -d

    print_success "Whombat started successfully!"
    echo ""
    print_info "Access Whombat at: http://localhost:5000"
    print_info "View logs with: $0 logs"
    print_info "Stop with: $0 stop"
}

# Stop command
cmd_stop() {
    print_header "Stopping Whombat"

    # Try to stop all possible compose files
    for compose_file in compose.simple.yaml compose.postgres.yaml compose.dev.yaml compose.prod.yaml; do
        if docker compose -f "$compose_file" ps -q 2>/dev/null | grep -q .; then
            print_info "Stopping containers from $compose_file..."
            docker compose -f "$compose_file" down
        fi
    done

    print_success "Whombat stopped"
}

# Restart command
cmd_restart() {
    local mode=${1:-simple}
    print_header "Restarting Whombat"
    cmd_stop
    sleep 2
    cmd_start "$mode"
}

# Logs command
cmd_logs() {
    local service=${1:-}

    # Find which compose file is running
    local compose_file=""
    for cf in compose.simple.yaml compose.postgres.yaml compose.dev.yaml compose.prod.yaml; do
        if docker compose -f "$cf" ps -q 2>/dev/null | grep -q .; then
            compose_file="$cf"
            break
        fi
    done

    if [ -z "$compose_file" ]; then
        print_error "No running Whombat containers found"
        exit 1
    fi

    if [ -n "$service" ]; then
        docker compose -f "$compose_file" logs -f "$service"
    else
        docker compose -f "$compose_file" logs -f
    fi
}

# Status command
cmd_status() {
    print_header "Whombat Container Status"

    local found=false
    for compose_file in compose.simple.yaml compose.postgres.yaml compose.dev.yaml compose.prod.yaml; do
        if docker compose -f "$compose_file" ps -q 2>/dev/null | grep -q .; then
            print_info "Containers from $compose_file:"
            docker compose -f "$compose_file" ps
            found=true
            echo ""
        fi
    done

    if [ "$found" = false ]; then
        print_warning "No running Whombat containers found"
    fi
}

# Clean command
cmd_clean() {
    print_header "Cleaning Whombat Containers"

    print_warning "This will stop and remove all Whombat containers and networks"
    read -p "Continue? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Cancelled"
        exit 0
    fi

    for compose_file in compose.simple.yaml compose.postgres.yaml compose.dev.yaml compose.prod.yaml; do
        if [ -f "$compose_file" ]; then
            docker compose -f "$compose_file" down 2>/dev/null || true
        fi
    done

    print_success "Cleanup complete"
}

# Clean all command
cmd_clean_all() {
    print_header "Cleaning ALL Whombat Data"

    print_error "WARNING: This will delete ALL data including databases!"
    print_warning "This action cannot be undone!"
    read -p "Are you absolutely sure? (yes/N) " -r
    echo
    if [[ ! $REPLY == "yes" ]]; then
        print_info "Cancelled"
        exit 0
    fi

    for compose_file in compose.simple.yaml compose.postgres.yaml compose.dev.yaml compose.prod.yaml; do
        if [ -f "$compose_file" ]; then
            docker compose -f "$compose_file" down -v 2>/dev/null || true
        fi
    done

    print_success "All data removed"
}

# Build command
cmd_build() {
    local mode=${1:-simple}
    local compose_file=$(get_compose_file "$mode")

    print_header "Building Whombat Docker Images"

    docker compose -f "$compose_file" build --no-cache

    print_success "Build complete"
}

# Help command
cmd_help() {
    cat << EOF
Whombat Docker Management Script

Usage: $0 [command] [options]

Commands:
  start [mode]     Start Whombat containers
                   Modes: simple (default), postgres, dev, prod
  stop             Stop all Whombat containers
  restart [mode]   Restart Whombat containers
  logs [service]   Show container logs (optionally for specific service)
  status           Show status of running containers
  build [mode]     Rebuild Docker images
  clean            Stop and remove containers and networks
  clean-all        Stop and remove everything including volumes (DATA LOSS!)
  help             Show this help message

Examples:
  $0 start              # Start with SQLite (simple mode)
  $0 start postgres     # Start with PostgreSQL
  $0 start dev          # Start in development mode
  $0 logs               # Show all logs
  $0 logs whombat       # Show only Whombat logs
  $0 stop               # Stop all containers
  $0 clean              # Clean up containers

For more information, see the documentation in docs/
EOF
}

# Main command dispatcher
main() {
    local command=${1:-help}
    shift || true

    case $command in
        start)
            cmd_start "$@"
            ;;
        stop)
            cmd_stop
            ;;
        restart)
            cmd_restart "$@"
            ;;
        logs)
            cmd_logs "$@"
            ;;
        status)
            cmd_status
            ;;
        build)
            cmd_build "$@"
            ;;
        clean)
            cmd_clean
            ;;
        clean-all)
            cmd_clean_all
            ;;
        help|--help|-h)
            cmd_help
            ;;
        *)
            print_error "Unknown command: $command"
            echo ""
            cmd_help
            exit 1
            ;;
    esac
}

main "$@"
