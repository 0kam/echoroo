"""Setup routes for administrative configuration."""

import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, DirectoryPath

from echoroo.ml.installer import (
    InstallStatus,
    check_all_models,
    check_birdnet_available,
    get_installer,
)
from echoroo.schemas.setup import (
    InstallRequest,
    InstallResponse,
    ModelStatus,
    ModelsStatus,
)
from echoroo.system.settings import Settings, get_settings, write_settings_to_file

__all__ = ["get_setup_router"]

logger = logging.getLogger(__name__)


class _AudioDirPayload(BaseModel):
    audio_dir: DirectoryPath


def get_setup_router(settings: Settings) -> APIRouter:
    """Create router for setup and configuration endpoints.

    Parameters
    ----------
    settings : Settings
        Application settings.

    Returns
    -------
    APIRouter
        FastAPI router with setup endpoints.
    """
    router = APIRouter()

    # Audio directory configuration
    @router.get("/audio_dir/")
    def get_audio_directory(current: Settings = Depends(get_settings)):
        """Return the current audio directory.

        Returns
        -------
        dict
            Dictionary with 'audio_dir' key containing absolute path.
        """
        return {"audio_dir": str(current.audio_dir.resolve())}

    @router.post("/audio_dir/")
    def update_audio_directory(
        payload: _AudioDirPayload,
        current: Settings = Depends(get_settings),
    ):
        """Persist a new audio directory to the settings file.

        Parameters
        ----------
        payload : _AudioDirPayload
            Payload with new audio directory path.
        current : Settings
            Current application settings.

        Returns
        -------
        dict
            Dictionary with updated 'audio_dir' path.
        """
        resolved: Path = payload.audio_dir.resolve()
        write_settings_to_file(
            current.model_copy(update={"audio_dir": resolved})
        )
        return {"audio_dir": str(resolved)}

    # Model installation endpoints
    @router.get("/models/status/", response_model=ModelsStatus)
    def get_models_status():
        """Check installation status of all ML models.

        Returns
        -------
        ModelsStatus
            Status information for BirdNET model.

        Examples
        --------
        GET /api/v1/setup/models/status/

        Response:
        {
            "birdnet": {
                "name": "birdnet",
                "status": "installed",
                "package_available": true,
                ...
            },
            "created_at": "2025-12-05T10:30:00"
        }
        """
        try:
            statuses = check_all_models()

            # Build BirdNET status
            birdnet_status = ModelStatus(
                name="birdnet",
                status=statuses.get("birdnet", InstallStatus.FAILED),
                package_available=check_birdnet_available(),
                requires_credentials=False,
                credentials_configured=True,
                message=(
                    "Install with: pip install birdnet"
                    if not check_birdnet_available()
                    else None
                ),
            )

            return ModelsStatus(
                birdnet=birdnet_status,
                perch=None,  # Perch support removed in v0.8.6+
                created_at=datetime.now(),
            )

        except Exception as e:
            logger.error(f"Failed to check model status: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to check model status: {str(e)}",
            )

    @router.post(
        "/models/{model_name}/install/",
        response_model=InstallResponse,
    )
    async def install_model(model_name: str, request: InstallRequest):
        """Install a specific ML model.

        Parameters
        ----------
        model_name : str
            Name of model to install ("birdnet").
        request : InstallRequest
            Installation request parameters.

        Returns
        -------
        InstallResponse
            Installation result with updated status.

        Raises
        ------
        HTTPException
            If model name is invalid or installation fails.

        Examples
        --------
        POST /api/v1/setup/models/birdnet/install/
        {
            "model_name": "birdnet",
            "force_reinstall": false
        }

        Response:
        {
            "success": true,
            "message": "BirdNET installed successfully",
            "status": {
                "name": "birdnet",
                "status": "installed",
                ...
            }
        }
        """
        try:
            # Validate model name
            if model_name.lower() not in ["birdnet"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown model: {model_name}. "
                    f"Available models: birdnet",
                )

            # Get installer
            installer = get_installer(model_name)

            # Check if already installed
            current_status = installer.check_status()
            if (
                current_status == InstallStatus.INSTALLED
                and not request.force_reinstall
            ):
                return InstallResponse(
                    success=True,
                    message=f"{model_name} is already installed",
                    status=ModelStatus(
                        name=model_name,
                        status=current_status,
                        package_available=True,
                    ),
                )

            # Uninstall if force reinstall
            if request.force_reinstall and current_status == InstallStatus.INSTALLED:
                logger.info(f"Uninstalling {model_name} for reinstallation")
                installer.uninstall()

            # Perform installation
            logger.info(f"Starting installation of {model_name}")
            success = await installer.install()

            # Get updated status
            new_status = installer.check_status()

            if success and new_status == InstallStatus.INSTALLED:
                return InstallResponse(
                    success=True,
                    message=f"{model_name} installed successfully",
                    status=ModelStatus(
                        name=model_name,
                        status=new_status,
                        package_available=True,
                    ),
                )
            else:
                return InstallResponse(
                    success=False,
                    message=f"{model_name} installation failed",
                    status=ModelStatus(
                        name=model_name,
                        status=new_status,
                    ),
                )

        except Exception as e:
            logger.error(f"Failed to install {model_name}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Installation failed: {str(e)}",
            )

    @router.post("/models/{model_name}/uninstall/")
    async def uninstall_model(model_name: str):
        """Uninstall a specific ML model.

        Parameters
        ----------
        model_name : str
            Name of model to uninstall ("birdnet").

        Returns
        -------
        dict
            Result message.

        Raises
        ------
        HTTPException
            If model name is invalid or uninstallation fails.

        Examples
        --------
        POST /api/v1/setup/models/birdnet/uninstall/

        Response:
        {
            "success": true,
            "message": "BirdNET uninstalled successfully"
        }
        """
        try:
            # Validate model name
            if model_name.lower() not in ["birdnet"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown model: {model_name}. "
                    f"Available models: birdnet",
                )

            # Get installer
            installer = get_installer(model_name)

            # Check if installed
            current_status = installer.check_status()
            if current_status == InstallStatus.NOT_INSTALLED:
                return {
                    "success": True,
                    "message": f"{model_name} is not installed",
                }

            # Uninstall
            logger.info(f"Uninstalling {model_name}")
            installer.uninstall()

            # Verify uninstallation
            new_status = installer.check_status()
            if new_status == InstallStatus.NOT_INSTALLED:
                return {
                    "success": True,
                    "message": f"{model_name} uninstalled successfully",
                }
            else:
                return {
                    "success": False,
                    "message": f"{model_name} uninstallation may be incomplete",
                }

        except Exception as e:
            logger.error(f"Failed to uninstall {model_name}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Uninstallation failed: {str(e)}",
            )

    return router
