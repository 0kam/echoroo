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
- Registration should happen at module load time, not runtime
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Type

if TYPE_CHECKING:
    from echoroo.ml.base import InferenceEngine, ModelLoader, ModelSpecification
    from echoroo.ml.filters import PredictionFilter

__all__ = [
    "ModelRegistry",
    "ModelInfo",
    "ModelNotFoundError",
]

logger = logging.getLogger(__name__)


class ModelNotFoundError(Exception):
    """Raised when a requested model is not found in the registry."""

    pass


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
    filter_class : Type[PredictionFilter] | None
        Optional class for filtering predictions.
    description : str
        Human-readable description of the model.
    """

    name: str
    loader_class: Type[ModelLoader]
    engine_class: Type[InferenceEngine]
    filter_class: Type[PredictionFilter] | None = None
    description: str = ""


class ModelRegistry:
    """Registry for ML model loaders and inference engines.

    This class provides a centralized registry for ML models, enabling
    dynamic model discovery and instantiation. Models register themselves
    at import time, and other components can retrieve them by name.

    The registry is implemented as a class with class methods for
    simplicity and to avoid the need for a singleton instance.

    Examples
    --------
    Registering a new model:

    >>> from echoroo.ml.registry import ModelRegistry
    >>> from my_model import MyLoader, MyEngine, MyFilter
    >>>
    >>> ModelRegistry.register(
    ...     name="my_model",
    ...     loader_class=MyLoader,
    ...     engine_class=MyEngine,
    ...     filter_class=MyFilter,  # optional
    ...     description="My custom model for bird identification",
    ... )

    Using the registry:

    >>> # Get loader class and instantiate
    >>> loader_cls = ModelRegistry.get_loader_class("birdnet")
    >>> loader = loader_cls()
    >>> loader.load()
    >>>
    >>> # Get engine class
    >>> engine_cls = ModelRegistry.get_engine_class("birdnet")
    >>> engine = engine_cls(loader.get_model())
    >>>
    >>> # Get full model info
    >>> info = ModelRegistry.get_model_info("birdnet")
    >>> print(info.description)

    Notes
    -----
    - Registration is idempotent - registering the same model twice
      will update the existing registration
    - Thread-safe for reads, but registration should happen at
      module load time
    """

    _models: dict[str, ModelInfo] = {}

    @classmethod
    def register(
        cls,
        name: str,
        loader_class: Type[ModelLoader],
        engine_class: Type[InferenceEngine],
        filter_class: Type[PredictionFilter] | None = None,
        description: str = "",
    ) -> None:
        """Register a model with the registry.

        Parameters
        ----------
        name : str
            Unique identifier for the model. Should be lowercase and
            contain only alphanumeric characters and underscores.
        loader_class : Type[ModelLoader]
            Class for loading the model. Must implement the ModelLoader
            protocol.
        engine_class : Type[InferenceEngine]
            Class for running inference. Must implement the InferenceEngine
            protocol.
        filter_class : Type[PredictionFilter] | None, optional
            Optional class for filtering predictions. If provided, must
            implement the PredictionFilter protocol.
        description : str, optional
            Human-readable description of the model.

        Examples
        --------
        >>> ModelRegistry.register(
        ...     name="birdnet",
        ...     loader_class=BirdNETLoader,
        ...     engine_class=BirdNETInference,
        ...     filter_class=BirdNETMetadataFilter,
        ...     description="BirdNET V2.4 bird species identification",
        ... )

        Notes
        -----
        - Registration is idempotent
        - Name should be lowercase for consistency
        - Registration should happen at module import time
        """
        if name in cls._models:
            logger.debug("Updating registration for model '%s'", name)
        else:
            logger.debug("Registering model '%s'", name)

        cls._models[name] = ModelInfo(
            name=name,
            loader_class=loader_class,
            engine_class=engine_class,
            filter_class=filter_class,
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
            True if the model was removed, False if it wasn't registered.
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
        info = cls._get_model_info_or_raise(name)
        return info.loader_class

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
        info = cls._get_model_info_or_raise(name)
        return info.engine_class

    @classmethod
    def get_filter_class(cls, name: str) -> Type[PredictionFilter] | None:
        """Get the prediction filter class for a model.

        Parameters
        ----------
        name : str
            Name of the model.

        Returns
        -------
        Type[PredictionFilter] | None
            The filter class if one is registered, None otherwise.

        Raises
        ------
        ModelNotFoundError
            If the model is not registered.
        """
        info = cls._get_model_info_or_raise(name)
        return info.filter_class

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
    def clear(cls) -> None:
        """Clear all registered models.

        This is primarily useful for testing.
        """
        cls._models.clear()
        logger.debug("Cleared all model registrations")

    @classmethod
    def list_models(cls) -> list[ModelInfo]:
        """Get information about all registered models.

        Returns
        -------
        list[ModelInfo]
            List of ModelInfo objects for all registered models.
        """
        return list(cls._models.values())
