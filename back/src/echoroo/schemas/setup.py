"""Schemas for system setup and model installation."""

from datetime import datetime

from pydantic import ConfigDict, Field

from echoroo.ml.installer.base import InstallStatus
from echoroo.schemas.base import BaseSchema

__all__ = [
    "InstallRequest",
    "InstallResponse",
    "ModelStatus",
    "ModelsStatus",
]


class ModelStatus(BaseSchema):
    """Status information for a single ML model.

    Attributes
    ----------
    name : str
        Model name (e.g., "birdnet", "perch").
    status : InstallStatus
        Current installation status.
    installed_version : str | None
        Version string of installed model, or None if not installed.
        Default is None.
    package_available : bool
        Whether the required Python package is installed.
        Default is False.
    requires_credentials : bool
        Whether the model requires API credentials (e.g., Kaggle).
        Default is False.
    credentials_configured : bool
        Whether required credentials are configured.
        Default is False.
    message : str | None
        Additional status message or instructions.
        Default is None.

    Examples
    --------
    >>> status = ModelStatus(
    ...     name="birdnet",
    ...     status=InstallStatus.INSTALLED,
    ...     installed_version="2.4",
    ...     package_available=True,
    ... )
    >>> print(f"{status.name}: {status.status.value}")
    birdnet: installed
    """

    name: str = Field(..., description="Model name")
    status: InstallStatus = Field(..., description="Installation status")
    installed_version: str | None = Field(
        default=None,
        description="Installed model version",
    )
    package_available: bool = Field(
        default=False,
        description="Whether required package is installed",
    )
    requires_credentials: bool = Field(
        default=False,
        description="Whether model requires API credentials",
    )
    credentials_configured: bool = Field(
        default=False,
        description="Whether required credentials are configured",
    )
    message: str | None = Field(
        default=None,
        description="Additional status message or instructions",
    )


class ModelsStatus(BaseSchema):
    """Status information for all ML models.

    Attributes
    ----------
    birdnet : ModelStatus
        Status of BirdNET model.
    perch : ModelStatus | None
        Status of Perch model. None indicates Perch support has been removed.
    created_at : datetime
        Timestamp when status was checked.

    Examples
    --------
    >>> from datetime import datetime
    >>> status = ModelsStatus(
    ...     birdnet=ModelStatus(name="birdnet", status=InstallStatus.INSTALLED),
    ...     perch=None,  # Perch support removed in v0.8.6+
    ...     created_at=datetime.now(),
    ... )
    >>> print(f"BirdNET: {status.birdnet.status.value}")
    BirdNET: installed
    """

    birdnet: ModelStatus = Field(..., description="BirdNET model status")
    perch: ModelStatus | None = Field(
        default=None,
        description="Perch model status (deprecated, removed in v0.8.6+)",
    )
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="Status check timestamp",
    )


class InstallRequest(BaseSchema):
    """Request to install a model.

    Attributes
    ----------
    model_name : str
        Name of model to install ("birdnet").
    force_reinstall : bool
        Whether to reinstall even if already installed.
        Default is False.

    Examples
    --------
    >>> request = InstallRequest(model_name="birdnet")
    >>> print(f"Installing {request.model_name}")
    Installing birdnet
    """

    model_config = ConfigDict(protected_namespaces=())

    model_name: str = Field(
        ...,
        description="Model name to install",
        pattern="^(birdnet)$",
    )
    force_reinstall: bool = Field(
        False,
        description="Force reinstallation if already installed",
    )


class InstallResponse(BaseSchema):
    """Response from model installation request.

    Attributes
    ----------
    success : bool
        Whether installation succeeded.
    message : str
        Human-readable status message.
    status : ModelStatus
        Updated model status after installation attempt.

    Examples
    --------
    >>> response = InstallResponse(
    ...     success=True,
    ...     message="BirdNET installed successfully",
    ...     status=ModelStatus(name="birdnet", status=InstallStatus.INSTALLED),
    ... )
    >>> if response.success:
    ...     print(response.message)
    BirdNET installed successfully
    """

    success: bool = Field(..., description="Installation success flag")
    message: str = Field(..., description="Status message")
    status: ModelStatus = Field(..., description="Updated model status")
