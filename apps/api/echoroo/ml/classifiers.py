"""Unified Classifier module for Active Learning and Model Training.

This module provides a unified interface for the Self-Training SVM classifier
that can be used both during active learning iterations and for final model
training/deployment.

Supported classifier types:
- Self-Training (SVM): Semi-supervised learning with linear SVM base estimator,
  with automatic C parameter tuning via stratified K-Fold cross-validation.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.cluster import MiniBatchKMeans
from sklearn.decomposition import PCA
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import Normalizer
from sklearn.semi_supervised import SelfTrainingClassifier
from sklearn.svm import SVC

logger = logging.getLogger(__name__)

__all__ = [
    "ClassifierType",
    "UnifiedClassifier",
    "train_with_cv",
    "reduce_unlabeled_samples",
]


class ClassifierType(StrEnum):
    """Classifier type for active learning and model training.

    Only Self-Training+SVM is supported, with automatic C parameter tuning
    via stratified K-Fold cross-validation.
    """

    SELF_TRAINING_SVM = "self_training_svm"
    """Self-Training with linear SVM - semi-supervised learning with automatic C tuning."""


class UnifiedClassifier:
    """Unified classifier supporting Self-Training SVM.

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
                "estimator": SVC(
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
        if custom_params and classifier_type == ClassifierType.SELF_TRAINING_SVM and "C" in custom_params:
            config = config.copy()
            config["params"] = config["params"].copy()
            config["params"]["estimator"] = SVC(
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
    ) -> UnifiedClassifier:
        """Fit the classifier on labeled embeddings.

        For semi-supervised classifiers (SelfTrainingClassifier), unlabeled
        data can be provided to improve the model.

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
            unlabeled embedding vectors. Combined with labeled data and
            marked with label -1 (sklearn convention).

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

        # Handle single-class edge case: no meaningful classifier can be trained
        unique_labels = np.unique(labels)
        if len(unique_labels) < 2:
            self._single_class = int(unique_labels[0])
            self.is_fitted = True
            logger.warning(
                "Only one class present in labels (%d). "
                "Classifier will return constant predictions.",
                self._single_class,
            )
            return self

        self._single_class = None

        # Prepare data for semi-supervised learning if applicable
        if self._is_semi_supervised() and unlabeled_embeddings is not None:
            n_labeled = len(embeddings)
            n_unlabeled = len(unlabeled_embeddings)

            combined_embeddings = np.vstack([embeddings, unlabeled_embeddings])
            combined_labels = np.concatenate([labels, np.full(n_unlabeled, -1)])

            logger.info(
                "Semi-supervised training for %s: n_labeled=%d, n_unlabeled=%d, "
                "embedding_dim=%d",
                self.classifier_type.value,
                n_labeled,
                n_unlabeled,
                embeddings.shape[1],
            )

            train_embeddings = combined_embeddings
            train_labels = combined_labels
        else:
            train_embeddings = embeddings
            train_labels = labels

        mean_norm = float(np.mean(np.linalg.norm(train_embeddings, axis=1)))
        logger.debug(
            "Fitting %s: n_samples=%d, embedding_dim=%d, mean_norm_before_pipeline=%.4f",
            self.classifier_type.value,
            len(train_embeddings),
            train_embeddings.shape[1],
            mean_norm,
        )

        self.model.fit(train_embeddings, train_labels)
        self.is_fitted = True

        # Log how many unlabeled samples were assigned pseudo-labels
        if self._is_semi_supervised() and unlabeled_embeddings is not None:
            clf = self.model["classifier"]
            if hasattr(clf, "transduction_"):
                n_labeled_by_self = int(np.sum(clf.transduction_ != -1)) - len(labels)
                logger.info(
                    "Self-training labeled %d out of %d unlabeled samples",
                    n_labeled_by_self,
                    len(unlabeled_embeddings),
                )

        return self

    def decision_function(self, embeddings: np.ndarray) -> np.ndarray:
        """Get signed distance from SVM decision boundary.

        Positive values indicate a predicted positive class, negative values
        indicate a predicted negative class. Magnitude indicates confidence.

        For SelfTrainingClassifier, accesses the underlying fitted estimator
        to call its decision_function directly. For single-class models, returns
        a constant large positive or negative value.

        Parameters
        ----------
        embeddings
            Array of shape (n_samples, embedding_dim) containing
            embedding vectors to score.

        Returns
        -------
        np.ndarray
            Array of shape (n_samples,) containing signed distances
            from the SVM decision boundary.

        Raises
        ------
        RuntimeError
            If the classifier has not been fitted.
        """
        if not self.is_fitted:
            raise RuntimeError("Classifier has not been fitted. Call fit() first.")

        if self._single_class is not None:
            val = 10.0 if self._single_class == 1 else -10.0
            result: np.ndarray = np.full(len(embeddings), val)
            return result

        # Normalize embeddings through the pipeline's normalizer step
        normalizer = self.model["normalizer"]
        normalized: np.ndarray = normalizer.transform(embeddings)

        # SelfTrainingClassifier wraps the base estimator
        classifier = self.model["classifier"]
        if hasattr(classifier, "estimator_"):
            # Fitted SelfTrainingClassifier exposes the trained base estimator
            distances: np.ndarray = classifier.estimator_.decision_function(normalized)
            return distances
        elif hasattr(classifier, "decision_function"):
            distances = classifier.decision_function(normalized)
            return distances
        else:
            # Fallback: convert predict_proba output to a centered distance proxy
            proba = self.predict_proba(embeddings)
            return proba - 0.5

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
            positive class (class 1) for each sample.

        Raises
        ------
        RuntimeError
            If the classifier has not been fitted.
        """
        if not self.is_fitted:
            raise RuntimeError("Classifier has not been fitted. Call fit() first.")

        if self._single_class is not None:
            return np.full(len(embeddings), float(self._single_class))

        mean_norm = float(np.mean(np.linalg.norm(embeddings, axis=1)))
        logger.debug(
            "Predicting with %s: n_samples=%d, mean_norm_before_pipeline=%.4f",
            self.classifier_type.value,
            len(embeddings),
            mean_norm,
        )

        proba: np.ndarray = self.model.predict_proba(embeddings)
        # Locate positive class (1) column
        classifier = self.model["classifier"]
        if hasattr(classifier, "classes_") and len(classifier.classes_) > 1:
            if classifier.classes_[1] == 1:
                result: np.ndarray = proba[:, 1]
                return result
            else:
                result = proba[:, 0]
                return result
        last: np.ndarray = proba[:, -1]
        return last

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

        preds: np.ndarray = self.model.predict(embeddings)
        return preds

    def save(self, path: str | Path) -> None:
        """Save the trained classifier to a file using joblib.

        Parameters
        ----------
        path
            File path to save the classifier.

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
        logger.info("Classifier saved to %s", path)

    @classmethod
    def load(cls, path: str | Path) -> UnifiedClassifier:
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

        logger.info("Classifier loaded from %s", path)
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
                "description": (
                    "Semi-supervised learning with linear SVM base estimator "
                    "and automatic C parameter tuning via cross-validation."
                ),
            },
        ]


def train_with_cv(
    embeddings: np.ndarray,
    labels: np.ndarray,
    unlabeled_embeddings: np.ndarray | None = None,
    c_values: list[float] | None = None,
    n_splits: int = 3,
    random_state: int = 42,
    recording_ids: np.ndarray | None = None,
    unlabeled_recording_ids: np.ndarray | None = None,
) -> tuple[UnifiedClassifier, dict[str, Any]]:
    """Train a UnifiedClassifier with cross-validation-based C parameter tuning.

    Follows a strict train/test isolation protocol:

    1. Split 20% of labeled data as a held-out test set (stratified, before CV).
    2. Run CV on the remaining 80% only to select the best C value.
    3. Train an evaluation model on the 80% train set (+ unlabeled embeddings
       whose recordings do NOT appear in the test set) and evaluate it on the
       held-out 20% — this is the source of reported metrics.
    4. Train a final deployment model on ALL labeled data (+ all unlabeled
       embeddings) using the best C.
    5. Return the final deployment model (step 4) and the metrics from step 3.

    Parameters
    ----------
    embeddings
        Array of shape (n_samples, embedding_dim) containing labeled embedding
        vectors. Expected embedding_dim is 1536 (Perch).
    labels
        Array of shape (n_samples,) with binary labels (0 or 1).
    unlabeled_embeddings
        Optional array of shape (n_unlabeled, embedding_dim) for semi-supervised
        training. Used in both the eval model (recordings not in test set) and
        the final deployment model (all unlabeled).
    c_values
        List of C values to search over. Defaults to [0.1, 1.0, 10.0].
    n_splits
        Number of folds for stratified K-Fold CV. Default is 3.
    random_state
        Random seed for reproducibility. Default is 42.
    recording_ids
        Optional array of shape (n_samples,) containing recording IDs for each
        labeled embedding. When provided and there are at least ``n_splits * 2``
        unique recordings, StratifiedGroupKFold is used to prevent data leakage
        across recordings within CV folds. Also used to identify which unlabeled
        embeddings belong to test recordings so they can be excluded from the
        eval model.
    unlabeled_recording_ids
        Optional array of shape (n_unlabeled,) containing recording IDs for each
        unlabeled embedding. When both ``recording_ids`` and
        ``unlabeled_recording_ids`` are provided, unlabeled embeddings whose
        recording appears in the test split are excluded from the eval model
        (but still used in the final deployment model).

    Returns
    -------
    tuple[UnifiedClassifier, dict]
        Trained classifier (deployment model, fit on ALL data) and metrics
        dictionary from the eval model (fit on 80% train set only), containing:
        - best_c: chosen C value
        - cv_scores: dict mapping C value to mean CV F1
        - cv_method: "stratified_group_kfold" | "stratified_kfold"
        - cv_warning: (optional) "insufficient_recordings" if group CV was
          requested but fell back to standard CV
        - accuracy, precision, recall, f1
        - roc_auc, pr_auc
        - confusion_matrix (as nested list)
        - n_train, n_test, skipped_cv (bool)

    Notes
    -----
    CV is skipped (uses default C=1.0) when fewer than 10 samples per class
    are available in the labeled set, or when n_splits > number of minority
    class samples.
    """
    if c_values is None:
        c_values = [0.1, 1.0, 10.0]

    unique, counts = np.unique(labels, return_counts=True)
    class_counts = dict(zip(unique.tolist(), counts.tolist(), strict=False))

    logger.info(
        "train_with_cv: n_labeled=%d, class_counts=%s, n_unlabeled=%s",
        len(embeddings),
        class_counts,
        len(unlabeled_embeddings) if unlabeled_embeddings is not None else 0,
    )

    # ------------------------------------------------------------------
    # Step 1: Split 20% test set UPFRONT — before any CV or model fitting.
    # This ensures the test set is never seen during hyperparameter selection.
    # ------------------------------------------------------------------
    test_size = 0.2
    try:
        train_idx, test_idx = train_test_split(
            np.arange(len(embeddings)),
            test_size=test_size,
            stratify=labels,
            random_state=random_state,
        )
    except ValueError:
        logger.warning(
            "Stratified split failed (too few samples per class). "
            "Falling back to random split."
        )
        train_idx, test_idx = train_test_split(
            np.arange(len(embeddings)),
            test_size=test_size,
            random_state=random_state,
        )

    X_train, X_test = embeddings[train_idx], embeddings[test_idx]
    y_train, y_test = labels[train_idx], labels[test_idx]
    rec_ids_train = recording_ids[train_idx] if recording_ids is not None else None

    # Identify recording IDs that appear in the test split (for unlabeled filtering)
    test_recording_ids: set[Any] = set()
    if recording_ids is not None:
        test_recording_ids = set(recording_ids[test_idx].tolist())
        logger.info(
            "train_with_cv: test split contains %d unique recordings",
            len(test_recording_ids),
        )

    n_test = len(X_test)
    n_train = len(X_train)

    logger.info(
        "train_with_cv: train=%d, test=%d (%.0f%% split)",
        n_train,
        n_test,
        test_size * 100,
    )

    # ------------------------------------------------------------------
    # Step 2: Determine whether CV is feasible on the 80% train set.
    # ------------------------------------------------------------------
    train_unique, train_counts = np.unique(y_train, return_counts=True)
    min_train_class_count = int(min(train_counts))
    skip_cv = min_train_class_count < 10 or min_train_class_count < n_splits

    best_c = 1.0
    cv_scores: dict[float, float] = {}
    cv_method = "stratified_kfold"
    cv_warning: str | None = None

    if skip_cv:
        logger.warning(
            "Insufficient data for CV (min train class count=%d, n_splits=%d). "
            "Skipping CV and using default C=1.0.",
            min_train_class_count,
            n_splits,
        )
    else:
        # Decide which CV strategy to use — operate only on the 80% train split
        use_group_cv = False
        if rec_ids_train is not None:
            unique_recordings = np.unique(rec_ids_train)
            if len(unique_recordings) >= n_splits * 2:
                use_group_cv = True
                cv_method = "stratified_group_kfold"
                logger.info(
                    "train_with_cv: using StratifiedGroupKFold "
                    "(unique_recordings=%d, n_splits=%d)",
                    len(unique_recordings),
                    n_splits,
                )
            else:
                cv_warning = "insufficient_recordings"
                logger.warning(
                    "train_with_cv: recording_ids provided but only %d unique recordings "
                    "(need >= %d for grouped CV). Falling back to StratifiedKFold.",
                    len(unique_recordings),
                    n_splits * 2,
                )

        if use_group_cv:
            sgkf = StratifiedGroupKFold(
                n_splits=n_splits, shuffle=True, random_state=random_state
            )

            for c in c_values:
                fold_f1_scores: list[float] = []

                for fold_idx, (train_fold, val_fold) in enumerate(
                    sgkf.split(X_train, y_train, groups=rec_ids_train)
                ):
                    X_tr, X_val = X_train[train_fold], X_train[val_fold]
                    y_tr, y_val = y_train[train_fold], y_train[val_fold]

                    clf = UnifiedClassifier(
                        classifier_type=ClassifierType.SELF_TRAINING_SVM,
                        custom_params={"C": c},
                    )
                    # CV uses only labeled data (no unlabeled) for fair comparison
                    clf.fit(X_tr, y_tr)

                    if clf._single_class is not None:
                        fold_f1_scores.append(0.0)
                        logger.debug(
                            "C=%.3f fold=%d (group): single class, assigning F1=0",
                            c,
                            fold_idx,
                        )
                    else:
                        y_pred = clf.predict(X_val)
                        fold_f1 = float(
                            f1_score(y_val, y_pred, average="weighted", zero_division=0)
                        )
                        fold_f1_scores.append(fold_f1)
                        logger.debug(
                            "C=%.3f fold=%d (group): F1=%.4f", c, fold_idx, fold_f1
                        )

                mean_f1 = float(np.mean(fold_f1_scores))
                cv_scores[c] = mean_f1
                logger.info("C=%.3f (group CV): mean CV F1=%.4f", c, mean_f1)

        else:
            # Standard Stratified K-Fold CV to select best C
            skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=random_state)

            for c in c_values:
                fold_f1_scores_std: list[float] = []

                for fold_idx, (train_idx_fold, val_idx_fold) in enumerate(
                    skf.split(X_train, y_train)
                ):
                    X_tr, X_val = X_train[train_idx_fold], X_train[val_idx_fold]
                    y_tr, y_val = y_train[train_idx_fold], y_train[val_idx_fold]

                    clf = UnifiedClassifier(
                        classifier_type=ClassifierType.SELF_TRAINING_SVM,
                        custom_params={"C": c},
                    )
                    # CV uses only labeled data (no unlabeled) for fair comparison
                    clf.fit(X_tr, y_tr)

                    if clf._single_class is not None:
                        # Degenerate fold — assign 0 F1
                        fold_f1_scores_std.append(0.0)
                        logger.debug(
                            "C=%.3f fold=%d: single class, assigning F1=0", c, fold_idx
                        )
                    else:
                        y_pred = clf.predict(X_val)
                        fold_f1 = float(
                            f1_score(y_val, y_pred, average="weighted", zero_division=0)
                        )
                        fold_f1_scores_std.append(fold_f1)
                        logger.debug("C=%.3f fold=%d: F1=%.4f", c, fold_idx, fold_f1)

                mean_f1 = float(np.mean(fold_f1_scores_std))
                cv_scores[c] = mean_f1
                logger.info("C=%.3f: mean CV F1=%.4f", c, mean_f1)

        best_c = max(cv_scores, key=lambda k: cv_scores[k])
        logger.info("Best C=%.3f (mean CV F1=%.4f)", best_c, cv_scores[best_c])

    # ------------------------------------------------------------------
    # Step 3: Train eval model on 80% train set + filtered unlabeled data.
    # Unlabeled embeddings whose recordings appear in the test set are excluded
    # to prevent any indirect leakage into the evaluation metrics.
    # ------------------------------------------------------------------
    eval_unlabeled: np.ndarray | None = None
    if unlabeled_embeddings is not None and len(unlabeled_embeddings) > 0:
        if unlabeled_recording_ids is not None and len(test_recording_ids) > 0:
            # Exclude unlabeled samples from test recordings
            keep_mask = np.array([
                rid not in test_recording_ids
                for rid in unlabeled_recording_ids.tolist()
            ])
            eval_unlabeled = unlabeled_embeddings[keep_mask]
            n_excluded = int(np.sum(~keep_mask))
            logger.info(
                "train_with_cv: excluded %d unlabeled embeddings from test recordings "
                "for eval model (%d remaining)",
                n_excluded,
                len(eval_unlabeled),
            )
            if len(eval_unlabeled) == 0:
                eval_unlabeled = None
        else:
            # No recording-level filtering possible; use all unlabeled for eval model
            eval_unlabeled = unlabeled_embeddings

    eval_clf = UnifiedClassifier(
        classifier_type=ClassifierType.SELF_TRAINING_SVM,
        custom_params={"C": best_c},
    )
    eval_clf.fit(X_train, y_train, unlabeled_embeddings=eval_unlabeled)
    logger.info(
        "Eval classifier fitted on %d labeled train samples "
        "(+ %d unlabeled, test-recording-filtered).",
        n_train,
        len(eval_unlabeled) if eval_unlabeled is not None else 0,
    )

    # ------------------------------------------------------------------
    # Step 4: Train FINAL deployment model on ALL labeled data + all unlabeled.
    # This model is serialized and deployed — it never uses the test split
    # for fitting, so there is no leakage; the test split was only used to
    # measure the eval model above.
    # ------------------------------------------------------------------
    final_clf = UnifiedClassifier(
        classifier_type=ClassifierType.SELF_TRAINING_SVM,
        custom_params={"C": best_c},
    )
    final_clf.fit(embeddings, labels, unlabeled_embeddings=unlabeled_embeddings)
    logger.info(
        "Final deployment classifier fitted on all %d labeled samples "
        "(+ %d unlabeled).",
        len(embeddings),
        len(unlabeled_embeddings) if unlabeled_embeddings is not None else 0,
    )

    # ------------------------------------------------------------------
    # Step 5: Evaluate the eval model on the held-out 20% test set.
    # Report these metrics (not the final model's performance).
    # ------------------------------------------------------------------
    metrics: dict[str, Any] = {
        "best_c": best_c,
        "cv_scores": cv_scores,
        "skipped_cv": skip_cv,
        "cv_method": cv_method,
        "n_train": n_train,
        "n_test": n_test,
    }
    if cv_warning is not None:
        metrics["cv_warning"] = cv_warning

    if eval_clf._single_class is not None:
        # Degenerate case — populate with fallback metrics
        logger.warning(
            "Eval classifier has single class (%d). Metrics are trivial.",
            eval_clf._single_class,
        )
        metrics.update({
            "accuracy": float(eval_clf._single_class),
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "roc_auc": 0.5,
            "pr_auc": 0.0,
            "confusion_matrix": [[0, 0], [0, 0]],
        })
    else:
        y_pred = eval_clf.predict(X_test)
        y_proba = eval_clf.predict_proba(X_test)

        acc = float(accuracy_score(y_test, y_pred))
        prec = float(precision_score(y_test, y_pred, zero_division=0))
        rec = float(recall_score(y_test, y_pred, zero_division=0))
        f1 = float(f1_score(y_test, y_pred, zero_division=0))

        # AUC metrics require both classes to be present in y_test
        try:
            roc_auc = float(roc_auc_score(y_test, y_proba))
        except ValueError:
            logger.warning("ROC-AUC could not be computed (only one class in y_test).")
            roc_auc = float("nan")

        try:
            pr_auc = float(average_precision_score(y_test, y_proba))
        except ValueError:
            logger.warning("PR-AUC could not be computed (only one class in y_test).")
            pr_auc = float("nan")

        cm = confusion_matrix(y_test, y_pred).tolist()

        metrics.update({
            "accuracy": acc,
            "precision": prec,
            "recall": rec,
            "f1": f1,
            "roc_auc": roc_auc,
            "pr_auc": pr_auc,
            "confusion_matrix": cm,
        })

        logger.info(
            "Test metrics (eval model on held-out 20%%): accuracy=%.4f, precision=%.4f, "
            "recall=%.4f, f1=%.4f, roc_auc=%.4f, pr_auc=%.4f",
            acc,
            prec,
            rec,
            f1,
            roc_auc,
            pr_auc,
        )

    # Return the final deployment model (trained on ALL data) + metrics from eval model
    return final_clf, metrics


def reduce_unlabeled_samples(
    embeddings: np.ndarray,
    max_samples: int = 2000,
    method: str = "random",
    n_clusters: int = 1000,
    samples_per_cluster: int = 2,
    pca_dims: int = 256,
    random_state: int = 42,
) -> np.ndarray:
    """Reduce a large pool of unlabeled embeddings for semi-supervised training.

    Parameters
    ----------
    embeddings
        Array of shape (n_samples, embedding_dim) to subsample.
    max_samples
        Maximum number of samples to return for the "random" method.
        Ignored for "kmeans" (which uses n_clusters * samples_per_cluster).
    method
        Subsampling strategy:
        - "random": simple random sampling (fast, suitable for most cases).
        - "kmeans": PCA dimensionality reduction → MiniBatchKMeans clustering
          → select the samples closest to each centroid (better coverage of
          the embedding space diversity).
    n_clusters
        Number of clusters for the "kmeans" method.
    samples_per_cluster
        Number of samples to select per cluster for "kmeans".
    pca_dims
        Number of PCA dimensions to reduce to before clustering.
        Must be <= embedding_dim and <= n_samples.
    random_state
        Random seed for reproducibility.

    Returns
    -------
    np.ndarray
        Reduced array of shape (m, embedding_dim) where m <= max_samples
        (random) or m <= n_clusters * samples_per_cluster (kmeans).

    Raises
    ------
    ValueError
        If method is not "random" or "kmeans", or if embeddings is empty.
    """
    if len(embeddings) == 0:
        raise ValueError("embeddings array is empty.")

    if method not in ("random", "kmeans"):
        raise ValueError(f"method must be 'random' or 'kmeans', got '{method}'.")

    n = len(embeddings)

    if method == "random":
        if n <= max_samples:
            logger.debug(
                "reduce_unlabeled_samples(random): %d <= max_samples=%d, returning all.",
                n,
                max_samples,
            )
            return embeddings

        rng = np.random.default_rng(random_state)
        idx: np.ndarray = rng.choice(n, size=max_samples, replace=False)
        logger.info(
            "reduce_unlabeled_samples(random): %d → %d samples", n, max_samples
        )
        sampled: np.ndarray = embeddings[idx]
        return sampled

    # method == "kmeans"
    actual_pca_dims = min(pca_dims, embeddings.shape[1], n)
    actual_n_clusters = min(n_clusters, n)

    logger.info(
        "reduce_unlabeled_samples(kmeans): n=%d, pca_dims=%d, n_clusters=%d, "
        "samples_per_cluster=%d",
        n,
        actual_pca_dims,
        actual_n_clusters,
        samples_per_cluster,
    )

    # PCA reduction for faster clustering
    if actual_pca_dims < embeddings.shape[1]:
        pca = PCA(n_components=actual_pca_dims, random_state=random_state)
        reduced = pca.fit_transform(embeddings)
        logger.debug(
            "PCA: %d → %d dims (explained variance ratio sum=%.4f)",
            embeddings.shape[1],
            actual_pca_dims,
            float(pca.explained_variance_ratio_.sum()),
        )
    else:
        reduced = embeddings

    # MiniBatchKMeans for scalability
    kmeans = MiniBatchKMeans(
        n_clusters=actual_n_clusters,
        random_state=random_state,
        n_init=3,
        batch_size=min(1024, n),
    )
    cluster_labels = kmeans.fit_predict(reduced)
    centroids = kmeans.cluster_centers_

    selected_indices: list[int] = []
    for cluster_id in range(actual_n_clusters):
        cluster_mask = cluster_labels == cluster_id
        cluster_idx = np.where(cluster_mask)[0]

        if len(cluster_idx) == 0:
            continue

        # Compute distances from cluster members to centroid
        centroid = centroids[cluster_id]
        dists = np.linalg.norm(reduced[cluster_idx] - centroid, axis=1)
        n_select = min(samples_per_cluster, len(cluster_idx))
        nearest = cluster_idx[np.argsort(dists)[:n_select]]
        selected_indices.extend(nearest.tolist())

    result: np.ndarray = embeddings[np.array(selected_indices)]
    logger.info(
        "reduce_unlabeled_samples(kmeans): %d → %d samples", n, len(result)
    )
    return result
