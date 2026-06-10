# Echoroo

Echoroo is an open-source, web-based ecoacoustic platform. Integrated with state-of-the-art AI, Echoroo enables fast and efficient analysis, search, and development of new models for acoustic data.

## Quick Start

### Docker (Recommended)

The easiest way to get started with Echoroo:

```bash
# Clone the repository
git clone https://github.com/0kam/echoroo.git
cd echoroo

# Configure settings
cp .env.example .env
# Edit .env to set:
#   - POSTGRES_PASSWORD (required)
#   - INVITATION_TOKEN_HMAC_KEY (required)
#   - ECHOROO_AUDIO_DIR (required - path to your audio files)
# Generate a value for INVITATION_TOKEN_HMAC_KEY with:
openssl rand -hex 32

# Prepare local dev prerequisites and validate configuration
./echoroo.sh install
./echoroo.sh checkenv

# Start Echoroo (development mode)
./echoroo.sh start
```

Then open http://localhost:5173 in your browser.

If `.env` is missing, `install` creates it from `.env.example` and exits
non-zero so you can edit the required values before starting.

See [DOCKER.md](DOCKER.md) for detailed Docker instructions.

### Local Development (Without Docker)

For development without Docker:

```bash
# Start PostgreSQL (required)
# See CONFIGURATION.md for database setup options

# Start backend (Terminal 1)
cd apps/api && uv run uvicorn echoroo.main:app --reload

# Start frontend (Terminal 2)
cd apps/web && npm run dev
```

**Requirements:** Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 20+, PostgreSQL (or SQLite)

For detailed instructions, refer to the [Configuration Guide](CONFIGURATION.md).

## Usage

### Running Echoroo with Docker

**Development:**
```bash
./echoroo.sh start          # Start
./echoroo.sh status         # Show containers and health
./echoroo.sh logs           # View logs
./echoroo.sh stop           # Stop containers, keep data
./echoroo.sh db             # Connect to database
./echoroo.sh migrate        # Run Alembic migrations
./echoroo.sh update --ref main
./echoroo.sh update --yes-migrate
./echoroo.sh seed e2e [args...]  # Seed E2E data; stdout includes sensitive JSON
```

**Rebuild images:**
```bash
./echoroo.sh start --build
./echoroo.sh build
./echoroo.sh build --no-cache
```

### Documentation

For detailed information about using Echoroo, refer to:
- [Docker Guide](DOCKER.md) - Docker deployment instructions
- [Configuration Guide](CONFIGURATION.md) - Environment configuration

## ML Configuration

Echoroo uses GPU-accelerated machine learning models (BirdNET, Perch — both on TensorFlow) for species detection. The defaults below preserve GPU behaviour, so a host with a working GPU needs none of these set. Configure them in your `.env` file:

| Variable | Description | Default |
|----------|-------------|---------|
| `ECHOROO_ML_USE_GPU` | Use the GPU for inference. `false` forces CPU (`CUDA_VISIBLE_DEVICES=-1`) for both BirdNET and Perch. | `true` |
| `ECHOROO_ML_GPU_BATCH_SIZE` | Segments processed in parallel per inference batch | `16` |
| `ECHOROO_ML_FEEDERS` | Number of file feeder processes for audio loading | `1` |
| `ECHOROO_ML_WORKERS` | Number of inference workers | `1` |
| `ECHOROO_ML_CPU_NUM_THREADS` | Thread cap applied **only** in CPU mode (bounds TF / OpenMP / BLAS pools so CPU inference does not exhaust RAM) | `8` |
| `ECHOROO_ML_CPU_WARMUP_BATCHES` | Comma-separated Perch warmup batch sizes used **only** in CPU mode (empty = skip warmup). GPU mode always warms up `1,6,10,16`. | `1` |
| `ECHOROO_ML_GPU_ALLOW_GROWTH` | In GPU mode, set `TF_FORCE_GPU_ALLOW_GROWTH=true` so TF grows GPU memory on demand | `true` |
| `ECHOROO_WORKER_MEM_LIMIT` | Compose-level RAM cap for the worker container (`0` = unlimited). Set e.g. `24g` on a CPU/Blackwell box to keep the host alive. | `0` |

### Troubleshooting: CUDA_ERROR_OUT_OF_MEMORY

If you encounter GPU memory errors during ML inference:

1. **Reduce batch size:** Lower `ECHOROO_ML_GPU_BATCH_SIZE` (try 8 or 4)
2. **Reduce feeders:** Lower `ECHOROO_ML_FEEDERS`
3. **Use CPU:** Set `ECHOROO_ML_USE_GPU=false` (slower but avoids GPU memory issues; also bound RAM with `ECHOROO_WORKER_MEM_LIMIT`)

### Unsupported or absent GPU (e.g. Blackwell / sm_120)

On a host whose GPU is enumerated by TensorFlow but unusable (e.g. NVIDIA Blackwell / RTX 50-series / sm_120), TF lists the device then crashes at kernel launch, so auto-detection alone is not enough. Set `ECHOROO_ML_USE_GPU=false` to force CPU inference for both BirdNET and Perch, and set `ECHOROO_WORKER_MEM_LIMIT` (e.g. `24g`, ~40% of host RAM) to keep CPU inference from exhausting RAM and rebooting the host. CPU mode is slower but stable.

## Acknowledgements

This project is built upon the [Whombat](https://github.com/mbsantiago/whombat) project, originally developed with the generous support of the Mexican Council of the Humanities, Science and Technology (**CONAHCyT**; Award Number 2020-000017-02EXTF-00334) and University College London (**UCL**).
