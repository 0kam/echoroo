# Whombat

![GitHub License](https://img.shields.io/github/license/mbsantiago/whombat)
![Python Version from PEP 621 TOML](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fmbsantiago%2Fwhombat%2Fdev%2Fback%2Fpyproject.toml)
![Static Badge](https://img.shields.io/badge/formatting-black-black)
[![codecov](https://codecov.io/gh/mbsantiago/whombat/graph/badge.svg?token=WMzUfSXIyL)](https://codecov.io/gh/mbsantiago/whombat)
![build](https://github.com/mbsantiago/whombat/actions/workflows/bundle.yml/badge.svg)
![lint](https://github.com/mbsantiago/whombat/actions/workflows/lint.yml/badge.svg)
![docs](https://github.com/mbsantiago/whombat/actions/workflows/docs.yml/badge.svg)
![tests](https://github.com/mbsantiago/whombat/actions/workflows/test.yml/badge.svg)
[![DOI](https://zenodo.org/badge/682458553.svg)](https://zenodo.org/doi/10.5281/zenodo.10604169)

**Whombat** is an open-source, web-based audio annotation tool designed to streamline audio data labeling and annotation, with a particular focus on supporting machine learning model development.

## Quick Start

### 🐳 Docker (Recommended)

The easiest way to get started with Whombat:

```bash
# Clone the repository
git clone https://github.com/mbsantiago/whombat.git
cd whombat

# Configure settings
cp .env.example .env
# Edit .env to set WHOMBAT_AUDIO_DIR to your audio files location

# Start Whombat
./scripts/docker.sh start
```

Then open http://localhost:5000 in your browser.

See [DOCKER.md](DOCKER.md) for detailed Docker instructions.

### 📦 Other Installation Methods

- **Standalone Executable**: Download from [Releases](https://github.com/mbsantiago/whombat/releases)
- **Python Package**: `pip install whombat`

For detailed installation instructions, refer to the [Installation Guide](https://mbsantiago.github.io/whombat/user_guide/installation/).

## Usage

### Running Whombat

**With Docker:**
```bash
./scripts/docker.sh start    # Start
./scripts/docker.sh logs     # View logs
./scripts/docker.sh stop     # Stop
```

**With Python:**
```bash
python -m whombat
# or simply
whombat
```

**With Executable:**
Double-click the downloaded executable file.

### Documentation

We have prepared a comprehensive [User Guide](https://mbsantiago.github.io/whombat/user_guide/) to accompany you in your annotation work, covering all features and workflows.

## Contribution

As a open source project we are incredibly excited for having contributions from the community.
Head over to the [Contributions](https://mbsantiago.github.io/whombat/CONTRIBUTING/) section of the documentation to see how you can contribute.

## Citation

If you want to use Whombat for your research, please cite as:

> Balvanera, S. M., Mac Aodha, O., Weldy, M. J., Pringle, H., Browning, E., & Jones, K. E. (2023). Whombat: An open-source annotation tool for machine learning development in bioacoustics. arXiv preprint [arXiv:2308.12688](https://arxiv.org/abs/2308.12688).

## Acknowledgements

Whombat has been developed with the generous support of the Mexican Council of the Humanities, Science and Technology (**CONAHCyT**; Award Number 2020-000017-02EXTF-00334) and University College London (**UCL**).
