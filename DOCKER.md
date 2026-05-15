# Echoroo Docker Guide

This guide covers the current Docker development environment.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) 24.0+
- [Docker Compose](https://docs.docker.com/compose/install/) 2.0+

## Quick Start

```bash
git clone https://github.com/0kam/echoroo.git
cd echoroo

cp .env.example .env
# Edit .env and set:
#   - POSTGRES_PASSWORD
#   - ECHOROO_AUDIO_DIR

./scripts/gen-redis-dev-cert.sh
./scripts/docker.sh dev
```

Open http://localhost:5173 in your browser. The backend API is exposed at http://localhost:8002.

## Management Script

All Docker operations use `./scripts/docker.sh`:

```bash
./scripts/docker.sh dev [command] [service]
```

| Command | Description |
|---------|-------------|
| `start` (default) | Start containers |
| `stop` | Stop containers |
| `restart [service]` | Restart all containers or one service |
| `logs [service]` | Show logs |
| `status` | Show container status |
| `shell [service]` | Open a shell in a service container |
| `db` | Connect to PostgreSQL |
| `build` | Rebuild images |
| `clean` | Stop and remove containers |
| `clean-all` | Remove containers and volumes |

To rebuild images on start or restart:

```bash
ECHOROO_BUILD=1 ./scripts/docker.sh dev
ECHOROO_BUILD=1 ./scripts/docker.sh dev restart
```

For an explicit no-cache rebuild:

```bash
./scripts/docker.sh dev build
./scripts/docker.sh dev restart
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| `frontend` | `5173` | SvelteKit development server |
| `backend` | `8002` | FastAPI server with hot reload |
| `db` | `5432` | PostgreSQL with pgvector |
| `redis` | `6379` | Redis for queues and cache |
| `localstack` | `4566` | Local AWS-compatible services |
| `worker` | - | GPU Celery worker |
| `worker-cpu` | - | CPU/default Celery worker |
| `beat` | - | Celery beat scheduler |

## Source Layout

The Docker compose file builds from the current monorepo layout:

| Path | Purpose |
|------|---------|
| `compose.dev.yaml` | Development compose stack |
| `apps/api/Dockerfile.dev` | Backend and worker image |
| `apps/web/Dockerfile.dev` | Frontend image |
| `apps/api/` | FastAPI backend source |
| `apps/web/` | SvelteKit frontend source |

There is no production compose file in this repository at the moment. `./scripts/docker.sh prod` expects `compose.prod.yaml` and will fail until a production stack is added.

## GPU Support

The `worker` service reserves one NVIDIA GPU by default. If you do not have an NVIDIA GPU, remove or comment out the `worker.deploy.resources.reservations.devices` section in `compose.dev.yaml`, then start the dev stack normally:

```bash
./scripts/docker.sh dev
```

ML models are cached in the `echoroo-dev-ml-models` Docker volume.

## Common Tasks

```bash
# View all logs
./scripts/docker.sh dev logs

# View one service
./scripts/docker.sh dev logs backend

# Open a backend shell
./scripts/docker.sh dev shell backend

# Restart both worker queues after queue-code changes
./scripts/docker.sh dev restart workers

# Connect to PostgreSQL
./scripts/docker.sh dev db
```

## Data

Audio files are mounted read-only from the host path configured by `ECHOROO_AUDIO_DIR`:

```bash
ECHOROO_AUDIO_DIR=/path/to/audio/files
```

LocalStack data defaults to `./.data/localstack` and can be customized with:

```bash
ECHOROO_LOCALSTACK_DATA=/path/to/localstack-data
```

## Troubleshooting

### Containers Do Not Start

```bash
./scripts/docker.sh dev status
./scripts/docker.sh dev logs
```

### Port Already In Use

```bash
ECHOROO_FRONTEND_PORT=5174
ECHOROO_API_PORT=8003
POSTGRES_PORT=5433
```

### Rebuild From Scratch

```bash
./scripts/docker.sh dev clean
./scripts/docker.sh dev build
./scripts/docker.sh dev
```

Use `clean-all` only when you want to delete Docker volumes as well.

## Environment Variables

See [CONFIGURATION.md](CONFIGURATION.md) for the environment variable reference.
