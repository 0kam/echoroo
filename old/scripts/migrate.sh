#!/bin/bash
# Echoroo Database Migration Script
#
# Usage:
#   ./scripts/migrate.sh              - Run pending migrations (upgrade head)
#   ./scripts/migrate.sh status       - Show current migration status
#   ./scripts/migrate.sh history      - Show migration history
#   ./scripts/migrate.sh upgrade HEAD - Upgrade to latest
#   ./scripts/migrate.sh downgrade -1 - Downgrade one revision

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
BACK_DIR="$PROJECT_DIR/back"

# Helper functions
info() { echo -e "${BLUE}i${NC} $1"; }
success() { echo -e "${GREEN}OK${NC} $1"; }
warn() { echo -e "${YELLOW}!${NC} $1"; }
error() { echo -e "${RED}x${NC} $1"; exit 1; }

# Load environment variables
load_env() {
    if [ -f "$PROJECT_DIR/.env" ]; then
        set -a
        source "$PROJECT_DIR/.env"
        set +a
    fi

    # Database connection (defaults for local dev)
    export ECHOROO_DB_DIALECT="${ECHOROO_DB_DIALECT:-postgresql}"
    export ECHOROO_DB_HOST="${ECHOROO_DB_HOST:-localhost}"
    export ECHOROO_DB_PORT="${ECHOROO_DB_PORT:-5432}"
    export ECHOROO_DB_NAME="${ECHOROO_DB_NAME:-echoroo}"
    export ECHOROO_DB_USERNAME="${ECHOROO_DB_USERNAME:-postgres}"
    export ECHOROO_DB_PASSWORD="${ECHOROO_DB_PASSWORD:-cf3871bf}"
}

# Check if database is accessible
check_db() {
    if ! docker exec echoroo-db pg_isready -U postgres > /dev/null 2>&1; then
        error "Database is not running. Start with: ./scripts/docker.sh dev"
    fi
}

# Run alembic command
run_alembic() {
    cd "$BACK_DIR"

    # Ensure venv exists
    if [ ! -d "$BACK_DIR/.venv" ]; then
        info "Installing dependencies..."
        uv sync
    fi

    # Use the project's venv directly
    PYTHONPATH="$BACK_DIR/src:$PYTHONPATH" "$BACK_DIR/.venv/bin/python" -m alembic "$@"
}

# Show current status
show_status() {
    info "Current migration status:"
    docker exec echoroo-db psql -U postgres -d echoroo -c "SELECT version_num FROM alembic_version;" 2>/dev/null || echo "No migrations applied"
}

# Main
load_env
check_db

COMMAND="${1:-upgrade}"

case "$COMMAND" in
    status)
        show_status
        ;;
    history)
        info "Migration history:"
        run_alembic history --verbose
        ;;
    upgrade)
        TARGET="${2:-head}"
        info "Upgrading to: $TARGET"
        run_alembic upgrade "$TARGET"
        success "Migration complete"
        show_status
        ;;
    downgrade)
        TARGET="${2:--1}"
        warn "Downgrading to: $TARGET"
        run_alembic downgrade "$TARGET"
        success "Downgrade complete"
        show_status
        ;;
    *)
        # Pass through to alembic
        info "Running: alembic $*"
        run_alembic "$@"
        ;;
esac
