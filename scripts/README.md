# Echoroo Scripts

This directory contains scripts for managing the Echoroo application.

## Scripts

```
scripts/
├── docker.sh     # Docker container management
├── setup.sh      # Local development environment setup
├── init-db.sql   # PostgreSQL database initialization
└── README.md     # This file
```

---

## Quick Start

### Option 1: Docker (Recommended)

```bash
# Configure environment
cp .env.example .env
vim .env  # Set POSTGRES_PASSWORD and ECHOROO_AUDIO_DIR

# Start development environment
./scripts/docker.sh dev
```

### Option 2: Local Development (Without Docker)

```bash
# Run setup script
./scripts/setup.sh

# Configure environment
vim .env  # Set ECHOROO_AUDIO_DIR

# Start backend (Terminal 1)
cd back && uv run python -m echoroo

# Start frontend (Terminal 2)
cd front && npm run dev
```

---

## docker.sh - Docker Management

Manages Echoroo Docker containers for both development and production.

### Usage

```bash
./scripts/docker.sh <environment> <command>
```

### Environments

| Environment | Description |
|-------------|-------------|
| `dev` | Development environment with hot reload |
| `prod` | Production environment with Traefik proxy |

### Commands

| Command | Description |
|---------|-------------|
| `start` | Start containers (default) |
| `stop` | Stop containers |
| `restart` | Restart containers |
| `logs [service]` | Show logs |
| `status` | Show container status |
| `shell [service]` | Open shell in container |
| `db` | Connect to PostgreSQL CLI |
| `build` | Rebuild Docker images |
| `watch` | Start with hot reload (dev only) |
| `clean` | Stop and remove containers |
| `clean-all` | Remove everything including volumes |
| `help` | Show help |

### Examples

```bash
# Development
./scripts/docker.sh dev              # Start
./scripts/docker.sh dev logs         # View all logs
./scripts/docker.sh dev logs backend # View backend logs
./scripts/docker.sh dev db           # Connect to database
./scripts/docker.sh dev watch        # Start with hot reload
./scripts/docker.sh dev stop         # Stop

# Production
./scripts/docker.sh prod             # Start
./scripts/docker.sh prod logs        # View logs
./scripts/docker.sh prod stop        # Stop
```

---

## setup.sh - Local Development Setup

Sets up the local development environment without Docker.

### Usage

```bash
./scripts/setup.sh
```

### What it does

1. Checks system requirements (Python 3, uv, Node.js, npm)
2. Creates backend virtual environment and installs dependencies
3. Installs frontend npm packages
4. Creates `.env` file from `.env.example`
5. Creates `logs/` directory

### Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Node.js 18+
- npm

### After setup

Start the servers manually:

```bash
# Terminal 1: Backend
cd back && uv run python -m echoroo

# Terminal 2: Frontend
cd front && npm run dev
```

---

## init-db.sql - Database Initialization

SQL script for initializing PostgreSQL database with required extensions.

This script is automatically executed when the PostgreSQL container starts for the first time.

**Contents:**
- Creates `vector` extension (pgvector for ML embeddings)

---

## Environment Variables

All scripts read configuration from the root `.env` file.

### Required Variables

| Variable | Description |
|----------|-------------|
| `POSTGRES_PASSWORD` | Database password |
| `ECHOROO_AUDIO_DIR` | Path to audio files directory |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_DB` | `echoroo` | Database name |
| `POSTGRES_USER` | `postgres` | Database user |
| `POSTGRES_PORT` | `5432` | Database port (dev only) |
| `ECHOROO_DOMAIN` | `localhost` | Domain for accessing Echoroo |
| `ECHOROO_PORT` | `5000` | Backend port |
| `ECHOROO_FRONTEND_PORT` | `3000` | Frontend port (dev only) |
| `DOMAIN` | - | Domain name (prod only) |
| `BACKEND_REPLICAS` | `1` | Number of backend replicas (prod only) |

See [CONFIGURATION.md](../CONFIGURATION.md) for full details.

---

## Troubleshooting

### Permission denied

```bash
chmod +x scripts/*.sh
```

### Port already in use

```bash
# Check what's using the port
sudo lsof -i :3000
sudo lsof -i :5000

# Kill process
kill -9 <PID>
```

### Docker containers not starting

```bash
# Check status
./scripts/docker.sh dev status

# Check logs
./scripts/docker.sh dev logs

# Rebuild
./scripts/docker.sh dev build
```

### Backend won't start (local development)

```bash
# Check virtual environment
ls back/.venv

# Reinstall dependencies
cd back && uv sync
```

### Frontend won't start (local development)

```bash
# Check node_modules
ls front/node_modules

# Reinstall dependencies
cd front && npm install
```

---

## Related Documentation

- [DOCKER.md](../DOCKER.md) - Detailed Docker guide
- [CONFIGURATION.md](../CONFIGURATION.md) - Environment configuration
- [.env.example](../.env.example) - Environment variables template
