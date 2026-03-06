"""Model registry for dynamic model discovery and loading.

This module provides a registry pattern for ML models, allowing new models
to be added without modifying the inference worker or other core components.

Each model registers its loader and inference engine classes, which can then
be retrieved by name. This enables extensibility and clean separation between
model implementations and the orchestration layer.

Example
-------
>>> from echoroo.ml.registry import ModelRegistry
>>> from echoroo.ml.birdnet import BirdNETLoader, BirdNETInference
>>>
>>> # Register a model (typically done in model's __init__.py)
>>> ModelRegistry.register("birdnet", BirdNETLoader, BirdNETInference)
>>>
>>> # Get model components by name
>>> loader_cls = ModelRegistry.get_loader_class("birdnet")
>>> engine_cls = ModelRegistry.get_engine_class("birdnet")
>>>
>>> # Check available models
>>> available = ModelRegistry.available_models()

Notes
-----
- Models should register themselves when their module is imported
- The registry is global and thread-safe for reads
- Registration should happen at module load time, not at runtime
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Type

if TYPE_CHECKING:
    from echoroo.ml.base import InferenceEngine, ModelLoader

__all__ = [
    "ModelRegistry",
    "ModelInfo",
    "ModelNotFoundError",
]

logger = logging.getLogger(__name__)


class ModelNotFoundError(Exception):
    """Raised when a requested model is not found in the registry."""


@dataclass
class ModelInfo:
    """Information about a registered model.

    Attributes
    ----------
    name : str
        Unique identifier for the model.
    loader_class : Type[ModelLoader]
        Class for loading the model.
    engine_class : Type[InferenceEngine]
        Class for running inference.
    description : str
        Human-readable description of the model.
    """

    name: str
    loader_class: Type[ModelLoader]
    engine_class: Type[InferenceEngine]
    description: str = ""


class ModelRegistry:
    """Registry for ML model loaders and inference engines.

    This class provides a centralized registry for ML models, enabling
    dynamic model discovery and instantiation. Models register themselves
    at import time, and other components can retrieve them by name.

    The registry is implemented as a class with class methods to avoid
    the need for a singleton instance.

    Examples
    --------
    Registering a new model:

    >>> ModelRegistry.register(
    ...     name="birdnet",
    ...     loader_class=BirdNETLoader,
    ...     engine_class=BirdNETInference,
    ...     description="BirdNET V2.4 bird species identification",
    ... )

    Using the registry:

    >>> loader_cls = ModelRegistry.get_loader_class("birdnet")
    >>> loader = loader_cls()
    >>> loader.load()
    >>> engine_cls = ModelRegistry.get_engine_class("birdnet")
    >>> engine = engine_cls(loader)

    Notes
    -----
    - Registration is idempotent - registering the same model twice
      will update the existing registration
    - Thread-safe for reads, but registration should happen at module load time
    """

    _models: dict[str, ModelInfo] = {}

    @classmethod
    def register(
        cls,
        name: str,
        loader_class: Type[ModelLoader],
        engine_class: Type[InferenceEngine],
        description: str = "",
    ) -> None:
        """Register a model with the registry.

        Parameters
        ----------
        name : str
            Unique identifier for the model. Should be lowercase.
        loader_class : Type[ModelLoader]
            Class for loading the model.
        engine_class : Type[InferenceEngine]
            Class for running inference.
        description : str, optional
            Human-readable description of the model.

        Notes
        -----
        Registration is idempotent. Registering the same name twice
        updates the existing entry.
        """
        if name in cls._models:
            logger.debug("Updating registration for model '%s'", name)
        else:
            logger.debug("Registering model '%s'", name)

        cls._models[name] = ModelInfo(
            name=name,
            loader_class=loader_class,
            engine_class=engine_class,
            description=description,
        )

    @classmethod
    def unregister(cls, name: str) -> bool:
        """Remove a model from the registry.

        Parameters
        ----------
        name : str
            Name of the model to remove.

        Returns
        -------
        bool
            True if the model was removed, False if it was not registered.
        """
        if name in cls._models:
            del cls._models[name]
            logger.debug("Unregistered model '%s'", name)
            return True
        return False

    @classmethod
    def get_loader_class(cls, name: str) -> Type[ModelLoader]:
        """Get the loader class for a model.

        Parameters
        ----------
        name : str
            Name of the model.

        Returns
        -------
        Type[ModelLoader]
            The loader class for the model.

        Raises
        ------
        ModelNotFoundError
            If the model is not registered.
        """
        return cls._get_model_info_or_raise(name).loader_class

    @classmethod
    def get_engine_class(cls, name: str) -> Type[InferenceEngine]:
        """Get the inference engine class for a model.

        Parameters
        ----------
        name : str
            Name of the model.

        Returns
        -------
        Type[InferenceEngine]
            The inference engine class for the model.

        Raises
        ------
        ModelNotFoundError
            If the model is not registered.
        """
        return cls._get_model_info_or_raise(name).engine_class

    @classmethod
    def get_model_info(cls, name: str) -> ModelInfo | None:
        """Get full information about a registered model.

        Parameters
        ----------
        name : str
            Name of the model.

        Returns
        -------
        ModelInfo | None
            Model information if found, None otherwise.
        """
        return cls._models.get(name)

    @classmethod
    def _get_model_info_or_raise(cls, name: str) -> ModelInfo:
        """Get model info or raise ModelNotFoundError.

        Parameters
        ----------
        name : str
            Name of the model.

        Returns
        -------
        ModelInfo
            The model information.

        Raises
        ------
        ModelNotFoundError
            If the model is not registered.
        """
        info = cls._models.get(name)
        if info is None:
            available = cls.available_models()
            raise ModelNotFoundError(
                f"Model '{name}' not found. Available models: {available}"
            )
        return info

    @classmethod
    def available_models(cls) -> list[str]:
        """Get list of registered model names.

        Returns
        -------
        list[str]
            List of model names in registration order.
        """
        return list(cls._models.keys())

    @classmethod
    def is_registered(cls, name: str) -> bool:
        """Check if a model is registered.

        Parameters
        ----------
        name : str
            Name of the model.

        Returns
        -------
        bool
            True if the model is registered.
        """
        return name in cls._models

    @classmethod
    def list_models(cls) -> list[ModelInfo]:
        """Get information about all registered models.

        Returns
        -------
        list[ModelInfo]
            List of ModelInfo objects for all registered models.
        """
        return list(cls._models.values())

    @classmethod
    def clear(cls) -> None:
        """Clear all registered models.

        Primarily useful for testing.
        """
        cls._models.clear()
        logger.debug("Cleared all model registrations")
