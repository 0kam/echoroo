"""Seed sampling algorithms for bioacoustic species classifier training.

Provides functions to select diverse, representative training samples from audio
embeddings (1536-dim Perch vectors). Sampling is split into three categories:

- easy_positive: highest-similarity candidates (confident positives)
- boundary:      mid-range similarity candidates (decision-boundary examples)
- others:        diverse low-similarity candidates via farthest-first selection

All functions are pure (no DB, no async). Callers are responsible for fetching
embeddings from the database before invoking these functions.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from scipy.spatial.distance import cdist


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SeedSamplingConfig:
    """Configuration for the three-category seed sampling strategy.

    Attributes
    ----------
    easy_positive_k:
        Number of top-similarity candidates to select as easy positives.
    boundary_n:
        Size of the boundary candidate pool (ranked just below easy positives).
    boundary_m:
        Number of samples to randomly draw from the boundary pool.
    others_p:
        Number of diverse "others" samples selected via farthest-first.
    """

    easy_positive_k: int = 5
    boundary_n: int = 200
    boundary_m: int = 10
    others_p: int = 20


@dataclass
class SeedSample:
    """A single selected seed sample with its metadata.

    Attributes
    ----------
    embedding_id:
        UUID (as string) of the selected embedding row.
    recording_id:
        UUID (as string) of the recording that contains the embedding.
    sample_type:
        Category of this sample: 'easy_positive', 'boundary', or 'others'.
    similarity:
        Max cosine similarity of this embedding against all query vectors.
    """

    embedding_id: str
    recording_id: str
    sample_type: str  # 'easy_positive' | 'boundary' | 'others'
    similarity: float


# ---------------------------------------------------------------------------
# Core algorithm: farthest-first selection
# ---------------------------------------------------------------------------


def farthest_first_selection(
    candidates: np.ndarray,
    seeds: np.ndarray,
    k: int,
) -> np.ndarray:
    """Select k indices from candidates that maximise min-distance to the seed pool.

    Uses a greedy farthest-first (coreset) algorithm:
    1. Compute distances from every candidate to every seed.
    2. Each iteration picks the candidate whose minimum distance to the
       current pool (seeds + already-selected points) is largest.
    3. The newly picked point is added to the pool and the min-distance
       array is updated.

    Parameters
    ----------
    candidates:
        Array of shape (N, D) — embedding vectors to select from.
    seeds:
        Array of shape (M, D) — existing reference points that selected
        points should be diverse from.
    k:
        Number of points to select.

    Returns
    -------
    np.ndarray
        1-D integer array of length min(k, N) with indices into ``candidates``.
    """
    n = len(candidates)
    if n == 0 or k <= 0:
        return np.array([], dtype=np.intp)

    k = min(k, n)

    # Compute initial min-distance from each candidate to the seed pool.
    # cdist returns shape (N, M); we take the row-wise minimum.
    if len(seeds) > 0:
        dist_to_seeds = cdist(candidates, seeds, metric="cosine")  # (N, M)
        min_dist = dist_to_seeds.min(axis=1)  # (N,)
    else:
        # No seeds — all candidates are equidistant; break ties arbitrarily.
        min_dist = np.ones(n, dtype=np.float64)

    selected: list[int] = []

    for _ in range(k):
        # Pick the candidate farthest from the current pool.
        idx = int(np.argmax(min_dist))
        selected.append(idx)

        if len(selected) < k:
            # Update min distances using the newly selected point.
            new_dists = cdist(candidates, candidates[idx : idx + 1], metric="cosine").ravel()  # (N,)
            min_dist = np.minimum(min_dist, new_dists)
            # Exclude the selected point from future picks.
            min_dist[idx] = -np.inf

    return np.array(selected, dtype=np.intp)


# ---------------------------------------------------------------------------
# Max cosine similarity helper
# ---------------------------------------------------------------------------


def _max_cosine_similarity(
    query_vectors: np.ndarray,
    candidate_vectors: np.ndarray,
) -> np.ndarray:
    """Return max cosine similarity for each candidate across all query vectors.

    Parameters
    ----------
    query_vectors:
        Array of shape (Q, D).
    candidate_vectors:
        Array of shape (N, D).

    Returns
    -------
    np.ndarray
        Array of shape (N,) with values in [-1, 1].
    """
    # cdist with cosine gives cosine *distance* = 1 - cosine_similarity.
    dist = cdist(candidate_vectors, query_vectors, metric="cosine")  # (N, Q)
    # Convert distance → similarity, then take per-row maximum.
    return 1.0 - dist.min(axis=1)  # max similarity = 1 - min distance


# ---------------------------------------------------------------------------
# High-level orchestrator
# ---------------------------------------------------------------------------


def compute_seed_samples(
    query_vectors: np.ndarray,
    candidate_ids: np.ndarray,
    candidate_vectors: np.ndarray,
    candidate_recording_ids: np.ndarray,
    config: SeedSamplingConfig,
) -> list[SeedSample]:
    """Orchestrate three-category seed sampling on pre-fetched embedding data.

    Categories
    ----------
    easy_positive:
        The top ``config.easy_positive_k`` candidates by cosine similarity to
        the query vectors.
    boundary:
        From rank ``easy_positive_k + 1`` to ``easy_positive_k + boundary_n``,
        randomly sample ``boundary_m`` candidates.
    others:
        From the remaining candidates, sub-sample at most 1 000 points via
        farthest-first (using the full query set as seeds), then select
        ``others_p`` further points via farthest-first from that pool.

    Parameters
    ----------
    query_vectors:
        Array of shape (Q, D) — reference embeddings for the target species.
    candidate_ids:
        1-D array of length N — UUID strings (or any hashable ID) for each
        embedding row.
    candidate_vectors:
        Array of shape (N, D) — embedding vectors corresponding to
        ``candidate_ids``.
    candidate_recording_ids:
        1-D array of length N — recording UUID strings for each embedding.
    config:
        Sampling hyper-parameters.

    Returns
    -------
    list[SeedSample]
        Flat list of selected samples across all three categories.
        May be shorter than requested if there are fewer candidates than
        the sum of ``easy_positive_k + boundary_m + others_p``.
    """
    n = len(candidate_ids)
    if n == 0 or len(query_vectors) == 0:
        return []

    # ------------------------------------------------------------------
    # Step 1 — compute max cosine similarity for every candidate
    # ------------------------------------------------------------------
    similarities = _max_cosine_similarity(query_vectors, candidate_vectors)  # (N,)

    # Sort by similarity descending; ranked_indices[0] = highest-similarity
    ranked_indices = np.argsort(-similarities)

    # ------------------------------------------------------------------
    # Step 2 — easy positives (top-k)
    # ------------------------------------------------------------------
    ep_k = min(config.easy_positive_k, n)
    ep_indices = ranked_indices[:ep_k]

    # ------------------------------------------------------------------
    # Step 3 — boundary (next boundary_n, randomly pick boundary_m)
    # ------------------------------------------------------------------
    boundary_start = ep_k
    boundary_end = min(ep_k + config.boundary_n, n)
    boundary_pool = ranked_indices[boundary_start:boundary_end]

    b_m = min(config.boundary_m, len(boundary_pool))
    if b_m > 0:
        rng = np.random.default_rng()
        boundary_indices = rng.choice(boundary_pool, size=b_m, replace=False)
    else:
        boundary_indices = np.array([], dtype=np.intp)

    # ------------------------------------------------------------------
    # Step 4 — others (farthest-first from remaining candidates)
    # ------------------------------------------------------------------
    others_pool_indices = ranked_indices[boundary_end:]

    samples: list[SeedSample] = []

    # Build easy-positive results first
    for idx in ep_indices:
        samples.append(
            SeedSample(
                embedding_id=str(candidate_ids[idx]),
                recording_id=str(candidate_recording_ids[idx]),
                sample_type="easy_positive",
                similarity=float(similarities[idx]),
            )
        )

    # Boundary results
    for idx in boundary_indices:
        samples.append(
            SeedSample(
                embedding_id=str(candidate_ids[idx]),
                recording_id=str(candidate_recording_ids[idx]),
                sample_type="boundary",
                similarity=float(similarities[idx]),
            )
        )

    # Others — sub-sample pool to at most 1 000 before farthest-first
    o_p = config.others_p
    if len(others_pool_indices) > 0 and o_p > 0:
        max_pool = 1000
        if len(others_pool_indices) > max_pool:
            rng = np.random.default_rng()
            sub_pool = rng.choice(others_pool_indices, size=max_pool, replace=False)
        else:
            sub_pool = others_pool_indices

        others_candidates = candidate_vectors[sub_pool]
        others_selected_local = farthest_first_selection(
            candidates=others_candidates,
            seeds=query_vectors,
            k=o_p,
        )
        others_global_indices = sub_pool[others_selected_local]

        for idx in others_global_indices:
            samples.append(
                SeedSample(
                    embedding_id=str(candidate_ids[idx]),
                    recording_id=str(candidate_recording_ids[idx]),
                    sample_type="others",
                    similarity=float(similarities[idx]),
                )
            )

    return samples
