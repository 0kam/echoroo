# Echoroo Docker Guide

This guide covers the current Docker development environment. The top-level
`./echoroo.sh` script is the supported user-facing entry point.

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
#   - INVITATION_TOKEN_HMAC_KEY
#   - ECHOROO_AUDIO_DIR
# Generate a value for INVITATION_TOKEN_HMAC_KEY with:
openssl rand -hex 32

./echoroo.sh install
./echoroo.sh checkenv
./echoroo.sh start
```

If `.env` is missing, `install` creates it from `.env.example` and exits
non-zero so you can edit the required values before starting the stack.

Open http://localhost:5173 in your browser. The backend API is exposed at http://localhost:8002.

## Management Script

All Docker operations use `./echoroo.sh`:

```bash
./echoroo.sh [command] [args]
```

| Command | Description |
|---------|-------------|
| `install` | Prepare local dev prerequisites and generate Redis dev TLS certificates. If `.env` is created, exits non-zero for editing |
| `checkenv` | Validate required `.env` settings before startup |
| `start` | Start containers |
| `stop` | Stop containers |
| `restart [service]` | Restart all containers or one service |
| `update [--allow-dirty] [--yes-migrate] [--ref <branch-or-ref>]` | Fast-forward the current branch or explicit ref, pull images where possible, build, optionally migrate, and start. Aborts on dirty git status unless `--allow-dirty` is provided |
| `version` | Show CLI, git, app, Docker, Compose, and Alembic versions |
| `logs [service]` | Show logs |
| `status` | Show container status |
| `shell [service]` | Open a shell in a service container |
| `db` | Connect to PostgreSQL |
| `migrate` | Run Alembic migrations in the backend container |
| `seed e2e [args...]` | Run `echoroo.scripts.seed_e2e_permissions`. With no args, passes `--confirm`; explicit args are forwarded unchanged |
| `build [--no-cache] [service...]` | Build images with cache by default; pass `--no-cache` for a clean rebuild |
| `clean` | Stop and remove containers |
| `clean-all` | Remove containers and volumes after typed confirmation |

The old `./scripts/docker.sh` path remains as a compatibility wrapper.

To rebuild images on start or restart:

```bash
./echoroo.sh start --build
```

For an explicit no-cache rebuild:

```bash
./echoroo.sh build --no-cache
./echoroo.sh restart
```

`update` runs `git pull --ff-only` on the current branch by default and warns
when that branch is not the default branch. To update from a specific branch or
ref, use `./echoroo.sh update --ref main`; the script fetches `origin <ref>` and
fast-forwards to `FETCH_HEAD`.

`update` refuses to run on a dirty git worktree, including untracked files. Use
`./echoroo.sh update --allow-dirty` only when you intentionally want to update
with local changes present.

Migrations are not run automatically during `update`. After updating, run
`./echoroo.sh migrate`, or pass `./echoroo.sh update --yes-migrate` to include
migrations. `--yes-migrate` prints a database backup/snapshot warning and
Alembic state before applying DB schema changes.

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

There is no production compose file in this repository at the moment. `./echoroo.sh prod ...`
exits with an unsupported-environment error until a production stack is added.

## GPU Support

The `worker` service reserves one NVIDIA GPU by default. If you do not have an NVIDIA GPU, remove or comment out the `worker.deploy.resources.reservations.devices` section in `compose.dev.yaml`, then start the dev stack normally:

```bash
./echoroo.sh start
```

ML models are cached in the `echoroo-dev-ml-models` Docker volume.

### GPU present but unusable by TensorFlow (e.g. Blackwell / sm_120)

Some GPUs (notably NVIDIA Blackwell / RTX 50-series / sm_120) are enumerated by TensorFlow but cannot actually run its kernels — TF lists the device and then crashes at kernel launch, which can take the host down. On such a box (the GPU is **present** but unusable), force CPU inference instead of relying on auto-detection:

```bash
# .env
ECHOROO_ML_USE_GPU=false        # forces CPU (CUDA_VISIBLE_DEVICES=-1) for BirdNET + Perch
ECHOROO_WORKER_MEM_LIMIT=24g    # bound worker RAM (~40% of host RAM) so CPU inference can't OOM-reboot the host
```

CPU mode is slower but stable. It also auto-caps inference threads (`ECHOROO_ML_CPU_NUM_THREADS`) and shrinks the Perch warmup (`ECHOROO_ML_CPU_WARMUP_BATCHES`). See [Configuration Guide](CONFIGURATION.md#machine-learning-settings) for the full ML env-var list.

> **No NVIDIA GPU at all?** `ECHOROO_ML_USE_GPU=false` is necessary but **not sufficient**. The `worker` service still reserves an NVIDIA device via `deploy.resources.reservations.devices`, so the container fails to start on a host with no NVIDIA GPU. You must **also** remove or comment out that block in `compose.dev.yaml` (see [GPU Support](#gpu-support) above) in addition to setting `ECHOROO_ML_USE_GPU=false`.

## Common Tasks

```bash
# View all logs
./echoroo.sh logs

# View one service
./echoroo.sh logs backend

# Open a backend shell
./echoroo.sh shell backend

# Restart both worker queues after queue-code changes
./echoroo.sh restart workers

# Connect to PostgreSQL
./echoroo.sh db

# Run migrations
./echoroo.sh migrate

# Seed permission E2E data
# Warning: stdout JSON includes credentials/tokens; handle it as sensitive.
./echoroo.sh seed e2e
./echoroo.sh seed e2e --prefix preview --password 'change-me'
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
./echoroo.sh status
./echoroo.sh logs
```

### Port Already In Use

```bash
ECHOROO_FRONTEND_PORT=5174
ECHOROO_API_PORT=8003
POSTGRES_PORT=5433
```

### Rebuild From Scratch

```bash
./echoroo.sh clean
./echoroo.sh build --no-cache
./echoroo.sh start
```

Use `clean-all` only when you want to delete Docker volumes as well.

## Environment Variables

See [CONFIGURATION.md](CONFIGURATION.md) for the environment variable reference.
