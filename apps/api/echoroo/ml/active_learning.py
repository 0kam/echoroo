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
    """

    embedding_id: str
    decision_distance: float


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
    """

    def __init__(self, k: int) -> None:
        self.k = k
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
        """Keep only the k entries with the smallest |decision_function| value.

        Entries closest to zero (the hyperplane) are the most uncertain and
        therefore the most valuable for active learning.
        """
        if not self._ids:
            return

        abs_d = np.abs(self._distances)
        k_actual = min(self.k, len(self._ids))
        top_idx = np.argsort(abs_d)[:k_actual]

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
