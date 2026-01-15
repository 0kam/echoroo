"""Active Learning module for iterative sample selection.

This module provides functionality for active learning in audio classification:
- Initial sampling with Easy Positives (EP), Boundary samples, and Others
- Farthest-first selection for diversity
- Sigmoid classifiers for uncertainty sampling
- Iterative sample selection based on model uncertainty

The active learning workflow:
1. Initial sampling: Select EP (high similarity), Boundary (medium similarity),
   and Others (diverse low similarity) samples
2. User labels samples as positive/negative
3. Train simple sigmoid classifiers on labeled data
4. Select new samples in the uncertainty region (0.25-0.75)
5. Repeat steps 2-4 until sufficient training data is collected
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from sklearn.cluster import MiniBatchKMeans
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import Normalizer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.ml.classifiers import ClassifierType, UnifiedClassifier
from echoroo.models.search_session import SampleType

logger = logging.getLogger(__name__)

__all__ = [
    "ActiveLearningConfig",
    "ClassifierType",
    "SigmoidClassifier",
    "UnifiedClassifier",
    "compute_initial_samples",
    "compute_similarities",
    "compute_cosine_similarities",
    "farthest_first_selection",
    "filter_valid_embeddings",
    "get_dataset_clip_embeddings",
    "run_active_learning_iteration",
    "MIN_EMBEDDING_NORM",
]

# Minimum L2 norm for valid embeddings. Embeddings with smaller norms
# are considered invalid (zero or near-zero) and excluded from processing.
MIN_EMBEDDING_NORM = 1e-6


@dataclass
class ActiveLearningConfig:
    """Configuration for active learning sampling.

    Attributes
    ----------
    easy_positive_k
        Number of top-k most similar clips to select as easy positives
        for each reference sound.
    boundary_n
        Number of clips below easy positives to consider for boundary sampling.
        Clips ranked from (easy_positive_k + 1) to (easy_positive_k + boundary_n)
        are candidates for boundary selection.
    boundary_m
        Number of boundary samples to randomly select from the boundary_n candidates.
    others_p
        Number of diverse samples to select from remaining clips using
        farthest-first selection.
    uncertainty_low
        Lower threshold for uncertainty region. Clips with model scores
        below this are considered confident negatives.
    uncertainty_high
        Upper threshold for uncertainty region. Clips with model scores
        above this are considered confident positives.
    samples_per_iteration
        Number of samples to select per active learning iteration.
    max_farthest_first_candidates
        Maximum number of candidates to consider for farthest-first selection.
        Random subsampling is applied if there are more candidates.
    """

    easy_positive_k: int = 5
    boundary_n: int = 200
    boundary_m: int = 10
    others_p: int = 20
    uncertainty_low: float = 0.25
    uncertainty_high: float = 0.75
    samples_per_iteration: int = 20
    max_farthest_first_candidates: int = 1000


def filter_valid_embeddings(
    embeddings: np.ndarray,
    min_norm: float = MIN_EMBEDDING_NORM,
) -> tuple[np.ndarray, np.ndarray]:
    """Filter out embeddings with L2 norm below threshold.

    Zero or near-zero embeddings cause numerical issues in cosine similarity
    and classification. This function returns a mask of valid embeddings.

    Parameters
    ----------
    embeddings
        Array of shape (n, dim) containing embedding vectors.
    min_norm
        Minimum L2 norm for valid embeddings.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        - valid_mask: Boolean array of shape (n,) where True = valid
        - norms: L2 norms of shape (n,) for all embeddings
    """
    norms = np.linalg.norm(embeddings, axis=1)
    valid_mask = norms >= min_norm
    return valid_mask, norms


class SigmoidClassifier:
    """Simple sigmoid classifier for binary tag classification.

    .. deprecated::
        Use :class:`~echoroo.ml.classifiers.UnifiedClassifier` instead.
        This class is kept for backward compatibility.

    Wraps sklearn's LogisticRegression with L2 normalization for embedding-based
    classification. Uses cosine-compatible geometry by normalizing embeddings
    before classification.

    Attributes
    ----------
    model
        Pipeline containing L2 normalizer and LogisticRegression.
    is_fitted
        Whether the model has been trained.
    """

    def __init__(self, C: float = 1.0, max_iter: int = 1000):
        """Initialize the sigmoid classifier.

        Parameters
        ----------
        C
            Inverse of regularization strength. Smaller values specify
            stronger regularization.
        max_iter
            Maximum number of iterations for optimization.
        """
        # Use Pipeline with L2 normalization for cosine-compatible geometry
        self.model = Pipeline([
            ("normalizer", Normalizer(norm="l2")),
            ("classifier", LogisticRegression(
                C=C,
                max_iter=max_iter,
                solver="lbfgs",
                random_state=42,
                class_weight="balanced",  # Handle class imbalance
            )),
        ])
        self.is_fitted = False

    def fit(self, embeddings: np.ndarray, labels: np.ndarray) -> "SigmoidClassifier":
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
        SigmoidClassifier
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
            self._single_class = unique_labels[0]
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
        if classifier.classes_[1] == 1:
            return proba[:, 1]
        else:
            return proba[:, 0]


def compute_similarities(
    query_embeddings: np.ndarray,
    candidate_embeddings: np.ndarray,
    distance_metric: str = "cosine",
) -> np.ndarray:
    """Compute max similarity for each candidate across all queries.

    For each candidate embedding, computes similarity to all query
    embeddings and returns the maximum similarity. Invalid embeddings
    (near-zero norm) are assigned similarity of -1.

    Parameters
    ----------
    query_embeddings
        Array of shape (q, dim) containing query embedding vectors.
    candidate_embeddings
        Array of shape (n, dim) containing candidate embedding vectors.
    distance_metric
        Distance metric to use: "cosine" or "euclidean".

    Returns
    -------
    np.ndarray
        Array of shape (n,) containing max similarity for each candidate.
        Invalid candidates have similarity -1.
    """
    if len(query_embeddings) == 0 or len(candidate_embeddings) == 0:
        return np.array([])

    # Filter out invalid embeddings (near-zero norm)
    query_valid_mask, query_norms = filter_valid_embeddings(query_embeddings)
    candidate_valid_mask, candidate_norms = filter_valid_embeddings(candidate_embeddings)

    # If no valid queries, return -1 for all candidates
    if not np.any(query_valid_mask):
        return np.full(len(candidate_embeddings), -1.0)

    # Initialize result with -1 for invalid candidates
    result = np.full(len(candidate_embeddings), -1.0)

    # Only process valid embeddings
    valid_queries = query_embeddings[query_valid_mask]
    valid_query_norms = query_norms[query_valid_mask, np.newaxis]

    valid_candidate_indices = np.where(candidate_valid_mask)[0]
    if len(valid_candidate_indices) == 0:
        return result

    valid_candidates = candidate_embeddings[valid_candidate_indices]
    valid_candidate_norms = candidate_norms[valid_candidate_indices, np.newaxis]

    # Normalize valid embeddings
    query_normalized = valid_queries / valid_query_norms
    candidate_normalized = valid_candidates / valid_candidate_norms

    if distance_metric == "cosine":
        # Cosine similarity = dot product of normalized vectors
        similarity_matrix = candidate_normalized @ query_normalized.T
    elif distance_metric == "euclidean":
        # Euclidean distance, then convert to similarity
        # For normalized vectors, compute distances efficiently
        # Distance = sqrt(2 - 2 * dot_product) for normalized vectors
        # Similarity = 1 / (1 + distance)
        dot_products = candidate_normalized @ query_normalized.T
        distances = np.sqrt(np.maximum(0, 2 - 2 * dot_products))
        similarity_matrix = 1.0 / (1.0 + distances)
    else:
        # Default to cosine for unknown metrics
        similarity_matrix = candidate_normalized @ query_normalized.T

    # Assign max similarity to valid candidates
    result[valid_candidate_indices] = np.max(similarity_matrix, axis=1)

    return result


def compute_cosine_similarities(
    query_embeddings: np.ndarray,
    candidate_embeddings: np.ndarray,
) -> np.ndarray:
    """Compute max cosine similarity for each candidate across all queries.

    This is a convenience wrapper around compute_similarities with cosine metric.

    Parameters
    ----------
    query_embeddings
        Array of shape (q, dim) containing query embedding vectors.
    candidate_embeddings
        Array of shape (n, dim) containing candidate embedding vectors.

    Returns
    -------
    np.ndarray
        Array of shape (n,) containing max similarity for each candidate.
        Invalid candidates have similarity -1.
    """
    return compute_similarities(query_embeddings, candidate_embeddings, "cosine")


def farthest_first_selection(
    embeddings: np.ndarray,
    seed_embeddings: np.ndarray,
    n_select: int,
    distance_metric: str = "cosine",
) -> list[int]:
    """Select n points that are farthest from seeds using greedy algorithm.

    Uses distance metric for diversity selection. At each step, selects
    the point with maximum minimum distance to all already selected points
    (including seeds). Invalid embeddings (near-zero norm) are excluded.

    Parameters
    ----------
    embeddings
        Array of shape (n, dim) containing candidate embedding vectors.
    seed_embeddings
        Array of shape (m, dim) containing seed embedding vectors.
        Selected points should be diverse from these seeds.
    n_select
        Number of points to select.
    distance_metric
        Distance metric to use: "cosine" or "euclidean".

    Returns
    -------
    list[int]
        Indices of selected points in the embeddings array.
    """
    if len(embeddings) == 0 or n_select <= 0:
        return []

    n_candidates = len(embeddings)

    # Filter out invalid embeddings
    valid_mask, emb_norms = filter_valid_embeddings(embeddings)
    n_valid = np.sum(valid_mask)

    if n_valid == 0:
        return []

    n_select = min(n_select, n_valid)

    # Normalize valid embeddings for cosine distance
    embeddings_normalized = np.zeros_like(embeddings)
    embeddings_normalized[valid_mask] = (
        embeddings[valid_mask] / emb_norms[valid_mask, np.newaxis]
    )

    # Initialize distances - invalid embeddings get -inf (never selected)
    min_distances = np.full(n_candidates, -np.inf)

    # Initialize distances to seeds for valid embeddings
    if len(seed_embeddings) > 0:
        seed_valid_mask, seed_norms = filter_valid_embeddings(seed_embeddings)
        if np.any(seed_valid_mask):
            valid_seeds = seed_embeddings[seed_valid_mask]
            valid_seed_norms = seed_norms[seed_valid_mask, np.newaxis]
            seeds_normalized = valid_seeds / valid_seed_norms

            if distance_metric == "cosine":
                # Cosine distance = 1 - cosine similarity
                seed_similarities = embeddings_normalized[valid_mask] @ seeds_normalized.T
                min_distances[valid_mask] = 1 - np.max(seed_similarities, axis=1)
            elif distance_metric == "euclidean":
                # Euclidean distance between normalized vectors
                dot_products = embeddings_normalized[valid_mask] @ seeds_normalized.T
                distances = np.sqrt(np.maximum(0, 2 - 2 * dot_products))
                min_distances[valid_mask] = np.min(distances, axis=1)
            else:
                # Default to cosine
                seed_similarities = embeddings_normalized[valid_mask] @ seeds_normalized.T
                min_distances[valid_mask] = 1 - np.max(seed_similarities, axis=1)
        else:
            # No valid seeds - all valid points equally far
            min_distances[valid_mask] = 1.0
    else:
        # No seeds - all valid points equally far
        min_distances[valid_mask] = 1.0

    selected_indices: list[int] = []

    for _ in range(n_select):
        # Select point with maximum minimum distance
        farthest_idx = int(np.argmax(min_distances))

        # Safety check: if best distance is -inf, no more valid candidates
        if min_distances[farthest_idx] == -np.inf:
            break

        selected_indices.append(farthest_idx)

        if len(selected_indices) < n_select:
            # Update distances based on newly selected point
            selected_embedding = embeddings_normalized[farthest_idx : farthest_idx + 1]

            if distance_metric == "cosine":
                # Cosine distance
                new_similarities = embeddings_normalized @ selected_embedding.T
                new_distances = 1 - new_similarities.flatten()
            elif distance_metric == "euclidean":
                # Euclidean distance between normalized vectors
                dot_products = embeddings_normalized @ selected_embedding.T
                new_distances = np.sqrt(np.maximum(0, 2 - 2 * dot_products)).flatten()
            else:
                # Default to cosine
                new_similarities = embeddings_normalized @ selected_embedding.T
                new_distances = 1 - new_similarities.flatten()

            # Update minimum distances (only for valid candidates)
            min_distances = np.minimum(min_distances, new_distances)

            # Mark selected point as already used
            min_distances[farthest_idx] = -np.inf

    return selected_indices


async def get_dataset_clip_embeddings(
    session: AsyncSession,
    ml_project_id: int,
    exclude_clip_ids: set[int] | None = None,
    max_samples: int | None = None,
) -> list[tuple[int, np.ndarray]]:
    """Get clip embeddings from ML project's dataset scopes.

    Retrieves embeddings for clips in datasets associated with the
    ML project through its dataset scopes. If max_samples is specified,
    uses a two-stage query to efficiently fetch a random subset.

    Parameters
    ----------
    session
        SQLAlchemy AsyncSession for database operations.
    ml_project_id
        ID of the ML project.
    exclude_clip_ids
        Optional set of clip IDs to exclude from results.
    max_samples
        Maximum number of samples to return. If None, returns all.
        When specified, performs random sampling at the database level
        for efficiency.

    Returns
    -------
    list[tuple[int, np.ndarray]]
        List of (clip_id, embedding) tuples.
    """
    params: dict = {"ml_project_id": ml_project_id}

    if exclude_clip_ids:
        exclude_clause = " AND ce.clip_id != ALL(:exclude_clip_ids)"
        params["exclude_clip_ids"] = list(exclude_clip_ids)
    else:
        exclude_clause = ""

    # Base query for clip_ids with proper joins
    base_from_clause = """
        FROM clip_embedding ce
        JOIN clip c ON ce.clip_id = c.id
        JOIN recording r ON c.recording_id = r.id
        JOIN dataset_recording dr ON r.id = dr.recording_id
        JOIN ml_project_dataset_scope mpds ON dr.dataset_id = mpds.dataset_id
        JOIN model_run mr ON ce.model_run_id = mr.id
        JOIN foundation_model_run fmr ON mpds.foundation_model_run_id = fmr.id
        WHERE mpds.ml_project_id = :ml_project_id
          AND fmr.model_run_id = ce.model_run_id
    """

    if max_samples is not None:
        # Two-stage query: first get random clip_ids (lightweight),
        # then fetch embeddings only for those clips
        logger.info(f"Using two-stage query with max_samples={max_samples}")

        # Stage 1: Get random clip_ids (no embedding data transferred)
        # Use subquery to work around PostgreSQL's DISTINCT + ORDER BY RANDOM() limitation
        clip_id_query = f"""
            SELECT clip_id FROM (
                SELECT DISTINCT ce.clip_id
                {base_from_clause}
                {exclude_clause}
            ) AS distinct_clips
            ORDER BY RANDOM()
            LIMIT :max_samples
        """
        params["max_samples"] = max_samples

        result = await session.execute(text(clip_id_query), params)
        clip_ids = [row.clip_id for row in result.fetchall()]

        if not clip_ids:
            return []

        logger.info(f"Stage 1: Selected {len(clip_ids)} random clip_ids")

        # Stage 2: Fetch embeddings only for selected clip_ids
        embedding_query = """
            SELECT DISTINCT ON (ce.clip_id)
                ce.clip_id,
                ce.embedding
            FROM clip_embedding ce
            JOIN model_run mr ON ce.model_run_id = mr.id
            JOIN ml_project_dataset_scope mpds ON mpds.ml_project_id = :ml_project_id
            JOIN foundation_model_run fmr ON mpds.foundation_model_run_id = fmr.id
            WHERE ce.clip_id = ANY(:selected_clip_ids)
              AND fmr.model_run_id = ce.model_run_id
            ORDER BY ce.clip_id
        """
        stage2_params = {
            "ml_project_id": ml_project_id,
            "selected_clip_ids": clip_ids,
        }

        result = await session.execute(text(embedding_query), stage2_params)
        rows = result.fetchall()
        logger.info(f"Stage 2: Fetched {len(rows)} embeddings")
    else:
        # Original query: fetch all embeddings
        query = f"""
            SELECT DISTINCT ON (ce.clip_id)
                ce.clip_id,
                ce.embedding
            {base_from_clause}
            {exclude_clause}
            ORDER BY ce.clip_id
        """

        result = await session.execute(text(query), params)
        rows = result.fetchall()

    # Parse embeddings and filter out invalid (near-zero) ones
    embeddings = []
    for row in rows:
        emb = row.embedding
        if isinstance(emb, str):
            emb = json.loads(emb)
        emb_array = np.array(emb, dtype=np.float32)

        # Skip invalid embeddings (near-zero norm)
        norm = np.linalg.norm(emb_array)
        if norm < MIN_EMBEDDING_NORM:
            continue

        embeddings.append((row.clip_id, emb_array))

    return embeddings


async def compute_initial_samples(
    session: AsyncSession,
    search_session_id: int,
    ml_project_id: int,
    reference_embeddings_by_tag: dict[int, list[np.ndarray]],
    config: ActiveLearningConfig | None = None,
    distance_metric: str = "cosine",
) -> tuple[list[dict], int]:
    """Compute initial sampling: EP + Boundary + Others.

    Performs initial sample selection for active learning:
    1. Easy Positives (EP): Top-k most similar clips to reference sounds
    2. Boundary: Randomly selected from top (k+1) to (k+n) range
    3. Others: Diverse samples from remaining clips using farthest-first

    Parameters
    ----------
    session
        SQLAlchemy AsyncSession for database operations.
    search_session_id
        ID of the search session.
    ml_project_id
        ID of the ML project.
    reference_embeddings_by_tag
        Dictionary mapping tag_id to list of reference embeddings.
    config
        Active learning configuration. Uses defaults if None.
    distance_metric
        Distance metric to use: "cosine" or "euclidean".

    Returns
    -------
    tuple[list[dict], int]
        - List of dicts with:
          - clip_id: int
          - similarity: float
          - sample_type: 'easy_positive' | 'boundary' | 'others'
          - source_tag_id: int | None
          - dataset_rank: int (1-based rank in full dataset)
        - Total number of clips in the dataset
    """
    if config is None:
        config = ActiveLearningConfig()

    # Get all clip embeddings from dataset scopes
    clip_embeddings = await get_dataset_clip_embeddings(
        session=session,
        ml_project_id=ml_project_id,
    )

    if not clip_embeddings:
        return [], 0

    clip_ids = np.array([ce[0] for ce in clip_embeddings])
    embeddings = np.array([ce[1] for ce in clip_embeddings])
    total_clips = len(clip_ids)

    results: list[dict] = []
    selected_clip_ids: set[int] = set()
    all_reference_embeddings: list[np.ndarray] = []

    # Track best rank for each clip across all tags (for Others filtering)
    # Also used for dataset_rank calculation (1-based)
    clip_best_ranks: dict[int, int] = {}

    # Process each target tag
    for tag_id, ref_embeddings in reference_embeddings_by_tag.items():
        if not ref_embeddings:
            continue

        ref_array = np.array(ref_embeddings)
        all_reference_embeddings.extend(ref_embeddings)

        # Compute similarities to reference sounds
        similarities = compute_similarities(ref_array, embeddings, distance_metric)

        # Sort by similarity (descending)
        sorted_indices = np.argsort(-similarities)

        # Track ranks for Others filtering
        for rank, idx in enumerate(sorted_indices):
            clip_id = int(clip_ids[idx])
            if clip_id not in clip_best_ranks:
                clip_best_ranks[clip_id] = rank
            else:
                clip_best_ranks[clip_id] = min(clip_best_ranks[clip_id], rank)

        # Select Easy Positives (top-k)
        ep_count = 0
        for rank_idx, idx in enumerate(sorted_indices):
            if ep_count >= config.easy_positive_k:
                break
            clip_id = int(clip_ids[idx])
            if clip_id not in selected_clip_ids:
                results.append({
                    "clip_id": clip_id,
                    "similarity": float(similarities[idx]),
                    "sample_type": SampleType.EASY_POSITIVE.value,
                    "source_tag_id": tag_id,
                    "dataset_rank": rank_idx + 1,  # 1-based rank in dataset
                })
                selected_clip_ids.add(clip_id)
                ep_count += 1

        # Select Boundary samples (random from top k+1 to k+n)
        boundary_start = config.easy_positive_k
        boundary_end = boundary_start + config.boundary_n

        # Get candidate indices for boundary (with rank info)
        boundary_candidates = []
        for i in range(boundary_start, min(boundary_end, len(sorted_indices))):
            idx = sorted_indices[i]
            clip_id = int(clip_ids[idx])
            if clip_id not in selected_clip_ids:
                # i is 0-based index in sorted order, so dataset_rank = i + 1
                boundary_candidates.append((idx, clip_id, float(similarities[idx]), i + 1))

        # Random selection from boundary candidates
        if boundary_candidates:
            n_boundary = min(config.boundary_m, len(boundary_candidates))
            rng = np.random.default_rng(seed=42 + tag_id)
            selected_boundary = rng.choice(
                len(boundary_candidates),
                size=n_boundary,
                replace=False,
            )

            for i in selected_boundary:
                idx, clip_id, sim, dataset_rank = boundary_candidates[i]
                results.append({
                    "clip_id": clip_id,
                    "similarity": sim,
                    "sample_type": SampleType.BOUNDARY.value,
                    "source_tag_id": tag_id,
                    "dataset_rank": dataset_rank,
                })
                selected_clip_ids.add(clip_id)

    # Select Others using farthest-first
    # Others should only include clips ranked AFTER boundary_end for ALL tags
    others_boundary = config.easy_positive_k + config.boundary_n

    # Build mask for Others candidates:
    # 1. Not already selected
    # 2. Ranked > boundary_end for all tags (best_rank >= others_boundary)
    others_candidates_mask = np.zeros(len(clip_ids), dtype=bool)
    for i, clip_id in enumerate(clip_ids):
        int_clip_id = int(clip_id)
        # Skip already selected clips
        if int_clip_id in selected_clip_ids:
            continue
        # Only include clips ranked below boundary_end for all tags
        if int_clip_id in clip_best_ranks and clip_best_ranks[int_clip_id] >= others_boundary:
            others_candidates_mask[i] = True

    remaining_indices = np.where(others_candidates_mask)[0]

    if len(remaining_indices) > 0 and all_reference_embeddings:
        # Subsample if too many candidates
        if len(remaining_indices) > config.max_farthest_first_candidates:
            rng = np.random.default_rng(seed=42)
            remaining_indices = rng.choice(
                remaining_indices,
                size=config.max_farthest_first_candidates,
                replace=False,
            )

        remaining_embeddings = embeddings[remaining_indices]
        seed_embeddings = np.array(all_reference_embeddings)

        # Farthest-first selection
        ff_selected = farthest_first_selection(
            embeddings=remaining_embeddings,
            seed_embeddings=seed_embeddings,
            n_select=config.others_p,
            distance_metric=distance_metric,
        )

        for ff_idx in ff_selected:
            original_idx = remaining_indices[ff_idx]
            clip_id = int(clip_ids[original_idx])

            # Compute similarity for the selected clip
            sim = compute_similarities(
                seed_embeddings,
                embeddings[original_idx : original_idx + 1],
                distance_metric,
            )

            # Get dataset_rank from clip_best_ranks (0-based, convert to 1-based)
            dataset_rank = clip_best_ranks.get(clip_id, total_clips) + 1

            results.append({
                "clip_id": clip_id,
                "similarity": float(sim[0]) if len(sim) > 0 else 0.0,
                "sample_type": SampleType.OTHERS.value,
                "source_tag_id": None,
                "dataset_rank": dataset_rank,
            })
            selected_clip_ids.add(clip_id)

    return results, total_clips


def perform_c_grid_search(
    embeddings: np.ndarray,
    labels: np.ndarray,
    c_values: list[float] = [0.1, 1.0, 10.0],
    test_size: float = 0.3,
    random_state: int = 42,
) -> tuple[float, dict[float, float]]:
    """Perform grid search over C parameter for SVM using train/test split.

    Splits labeled data into train/test sets using stratified sampling,
    trains Self-Training+SVM with different C values, and evaluates
    using F1 score on the test set.

    Parameters
    ----------
    embeddings : np.ndarray
        Training embeddings (n_samples, embedding_dim)
    labels : np.ndarray
        Binary labels (0 or 1)
    c_values : list[float]
        C values to try (default: [0.1, 1.0, 10.0])
    test_size : float
        Fraction of data to use for testing (default: 0.3)
    random_state : int
        Random seed for reproducibility (default: 42)

    Returns
    -------
    tuple[float, dict[float, float]]
        - best_c: The C value with highest F1 score
        - scores: Dictionary mapping C value to F1 score

    Raises
    ------
    ValueError
        If train/test split results in single-class subset
    """
    # Stratified train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        embeddings,
        labels,
        test_size=test_size,
        stratify=labels,
        random_state=random_state,
    )

    # Check for single-class subsets
    if len(np.unique(y_train)) < 2 or len(np.unique(y_test)) < 2:
        raise ValueError(
            f"Train/test split resulted in single-class subset: "
            f"train_classes={np.unique(y_train)}, test_classes={np.unique(y_test)}"
        )

    scores = {}
    for c in c_values:
        try:
            # Train classifier with this C value
            classifier = UnifiedClassifier(
                ClassifierType.SELF_TRAINING_SVM,
                custom_params={"C": c},
            )
            classifier.fit(X_train, y_train)

            # Predict on test set
            y_pred_proba = classifier.predict_proba(X_test)
            y_pred = (y_pred_proba >= 0.5).astype(int)

            # Calculate F1 score
            score = f1_score(y_test, y_pred)
            scores[c] = score

            logger.debug(f"C={c}: F1={score:.4f}")
        except Exception as e:
            logger.warning(f"C={c} failed during training: {e}")
            scores[c] = 0.0

    # Ensure at least one C value succeeded
    if all(s == 0.0 for s in scores.values()):
        raise ValueError("All C values failed during grid search")

    # Select best C
    best_c = max(scores, key=scores.get)
    return best_c, scores


def cluster_unlabeled_embeddings(
    embeddings: np.ndarray,
    n_clusters: int = 1000,
    samples_per_cluster: int = 2,
    random_state: int = 42,
) -> np.ndarray:
    """Cluster unlabeled embeddings using MiniBatchKMeans and keep representative samples.

    Uses MiniBatchKMeans for efficiency with large datasets. For each cluster,
    selects the k samples closest to the centroid to maintain diversity while
    reducing dataset size.

    Parameters
    ----------
    embeddings : np.ndarray
        Unlabeled embeddings (n_samples, embedding_dim)
    n_clusters : int
        Number of clusters to create (default: 1000)
    samples_per_cluster : int
        Number of samples to keep per cluster (default: 2)
    random_state : int
        Random seed for reproducibility (default: 42)

    Returns
    -------
    np.ndarray
        Subset of embeddings closest to cluster centroids
        Shape: (~n_clusters * samples_per_cluster, embedding_dim)
    """
    n_samples = len(embeddings)

    # Adjust n_clusters if needed
    actual_n_clusters = min(n_clusters, n_samples)
    if actual_n_clusters < n_clusters:
        logger.warning(
            f"Adjusting n_clusters from {n_clusters} to {actual_n_clusters} "
            f"due to limited samples ({n_samples})"
        )

    # Perform MiniBatchKMeans clustering
    logger.info(f"Running MiniBatchKMeans with {actual_n_clusters} clusters...")
    kmeans = MiniBatchKMeans(
        n_clusters=actual_n_clusters,
        random_state=random_state,
        batch_size=1024,
        n_init=3,
    )
    cluster_labels = kmeans.fit_predict(embeddings)

    # For each cluster, find samples closest to centroid
    selected_indices = []
    for cluster_id in range(actual_n_clusters):
        # Get indices of samples in this cluster
        cluster_mask = cluster_labels == cluster_id
        cluster_indices = np.where(cluster_mask)[0]

        if len(cluster_indices) == 0:
            continue

        # Calculate distances to centroid
        centroid = kmeans.cluster_centers_[cluster_id]
        cluster_embeddings = embeddings[cluster_indices]
        distances = np.linalg.norm(cluster_embeddings - centroid, axis=1)

        # Select k closest points
        k = min(samples_per_cluster, len(cluster_indices))
        closest_indices = cluster_indices[np.argsort(distances)[:k]]
        selected_indices.extend(closest_indices)

    logger.info(
        f"MiniBatchKMeans: {n_samples} samples -> "
        f"{actual_n_clusters} clusters -> {len(selected_indices)} selected"
    )

    return embeddings[selected_indices]


async def run_active_learning_iteration(
    session: AsyncSession,
    search_session_id: int,
    ml_project_id: int,
    config: ActiveLearningConfig | None = None,
    selected_tag_ids: set[int] | None = None,
) -> tuple[list[dict], dict[int, dict], list[dict]]:
    """Run one iteration of active learning using Self-Training+SVM with C grid search.

    Always uses Self-Training+SVM classifier with automatic C parameter tuning (grid
    search over [0.1, 1.0, 10.0]) based on F1 score evaluation. Unlabeled embeddings
    are automatically clustered using MiniBatchKMeans (1000 clusters, 2 samples per
    cluster) for efficient training.

    The workflow:
    1. Collect all labeled samples from the search session
    2. For each target tag with sufficient samples (≥10 per class):
       a. Perform C parameter grid search using 70/30 train/test split
       b. Select best C based on F1 score
       c. Retrain on all labeled data with best C
    3. Cluster unlabeled embeddings for Self-Training
    4. Train classifiers with unlabeled data
    5. Score all unlabeled clips and select samples from uncertainty region

    Parameters
    ----------
    session
        SQLAlchemy AsyncSession for database operations.
    search_session_id
        ID of the search session.
    ml_project_id
        ID of the ML project.
    config
        Active learning configuration. Uses defaults if None.
    selected_tag_ids
        Optional set of tag IDs to train classifiers for. If None, all target tags
        are used. If specified, only classifiers for these tags will be trained
        and used for sample selection.

    Returns
    -------
    tuple[list[dict], dict[int, dict], list[dict]]
        - new_samples: list of dicts with clip_id, model_score, source_tag_id,
          sample_type='active_learning'
        - metrics: dict[tag_id, dict] with positive_count, negative_count
        - score_distributions: list of dicts with tag_id, bin_counts, bin_edges,
          positive_count, negative_count, mean_score
    """
    if config is None:
        config = ActiveLearningConfig()

    # Get labeled data for this search session with multi-label support
    # Using search_result_tag junction table for assigned tags
    labeled_query = """
        SELECT
            sr.id as search_result_id,
            sr.clip_id,
            sr.is_negative,
            ce.embedding,
            COALESCE(
                array_agg(srt.tag_id) FILTER (WHERE srt.tag_id IS NOT NULL),
                ARRAY[]::integer[]
            ) as assigned_tag_ids
        FROM search_result sr
        JOIN clip_embedding ce ON sr.clip_id = ce.clip_id
        LEFT JOIN search_result_tag srt ON sr.id = srt.search_result_id
        JOIN ml_project_dataset_scope mpds ON (
            SELECT ml_project_id FROM search_session WHERE id = sr.search_session_id
        ) = mpds.ml_project_id
        JOIN foundation_model_run fmr ON mpds.foundation_model_run_id = fmr.id
        WHERE sr.search_session_id = :search_session_id
          AND sr.is_uncertain = false
          AND sr.is_skipped = false
          AND fmr.model_run_id = ce.model_run_id
        GROUP BY sr.id, sr.clip_id, sr.is_negative, ce.embedding
        HAVING COUNT(srt.tag_id) > 0 OR sr.is_negative = true
    """

    result = await session.execute(
        text(labeled_query),
        {"search_session_id": search_session_id},
    )
    labeled_rows = result.fetchall()

    if not labeled_rows:
        return [], {}, []

    # Get all target tags for this session
    target_tags_query = """
        SELECT tag_id FROM search_session_target_tag
        WHERE search_session_id = :search_session_id
    """
    result = await session.execute(
        text(target_tags_query),
        {"search_session_id": search_session_id},
    )
    target_tag_ids = {row.tag_id for row in result.fetchall()}

    if not target_tag_ids:
        return [], {}, []

    # Filter target_tag_ids if selected_tag_ids is provided
    if selected_tag_ids is not None:
        target_tag_ids = target_tag_ids & selected_tag_ids
        if not target_tag_ids:
            return [], {}, []

    # Collect all labeled samples with their embeddings
    # Structure: list of (embedding, assigned_tag_ids (list), is_negative)
    # Filter out invalid (near-zero) embeddings
    all_samples: list[tuple[np.ndarray, list[int], bool]] = []

    for row in labeled_rows:
        emb = row.embedding
        if isinstance(emb, str):
            emb = json.loads(emb)
        embedding = np.array(emb, dtype=np.float32)

        # Skip invalid embeddings
        if np.linalg.norm(embedding) < MIN_EMBEDDING_NORM:
            continue

        # Convert assigned_tag_ids to list
        assigned_tag_ids_list = list(row.assigned_tag_ids) if row.assigned_tag_ids else []
        all_samples.append((embedding, assigned_tag_ids_list, row.is_negative))

    # Collect labeled clip IDs for excluding from unlabeled data
    labeled_clip_ids = {row.clip_id for row in labeled_rows}

    # Always fetch unlabeled embeddings for Self-Training+SVM
    logger.info("Fetching unlabeled embeddings for Self-Training+SVM")

    unlabeled_clip_data = await get_dataset_clip_embeddings(
        session=session,
        ml_project_id=ml_project_id,
        exclude_clip_ids=labeled_clip_ids,
        max_samples=20000,
    )

    unlabeled_embeddings_array: np.ndarray | None = None
    if unlabeled_clip_data:
        unlabeled_embeddings_list = [emb for _, emb in unlabeled_clip_data]
        unlabeled_embeddings_raw = np.array(unlabeled_embeddings_list)

        # Cluster unlabeled embeddings using MiniBatchKMeans
        logger.info(
            f"Clustering {len(unlabeled_embeddings_raw)} unlabeled embeddings "
            f"into 1000 clusters, keeping 2 samples per cluster"
        )
        unlabeled_embeddings_array = cluster_unlabeled_embeddings(
            unlabeled_embeddings_raw,
            n_clusters=1000,
            samples_per_cluster=2,
        )
        logger.info(
            f"Reduced unlabeled embeddings from {len(unlabeled_embeddings_raw)} "
            f"to {len(unlabeled_embeddings_array)} via clustering"
        )
    else:
        logger.warning("No unlabeled embeddings available")

    # Train one classifier per target tag
    # For each tag:
    #   Positive = samples that have this tag in their assigned_tag_ids
    #   Negative = explicit negatives (N key) + samples assigned to OTHER tags only
    classifiers: dict[int, UnifiedClassifier] = {}
    metrics: dict[int, dict] = {}

    for tag_id in target_tag_ids:
        embeddings_list: list[np.ndarray] = []
        labels_list: list[int] = []
        positive_count = 0
        negative_count = 0

        for embedding, assigned_tag_ids_list, is_negative in all_samples:
            if tag_id in assigned_tag_ids_list and not is_negative:
                # This sample is positive for this tag (multi-label: may have other tags too)
                embeddings_list.append(embedding)
                labels_list.append(1)
                positive_count += 1
            elif is_negative or (assigned_tag_ids_list and tag_id not in assigned_tag_ids_list):
                # This sample is negative for this tag:
                # - Explicitly marked as negative (N key), OR
                # - Assigned to other tag(s) but NOT this tag
                embeddings_list.append(embedding)
                labels_list.append(0)
                negative_count += 1

        # Store metrics regardless of whether we can train
        metrics[tag_id] = {
            "positive_count": positive_count,
            "negative_count": negative_count,
        }

        # Define minimum samples required for grid search
        MIN_SAMPLES_FOR_GRID_SEARCH = 10  # per class

        # Only train if we have both positive and negative samples
        if (positive_count >= MIN_SAMPLES_FOR_GRID_SEARCH and
            negative_count >= MIN_SAMPLES_FOR_GRID_SEARCH):

            embeddings_array = np.array(embeddings_list)
            labels_array = np.array(labels_list)

            # Log training data statistics
            logger.info(
                f"Tag {tag_id} training data: "
                f"positive={positive_count}, negative={negative_count}, "
                f"embedding_shape={embeddings_array.shape}, "
                f"embedding_mean_norm={np.mean([np.linalg.norm(e) for e in embeddings_array]):.4f}"
            )

            # Compute pairwise distances between positive and negative samples
            positive_embeddings = embeddings_array[labels_array == 1]
            negative_embeddings = embeddings_array[labels_array == 0]

            if len(positive_embeddings) > 0 and len(negative_embeddings) > 0:
                # Compute mean intra-class and inter-class distances
                pos_centroid = np.mean(positive_embeddings, axis=0)
                neg_centroid = np.mean(negative_embeddings, axis=0)
                inter_class_dist = np.linalg.norm(pos_centroid - neg_centroid)

                # Compute cosine similarity between centroids
                cos_sim = np.dot(pos_centroid, neg_centroid) / (
                    np.linalg.norm(pos_centroid) * np.linalg.norm(neg_centroid)
                )

                logger.info(
                    f"Tag {tag_id} class separation: "
                    f"inter_class_distance={inter_class_dist:.4f}, "
                    f"centroid_cosine_similarity={cos_sim:.4f}"
                )

            # Perform C parameter grid search
            try:
                best_c, c_scores = perform_c_grid_search(
                    embeddings_array,
                    labels_array,
                    c_values=[0.1, 1.0, 10.0],
                    test_size=0.3,
                )
                logger.info(
                    f"Tag {tag_id} grid search results: {c_scores}, selected C={best_c}"
                )
            except ValueError as e:
                logger.warning(
                    f"Tag {tag_id} grid search failed: {e}. Using default C=1.0"
                )
                best_c = 1.0

            # Train classifier with best C on all labeled data
            classifier = UnifiedClassifier(
                ClassifierType.SELF_TRAINING_SVM,
                custom_params={"C": best_c},
            )

            # Train with unlabeled embeddings
            if unlabeled_embeddings_array is not None:
                logger.info(
                    f"Training Self-Training+SVM for tag {tag_id} with "
                    f"C={best_c}, {len(unlabeled_embeddings_array)} unlabeled samples"
                )
                classifier.fit(
                    embeddings_array,
                    labels_array,
                    unlabeled_embeddings=unlabeled_embeddings_array,
                )
            else:
                logger.info(
                    f"Training Self-Training+SVM for tag {tag_id} with "
                    f"C={best_c}, no unlabeled data"
                )
                classifier.fit(embeddings_array, labels_array)

            classifiers[tag_id] = classifier

        elif positive_count > 0 and negative_count > 0:
            # Insufficient samples for grid search, but train anyway with default C
            logger.warning(
                f"Tag {tag_id} has insufficient samples for grid search "
                f"(positive={positive_count}, negative={negative_count}). "
                f"Using default C=1.0 without grid search."
            )

            embeddings_array = np.array(embeddings_list)
            labels_array = np.array(labels_list)

            classifier = UnifiedClassifier(
                ClassifierType.SELF_TRAINING_SVM,
                custom_params={"C": 1.0},
            )

            if unlabeled_embeddings_array is not None:
                classifier.fit(
                    embeddings_array,
                    labels_array,
                    unlabeled_embeddings=unlabeled_embeddings_array,
                )
            else:
                classifier.fit(embeddings_array, labels_array)

            classifiers[tag_id] = classifier

            # Evaluate on training data to check if training was successful
            train_predictions = classifier.predict_proba(embeddings_array)
            train_pred_labels = (train_predictions >= 0.5).astype(int)
            train_accuracy = np.mean(train_pred_labels == labels_array)

            # Compute training prediction statistics
            pos_train_scores = train_predictions[labels_array == 1]
            neg_train_scores = train_predictions[labels_array == 0]

            # Filter out NaN and infinite values
            pos_train_scores = pos_train_scores[np.isfinite(pos_train_scores)]
            neg_train_scores = neg_train_scores[np.isfinite(neg_train_scores)]

            if len(pos_train_scores) > 0 and len(neg_train_scores) > 0:
                logger.info(
                    f"Tag {tag_id} training evaluation: "
                    f"accuracy={train_accuracy:.4f}, "
                    f"positive_scores: min={np.min(pos_train_scores):.4f}, "
                    f"max={np.max(pos_train_scores):.4f}, mean={np.mean(pos_train_scores):.4f}, "
                    f"negative_scores: min={np.min(neg_train_scores):.4f}, "
                    f"max={np.max(neg_train_scores):.4f}, mean={np.mean(neg_train_scores):.4f}"
                )
            else:
                logger.warning(
                    f"Tag {tag_id} training evaluation: "
                    f"accuracy={train_accuracy:.4f}, "
                    f"positive_scores: {len(pos_train_scores)} valid samples, "
                    f"negative_scores: {len(neg_train_scores)} valid samples"
                )

            # Store training scores in metrics for histogram overlay
            # Convert to list and ensure no NaN/inf values
            metrics[tag_id]["training_positive_scores"] = pos_train_scores.tolist()
            metrics[tag_id]["training_negative_scores"] = neg_train_scores.tolist()

    # Get unlabeled clip embeddings
    existing_clip_ids_query = """
        SELECT clip_id FROM search_result
        WHERE search_session_id = :search_session_id
    """
    result = await session.execute(
        text(existing_clip_ids_query),
        {"search_session_id": search_session_id},
    )
    existing_clip_ids = {row.clip_id for row in result.fetchall()}

    unlabeled_clips = await get_dataset_clip_embeddings(
        session=session,
        ml_project_id=ml_project_id,
        exclude_clip_ids=existing_clip_ids,
    )

    logger.info(
        f"Unlabeled clips: n={len(unlabeled_clips)}, "
        f"excluded_clips={len(existing_clip_ids)}"
    )

    # Compute model scores for each tag and aggregate
    new_samples: list[dict] = []
    uncertain_candidates: list[tuple[int, float, int]] = []  # (clip_id, score, tag_id)
    score_distributions: list[dict] = []

    # Always compute score distributions for visualization, even if no unlabeled clips or no classifiers
    if unlabeled_clips and classifiers:
        logger.info(f"Computing scores for {len(unlabeled_clips)} unlabeled clips")
        unlabeled_clip_ids = np.array([uc[0] for uc in unlabeled_clips])
        unlabeled_embeddings = np.array([uc[1] for uc in unlabeled_clips])

        # Log unlabeled embeddings statistics
        unlabeled_mean_norm = np.mean([np.linalg.norm(e) for e in unlabeled_embeddings])
        logger.info(
            f"Unlabeled embeddings: shape={unlabeled_embeddings.shape}, "
            f"mean_norm={unlabeled_mean_norm:.4f}"
        )

        for tag_id, classifier in classifiers.items():
            scores = classifier.predict_proba(unlabeled_embeddings)

            # Filter out NaN and infinite values from scores
            valid_mask = np.isfinite(scores)
            valid_scores = scores[valid_mask]
            n_invalid = len(scores) - len(valid_scores)

            if n_invalid > 0:
                logger.warning(
                    f"Tag {tag_id}: {n_invalid} invalid (NaN/inf) scores filtered out"
                )

            # Log score distribution statistics for debugging (use valid scores only)
            if len(valid_scores) > 0:
                logger.info(
                    f"Tag {tag_id} score distribution: "
                    f"n_samples={len(valid_scores)}, "
                    f"min={np.min(valid_scores):.4f}, "
                    f"max={np.max(valid_scores):.4f}, "
                    f"mean={np.mean(valid_scores):.4f}, "
                    f"std={np.std(valid_scores):.4f}, "
                    f"median={np.median(valid_scores):.4f}, "
                    f"positive_count={metrics[tag_id]['positive_count']}, "
                    f"negative_count={metrics[tag_id]['negative_count']}"
                )
            else:
                logger.warning(
                    f"Tag {tag_id}: No valid scores available, "
                    f"positive_count={metrics[tag_id]['positive_count']}, "
                    f"negative_count={metrics[tag_id]['negative_count']}"
                )

            # Compute score distribution for this tag (use valid scores only)
            bin_edges = np.linspace(0, 1, 21).tolist()  # 20 bins
            bin_counts, _ = np.histogram(valid_scores, bins=bin_edges)

            # Log histogram bins with counts > 0 for debugging
            non_zero_bins = [(i, bin_counts[i]) for i in range(len(bin_counts)) if bin_counts[i] > 0]
            logger.info(
                f"Tag {tag_id} non-zero bins (bin_index, count): {non_zero_bins}"
            )

            score_distributions.append({
                "tag_id": tag_id,
                "bin_counts": bin_counts.tolist(),
                "bin_edges": bin_edges,
                "positive_count": metrics[tag_id]["positive_count"],
                "negative_count": metrics[tag_id]["negative_count"],
                "mean_score": float(np.mean(valid_scores)) if len(valid_scores) > 0 else 0.0,
                "training_positive_scores": metrics[tag_id].get("training_positive_scores", []),
                "training_negative_scores": metrics[tag_id].get("training_negative_scores", []),
            })

            # Find samples in uncertainty region (only consider valid scores)
            valid_indices = np.where(valid_mask)[0]
            for idx, score in zip(valid_indices, valid_scores):
                if config.uncertainty_low <= score <= config.uncertainty_high:
                    clip_id = int(unlabeled_clip_ids[idx])
                    uncertain_candidates.append((clip_id, float(score), tag_id))

    # Create distributions for tags without classifiers or without unlabeled clips
    # This ensures all target tags have distribution data for visualization
    for tag_id in target_tag_ids:
        # Skip if already added (has classifier and unlabeled data)
        if any(d["tag_id"] == tag_id for d in score_distributions):
            continue

        bin_edges = np.linspace(0, 1, 21).tolist()  # 20 bins
        bin_counts = [0] * 20  # Empty bins

        score_distributions.append({
            "tag_id": tag_id,
            "bin_counts": bin_counts,
            "bin_edges": bin_edges,
            "positive_count": metrics.get(tag_id, {}).get("positive_count", 0),
            "negative_count": metrics.get(tag_id, {}).get("negative_count", 0),
            "mean_score": 0.0,
            "training_positive_scores": [],
            "training_negative_scores": [],
        })

    # Remove duplicates (same clip might be uncertain for multiple tags)
    seen_clips: set[int] = set()
    unique_candidates: list[tuple[int, float, int]] = []
    for clip_id, score, tag_id in uncertain_candidates:
        if clip_id not in seen_clips:
            unique_candidates.append((clip_id, score, tag_id))
            seen_clips.add(clip_id)

    # Uniform sampling from uncertainty region instead of prioritizing 0.5
    # This ensures diverse samples across the entire uncertainty range
    logger.info(
        f"Selecting {config.samples_per_iteration} samples from "
        f"{len(unique_candidates)} candidates via uniform sampling"
    )

    # Randomly sample from candidates to get uniform distribution
    if len(unique_candidates) > config.samples_per_iteration:
        import random
        selected_candidates = random.sample(unique_candidates, config.samples_per_iteration)
    else:
        selected_candidates = unique_candidates

    for clip_id, score, tag_id in selected_candidates:
        new_samples.append({
            "clip_id": clip_id,
            "model_score": score,
            "source_tag_id": tag_id,
            "sample_type": SampleType.ACTIVE_LEARNING.value,
        })

    return new_samples, metrics, score_distributions
