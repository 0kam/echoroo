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
#   - ECHOROO_AUDIO_DIR (required - path to your audio files)

# Generate local Redis TLS certificates
./scripts/gen-redis-dev-cert.sh

# Start Echoroo (development mode)
./scripts/docker.sh dev
```

Then open http://localhost:5173 in your browser.

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
./scripts/docker.sh dev              # Start
./scripts/docker.sh dev logs         # View logs
./scripts/docker.sh dev stop         # Stop
./scripts/docker.sh dev db           # Connect to database
```

**Rebuild images:**
```bash
ECHOROO_BUILD=1 ./scripts/docker.sh dev
./scripts/docker.sh dev build
```

### Documentation

For detailed information about using Echoroo, refer to:
- [Docker Guide](DOCKER.md) - Docker deployment instructions
- [Configuration Guide](CONFIGURATION.md) - Environment configuration

## ML Configuration

Echoroo uses GPU-accelerated machine learning models (BirdNET, Perch) for species detection. Configure these settings in your `.env` file:

| Variable | Description | Default |
|----------|-------------|---------|
| `ECHOROO_ML_USE_GPU` | Enable GPU acceleration | `true` |
| `ECHOROO_ML_GPU_DEVICE` | Device specification (`GPU`, `CPU`, `GPU:0`, `GPU:1`) | `GPU` |
| `ECHOROO_ML_GPU_BATCH_SIZE` | Segments processed in parallel per GPU inference | `16` |
| `ECHOROO_ML_FEEDERS` | Number of file feeder processes for audio loading | `8` |
| `ECHOROO_ML_WORKERS` | Number of GPU inference workers | `1` |

### Troubleshooting: CUDA_ERROR_OUT_OF_MEMORY

If you encounter GPU memory errors during ML inference:

1. **Reduce batch size:** Lower `ECHOROO_ML_GPU_BATCH_SIZE` (try 8 or 4)
2. **Reduce feeders:** Lower `ECHOROO_ML_FEEDERS` (try 4)
3. **Use CPU:** Set `ECHOROO_ML_USE_GPU=false` (slower but avoids GPU memory issues)
4. **Select specific GPU:** Set `ECHOROO_ML_GPU_DEVICE=GPU:0` or `GPU:1` if you have multiple GPUs

## Acknowledgements

This project is built upon the [Whombat](https://github.com/mbsantiago/whombat) project, originally developed with the generous support of the Mexican Council of the Humanities, Science and Technology (**CONAHCyT**; Award Number 2020-000017-02EXTF-00334) and University College London (**UCL**).
