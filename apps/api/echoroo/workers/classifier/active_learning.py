"""Active learning iteration Celery task and its async implementation.

Task name ``echoroo.workers.classifier_tasks.run_al_iteration`` is preserved
for Celery registration compatibility.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import numpy as np
from sqlalchemy import select, text

from echoroo.workers.celery_app import app
from echoroo.workers.classifier.utils import (
    _fetch_training_embeddings,
    _fetch_unlabeled_embeddings,
    _parse_vectors,
)
from echoroo.workers.db_utils import get_worker_engine_and_session_factory

logger = logging.getLogger(__name__)

# Minimum labels required to run an AL iteration. AL is specifically intended
# to help grow the labeled set, so the threshold is lower than for training.
_AL_MIN_POSITIVE_SAMPLES = 5
_AL_MIN_NEGATIVE_SAMPLES = 5

# Batch size for fetching project embeddings during active learning scoring
_AL_SCORING_BATCH_SIZE = 5000

# Number of uncertain candidates to maintain in the margin tracker
_AL_MARGIN_TRACKER_K = 60

# Number of final AL samples to select
_AL_SAMPLE_COUNT = 20

# Candidate pool size before lane splitting for multi-lane AL selection.
# Large enough to give the farthest-first "others" lane meaningful diversity
# while staying comfortably in memory.
_AL_MULTILANE_CANDIDATE_POOL = 200


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="echoroo.workers.classifier_tasks.run_al_iteration",
    time_limit=600,
    soft_time_limit=540,
    max_retries=1,
)
def run_al_iteration(_self: Any, model_id: str, round_id: str) -> dict[str, Any]:
    """Run one active learning iteration for a custom model.

    Trains a lightweight SVM on labeled data from completed sampling rounds,
    scores all unlabeled project embeddings to find the most uncertain ones,
    and populates the pre-created SamplingRound (round_id) with
    SamplingRoundItem records for human review.

    Args:
        model_id: UUID string of the CustomModel record.
        round_id: UUID string of the SamplingRound record (already in 'pending' status).

    Returns:
        Dict with AL iteration result summary (status, round_id, sample_count).
    """
    return asyncio.run(_run_al_iteration(model_id, round_id))

async def _run_al_iteration(model_id: str, round_id: str) -> dict[str, Any]:
    """Async implementation of active learning iteration.

    Args:
        model_id: UUID string of the CustomModel record.
        round_id: UUID string of the pre-created SamplingRound (status='pending').

    Returns:
        Dict with AL iteration result summary.
    """
    from echoroo.models.custom_model import CustomModel

    engine, session_factory = get_worker_engine_and_session_factory()

    # Use the round_id passed in from the API (pre-created pending round)
    round_id_str: str = round_id

    al_total_start = time.perf_counter()

    try:
        # ------------------------------------------------------------------
        # Step 1: Fetch and validate the CustomModel record
        # ------------------------------------------------------------------
        async with session_factory() as db:
            result = await db.execute(
                select(CustomModel).where(CustomModel.id == UUID(model_id))
            )
            model = result.scalar_one_or_none()

            if model is None:
                raise ValueError(f"CustomModel not found: {model_id}")

            project_id = model.project_id
            embedding_model_name = model.embedding_model_name
            target_tag_id = model.target_tag_id

        logger.info(
            "Starting AL iteration: model_id=%s, project_id=%s, "
            "embedding_model=%s",
            model_id,
            project_id,
            embedding_model_name,
        )

        # ------------------------------------------------------------------
        # Step 2: Fetch labeled training data from completed sampling rounds
        # ------------------------------------------------------------------
        fetch_labeled_start = time.perf_counter()
        async with session_factory() as db:
            training_rows = await _fetch_training_embeddings(
                db=db,
                model_id=UUID(model_id),
                embedding_model_name=embedding_model_name,
                target_tag_id=target_tag_id,
            )

        positive_rows = [r for r in training_rows if r["label"] == 1]
        negative_rows = [r for r in training_rows if r["label"] == 0]

        logger.info(
            "AL training data: positive=%d, negative=%d (model_id=%s)",
            len(positive_rows),
            len(negative_rows),
            model_id,
        )
        logger.info(
            "[timing] step=fetch_labeled project_id=%s elapsed=%.2fs n=%d",
            project_id,
            time.perf_counter() - fetch_labeled_start,
            len(training_rows),
        )

        if len(positive_rows) < _AL_MIN_POSITIVE_SAMPLES:
            raise ValueError(
                f"Insufficient positive examples for AL: {len(positive_rows)} "
                f"(minimum {_AL_MIN_POSITIVE_SAMPLES} required)."
            )
        if len(negative_rows) < _AL_MIN_NEGATIVE_SAMPLES:
            raise ValueError(
                f"Insufficient negative examples for AL: {len(negative_rows)} "
                f"(minimum {_AL_MIN_NEGATIVE_SAMPLES} required)."
            )

        # ------------------------------------------------------------------
        # Step 3: Build labeled arrays + fetch unlabeled pool, then train a
        # self-training SVM so pseudo-positives can be generated before AL
        # scoring. Pseudo-positives are critical for low-label regimes where
        # the base SVM otherwise collapses toward the negative class.
        # ------------------------------------------------------------------
        from echoroo.ml.classifiers import (  # noqa: PLC0415
            ClassifierType,
            UnifiedClassifier,
            cluster_unlabeled_embeddings,
        )

        embeddings_list = positive_rows + negative_rows
        raw_vectors = [r["vector"] for r in embeddings_list]
        vector_lengths = {len(v) for v in raw_vectors}
        if len(vector_lengths) != 1:
            raise ValueError(
                f"Inhomogeneous embedding vectors detected: found lengths {vector_lengths}."
            )

        embeddings_array = np.array(raw_vectors, dtype=np.float32)
        labels_array = np.array(
            [1] * len(positive_rows) + [0] * len(negative_rows), dtype=np.int32
        )
        labeled_vectors = embeddings_array  # keep reference for diversity seeds

        # Fetch a pool of unlabeled embeddings for semi-supervised training.
        labeled_embedding_ids = [r["embedding_id"] for r in embeddings_list]
        al_unlabeled: np.ndarray | None = None
        fetch_unlabeled_start = time.perf_counter()
        async with session_factory() as db:
            unlabeled_result = await _fetch_unlabeled_embeddings(
                db=db,
                project_id=project_id,
                embedding_model_name=embedding_model_name,
                exclude_embedding_ids=labeled_embedding_ids,
                # Pull a large pool so clustering can pick a diverse subset.
                max_samples=20000,
            )
        if unlabeled_result is not None:
            al_unlabeled = unlabeled_result[0]
        fetched_n = len(al_unlabeled) if al_unlabeled is not None else 0
        logger.info(
            "[timing] step=fetch_unlabeled project_id=%s elapsed=%.2fs n=%d",
            project_id,
            time.perf_counter() - fetch_unlabeled_start,
            fetched_n,
        )

        # Compress the pool with MiniBatchKMeans if it is large. Self-training
        # scales poorly with tens of thousands of unlabeled rows, so we pick
        # a diverse representative subset (~2000 samples).
        if al_unlabeled is not None and len(al_unlabeled) > 1000:
            cluster_start = time.perf_counter()
            before = len(al_unlabeled)
            al_unlabeled = cluster_unlabeled_embeddings(
                al_unlabeled,
                n_clusters=1000,
                samples_per_cluster=2,
            )
            logger.info(
                "[timing] step=cluster_unlabeled project_id=%s elapsed=%.2fs "
                "before=%d after=%d",
                project_id,
                time.perf_counter() - cluster_start,
                before,
                len(al_unlabeled),
            )

        # Self-training SVM fit. UnifiedClassifier already handles the
        # labeled + unlabeled concatenation and -1 label convention.
        classifier = UnifiedClassifier(
            classifier_type=ClassifierType.SELF_TRAINING_SVM,
        )
        fit_start = time.perf_counter()
        classifier.fit(
            embeddings_array,
            labels_array,
            unlabeled_embeddings=al_unlabeled,
        )
        pseudo_pos_count = 0
        try:
            inner = classifier.model["classifier"]
            # ``transduction_`` is a SelfTrainingClassifier attribute that the
            # Pipeline type does not expose; cast to Any so static analysis
            # does not complain about this diagnostic-only access.
            if hasattr(inner, "transduction_") and al_unlabeled is not None:
                transduction = cast(Any, inner).transduction_
                tail = transduction[len(labels_array):]
                pseudo_pos_count = int(np.sum(tail == 1))
        except Exception:  # noqa: BLE001 — diagnostic only
            pseudo_pos_count = 0
        logger.info(
            "[timing] step=fit project_id=%s elapsed=%.2fs labeled=%d "
            "unlabeled=%d pseudo_pos=%d",
            project_id,
            time.perf_counter() - fit_start,
            len(embeddings_array),
            int(len(al_unlabeled)) if al_unlabeled is not None else 0,
            pseudo_pos_count,
        )

        logger.info(
            "AL self-training SVM fitted on %d labeled samples "
            "(+%d unlabeled, pseudo_pos=%d) (model_id=%s)",
            len(embeddings_array),
            int(len(al_unlabeled)) if al_unlabeled is not None else 0,
            pseudo_pos_count,
            model_id,
        )

        # ------------------------------------------------------------------
        # Step 4: Collect excluded embedding IDs (cross-round dedup)
        # ------------------------------------------------------------------
        async with session_factory() as db:
            from echoroo.repositories.sampling_round import (  # noqa: PLC0415
                SamplingRoundRepository,
            )

            round_repo = SamplingRoundRepository(db)
            existing_embedding_ids = await round_repo.get_existing_embedding_ids(
                UUID(model_id)
            )

        # Convert to string list for SQL exclusion
        exclude_ids = [str(eid) for eid in existing_embedding_ids]

        logger.info(
            "Excluding %d already-sampled embedding IDs (model_id=%s)",
            len(exclude_ids),
            model_id,
        )

        # ------------------------------------------------------------------
        # Step 5: Score project embeddings in chunks, feed two margin trackers
        # ------------------------------------------------------------------
        # We maintain two trackers so the multi-lane selection has access to
        # both ends of the decision-function spectrum:
        #   * ``uncertain_tracker`` keeps the most-uncertain candidates
        #     (smallest |d|) — used to build the "boundary" lane and seed
        #     the "others" lane.
        #   * ``top_positive_tracker`` keeps the most-confident positives
        #     (largest signed d) — used to build the "easy_positive" lane.
        # After scoring we merge their outputs (deduping by embedding id)
        # and hand the combined pool to ``select_al_samples_multilane``.
        from echoroo.ml.active_learning import (  # noqa: PLC0415
            ALMultilaneSamplingConfig,
            MarginTracker,
            select_al_samples_multilane,
        )

        predict_proba_start = time.perf_counter()
        uncertain_tracker = MarginTracker(
            k=_AL_MULTILANE_CANDIDATE_POOL, mode="uncertain"
        )
        top_positive_tracker = MarginTracker(
            k=_AL_MULTILANE_CANDIDATE_POOL, mode="top_positive"
        )
        offset = 0
        total_scored = 0
        # Collected chunk distance arrays so we can build a global histogram
        # of sigmoid(decision_distance) over all scored unlabeled embeddings
        # once scoring completes. Using a list-of-arrays avoids quadratic
        # concatenation while keeping memory proportional to total_scored.
        all_distances_chunks: list[np.ndarray] = []

        while True:
            chunk_sql = text("""
                SELECT e.id, e.vector
                FROM embeddings e
                JOIN recordings r ON r.id = e.recording_id
                JOIN datasets d ON d.id = r.dataset_id
                WHERE
                    d.project_id = :project_id
                    AND e.model_name = :embedding_model_name
                    AND NOT (e.id = ANY(:exclude_ids))
                ORDER BY e.id
                LIMIT :limit OFFSET :offset
            """)

            async with session_factory() as db:
                rows = (
                    await db.execute(
                        chunk_sql,
                        {
                            "project_id": str(project_id),
                            "embedding_model_name": embedding_model_name,
                            "exclude_ids": exclude_ids,
                            "limit": _AL_SCORING_BATCH_SIZE,
                            "offset": offset,
                        },
                    )
                ).fetchall()

            if not rows:
                break

            chunk_ids = [str(r.id) for r in rows]
            chunk_vectors = _parse_vectors([r.vector for r in rows])
            chunk_distances = classifier.decision_function(chunk_vectors)

            uncertain_tracker.update(
                ids=chunk_ids,
                distances=chunk_distances,
                vectors=chunk_vectors,
            )
            top_positive_tracker.update(
                ids=chunk_ids,
                distances=chunk_distances,
                vectors=chunk_vectors,
            )

            # Keep the raw distances around so we can compute the global
            # score-distribution histogram after all chunks have been scored.
            all_distances_chunks.append(np.asarray(chunk_distances, dtype=np.float64))

            total_scored += len(rows)
            offset += len(rows)

            if len(rows) < _AL_SCORING_BATCH_SIZE:
                break

        logger.info(
            "AL scoring complete: %d embeddings scored (model_id=%s)",
            total_scored,
            model_id,
        )
        logger.info(
            "[timing] step=predict_proba project_id=%s elapsed=%.2fs n=%d",
            project_id,
            time.perf_counter() - predict_proba_start,
            total_scored,
        )

        # ------------------------------------------------------------------
        # Step 5b: Compute score-distribution histogram over all scored
        # embeddings. The UI uses this to visualise how the model's
        # prediction distribution shifts between AL iterations, which helps
        # users decide when to stop sampling and kick off training.
        # ------------------------------------------------------------------
        score_distribution: dict[str, Any] | None = None
        histogram_start = time.perf_counter()
        if all_distances_chunks:
            all_distances = np.concatenate(all_distances_chunks)
            # Logistic sigmoid maps the signed SVM decision distance into a
            # 0-1 probability: 0 -> 0.5, large positive -> ~1, large negative -> ~0.
            all_probs = 1.0 / (1.0 + np.exp(-all_distances))
            bin_edges_arr = np.linspace(0.0, 1.0, 21)
            bin_counts_arr, _ = np.histogram(all_probs, bins=bin_edges_arr)
            positive_count = int(np.sum(all_probs >= 0.5))
            negative_count = int(np.sum(all_probs < 0.5))
            score_distribution = {
                "bin_edges": [float(x) for x in bin_edges_arr.tolist()],
                "bin_counts": [int(c) for c in bin_counts_arr.tolist()],
                "mean_score": float(np.mean(all_probs)),
                "positive_count": positive_count,
                "negative_count": negative_count,
                "total_scored": int(all_probs.size),
            }
            logger.info(
                "AL score distribution: mean=%.4f, pos=%d, neg=%d, total=%d "
                "(model_id=%s)",
                score_distribution["mean_score"],
                positive_count,
                negative_count,
                score_distribution["total_scored"],
                model_id,
            )
            logger.info(
                "[timing] step=score_histogram project_id=%s elapsed=%.2fs n=%d",
                project_id,
                time.perf_counter() - histogram_start,
                int(all_probs.size),
            )

        # ------------------------------------------------------------------
        # Step 6: Merge tracker outputs and run multi-lane selection
        # ------------------------------------------------------------------
        uncertain_ids, uncertain_dists, uncertain_vecs = uncertain_tracker.get()
        top_pos_ids, top_pos_dists, top_pos_vecs = top_positive_tracker.get()

        # Merge while deduplicating by embedding id (a candidate can appear
        # in both trackers if its distance is both large-positive AND
        # near zero, which is impossible — but dedupe defensively anyway).
        merged_ids: list[str] = []
        merged_dists_list: list[float] = []
        merged_vecs_list: list[np.ndarray] = []
        seen: set[str] = set()

        def _append(eid: str, dist: float, vec: np.ndarray) -> None:
            if eid in seen:
                return
            seen.add(eid)
            merged_ids.append(eid)
            merged_dists_list.append(float(dist))
            merged_vecs_list.append(vec)

        for i, eid in enumerate(uncertain_ids):
            _append(eid, uncertain_dists[i], uncertain_vecs[i])
        for i, eid in enumerate(top_pos_ids):
            _append(eid, top_pos_dists[i], top_pos_vecs[i])

        merged_vectors = (
            np.vstack(merged_vecs_list) if merged_vecs_list else np.empty((0, 0))
        )
        merged_distances = np.array(merged_dists_list)

        multilane_config = ALMultilaneSamplingConfig(
            easy_positive_k=5,
            boundary_m=10,
            others_p=5,
            candidate_pool_size=_AL_MULTILANE_CANDIDATE_POOL,
        )
        al_samples = select_al_samples_multilane(
            candidate_ids=merged_ids,
            candidate_distances=merged_distances,
            candidate_vectors=merged_vectors,
            labeled_vectors=labeled_vectors,
            config=multilane_config,
        )

        # Per-lane counts for visibility in logs / debugging.
        lane_counts: dict[str, int] = {}
        for s in al_samples:
            lane_counts[s.sample_type] = lane_counts.get(s.sample_type, 0) + 1

        logger.info(
            "AL multi-lane selection: %d merged candidates -> %d selected "
            "(easy_positive=%d, boundary=%d, others=%d, model_id=%s)",
            len(merged_ids),
            len(al_samples),
            lane_counts.get("easy_positive", 0),
            lane_counts.get("boundary", 0),
            lane_counts.get("others", 0),
            model_id,
        )

        if not al_samples:
            raise ValueError(
                "No active learning candidates found. "
                "Ensure the project has unlabeled embeddings not yet sampled."
            )

        # ------------------------------------------------------------------
        # Step 7: Fetch embedding metadata (recording_id, start_time, end_time)
        # for the selected AL sample IDs
        # ------------------------------------------------------------------
        al_sample_ids = [s.embedding_id for s in al_samples]

        meta_sql = text("""
            SELECT e.id, e.recording_id, e.start_time, e.end_time
            FROM embeddings e
            WHERE e.id = ANY(:embedding_ids)
        """)

        async with session_factory() as db:
            meta_rows = (
                await db.execute(
                    meta_sql,
                    {"embedding_ids": al_sample_ids},
                )
            ).fetchall()

        meta_map = {str(r.id): r for r in meta_rows}

        # ------------------------------------------------------------------
        # Step 8: Load pre-created round, mark it running, then insert items
        # ------------------------------------------------------------------
        from echoroo.models.enums import DetectionSource, DetectionStatus  # noqa: PLC0415
        from echoroo.models.recording_annotation import (  # noqa: PLC0415
            RecordingAnnotation,
        )

        async with session_factory() as db:
            from echoroo.repositories.sampling_round import (  # noqa: PLC0415
                SamplingRoundRepository,
            )

            round_repo = SamplingRoundRepository(db)

            # Load the pre-created pending round and transition to running
            round_ = await round_repo.get_round(UUID(round_id_str))
            if round_ is None:
                raise ValueError(f"SamplingRound not found: {round_id_str}")

            round_number = round_.round_number
            round_.status = "running"
            await db.flush()

            now = datetime.now(UTC)
            item_dicts: list[dict[str, Any]] = []

            for sample in al_samples:
                meta = meta_map.get(sample.embedding_id)
                if meta is None:
                    logger.warning(
                        "Missing metadata for AL embedding_id=%s, skipping",
                        sample.embedding_id,
                    )
                    continue

                annotation = RecordingAnnotation(
                    recording_id=meta.recording_id,
                    tag_id=target_tag_id,
                    source=DetectionSource.SAMPLING_ROUND,
                    status=DetectionStatus.UNREVIEWED,
                    start_time=float(meta.start_time),
                    end_time=float(meta.end_time),
                    created_at=now,
                    updated_at=now,
                )
                db.add(annotation)
                await db.flush()
                await db.refresh(annotation)

                item_dicts.append(
                    {
                        "embedding_id": UUID(sample.embedding_id),
                        # Multi-lane AL tags each sample with its lane
                        # ("easy_positive" | "boundary" | "others"); falls
                        # back to "active_learning" for legacy single-lane
                        # samples.
                        "sample_type": sample.sample_type,
                        "annotation_id": annotation.id,
                        "similarity": None,
                        "decision_distance": sample.decision_distance,
                    }
                )

            await round_repo.add_items(UUID(round_id_str), item_dicts)
            await round_repo.update_round_status(
                round_id=UUID(round_id_str),
                status="completed",
                sample_count=len(item_dicts),
                score_distribution=score_distribution,
            )

            await db.commit()

        logger.info(
            "AL iteration completed: model_id=%s, round_id=%s, "
            "round_number=%d, sample_count=%d",
            model_id,
            round_id_str,
            round_number,
            len(item_dicts),
        )
        logger.info(
            "[timing] step=total project_id=%s elapsed=%.2fs",
            project_id,
            time.perf_counter() - al_total_start,
        )

        return {
            "status": "completed",
            "model_id": model_id,
            "round_id": round_id_str,
            "round_number": round_number,
            "sample_count": len(item_dicts),
        }

    except Exception as exc:
        logger.exception(
            "AL iteration failed: model_id=%s, round_id=%s", model_id, round_id_str
        )
        # Mark the pre-created sampling round as failed
        try:
            engine2, session_factory2 = get_worker_engine_and_session_factory()
            try:
                async with session_factory2() as db2:
                    from echoroo.repositories.sampling_round import (  # noqa: PLC0415
                        SamplingRoundRepository,
                    )

                    repo2 = SamplingRoundRepository(db2)
                    await repo2.update_round_status(
                        round_id=UUID(round_id_str),
                        status="failed",
                        error_message=str(exc),
                    )
                    await db2.commit()
            finally:
                await engine2.dispose()
        except Exception:
            logger.exception(
                "Failed to persist FAILED status for AL round_id=%s", round_id_str
            )
        raise

    finally:
        await engine.dispose()

