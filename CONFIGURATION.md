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

   # Required: Invitation token HMAC key
   # Generate with: openssl rand -hex 32
   INVITATION_TOKEN_HMAC_KEY=your_generated_hex_key

   # Required: Path to your audio files on the host
   ECHOROO_AUDIO_DIR=/path/to/your/audio/files
   ```

3. **Start Echoroo:**
   ```bash
   ./echoroo.sh start
   ```

That's it! Access the application at http://localhost:5173.

## Environment Variables

### Required Variables

| Variable | Description |
|----------|-------------|
| `POSTGRES_PASSWORD` | Database password (choose a secure password) |
| `INVITATION_TOKEN_HMAC_KEY` | HMAC key for invitation tokens. Generate with `openssl rand -hex 32` |
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
| `ECHOROO_API_PORT` | Backend API port | `8002` |
| `ECHOROO_FRONTEND_PORT` | Frontend port (dev only) | `5173` |

### Production Settings

A production compose file is not currently present in this repository. `./echoroo.sh prod ...` exits with an unsupported-environment error until a production stack is added.

### Development Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `ECHOROO_DEV` | Enable development mode | `true` |

### Machine Learning Settings

Echoroo uses machine learning models (BirdNET, Perch — both on TensorFlow) for species detection. The defaults preserve GPU behaviour, so a host with a working GPU needs none of these set.

| Variable | Description | Default |
|----------|-------------|---------|
| `ECHOROO_ML_USE_GPU` | Use the GPU for inference. `false` forces CPU (`CUDA_VISIBLE_DEVICES=-1`) for both BirdNET and Perch. | `true` |
| `ECHOROO_ML_GPU_BATCH_SIZE` | Segments processed in parallel per inference batch | `16` |
| `ECHOROO_ML_FEEDERS` | Number of file feeder processes for audio loading (minimum `1`) | `1` |
| `ECHOROO_ML_WORKERS` | Number of inference workers (minimum `1`) | `1` |
| `ECHOROO_ML_CPU_NUM_THREADS` | Thread cap applied **only** in CPU mode (bounds TF / OpenMP / BLAS pools so CPU inference does not exhaust RAM) | `8` |
| `ECHOROO_ML_CPU_WARMUP_BATCHES` | Comma-separated Perch warmup batch sizes used **only** in CPU mode (empty = skip warmup). GPU mode always warms up `1,6,10,16`. | `1` |
| `ECHOROO_ML_GPU_ALLOW_GROWTH` | In GPU mode, set `TF_FORCE_GPU_ALLOW_GROWTH=true` so TF grows GPU memory on demand | `true` |
| `ECHOROO_WORKER_MEM_LIMIT` | Compose-level RAM cap for the worker container (`0` = unlimited). Set e.g. `24g` on a CPU/Blackwell box. | `0` |

**Performance Tuning:**

- **GPU_BATCH_SIZE:** Higher values improve throughput but require more GPU memory. Reduce if you get `CUDA_ERROR_OUT_OF_MEMORY`.
- **FEEDERS:** More feeders speed up file I/O but use more CPU. Must be `>= 1`; setting `0` fails at startup with an opaque pydantic validation error. To effectively disable ML work, scale the worker container down (e.g. `replicas: 0`) instead of zeroing this.
- **WORKERS:** Usually 1 is optimal unless you have multiple GPUs. Must be `>= 1`; setting `0` fails at startup with an opaque pydantic validation error. To effectively disable ML work, scale the worker container down (e.g. `replicas: 0`) instead of zeroing this.
- **CPU mode:** When `ECHOROO_ML_USE_GPU=false`, inference threads are capped to `ECHOROO_ML_CPU_NUM_THREADS` and the Perch warmup shrinks to `ECHOROO_ML_CPU_WARMUP_BATCHES`; pair with `ECHOROO_WORKER_MEM_LIMIT` to bound RAM.

## Deployment Scenarios

### 1. Local Development with Docker

Perfect for development on your laptop/desktop using Docker.

```bash
# .env
POSTGRES_PASSWORD=dev_password
INVITATION_TOKEN_HMAC_KEY=replace_with_openssl_rand_hex_32_output
ECHOROO_AUDIO_DIR=/home/user/audio
ECHOROO_DOMAIN=localhost
ECHOROO_DEV=true
```

```bash
./echoroo.sh start
```

**Access:**
- Frontend: http://localhost:5173
- Backend API: http://localhost:8002
- API Docs: http://localhost:8002/docs
- Database: localhost:5432

### 2. Local Development Without Docker

For development without Docker containers.

**Requirements:**
- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Node.js 20+
- npm
- PostgreSQL with pgvector (optional, can use SQLite)

**Setup:**

```bash
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
cd apps/api && uv run uvicorn echoroo.main:app --reload

# Terminal 2: Frontend
cd apps/web && npm run dev
```

**Access:**
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000

### 3. Remote Server (IP Address)

For deployment on a remote server accessed by IP address.

```bash
# .env
POSTGRES_PASSWORD=secure_password
ECHOROO_AUDIO_DIR=/data/audio
ECHOROO_DOMAIN=192.168.1.100
```

**Access:**
- Frontend: http://192.168.1.100:5173
- Backend: http://192.168.1.100:8002

**Important:** Make sure firewall allows ports 5173 and 8002.

### 4. Production with Domain

Production deployment needs a new `compose.prod.yaml` or another deployment target. The current repository only defines the Docker development stack.

## Architecture

### Development Mode (`./echoroo.sh start`)

```
┌─────────────────────────────────────────────────────┐
│                    Host Machine                      │
├─────────────────────────────────────────────────────┤
│  Port 5173 ─────► Frontend (SvelteKit)              │
│  Port 8002 ─────► Backend (FastAPI)                 │
│  Port 5432 ─────► PostgreSQL + pgvector             │
└─────────────────────────────────────────────────────┘
```

- All services have ports exposed to host
- Hot reload enabled for both frontend and backend
- Database accessible from host for development tools

### Production Mode

Not currently defined in this repository. Add a production stack before documenting or using `./echoroo.sh prod ...`.

## Troubleshooting

### Cannot access from remote machine

1. **Check `ECHOROO_DOMAIN`:**
   ```bash
   # Should be your server's IP or domain, not localhost
   ECHOROO_DOMAIN=192.168.1.100
   ```

2. **Check firewall:**
   ```bash
   sudo ufw allow 5173
   sudo ufw allow 8002
   ```

### Database connection issues

1. **Check PostgreSQL is running:**
   ```bash
   ./echoroo.sh status
   ```

2. **Check database logs:**
   ```bash
   ./echoroo.sh logs db
   ```

3. **Connect to database directly:**
   ```bash
   ./echoroo.sh db
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
   ./echoroo.sh build --no-cache
   ```

2. **Remove all containers and volumes (DATA LOSS!):**
   ```bash
   ./echoroo.sh clean-all
   ```

## Summary

**What you need to configure:**
- `POSTGRES_PASSWORD` (database password)
- `INVITATION_TOKEN_HMAC_KEY` (invitation token HMAC key)
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
