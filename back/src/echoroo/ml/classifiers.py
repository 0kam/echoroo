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
- Self-Training (LR): Semi-supervised learning with Logistic Regression base
- Self-Training (SVM): Semi-supervised learning with SVM base
- Label Spreading: Semi-supervised graph-based learning with KNN kernel
"""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import Normalizer
from sklearn.semi_supervised import SelfTrainingClassifier
from sklearn.svm import SVC

logger = logging.getLogger(__name__)

__all__ = [
    "ClassifierType",
    "UnifiedClassifier",
]


class ClassifierType(str, Enum):
    """Classifier type for active learning and model training.

    Only Self-Training+SVM is supported, with automatic C parameter tuning
    via grid search and MiniBatchKMeans clustering for unlabeled data.
    """

    SELF_TRAINING_SVM = "self_training_svm"
    """Self-Training with linear SVM - semi-supervised learning with automatic C tuning."""


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
        ClassifierType.SELF_TRAINING_SVM: {
            "class": SelfTrainingClassifier,
            "params": {
                "base_estimator": SVC(
                    kernel="linear",
                    C=1.0,
                    probability=True,
                    random_state=42,
                    class_weight="balanced",
                ),
                "threshold": 0.9,
                "criterion": "threshold",
                "max_iter": 3,
            },
        },
    }

    def __init__(
        self,
        classifier_type: ClassifierType | str = ClassifierType.SELF_TRAINING_SVM,
        custom_params: dict[str, Any] | None = None,
    ):
        """Initialize the unified classifier with optional parameter overrides.

        Parameters
        ----------
        classifier_type
            The type of classifier to use. Can be a ClassifierType enum
            or a string matching one of the enum values.
        custom_params
            Optional parameters to override defaults (e.g., {"C": 10.0} for SVM).
            Currently supports C parameter for SELF_TRAINING_SVM.
        """
        if isinstance(classifier_type, str):
            classifier_type = ClassifierType(classifier_type)

        self.classifier_type = classifier_type

        # Get base config
        config = self.CLASSIFIER_CONFIGS[classifier_type].copy()

        # Apply custom parameters for Self-Training+SVM
        if custom_params and classifier_type == ClassifierType.SELF_TRAINING_SVM:
            if "C" in custom_params:
                # Create new base_estimator with custom C
                from sklearn.svm import SVC

                config = config.copy()
                config["params"] = config["params"].copy()
                config["params"]["base_estimator"] = SVC(
                    kernel="linear",
                    C=custom_params["C"],
                    probability=True,
                    random_state=42,
                    class_weight="balanced",
                )

        self.model = Pipeline([
            ("normalizer", Normalizer(norm="l2")),
            ("classifier", config["class"](**config["params"])),
        ])
        self.is_fitted = False
        self._single_class: int | None = None

    def _is_semi_supervised(self) -> bool:
        """Check if the classifier supports semi-supervised learning.

        Returns
        -------
        bool
            Always True since only Self-Training+SVM is supported.
        """
        return True

    def fit(
        self,
        embeddings: np.ndarray,
        labels: np.ndarray,
        unlabeled_embeddings: np.ndarray | None = None,
    ) -> "UnifiedClassifier":
        """Fit the classifier on labeled embeddings.

        For semi-supervised classifiers (SelfTrainingClassifier, LabelSpreading),
        unlabeled data can be provided to improve the model. For regular supervised
        classifiers, the unlabeled_embeddings parameter is ignored.

        Parameters
        ----------
        embeddings
            Array of shape (n_samples, embedding_dim) containing
            embedding vectors for training.
        labels
            Array of shape (n_samples,) containing binary labels
            (0 for negative, 1 for positive).
        unlabeled_embeddings
            Optional array of shape (n_unlabeled, embedding_dim) containing
            unlabeled embedding vectors. Only used by semi-supervised classifiers.
            For sklearn semi-supervised classifiers, these will be combined with
            labeled data and marked with label -1.

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

        # Check if we have both classes in labeled data
        unique_labels = np.unique(labels)
        if len(unique_labels) < 2:
            # If only one class, we can't train a meaningful classifier
            # Store the single class for prediction
            self._single_class = int(unique_labels[0])
            self.is_fitted = True
            return self

        self._single_class = None

        # Prepare data for semi-supervised learning if applicable
        if self._is_semi_supervised() and unlabeled_embeddings is not None:
            # Combine labeled and unlabeled data
            n_labeled = len(embeddings)
            n_unlabeled = len(unlabeled_embeddings)

            combined_embeddings = np.vstack([embeddings, unlabeled_embeddings])
            # Use -1 as the label for unlabeled samples (sklearn convention)
            combined_labels = np.concatenate([labels, np.full(n_unlabeled, -1)])

            logger.info(
                f"Semi-supervised training for {self.classifier_type.value}: "
                f"n_labeled={n_labeled}, n_unlabeled={n_unlabeled}, "
                f"embedding_dim={embeddings.shape[1]}"
            )

            train_embeddings = combined_embeddings
            train_labels = combined_labels
        else:
            if (
                unlabeled_embeddings is not None
                and not self._is_semi_supervised()
            ):
                logger.debug(
                    f"Ignoring unlabeled_embeddings for supervised classifier "
                    f"{self.classifier_type.value}"
                )
            train_embeddings = embeddings
            train_labels = labels

        # Log embeddings before normalization
        mean_norm = np.mean([np.linalg.norm(e) for e in train_embeddings])
        logger.debug(
            f"Fitting {self.classifier_type.value}: "
            f"n_samples={len(train_embeddings)}, "
            f"embedding_dim={train_embeddings.shape[1]}, "
            f"mean_norm_before_pipeline={mean_norm:.4f}"
        )

        self.model.fit(train_embeddings, train_labels)
        self.is_fitted = True

        # Log semi-supervised training results
        if self._is_semi_supervised() and unlabeled_embeddings is not None:
            clf = self.model["classifier"]
            if hasattr(clf, "transduction_"):
                # For SelfTrainingClassifier
                n_labeled_by_self = np.sum(clf.transduction_ != -1) - len(labels)
                logger.info(
                    f"Self-training labeled {n_labeled_by_self} out of "
                    f"{len(unlabeled_embeddings)} unlabeled samples"
                )

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

        # Log input embeddings
        mean_norm = np.mean([np.linalg.norm(e) for e in embeddings])
        logger.debug(
            f"Predicting with {self.classifier_type.value}: "
            f"n_samples={len(embeddings)}, "
            f"mean_norm_before_pipeline={mean_norm:.4f}"
        )

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
                "value": ClassifierType.SELF_TRAINING_SVM.value,
                "label": "Self-Training (SVM)",
                "description": "Semi-supervised learning with automatic C tuning and MiniBatchKMeans clustering",
            },
        ]
