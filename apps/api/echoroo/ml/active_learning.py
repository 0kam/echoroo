"""Active learning utilities for SVM-based species classifier training.

Provides a margin-sampling strategy that selects diverse, uncertain samples
from unlabeled audio embeddings for human review and labeling.

Workflow:
1. Score unlabeled embeddings with a trained SVM via ``decision_function``.
2. Pass batches to ``MarginTracker.update()`` to maintain a rolling top-k of
   samples closest to the decision boundary.
3. Call ``MarginTracker.get()`` to retrieve the final candidate set.
4. Pass candidates to ``select_al_samples()`` to apply farthest-first
   diversification and obtain the final list of ``ALSample`` records.

All functions are pure (no DB, no async). Callers are responsible for fetching
embeddings from the database and running SVM inference before invoking these
functions.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from echoroo.ml.sampling import farthest_first_selection

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ALSample:
    """A single active-learning candidate selected for human review.

    Attributes
    ----------
    embedding_id:
        UUID (as string) of the selected embedding row.
    decision_distance:
        Signed SVM ``decision_function`` distance to the hyperplane.
        Values near zero indicate high uncertainty.
    sample_type:
        Category of this sample. For legacy single-lane AL this defaults to
        ``"active_learning"``. For multi-lane AL this is one of
        ``"easy_positive"``, ``"boundary"``, or ``"others"``.
    """

    embedding_id: str
    decision_distance: float
    sample_type: str = "active_learning"


@dataclass
class ALMultilaneSamplingConfig:
    """Configuration for the three-lane active-learning sampling strategy.

    Mirrors the seed round structure but uses SVM decision distances instead
    of cosine similarities to score candidates.

    Attributes
    ----------
    easy_positive_k:
        Number of most-confident positive samples (highest signed
        ``decision_distance``) to include.
    boundary_m:
        Number of most-uncertain samples (smallest
        ``|decision_distance|``) to include.
    others_p:
        Number of diverse samples selected via farthest-first from the
        remaining candidates.
    candidate_pool_size:
        Size of the expanded candidate pool collected from scoring before
        lanes are split.  Should be large enough to cover all three lanes
        while still fitting comfortably in memory.
    """

    easy_positive_k: int = 5
    boundary_m: int = 10
    others_p: int = 5
    candidate_pool_size: int = 200


# ---------------------------------------------------------------------------
# MarginTracker
# ---------------------------------------------------------------------------


class MarginTracker:
    """Track top-k samples closest to SVM decision boundary.

    Designed for chunked processing: call ``update()`` with each batch of
    scored embeddings, then call ``get()`` once to retrieve the final
    candidates.  Internal state is pruned whenever it grows beyond ``2k``
    entries to keep memory usage bounded regardless of corpus size.

    Parameters
    ----------
    k:
        Number of candidates to maintain (and return from ``get()``).
    mode:
        Ranking strategy used during pruning:

        * ``"uncertain"`` (default): keep entries with the smallest
          ``|decision_distance|`` (closest to the hyperplane — most
          uncertain).
        * ``"top_positive"``: keep entries with the largest signed
          ``decision_distance`` (most-confident positive predictions).
          Used by the multi-lane AL strategy to surface easy-positive
          candidates.
    """

    def __init__(self, k: int, mode: str = "uncertain") -> None:
        if mode not in {"uncertain", "top_positive"}:
            raise ValueError(
                f"MarginTracker mode must be 'uncertain' or 'top_positive', got {mode!r}"
            )
        self.k = k
        self.mode = mode
        self._ids: list[str] = []
        self._distances: list[float] = []
        self._vectors: list[np.ndarray] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        ids: list[str],
        distances: np.ndarray,
        vectors: np.ndarray,
    ) -> None:
        """Add a batch of scored embeddings.

        Parameters
        ----------
        ids:
            List of embedding UUID strings for this batch.
        distances:
            1-D float array of signed ``decision_function`` values, one per
            sample in ``ids``.
        vectors:
            2-D float array of shape ``(len(ids), D)`` — the raw embedding
            vectors, required for subsequent farthest-first diversification.
        """
        self._ids.extend(ids)
        self._distances.extend(distances.tolist())
        # Store copies (not views) so the caller's chunk buffer can be GC'd.
        self._vectors.extend([v.copy() for v in vectors])

        # Prune eagerly once the buffer exceeds 2k to bound memory usage.
        if len(self._ids) > self.k * 2:
            self._prune()

    def get(self) -> tuple[list[str], np.ndarray, np.ndarray]:
        """Return the top-k candidates closest to the decision boundary.

        Returns
        -------
        tuple of:
            ids : list[str]
                Embedding UUID strings.
            distances : np.ndarray of shape (k,)
                Signed decision-function distances.
            vectors : np.ndarray of shape (k, D)
                Embedding vectors; empty array ``(0, 0)`` when there are no
                candidates.
        """
        self._prune()
        vectors_arr = (
            np.vstack(self._vectors) if self._vectors else np.empty((0, 0))
        )
        return self._ids, np.array(self._distances), vectors_arr

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prune(self) -> None:
        """Retain only the top-k entries according to the configured ``mode``.

        * ``mode == "uncertain"``: keep entries with the smallest
          ``|decision_function|`` value (closest to the hyperplane).
        * ``mode == "top_positive"``: keep entries with the largest
          signed ``decision_function`` value (most-confident positive).
        """
        if not self._ids:
            return

        distances_arr = np.array(self._distances)
        k_actual = min(self.k, len(self._ids))

        if self.mode == "top_positive":
            # argsort ascending; negate to get descending (largest first).
            top_idx = np.argsort(-distances_arr)[:k_actual]
        else:
            # Default: most-uncertain first.
            top_idx = np.argsort(np.abs(distances_arr))[:k_actual]

        self._ids = [self._ids[i] for i in top_idx]
        self._distances = [self._distances[i] for i in top_idx]
        self._vectors = [self._vectors[i] for i in top_idx]


# ---------------------------------------------------------------------------
# Sample selection
# ---------------------------------------------------------------------------


def select_al_samples(
    candidate_ids: list[str],
    candidate_distances: np.ndarray,
    candidate_vectors: np.ndarray,
    labeled_vectors: np.ndarray,
    n_samples: int = 20,
    oversample: int = 3,
) -> list[ALSample]:
    """Select diverse samples near the SVM decision boundary.

    Combines margin sampling (uncertainty) with farthest-first selection
    (diversity) to produce a set of active-learning candidates that are both
    informative and representative of under-explored regions of the embedding
    space.

    Algorithm
    ---------
    1. Sort ``candidate_ids`` by ascending ``|decision_distance|`` (closest to
       hyperplane = most uncertain).
    2. Take the top ``n_samples * oversample`` candidates as the uncertainty
       pool.
    3. Apply ``farthest_first_selection`` over the pool, using
       ``labeled_vectors`` as diversity seeds, to select ``n_samples`` points
       that are maximally spread out relative to already-labeled data.

    Parameters
    ----------
    candidate_ids:
        UUID strings for all margin candidates (output of
        ``MarginTracker.get()``).
    candidate_distances:
        1-D array of signed ``decision_function`` distances, one per entry in
        ``candidate_ids``.
    candidate_vectors:
        2-D array of shape ``(len(candidate_ids), D)`` — embedding vectors.
    labeled_vectors:
        2-D array of shape ``(L, D)`` — embedding vectors for already-labeled
        samples, used as diversity seeds.  May be empty (shape ``(0, D)``).
    n_samples:
        Number of active-learning samples to return.
    oversample:
        Oversampling factor applied to the uncertainty pool before diversity
        selection.  A higher value lets farthest-first explore a wider
        uncertainty region at the cost of slightly higher compute.

    Returns
    -------
    list[ALSample]
        Selected samples ordered by farthest-first traversal order (the first
        element is always the point farthest from ``labeled_vectors``).
        May contain fewer than ``n_samples`` entries if the candidate pool is
        small.
    """
    n = len(candidate_ids)
    if n == 0 or n_samples <= 0:
        return []

    # Step 1 — rank candidates by uncertainty (smallest |distance| first).
    abs_distances = np.abs(candidate_distances)
    pool_size = min(n_samples * oversample, n)
    pool_indices = np.argsort(abs_distances)[:pool_size]

    pool_vectors = candidate_vectors[pool_indices]  # (pool_size, D)

    # Step 2 — farthest-first diversification within the uncertainty pool.
    n_select = min(n_samples, pool_size)
    selected_local = farthest_first_selection(
        candidates=pool_vectors,
        seeds=labeled_vectors,
        k=n_select,
    )

    # Step 3 — map local pool indices back to original candidate indices.
    results: list[ALSample] = []
    for local_idx in selected_local:
        global_idx = int(pool_indices[local_idx])
        results.append(
            ALSample(
                embedding_id=candidate_ids[global_idx],
                decision_distance=float(candidate_distances[global_idx]),
            )
        )

    return results


def select_al_samples_multilane(
    candidate_ids: list[str],
    candidate_distances: np.ndarray,
    candidate_vectors: np.ndarray,
    labeled_vectors: np.ndarray,
    config: ALMultilaneSamplingConfig,
) -> list[ALSample]:
    """Select active-learning samples across three lanes (easy_positive / boundary / others).

    Mirrors the seed round's 3-lane layout but uses SVM decision distances
    instead of cosine similarity.

    Algorithm
    ---------
    1. Sort candidates by signed ``decision_distance`` descending.  Take the
       top ``config.easy_positive_k`` as the ``"easy_positive"`` lane
       (the model is most confidently positive about these).
    2. From the remaining candidates, sort by ``|decision_distance|``
       ascending and take the top ``config.boundary_m`` as the
       ``"boundary"`` lane (the model is most uncertain about these).
    3. From the still-remaining candidates, apply
       ``farthest_first_selection`` seeded by ``labeled_vectors`` together
       with the already-selected easy-positive and boundary vectors, and
       pick ``config.others_p`` as the ``"others"`` lane (diverse
       exploration).

    Parameters
    ----------
    candidate_ids:
        UUID strings for every candidate in the merged scoring pool.
    candidate_distances:
        1-D array of signed ``decision_function`` distances for each
        candidate.
    candidate_vectors:
        2-D array of shape ``(len(candidate_ids), D)`` — embedding vectors.
    labeled_vectors:
        2-D array of shape ``(L, D)`` — already-labeled embedding vectors,
        used as farthest-first seeds for the ``"others"`` lane.
        May be empty (shape ``(0, D)``).
    config:
        Hyper-parameters controlling per-lane sample counts.

    Returns
    -------
    list[ALSample]
        Samples ordered by lane (easy_positive → boundary → others).  Each
        sample carries its ``sample_type`` label.  May contain fewer than
        ``easy_positive_k + boundary_m + others_p`` entries if the
        candidate pool is small.
    """
    n = len(candidate_ids)
    if n == 0:
        return []

    # Step 1 — easy positives: top-k by signed decision distance descending.
    sorted_desc = np.argsort(-candidate_distances)
    ep_k = min(config.easy_positive_k, n)
    ep_indices = sorted_desc[:ep_k].tolist()
    ep_set = set(ep_indices)

    # Step 2 — boundary: smallest |decision_distance| from the remainder.
    remaining_after_ep = [i for i in range(n) if i not in ep_set]
    remaining_after_ep_arr = np.array(remaining_after_ep, dtype=np.intp)
    if len(remaining_after_ep_arr) > 0:
        abs_remaining = np.abs(candidate_distances[remaining_after_ep_arr])
        b_m = min(config.boundary_m, len(remaining_after_ep_arr))
        boundary_local = np.argsort(abs_remaining)[:b_m]
        boundary_indices = remaining_after_ep_arr[boundary_local].tolist()
    else:
        boundary_indices = []
    selected_set = ep_set | set(boundary_indices)

    # Step 3 — others: farthest-first from the still-remaining candidates,
    # seeded by labeled vectors + already-selected easy-positive/boundary.
    others_pool_global = np.array(
        [i for i in range(n) if i not in selected_set], dtype=np.intp
    )

    others_indices: list[int] = []
    if len(others_pool_global) > 0 and config.others_p > 0:
        # Build the combined seed set: labeled vectors plus already-picked
        # easy-positive and boundary vectors, so farthest-first avoids
        # clustering near those regions.
        selected_vectors_list: list[np.ndarray] = []
        if labeled_vectors is not None and len(labeled_vectors) > 0:
            selected_vectors_list.append(labeled_vectors)
        if ep_indices:
            selected_vectors_list.append(candidate_vectors[ep_indices])
        if boundary_indices:
            selected_vectors_list.append(candidate_vectors[boundary_indices])

        if selected_vectors_list:
            seeds = np.vstack(selected_vectors_list)
        else:
            # No seeds available — farthest-first falls back to uniform.
            seeds = np.empty((0, candidate_vectors.shape[1]))

        others_candidates = candidate_vectors[others_pool_global]
        others_local = farthest_first_selection(
            candidates=others_candidates,
            seeds=seeds,
            k=config.others_p,
        )
        others_indices = others_pool_global[others_local].tolist()

    # Assemble results in lane order: easy_positive → boundary → others.
    results: list[ALSample] = []
    for idx in ep_indices:
        results.append(
            ALSample(
                embedding_id=candidate_ids[idx],
                decision_distance=float(candidate_distances[idx]),
                sample_type="easy_positive",
            )
        )
    for idx in boundary_indices:
        results.append(
            ALSample(
                embedding_id=candidate_ids[idx],
                decision_distance=float(candidate_distances[idx]),
                sample_type="boundary",
            )
        )
    for idx in others_indices:
        results.append(
            ALSample(
                embedding_id=candidate_ids[idx],
                decision_distance=float(candidate_distances[idx]),
                sample_type="others",
            )
        )

    return results
