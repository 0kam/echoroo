# ML Model Installation System

## Overview

The ML model installation system provides automated downloading, verification, and installation of machine learning models used in Whombat. It supports multiple model backends (BirdNET, Perch) with different installation methods.

## Architecture

### Core Components

1. **Base Installer (`whombat.ml.installer.base`)**
   - `ModelInstaller`: Abstract base class for all installers
   - `InstallStatus`: Enum for tracking installation state
   - `ModelArtifact`: Metadata for downloadable files
   - `InstallationProgress`: Progress tracking for UI updates

2. **Model-Specific Installers**
   - `BirdNETInstaller`: Manages BirdNET metadata files
   - `PerchInstaller`: Manages Perch model via perch-hoplite

3. **REST API (`whombat.routes.setup`)**
   - `GET /api/v1/setup/models/status/`: Check all models
   - `POST /api/v1/setup/models/{model_name}/install/`: Install model
   - `POST /api/v1/setup/models/{model_name}/uninstall/`: Uninstall model

4. **Schemas (`whombat.schemas.setup`)**
   - `ModelStatus`: Status of single model
   - `ModelsStatus`: Status of all models
   - `InstallRequest`: Installation request
   - `InstallResponse`: Installation response

## Installation Methods

### BirdNET

**Installation Method**: Python package + optional metadata

The BirdNET model itself is distributed via the `birdnet` pip package (~100MB). The installer manages optional metadata files like species presence data for geographic filtering.

**Requirements**:
- `birdnet` package installed
- No API credentials required

**Installation**:
```bash
pip install birdnet
```

**Default Directory**: `~/.whombat/models/birdnet/`

### Perch

**Installation Method**: Kaggle download via perch-hoplite

The Perch model is hosted on Kaggle and downloaded automatically by the perch-hoplite package on first use (~100MB).

**Requirements**:
- `perch-hoplite` package installed
- Kaggle API credentials configured

**Installation**:
```bash
# Install perch-hoplite
pip install git+https://github.com/google-research/perch-hoplite.git

# Configure Kaggle credentials (choose one):
# 1. Environment variables
export KAGGLE_USERNAME=your_username
export KAGGLE_KEY=your_api_key

# 2. Config file at ~/.kaggle/kaggle.json
{
  "username": "your_username",
  "key": "your_api_key"
}
```

**Default Directory**: `~/.whombat/models/perch/`

## API Usage

### Check Installation Status

```python
from whombat.ml.installer import check_all_models, get_installer

# Check all models
status = check_all_models()
print(f"BirdNET: {status['birdnet'].value}")
print(f"Perch: {status['perch'].value}")

# Check specific model
installer = get_installer("birdnet")
status = installer.check_status()
print(f"BirdNET status: {status.value}")
```

### Install Model

```python
from whombat.ml.installer import get_installer

# Create installer
installer = get_installer("birdnet")

# Define progress callback (optional)
def on_progress(progress):
    print(f"{progress.progress:.0f}% - {progress.message}")

# Install with progress tracking
await installer.install(progress_callback=on_progress)
```

### Uninstall Model

```python
from whombat.ml.installer import get_installer

installer = get_installer("birdnet")
installer.uninstall()
```

## REST API Examples

### Get Status

```bash
curl http://localhost:5000/api/v1/setup/models/status/
```

Response:
```json
{
  "birdnet": {
    "name": "birdnet",
    "status": "installed",
    "installed_version": null,
    "package_available": true,
    "requires_credentials": false,
    "credentials_configured": true,
    "message": null
  },
  "perch": {
    "name": "perch",
    "status": "not_installed",
    "installed_version": null,
    "package_available": false,
    "requires_credentials": true,
    "credentials_configured": false,
    "message": "Install perch-hoplite package"
  },
  "created_at": "2025-12-05T10:30:00"
}
```

### Install Model

```bash
curl -X POST http://localhost:5000/api/v1/setup/models/birdnet/install/ \
  -H "Content-Type: application/json" \
  -d '{"model_name": "birdnet", "force_reinstall": false}'
```

Response:
```json
{
  "success": true,
  "message": "birdnet installed successfully",
  "status": {
    "name": "birdnet",
    "status": "installed",
    "package_available": true
  }
}
```

### Uninstall Model

```bash
curl -X POST http://localhost:5000/api/v1/setup/models/birdnet/uninstall/
```

Response:
```json
{
  "success": true,
  "message": "birdnet uninstalled successfully"
}
```

## Installation States

The system tracks the following installation states:

- `NOT_INSTALLED`: Model files not present
- `DOWNLOADING`: Download in progress
- `INSTALLED`: All required files present and verified
- `CORRUPTED`: Files present but checksum verification failed
- `FAILED`: Installation attempt failed

## Security Features

1. **Checksum Verification**: All downloads verified with SHA256 checksums
2. **Atomic Operations**: Downloads to temporary files, moved on success
3. **Credential Protection**: Kaggle credentials stored securely
4. **Directory Isolation**: Models installed to user-specific directories

## Error Handling

The system provides comprehensive error messages for common issues:

- Package not installed
- Missing credentials
- Network failures
- Checksum mismatches
- Insufficient disk space

Example error response:
```json
{
  "success": false,
  "message": "Installation failed: Kaggle credentials not configured",
  "status": {
    "name": "perch",
    "status": "failed",
    "message": "Set KAGGLE_USERNAME and KAGGLE_KEY environment variables"
  }
}
```

## Progress Tracking

The installation system supports real-time progress updates via callbacks:

```python
from whombat.ml.installer.base import InstallationProgress

def progress_callback(progress: InstallationProgress):
    print(f"Status: {progress.status.value}")
    print(f"Progress: {progress.progress:.1f}%")
    print(f"Message: {progress.message}")
    print(f"Downloaded: {progress.downloaded_mb:.1f}MB / {progress.total_mb:.1f}MB")

await installer.install(progress_callback=progress_callback)
```

## Extending the System

To add a new model installer:

1. Create installer class inheriting from `ModelInstaller`
2. Define model artifacts (files to download)
3. Implement `_post_install()` for model-specific setup
4. Add installer to `get_installer()` function
5. Update REST API to include new model

Example:
```python
from whombat.ml.installer.base import ModelInstaller, ModelArtifact

class MyModelInstaller(ModelInstaller):
    def __init__(self):
        artifacts = [
            ModelArtifact(
                name="model.pt",
                url="https://example.com/model.pt",
                checksum="abc123...",
                size_mb=500.0,
                required=True,
            )
        ]
        super().__init__(
            model_name="my_model",
            model_dir=Path.home() / ".whombat" / "models" / "my_model",
            artifacts=artifacts,
        )

    async def _post_install(self):
        # Custom post-installation logic
        pass
```

## File Locations

- **BirdNET**: `~/.whombat/models/birdnet/`
- **Perch**: `~/.whombat/models/perch/`
- **Settings**: Uses paths from `whombat.system.settings`

## Dependencies

- `aiohttp>=3.9.0`: Async HTTP client for downloads
- `birdnet>=0.2.0`: BirdNET model (optional)
- `perch-hoplite`: Perch model (optional, from GitHub)

## Testing

Run installer tests:
```bash
cd back
uv run python -c "from whombat.ml.installer import check_all_models; print(check_all_models())"
```

Type checking:
```bash
cd back
uv run pyright src/whombat/ml/installer/
```

## Troubleshooting

### BirdNET Installation Issues

**Issue**: `birdnet: not_installed`
**Solution**: Install the birdnet package
```bash
pip install birdnet
```

### Perch Installation Issues

**Issue**: `perch-hoplite package not installed`
**Solution**: Install from GitHub
```bash
pip install git+https://github.com/google-research/perch-hoplite.git
```

**Issue**: `Kaggle credentials not configured`
**Solution**: Set environment variables
```bash
export KAGGLE_USERNAME=your_username
export KAGGLE_KEY=your_api_key
```

**Issue**: `Failed to download Perch model`
**Solution**: Check Kaggle credentials and network connection

### General Issues

**Issue**: Checksum verification failed
**Solution**: Remove corrupted files and reinstall
```bash
rm -rf ~/.whombat/models/birdnet/
# Then reinstall via API
```

**Issue**: Download times out
**Solution**: Check network connection and firewall settings

## Future Enhancements

Potential improvements:

1. **Download Resumption**: Resume interrupted downloads
2. **Batch Operations**: Install multiple models simultaneously
3. **Version Management**: Support multiple model versions
4. **Automatic Updates**: Check for and install model updates
5. **Bandwidth Throttling**: Limit download speed
6. **Proxy Support**: Configure HTTP proxy for downloads
7. **Mirror Sites**: Support alternative download locations
8. **Compression**: Support compressed artifacts (tar.gz, zip)
