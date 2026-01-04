# Echoroo Configuration Guide

This guide explains how to configure Echoroo for different deployment scenarios.

## Quick Start

1. **Copy the environment template:**
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` and set required values:**
   ```bash
   # Required: Database password
   POSTGRES_PASSWORD=your_secure_password

   # Required: Path to your audio files on the host
   ECHOROO_AUDIO_DIR=/path/to/your/audio/files
   ```

3. **Start Echoroo:**
   ```bash
   ./scripts/docker.sh dev
   ```

That's it! Access the application at http://localhost:3000.

## Environment Variables

### Required Variables

| Variable | Description |
|----------|-------------|
| `POSTGRES_PASSWORD` | Database password (choose a secure password) |
| `ECHOROO_AUDIO_DIR` | Path on HOST where audio files are stored |

### Database Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_DB` | Database name | `echoroo` |
| `POSTGRES_USER` | Database user | `postgres` |
| `POSTGRES_PASSWORD` | Database password | *Required* |
| `POSTGRES_PORT` | Database port (dev only, exposed to host) | `5432` |

### Network Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ECHOROO_DOMAIN` | Domain or IP for accessing Echoroo | `localhost` |
| `ECHOROO_PORT` | Backend API port | `5000` |
| `ECHOROO_FRONTEND_PORT` | Frontend port (dev only) | `3000` |

### Production Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `DOMAIN` | Domain name (required for production) | - |
| `PORT` | External port | `80` |
| `BACKEND_REPLICAS` | Number of backend replicas | `1` |

### Development Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `ECHOROO_DEV` | Enable development mode | `true` |

### Machine Learning Settings

Echoroo uses GPU-accelerated machine learning models (BirdNET, Perch) for species detection.

| Variable | Description | Default |
|----------|-------------|---------|
| `ECHOROO_ML_USE_GPU` | Enable GPU acceleration for ML models | `true` |
| `ECHOROO_ML_GPU_DEVICE` | Device specification (`GPU`, `CPU`, `GPU:0`, `GPU:1`) | `GPU` |
| `ECHOROO_ML_GPU_BATCH_SIZE` | Segments processed in parallel per GPU inference | `16` |
| `ECHOROO_ML_FEEDERS` | Number of file feeder processes for audio loading | `8` |
| `ECHOROO_ML_WORKERS` | Number of GPU inference workers | `1` |

**Performance Tuning:**

- **GPU_BATCH_SIZE:** Higher values improve throughput but require more GPU memory. Reduce if you get `CUDA_ERROR_OUT_OF_MEMORY`.
- **FEEDERS:** More feeders speed up file I/O but use more CPU. Typical values: 4-16.
- **WORKERS:** Usually 1 is optimal unless you have multiple GPUs.

## Deployment Scenarios

### 1. Local Development with Docker

Perfect for development on your laptop/desktop using Docker.

```bash
# .env
POSTGRES_PASSWORD=dev_password
ECHOROO_AUDIO_DIR=/home/user/audio
ECHOROO_DOMAIN=localhost
ECHOROO_DEV=true
```

```bash
./scripts/docker.sh dev
```

**Access:**
- Frontend: http://localhost:3000
- Backend API: http://localhost:5000
- API Docs: http://localhost:5000/docs
- Database: localhost:5432

### 2. Local Development Without Docker

For development without Docker containers.

**Requirements:**
- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Node.js 18+
- npm
- PostgreSQL with pgvector (optional, can use SQLite)

**Setup:**

```bash
# Install dependencies
./scripts/setup.sh

# Configure environment
vim .env
```

**Database Setup:**

If you want to use PostgreSQL (recommended for production-like development), you need to start PostgreSQL manually:

**Option 1: Using Docker for PostgreSQL only**
```bash
docker run -d \
  --name echoroo-postgres \
  -e POSTGRES_PASSWORD=your_password \
  -e POSTGRES_DB=echoroo \
  -p 5432:5432 \
  pgvector/pgvector:pg17
```

**Option 2: System PostgreSQL**
```bash
# Ubuntu/Debian
sudo apt-get install postgresql postgresql-contrib
sudo systemctl start postgresql

# Install pgvector extension (required for vector similarity search)
# Follow instructions at: https://github.com/pgvector/pgvector
```

**Option 3: Using SQLite (for simple development)**
```bash
# Set ECHOROO_DB_DIALECT=sqlite in .env
# No database setup needed - SQLite database will be created automatically
```

Then configure your database connection in `.env`:
```bash
# For PostgreSQL
ECHOROO_DB_DIALECT=postgresql
ECHOROO_DB_HOST=localhost
ECHOROO_DB_PORT=5432
ECHOROO_DB_NAME=echoroo
ECHOROO_DB_USERNAME=postgres
ECHOROO_DB_PASSWORD=your_password

# Or for SQLite
ECHOROO_DB_DIALECT=sqlite
```

**Start servers:**

```bash
# Terminal 1: Backend
cd back && uv run python -m echoroo

# Terminal 2: Frontend
cd front && npm run dev
```

**Access:**
- Frontend: http://localhost:3000
- Backend API: http://localhost:5000

### 3. Remote Server (IP Address)

For deployment on a remote server accessed by IP address.

```bash
# .env
POSTGRES_PASSWORD=secure_password
ECHOROO_AUDIO_DIR=/data/audio
ECHOROO_DOMAIN=192.168.1.100
```

**Access:**
- Frontend: http://192.168.1.100:3000
- Backend: http://192.168.1.100:5000

**Important:** Make sure firewall allows ports 3000 and 5000.

### 4. Production with Domain

For production deployment with Traefik reverse proxy.

```bash
# .env
POSTGRES_PASSWORD=very_secure_password
ECHOROO_AUDIO_DIR=/data/audio
DOMAIN=echoroo.example.com
BACKEND_REPLICAS=3
```

**Access:**
- Application: http://echoroo.example.com
- Traefik Dashboard: http://localhost:8080

## Architecture

### Development Mode (`./scripts/docker.sh dev`)

```
┌─────────────────────────────────────────────────────┐
│                    Host Machine                      │
├─────────────────────────────────────────────────────┤
│  Port 3000 ─────► Frontend (Next.js)                │
│  Port 5000 ─────► Backend (FastAPI)                 │
│  Port 5432 ─────► PostgreSQL + pgvector             │
└─────────────────────────────────────────────────────┘
```

- All services have ports exposed to host
- Hot reload enabled for both frontend and backend
- Database accessible from host for development tools

### Production Mode (`./scripts/docker.sh prod`)

```
┌─────────────────────────────────────────────────────┐
│                    Host Machine                      │
├─────────────────────────────────────────────────────┤
│  Port 80 ─────► Traefik Reverse Proxy               │
│                      │                               │
│                      ▼                               │
│               Backend (FastAPI) x N replicas        │
│                      │                               │
│                      ▼                               │
│               PostgreSQL + pgvector                 │
│               (internal network only)               │
└─────────────────────────────────────────────────────┘
```

- Only port 80 exposed
- Database not accessible from outside
- Load balancing across multiple backend replicas
- Frontend bundled into backend

## Troubleshooting

### Cannot access from remote machine

1. **Check `ECHOROO_DOMAIN`:**
   ```bash
   # Should be your server's IP or domain, not localhost
   ECHOROO_DOMAIN=192.168.1.100
   ```

2. **Check firewall:**
   ```bash
   sudo ufw allow 3000
   sudo ufw allow 5000
   ```

### Database connection issues

1. **Check PostgreSQL is running:**
   ```bash
   ./scripts/docker.sh dev status
   ```

2. **Check database logs:**
   ```bash
   ./scripts/docker.sh dev logs db
   ```

3. **Connect to database directly:**
   ```bash
   ./scripts/docker.sh dev db
   ```

### Audio files not accessible

1. **Verify `ECHOROO_AUDIO_DIR` path exists:**
   ```bash
   ls -la $ECHOROO_AUDIO_DIR
   ```

2. **Check the path is absolute, not relative:**
   ```bash
   # Correct
   ECHOROO_AUDIO_DIR=/home/user/audio

   # Wrong
   ECHOROO_AUDIO_DIR=./audio
   ```

### Container build fails

1. **Clean and rebuild:**
   ```bash
   ./scripts/docker.sh dev build
   ```

2. **Remove all containers and volumes (DATA LOSS!):**
   ```bash
   ./scripts/docker.sh dev clean-all
   ```

## Summary

**What you need to configure:**
- `POSTGRES_PASSWORD` (database password)
- `ECHOROO_AUDIO_DIR` (path to audio files)

**What's automatically configured:**
- Database setup with pgvector extension
- Network configuration
- CORS settings
- Health checks

**Result:**
- One simple configuration file (`.env`)
- Works out of the box
- Easy to deploy anywhere
