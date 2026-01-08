"""Unified Classifier module for Active Learning and Model Training.

This module provides a unified interface for multiple classifier types
that can be used both during active learning iterations and for final
model training/deployment.

Supported classifier types:
- Logistic Regression: Fast, linear classifier (default for active learning)
- SVM Linear: Linear SVM with probability estimates
- MLP Small: Single hidden layer neural network (256 units)
- MLP Medium: Two hidden layer neural network (256, 128 units)
- Random Forest: Ensemble method, robust to noisy labels
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import Normalizer
from sklearn.svm import SVC

__all__ = [
    "ClassifierType",
    "UnifiedClassifier",
]


class ClassifierType(str, Enum):
    """Supported classifier types for active learning and model training."""

    LOGISTIC_REGRESSION = "logistic_regression"
    """Logistic Regression - fast, linear, good for cosine similarity space."""

    SVM_LINEAR = "svm_linear"
    """Linear SVM - linear classifier with margin-based optimization."""

    MLP_SMALL = "mlp_small"
    """Small MLP - single hidden layer (256 units), captures nonlinear patterns."""

    MLP_MEDIUM = "mlp_medium"
    """Medium MLP - two hidden layers (256, 128 units), more capacity."""

    RANDOM_FOREST = "random_forest"
    """Random Forest - ensemble method, robust to noisy labels."""


class UnifiedClassifier:
    """Unified classifier supporting multiple model types.

    This classifier wraps sklearn classifiers with L2 normalization
    for embedding-based classification. All models use cosine-compatible
    geometry by normalizing embeddings before classification.

    Attributes
    ----------
    classifier_type
        The type of classifier being used.
    model
        The sklearn Pipeline containing normalizer and classifier.
    is_fitted
        Whether the model has been trained.
    """

    CLASSIFIER_CONFIGS: dict[ClassifierType, dict[str, Any]] = {
        ClassifierType.LOGISTIC_REGRESSION: {
            "class": LogisticRegression,
            "params": {
                "C": 1.0,
                "max_iter": 1000,
                "solver": "lbfgs",
                "random_state": 42,
                "class_weight": "balanced",
            },
        },
        ClassifierType.SVM_LINEAR: {
            "class": SVC,
            "params": {
                "kernel": "linear",
                "C": 1.0,
                "probability": True,
                "random_state": 42,
                "class_weight": "balanced",
            },
        },
        ClassifierType.MLP_SMALL: {
            "class": MLPClassifier,
            "params": {
                "hidden_layer_sizes": (256,),
                "max_iter": 500,
                "early_stopping": True,
                "validation_fraction": 0.1,
                "n_iter_no_change": 10,
                "random_state": 42,
            },
        },
        ClassifierType.MLP_MEDIUM: {
            "class": MLPClassifier,
            "params": {
                "hidden_layer_sizes": (256, 128),
                "max_iter": 500,
                "early_stopping": True,
                "validation_fraction": 0.1,
                "n_iter_no_change": 10,
                "random_state": 42,
            },
        },
        ClassifierType.RANDOM_FOREST: {
            "class": RandomForestClassifier,
            "params": {
                "n_estimators": 100,
                "class_weight": "balanced",
                "n_jobs": -1,
                "random_state": 42,
            },
        },
    }

    def __init__(
        self,
        classifier_type: ClassifierType | str = ClassifierType.LOGISTIC_REGRESSION,
    ):
        """Initialize the unified classifier.

        Parameters
        ----------
        classifier_type
            The type of classifier to use. Can be a ClassifierType enum
            or a string matching one of the enum values.
        """
        if isinstance(classifier_type, str):
            classifier_type = ClassifierType(classifier_type)

        self.classifier_type = classifier_type
        config = self.CLASSIFIER_CONFIGS[classifier_type]

        self.model = Pipeline([
            ("normalizer", Normalizer(norm="l2")),
            ("classifier", config["class"](**config["params"])),
        ])
        self.is_fitted = False
        self._single_class: int | None = None

    def fit(
        self,
        embeddings: np.ndarray,
        labels: np.ndarray,
    ) -> "UnifiedClassifier":
        """Fit the classifier on labeled embeddings.

        Parameters
        ----------
        embeddings
            Array of shape (n_samples, embedding_dim) containing
            embedding vectors for training.
        labels
            Array of shape (n_samples,) containing binary labels
            (0 for negative, 1 for positive).

        Returns
        -------
        UnifiedClassifier
            Self, for method chaining.

        Raises
        ------
        ValueError
            If embeddings and labels have mismatched lengths.
        """
        if len(embeddings) != len(labels):
            raise ValueError(
                f"Embeddings and labels must have same length, "
                f"got {len(embeddings)} and {len(labels)}"
            )

        # Check if we have both classes
        unique_labels = np.unique(labels)
        if len(unique_labels) < 2:
            # If only one class, we can't train a meaningful classifier
            # Store the single class for prediction
            self._single_class = int(unique_labels[0])
            self.is_fitted = True
            return self

        self._single_class = None
        self.model.fit(embeddings, labels)
        self.is_fitted = True
        return self

    def predict_proba(self, embeddings: np.ndarray) -> np.ndarray:
        """Predict probability of positive class for each embedding.

        Parameters
        ----------
        embeddings
            Array of shape (n_samples, embedding_dim) containing
            embedding vectors to classify.

        Returns
        -------
        np.ndarray
            Array of shape (n_samples,) containing probability of
            positive class for each sample.

        Raises
        ------
        RuntimeError
            If the classifier has not been fitted.
        """
        if not self.is_fitted:
            raise RuntimeError("Classifier has not been fitted. Call fit() first.")

        if self._single_class is not None:
            # Return constant probability based on the single class seen
            return np.full(len(embeddings), float(self._single_class))

        # Return probability of positive class (class 1)
        proba = self.model.predict_proba(embeddings)
        # Handle case where classes might be [0, 1] or just [1]
        classifier = self.model["classifier"]
        if hasattr(classifier, "classes_") and len(classifier.classes_) > 1:
            if classifier.classes_[1] == 1:
                return proba[:, 1]
            else:
                return proba[:, 0]
        return proba[:, -1]

    def predict(self, embeddings: np.ndarray) -> np.ndarray:
        """Predict class labels for each embedding.

        Parameters
        ----------
        embeddings
            Array of shape (n_samples, embedding_dim) containing
            embedding vectors to classify.

        Returns
        -------
        np.ndarray
            Array of shape (n_samples,) containing predicted class
            labels (0 or 1).

        Raises
        ------
        RuntimeError
            If the classifier has not been fitted.
        """
        if not self.is_fitted:
            raise RuntimeError("Classifier has not been fitted. Call fit() first.")

        if self._single_class is not None:
            return np.full(len(embeddings), self._single_class)

        return self.model.predict(embeddings)

    def save(self, path: str | Path) -> None:
        """Save the trained classifier to a file.

        Parameters
        ----------
        path
            Path to save the classifier. Will use joblib format.

        Raises
        ------
        RuntimeError
            If the classifier has not been fitted.
        """
        if not self.is_fitted:
            raise RuntimeError("Classifier has not been fitted. Call fit() first.")

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        save_data = {
            "classifier_type": self.classifier_type.value,
            "model": self.model,
            "single_class": self._single_class,
        }
        joblib.dump(save_data, path)

    @classmethod
    def load(cls, path: str | Path) -> "UnifiedClassifier":
        """Load a trained classifier from a file.

        Parameters
        ----------
        path
            Path to the saved classifier file.

        Returns
        -------
        UnifiedClassifier
            Loaded classifier instance.
        """
        path = Path(path)
        save_data = joblib.load(path)

        instance = cls.__new__(cls)
        instance.classifier_type = ClassifierType(save_data["classifier_type"])
        instance.model = save_data["model"]
        instance._single_class = save_data["single_class"]
        instance.is_fitted = True
        return instance

    @classmethod
    def get_available_types(cls) -> list[dict[str, str]]:
        """Get list of available classifier types with descriptions.

        Returns
        -------
        list[dict[str, str]]
            List of dicts with 'value', 'label', and 'description' keys.
        """
        return [
            {
                "value": ClassifierType.LOGISTIC_REGRESSION.value,
                "label": "Logistic Regression",
                "description": "Fast linear classifier (recommended for most cases)",
            },
            {
                "value": ClassifierType.SVM_LINEAR.value,
                "label": "Linear SVM",
                "description": "Linear classifier with margin-based optimization",
            },
            {
                "value": ClassifierType.MLP_SMALL.value,
                "label": "Small Neural Network",
                "description": "256-unit hidden layer, captures nonlinear patterns",
            },
            {
                "value": ClassifierType.MLP_MEDIUM.value,
                "label": "Medium Neural Network",
                "description": "256+128-unit hidden layers, more capacity",
            },
            {
                "value": ClassifierType.RANDOM_FOREST.value,
                "label": "Random Forest",
                "description": "Ensemble method, robust to noisy labels",
            },
        ]
