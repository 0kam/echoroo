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
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import Normalizer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "ActiveLearningConfig",
    "SigmoidClassifier",
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
) -> list[tuple[int, np.ndarray]]:
    """Get all clip embeddings from ML project's dataset scopes.

    Retrieves embeddings for all clips in datasets associated with the
    ML project through its dataset scopes.

    Parameters
    ----------
    session
        SQLAlchemy AsyncSession for database operations.
    ml_project_id
        ID of the ML project.
    exclude_clip_ids
        Optional set of clip IDs to exclude from results.

    Returns
    -------
    list[tuple[int, np.ndarray]]
        List of (clip_id, embedding) tuples.
    """
    # Query to get embeddings from all dataset scopes
    query = """
        SELECT DISTINCT ON (ce.clip_id)
            ce.clip_id,
            ce.embedding
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

    params: dict = {"ml_project_id": ml_project_id}

    if exclude_clip_ids:
        query += " AND ce.clip_id != ALL(:exclude_clip_ids)"
        params["exclude_clip_ids"] = list(exclude_clip_ids)

    query += " ORDER BY ce.clip_id"

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
) -> list[dict]:
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
    list[dict]
        List of dicts with:
        - clip_id: int
        - similarity: float
        - sample_type: 'easy_positive' | 'boundary' | 'others'
        - source_tag_id: int | None
    """
    if config is None:
        config = ActiveLearningConfig()

    # Get all clip embeddings from dataset scopes
    clip_embeddings = await get_dataset_clip_embeddings(
        session=session,
        ml_project_id=ml_project_id,
    )

    if not clip_embeddings:
        return []

    clip_ids = np.array([ce[0] for ce in clip_embeddings])
    embeddings = np.array([ce[1] for ce in clip_embeddings])

    results: list[dict] = []
    selected_clip_ids: set[int] = set()
    all_reference_embeddings: list[np.ndarray] = []

    # Track best rank for each clip across all tags (for Others filtering)
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
        for idx in sorted_indices:
            if ep_count >= config.easy_positive_k:
                break
            clip_id = int(clip_ids[idx])
            if clip_id not in selected_clip_ids:
                results.append({
                    "clip_id": clip_id,
                    "similarity": float(similarities[idx]),
                    "sample_type": "easy_positive",
                    "source_tag_id": tag_id,
                })
                selected_clip_ids.add(clip_id)
                ep_count += 1

        # Select Boundary samples (random from top k+1 to k+n)
        boundary_start = config.easy_positive_k
        boundary_end = boundary_start + config.boundary_n

        # Get candidate indices for boundary
        boundary_candidates = []
        for i in range(boundary_start, min(boundary_end, len(sorted_indices))):
            idx = sorted_indices[i]
            clip_id = int(clip_ids[idx])
            if clip_id not in selected_clip_ids:
                boundary_candidates.append((idx, clip_id, float(similarities[idx])))

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
                idx, clip_id, sim = boundary_candidates[i]
                results.append({
                    "clip_id": clip_id,
                    "similarity": sim,
                    "sample_type": "boundary",
                    "source_tag_id": tag_id,
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

            results.append({
                "clip_id": clip_id,
                "similarity": float(sim[0]) if len(sim) > 0 else 0.0,
                "sample_type": "others",
                "source_tag_id": None,
            })
            selected_clip_ids.add(clip_id)

    return results


async def run_active_learning_iteration(
    session: AsyncSession,
    search_session_id: int,
    ml_project_id: int,
    config: ActiveLearningConfig | None = None,
    selected_tag_ids: set[int] | None = None,
) -> tuple[list[dict], dict[int, dict], list[dict]]:
    """Run one iteration of active learning.

    Trains classifiers on labeled data and selects new samples from
    the uncertainty region (between uncertainty_low and uncertainty_high).

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

    # Get labeled data for this search session
    labeled_query = """
        SELECT
            sr.clip_id,
            sr.assigned_tag_id,
            sr.is_negative,
            ce.embedding
        FROM search_result sr
        JOIN clip_embedding ce ON sr.clip_id = ce.clip_id
        JOIN ml_project_dataset_scope mpds ON (
            SELECT ml_project_id FROM search_session WHERE id = sr.search_session_id
        ) = mpds.ml_project_id
        JOIN foundation_model_run fmr ON mpds.foundation_model_run_id = fmr.id
        WHERE sr.search_session_id = :search_session_id
          AND (sr.assigned_tag_id IS NOT NULL OR sr.is_negative = true)
          AND sr.is_uncertain = false
          AND sr.is_skipped = false
          AND fmr.model_run_id = ce.model_run_id
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
    # Structure: list of (embedding, assigned_tag_id or None, is_negative)
    # Filter out invalid (near-zero) embeddings
    all_samples: list[tuple[np.ndarray, int | None, bool]] = []

    for row in labeled_rows:
        emb = row.embedding
        if isinstance(emb, str):
            emb = json.loads(emb)
        embedding = np.array(emb, dtype=np.float32)

        # Skip invalid embeddings
        if np.linalg.norm(embedding) < MIN_EMBEDDING_NORM:
            continue

        all_samples.append((embedding, row.assigned_tag_id, row.is_negative))

    # Train one classifier per target tag
    # For each tag:
    #   Positive = samples assigned to this tag
    #   Negative = explicit negatives (N key) + samples assigned to OTHER tags
    classifiers: dict[int, SigmoidClassifier] = {}
    metrics: dict[int, dict] = {}

    for tag_id in target_tag_ids:
        embeddings_list: list[np.ndarray] = []
        labels_list: list[int] = []
        positive_count = 0
        negative_count = 0

        for embedding, assigned_tag_id, is_negative in all_samples:
            if assigned_tag_id == tag_id and not is_negative:
                # This sample is positive for this tag
                embeddings_list.append(embedding)
                labels_list.append(1)
                positive_count += 1
            elif is_negative or (assigned_tag_id is not None and assigned_tag_id != tag_id):
                # This sample is negative for this tag:
                # - Explicitly marked as negative (N key), OR
                # - Assigned to a different tag
                embeddings_list.append(embedding)
                labels_list.append(0)
                negative_count += 1

        metrics[tag_id] = {
            "positive_count": positive_count,
            "negative_count": negative_count,
        }

        # Only train if we have both positive and negative samples
        if positive_count > 0 and negative_count > 0:
            embeddings_array = np.array(embeddings_list)
            labels_array = np.array(labels_list)

            classifier = SigmoidClassifier()
            classifier.fit(embeddings_array, labels_array)
            classifiers[tag_id] = classifier

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

    if not unlabeled_clips:
        return [], metrics, []

    unlabeled_clip_ids = np.array([uc[0] for uc in unlabeled_clips])
    unlabeled_embeddings = np.array([uc[1] for uc in unlabeled_clips])

    # Compute model scores for each tag and aggregate
    new_samples: list[dict] = []
    uncertain_candidates: list[tuple[int, float, int]] = []  # (clip_id, score, tag_id)
    score_distributions: list[dict] = []

    for tag_id, classifier in classifiers.items():
        scores = classifier.predict_proba(unlabeled_embeddings)

        # Compute score distribution for this tag
        bin_edges = np.linspace(0, 1, 21).tolist()  # 20 bins
        bin_counts, _ = np.histogram(scores, bins=bin_edges)

        score_distributions.append({
            "tag_id": tag_id,
            "bin_counts": bin_counts.tolist(),
            "bin_edges": bin_edges,
            "positive_count": metrics[tag_id]["positive_count"],
            "negative_count": metrics[tag_id]["negative_count"],
            "mean_score": float(np.mean(scores)) if len(scores) > 0 else 0.0,
        })

        # Find samples in uncertainty region
        for i, score in enumerate(scores):
            if config.uncertainty_low <= score <= config.uncertainty_high:
                clip_id = int(unlabeled_clip_ids[i])
                uncertain_candidates.append((clip_id, float(score), tag_id))

    # Remove duplicates (same clip might be uncertain for multiple tags)
    seen_clips: set[int] = set()
    unique_candidates: list[tuple[int, float, int]] = []
    for clip_id, score, tag_id in uncertain_candidates:
        if clip_id not in seen_clips:
            unique_candidates.append((clip_id, score, tag_id))
            seen_clips.add(clip_id)

    # Sort by uncertainty (closest to 0.5 is most uncertain)
    unique_candidates.sort(key=lambda x: abs(x[1] - 0.5))

    # Select top samples_per_iteration samples
    for clip_id, score, tag_id in unique_candidates[: config.samples_per_iteration]:
        new_samples.append({
            "clip_id": clip_id,
            "model_score": score,
            "source_tag_id": tag_id,
            "sample_type": "active_learning",
        })

    return new_samples, metrics, score_distributions
