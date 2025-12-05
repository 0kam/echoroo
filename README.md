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

# Start Echoroo (development mode)
./scripts/docker.sh dev
```

Then open http://localhost:3000 in your browser.

See [DOCKER.md](DOCKER.md) for detailed Docker instructions.

### Other Installation Methods

- **Python Package**: Install from the source code

For detailed installation instructions, refer to the [Configuration Guide](CONFIGURATION.md).

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

## Contribution

We welcome contributions from the community. Please refer to the contribution guidelines for information on how you can contribute.

## Citation

If you use this tool in your research, please cite the original Whombat paper:

> Balvanera, S. M., Mac Aodha, O., Weldy, M. J., Pringle, H., Browning, E., & Jones, K. E. (2023). Whombat: An open-source annotation tool for machine learning development in bioacoustics. arXiv preprint [arXiv:2308.12688](https://arxiv.org/abs/2308.12688).

## Acknowledgements

This project is built upon the Whombat project, originally developed with the generous support of the Mexican Council of the Humanities, Science and Technology (**CONAHCyT**; Award Number 2020-000017-02EXTF-00334) and University College London (**UCL**).
