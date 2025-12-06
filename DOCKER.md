# Echoroo Docker Guide

This guide covers running Echoroo with Docker in both development and production environments.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (version 24.0+)
- [Docker Compose](https://docs.docker.com/compose/install/) (version 2.0+)

## Quick Start

```bash
# Clone the repository
git clone https://github.com/0kam/echoroo.git
cd echoroo

# Configure environment
cp .env.example .env
# Edit .env and set:
#   - POSTGRES_PASSWORD (required)
#   - ECHOROO_AUDIO_DIR (required)

# Build base image (one-time, contains PyTorch and ML dependencies)
cd back && docker build -f Dockerfile.base -t echoroo-base:latest .
cd ..

# Start development environment
./scripts/docker.sh dev
```

Access the application at http://localhost:3000.

## Management Script

All Docker operations are managed through `./scripts/docker.sh`:

```bash
./scripts/docker.sh <environment> <command>
```

### Environments

| Environment | Description |
|-------------|-------------|
| `dev` | Development with hot reload, exposed ports |
| `prod` | Production with Traefik proxy, scalable |

### Commands

| Command | Description |
|---------|-------------|
| `start` (default) | Start containers |
| `stop` | Stop containers |
| `restart` | Restart containers |
| `logs [service]` | Show logs (optionally for specific service) |
| `status` | Show container status |
| `shell [service]` | Open shell in container (default: backend) |
| `db` | Connect to PostgreSQL CLI |
| `build` | Rebuild Docker images |
| `watch` | Start with hot reload (dev only) |
| `clean` | Stop and remove containers |
| `clean-all` | Remove everything including volumes (DATA LOSS!) |
| `help` | Show help |

## Development Environment

### Base Image Architecture

The development environment uses a **two-layer image architecture** to optimize build times:

```
┌─────────────────────────────────────────────────┐
│  echoroo-base:latest                            │
│  - Python 3.12 runtime                          │
│  - PyTorch, torchaudio, torchcodec (~2GB)       │
│  - All pip dependencies                         │
│  - Build once, reuse always                     │
└─────────────────────────────────────────────────┘
                    ▲
                    │ (volume mount)
┌─────────────────────────────────────────────────┐
│  Your source code (./back/src)                  │
│  - Mounted at runtime                           │
│  - No rebuild needed for code changes           │
└─────────────────────────────────────────────────┘
```

**Benefits:**
- Initial base image build: ~10 minutes (one-time)
- Code changes: instant (no rebuild needed)
- Dependency changes: rebuild base image only

### Building the Base Image

Build the base image once, or when dependencies change:

```bash
cd back && docker build -f Dockerfile.base -t echoroo-base:latest .
```

This image contains all heavy ML dependencies (PyTorch, etc.) and only needs to be rebuilt when `pyproject.toml` or `uv.lock` changes.

### Starting

```bash
# Start all services (source code is volume-mounted)
./scripts/docker.sh dev

# Start with hot reload (watches for file changes)
./scripts/docker.sh dev watch
```

### Services

| Service | Port | Description |
|---------|------|-------------|
| Frontend | 3000 | Next.js development server |
| Backend | 5000 | FastAPI server with hot reload |
| Database | 5432 | PostgreSQL with pgvector |

### Accessing Services

```bash
# View all logs
./scripts/docker.sh dev logs

# View specific service logs
./scripts/docker.sh dev logs backend
./scripts/docker.sh dev logs frontend
./scripts/docker.sh dev logs db

# Open shell in backend container
./scripts/docker.sh dev shell backend

# Connect to database
./scripts/docker.sh dev db
```

### Development Workflow

The development environment supports hot reload via volume mounts:

1. **Backend changes**: Edit files in `back/src/` - changes are available immediately (restart container if needed)
2. **Frontend changes**: Edit files in `front/src/` - changes are synced automatically

**No Docker rebuild is needed for code changes!**

To use hot reload with watch mode:

```bash
./scripts/docker.sh dev watch
```

### Rebuilding

**For code changes:** No rebuild needed - just restart the container:

```bash
./scripts/docker.sh dev restart
```

**When you change dependencies** (pyproject.toml, uv.lock):

```bash
# Rebuild the base image
cd back && docker build -f Dockerfile.base -t echoroo-base:latest .

# Restart containers
./scripts/docker.sh dev restart
```

**For frontend dependency changes** (package.json):

```bash
# Rebuild frontend image
./scripts/docker.sh dev build

# Restart
./scripts/docker.sh dev restart
```

## Production Environment

### Prerequisites

1. A domain name pointing to your server
2. Ports 80 and 8080 available

### Configuration

Edit `.env` for production:

```bash
POSTGRES_PASSWORD=very_secure_password_here
ECHOROO_AUDIO_DIR=/data/audio
DOMAIN=echoroo.example.com
BACKEND_REPLICAS=3
```

### Starting

```bash
./scripts/docker.sh prod
```

### Architecture

Production mode uses Traefik as a reverse proxy:

```
Internet
    │
    ▼
Port 80 ──► Traefik ──► Backend (x N replicas)
                              │
                              ▼
                        PostgreSQL
                   (internal network)
```

Features:
- Load balancing across backend replicas
- Automatic health checks
- Database isolated in internal network
- Frontend bundled into backend static files

### Scaling

Adjust the number of backend replicas:

```bash
# In .env
BACKEND_REPLICAS=5

# Restart
./scripts/docker.sh prod restart
```

### Monitoring

```bash
# Check status
./scripts/docker.sh prod status

# View logs
./scripts/docker.sh prod logs

# Traefik dashboard
# Available at http://localhost:8080
```

## Services Reference

### Database (PostgreSQL + pgvector)

- **Image**: `pgvector/pgvector:pg16`
- **Volume**: `echoroo-dev-db` (dev) or `echoroo-prod-db` (prod)
- **Features**: pgvector extension for ML embeddings

Connect to database:

```bash
./scripts/docker.sh dev db
```

Or from host (dev only):

```bash
psql -h localhost -U postgres -d echoroo
```

### Backend (FastAPI)

- **Port**: 5000
- **API Docs**: http://localhost:5000/docs
- **Health Check**: http://localhost:5000/api/v1/

### Frontend (Next.js)

- **Port**: 3000 (dev only)
- **Note**: In production, frontend is bundled into backend

## Data Management

### Volumes

| Volume | Purpose |
|--------|---------|
| `echoroo-dev-db` / `echoroo-prod-db` | PostgreSQL data |
| `echoroo-dev-data` | Backend data (dev only) |

### Audio Files

Audio files are mounted read-only from the host:

```bash
# In .env
ECHOROO_AUDIO_DIR=/path/to/audio/files
```

The directory is mounted at `/audio` inside containers.

### Backup

Backup the database:

```bash
docker exec echoroo-db pg_dump -U postgres echoroo > backup.sql
```

Restore from backup:

```bash
cat backup.sql | docker exec -i echoroo-db psql -U postgres echoroo
```

### Reset

To completely reset (WARNING: deletes all data!):

```bash
./scripts/docker.sh dev clean-all
```

## Troubleshooting

### Containers not starting

```bash
# Check status
./scripts/docker.sh dev status

# Check logs for errors
./scripts/docker.sh dev logs
```

### Database connection failed

```bash
# Check if db container is healthy
docker ps | grep echoroo-db

# Check db logs
./scripts/docker.sh dev logs db
```

### Port already in use

```bash
# Find what's using the port
sudo lsof -i :3000

# Use different ports in .env
ECHOROO_PORT=5001
ECHOROO_FRONTEND_PORT=3001
POSTGRES_PORT=5433
```

### Build failures

```bash
# Clean rebuild
./scripts/docker.sh dev build

# If still failing, remove all and start fresh
docker system prune -a
./scripts/docker.sh dev
```

### Audio files not visible

1. Check the path in `.env`:
   ```bash
   echo $ECHOROO_AUDIO_DIR
   ls -la $ECHOROO_AUDIO_DIR
   ```

2. Ensure it's an absolute path:
   ```bash
   # Correct
   ECHOROO_AUDIO_DIR=/home/user/audio

   # Wrong
   ECHOROO_AUDIO_DIR=./audio
   ```

### Hot reload not working

Use watch mode:

```bash
./scripts/docker.sh dev watch
```

If still not working, check file permissions and Docker's file sharing settings.

## Docker Files

| File | Purpose |
|------|---------|
| `compose.dev.yaml` | Development environment |
| `compose.prod.yaml` | Production environment |
| `back/Dockerfile` | Production backend image (full build) |
| `back/Dockerfile.base` | Base image with ML dependencies (PyTorch, etc.) |
| `back/Dockerfile.dev` | Development image (extends base, optional) |
| `front/Dockerfile` | Frontend image |

## Environment Variables

See [CONFIGURATION.md](CONFIGURATION.md) for complete environment variable reference.
