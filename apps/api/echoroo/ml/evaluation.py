"""Evaluation utilities for the model training pipeline.

This module provides:
- AuditSample: dataclass representing a score-stratified sample for human audit.
- select_audit_set: score-stratified sampling for human-in-the-loop evaluation.
- evaluate_on_audit_set: compute classification metrics from audited labels.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

if TYPE_CHECKING:
    from echoroo.ml.classifiers import UnifiedClassifier

logger = logging.getLogger(__name__)

__all__ = [
    "AuditSample",
    "select_audit_set",
    "evaluate_on_audit_set",
]


@dataclass
class AuditSample:
    """A single sample selected for human audit.

    Attributes
    ----------
    embedding_id
        Unique identifier of the embedding.
    recording_id
        Identifier of the source recording.
    predicted_proba
        Classifier probability for the positive class (0.0–1.0).
    """

    embedding_id: str
    recording_id: str
    predicted_proba: float


def select_audit_set(
    all_embedding_ids: list[str],
    all_recording_ids: list[str],
    all_vectors: np.ndarray,
    exclude_ids: set[str],
    classifier: UnifiedClassifier,
    n_per_bucket: int = 6,
    n_buckets: int = 5,
) -> list[AuditSample]:
    """Select a score-stratified audit set from the embedding pool.

    Scores all candidate embeddings with the classifier, divides the [0, 1]
    probability range into ``n_buckets`` equal-width buckets, and randomly
    samples up to ``n_per_bucket`` items from each bucket.

    Parameters
    ----------
    all_embedding_ids
        List of embedding IDs corresponding to rows in ``all_vectors``.
    all_recording_ids
        List of recording IDs corresponding to rows in ``all_vectors``.
    all_vectors
        Array of shape (n_embeddings, embedding_dim) — full candidate pool.
    exclude_ids
        Set of embedding IDs to exclude (e.g., already-labeled samples).
    classifier
        A fitted ``UnifiedClassifier`` used for scoring.
    n_per_bucket
        Maximum number of samples to draw from each score bucket.
    n_buckets
        Number of equal-width buckets over [0, 1].

    Returns
    -------
    list[AuditSample]
        Selected audit samples, one entry per selected embedding.
        May contain fewer than ``n_per_bucket * n_buckets`` items if the
        candidate pool is sparse in some score ranges.
    """
    if len(all_embedding_ids) != len(all_vectors) or len(all_recording_ids) != len(all_vectors):
        raise ValueError(
            "all_embedding_ids, all_recording_ids and all_vectors must have the same length."
        )

    # Build mask for candidates (exclude already-labeled)
    candidate_mask = np.array(
        [eid not in exclude_ids for eid in all_embedding_ids], dtype=bool
    )
    n_candidates = int(candidate_mask.sum())

    if n_candidates == 0:
        logger.warning("select_audit_set: no candidates after exclusion, returning empty list.")
        return []

    candidate_indices = np.where(candidate_mask)[0]
    candidate_vectors = all_vectors[candidate_mask]
    candidate_embedding_ids = [all_embedding_ids[i] for i in candidate_indices]
    candidate_recording_ids = [all_recording_ids[i] for i in candidate_indices]

    # Score candidates
    probas: np.ndarray = classifier.predict_proba(candidate_vectors)

    logger.info(
        "select_audit_set: n_candidates=%d, n_buckets=%d, n_per_bucket=%d",
        n_candidates,
        n_buckets,
        n_per_bucket,
    )

    # Stratified bucket sampling
    bucket_edges = np.linspace(0.0, 1.0, n_buckets + 1)
    rng = np.random.default_rng(seed=42)

    selected: list[AuditSample] = []

    for bucket_idx in range(n_buckets):
        low = bucket_edges[bucket_idx]
        high = bucket_edges[bucket_idx + 1]

        if bucket_idx == n_buckets - 1:
            # Include upper bound in last bucket
            in_bucket = np.where((probas >= low) & (probas <= high))[0]
        else:
            in_bucket = np.where((probas >= low) & (probas < high))[0]

        if len(in_bucket) == 0:
            logger.debug(
                "select_audit_set: bucket %d [%.2f, %.2f) is empty, skipping.",
                bucket_idx,
                low,
                high,
            )
            continue

        n_draw = min(n_per_bucket, len(in_bucket))
        drawn_local = rng.choice(in_bucket, size=n_draw, replace=False)

        for local_idx in drawn_local:
            selected.append(
                AuditSample(
                    embedding_id=candidate_embedding_ids[local_idx],
                    recording_id=candidate_recording_ids[local_idx],
                    predicted_proba=float(probas[local_idx]),
                )
            )

        logger.debug(
            "select_audit_set: bucket %d [%.2f, %.2f): %d available, drew %d",
            bucket_idx,
            low,
            high,
            len(in_bucket),
            n_draw,
        )

    logger.info(
        "select_audit_set: selected %d audit samples from %d candidates",
        len(selected),
        n_candidates,
    )
    return selected


def evaluate_on_audit_set(
    true_labels: list[int] | np.ndarray,
    predicted_probas: list[float] | np.ndarray,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """Compute classification metrics from human-audited labels.

    Parameters
    ----------
    true_labels
        Ground-truth binary labels (0 or 1) assigned by human auditors.
    predicted_probas
        Classifier-predicted probabilities for the positive class (0.0–1.0).
    threshold
        Decision threshold for converting probabilities to predictions.

    Returns
    -------
    dict[str, Any]
        Metrics dictionary containing:
        - accuracy, precision, recall, f1 (float)
        - roc_auc, pr_auc (float or nan when not computable)
        - confusion_matrix (nested list [[TN, FP], [FN, TP]])
        - n_audited (int) — number of audited samples used
        - n_total (int) — total number of audit samples (same as n_audited here;
          the calling service may override n_total with the full audit set size)
        - threshold (float)

    Notes
    -----
    When all labels belong to a single class, AUC metrics are set to
    ``float("nan")`` and a warning is logged. Precision/recall edge cases
    use zero_division=0 (returns 0.0).
    """
    y_true = np.asarray(true_labels, dtype=int)
    y_proba = np.asarray(predicted_probas, dtype=float)

    if len(y_true) != len(y_proba):
        raise ValueError(
            f"true_labels and predicted_probas must have the same length, "
            f"got {len(y_true)} and {len(y_proba)}."
        )

    n_samples = len(y_true)

    if n_samples == 0:
        logger.warning("evaluate_on_audit_set: received empty arrays.")
        return {
            "accuracy": float("nan"),
            "precision": float("nan"),
            "recall": float("nan"),
            "f1": float("nan"),
            "roc_auc": float("nan"),
            "pr_auc": float("nan"),
            "confusion_matrix": [[0, 0], [0, 0]],
            "n_audited": 0,
            "n_total": 0,
        }

    y_pred = (y_proba >= threshold).astype(int)

    unique_labels = np.unique(y_true)
    single_class = len(unique_labels) < 2

    if single_class:
        logger.warning(
            "evaluate_on_audit_set: only one class present in true_labels (%s). "
            "AUC metrics are not computable.",
            unique_labels.tolist(),
        )

    acc = float(accuracy_score(y_true, y_pred))
    prec = float(precision_score(y_true, y_pred, zero_division=0))
    rec = float(recall_score(y_true, y_pred, zero_division=0))
    f1 = float(f1_score(y_true, y_pred, zero_division=0))

    if single_class:
        roc_auc = float("nan")
        pr_auc = float("nan")
    else:
        try:
            roc_auc = float(roc_auc_score(y_true, y_proba))
        except ValueError:
            logger.warning("evaluate_on_audit_set: ROC-AUC could not be computed.")
            roc_auc = float("nan")

        try:
            pr_auc = float(average_precision_score(y_true, y_proba))
        except ValueError:
            logger.warning("evaluate_on_audit_set: PR-AUC could not be computed.")
            pr_auc = float("nan")

    cm = confusion_matrix(y_true, y_pred, labels=[0, 1]).tolist()

    metrics: dict[str, Any] = {
        "accuracy": acc,
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "confusion_matrix": cm,
        "n_audited": n_samples,
        "n_total": n_samples,
    }

    logger.info(
        "evaluate_on_audit_set: n=%d, accuracy=%.4f, precision=%.4f, "
        "recall=%.4f, f1=%.4f, roc_auc=%s, pr_auc=%s",
        n_samples,
        acc,
        prec,
        rec,
        f1,
        f"{roc_auc:.4f}" if not np.isnan(roc_auc) else "nan",
        f"{pr_auc:.4f}" if not np.isnan(pr_auc) else "nan",
    )

    return metrics
