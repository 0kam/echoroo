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

# Build base image (one-time, contains ML dependencies)
cd back && docker build -f Dockerfile.base -t echoroo-base:latest .
cd ..

# Start Echoroo (development mode)
./scripts/docker.sh dev
```

Then open http://localhost:3000 in your browser.

See [DOCKER.md](DOCKER.md) for detailed Docker instructions.

### Local Development (Without Docker)

For development without Docker:

```bash
# Run setup script
./scripts/setup.sh

# Start PostgreSQL (required)
# See QUICK_START.md for database setup options

# Start backend (Terminal 1)
cd back && uv run python -m echoroo

# Start frontend (Terminal 2)
cd front && npm run dev
```

**Requirements:** Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 18+, PostgreSQL (or SQLite)

For detailed instructions, refer to the [Quick Start Guide](QUICK_START.md) or [Configuration Guide](CONFIGURATION.md).

## Usage

### Running Echoroo with Docker

**Development:**
```bash
./scripts/docker.sh dev              # Start
./scripts/docker.sh dev logs         # View logs
./scripts/docker.sh dev stop         # Stop
./scripts/docker.sh dev db           # Connect to database
```

**Production:**
```bash
./scripts/docker.sh prod             # Start
./scripts/docker.sh prod logs        # View logs
./scripts/docker.sh prod stop        # Stop
```

### Documentation

For detailed information about using Echoroo, refer to:
- [Docker Guide](DOCKER.md) - Docker deployment instructions
- [Configuration Guide](CONFIGURATION.md) - Environment configuration

## Acknowledgements

This project is built upon the [Whombat](https://github.com/mbsantiago/whombat) project, originally developed with the generous support of the Mexican Council of the Humanities, Science and Technology (**CONAHCyT**; Award Number 2020-000017-02EXTF-00334) and University College London (**UCL**).
