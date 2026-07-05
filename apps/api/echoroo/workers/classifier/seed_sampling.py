"""Seed sample generation Celery task and its async implementation.

Task name ``echoroo.workers.classifier_tasks.generate_seed_samples`` is
preserved for Celery registration compatibility.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from echoroo.workers.celery_app import app
from echoroo.workers.classifier.utils import _parse_vectors
from echoroo.workers.db_utils import get_worker_engine_and_session_factory

logger = logging.getLogger(__name__)


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="echoroo.workers.classifier_tasks.generate_seed_samples",
    time_limit=600,
    soft_time_limit=540,
)
def generate_seed_samples(_self: Any, model_id: str, round_id: str) -> dict[str, Any]:
    """Generate three-category seed samples for a custom model.

    Fetches reference embedding vectors stored in training_config, queries
    candidate embeddings from the project's pgvector store, runs the
    farthest-first seed sampling algorithm, and creates Annotation +
    SamplingRoundItem records in the database.

    Args:
        model_id: UUID string of the CustomModel record.
        round_id: UUID string of the SamplingRound record (already in 'pending' status).

    Returns:
        Dict with sampling result summary (status, sample_count).
    """
    return asyncio.run(_generate_seed_samples(model_id, round_id))

async def _generate_seed_samples(model_id: str, round_id: str) -> dict[str, Any]:
    """Async implementation of seed sample generation.

    Args:
        model_id: UUID string of the CustomModel record.
        round_id: UUID string of the SamplingRound record.

    Returns:
        Dict with sampling result summary.
    """
    from echoroo.models.custom_model import CustomModel, CustomModelStatus

    engine, session_factory = get_worker_engine_and_session_factory()
    try:
        async with session_factory() as db:
            # ------------------------------------------------------------------
            # Step 1: Fetch and validate the CustomModel record
            # ------------------------------------------------------------------
            result = await db.execute(
                select(CustomModel).where(CustomModel.id == UUID(model_id))
            )
            model = result.scalar_one_or_none()

            if model is None:
                raise ValueError(f"CustomModel not found: {model_id}")

            if model.status not in (
                CustomModelStatus.DRAFT,
                CustomModelStatus.FAILED,
            ):
                raise ValueError(
                    f"Cannot generate seed samples for model with status '{model.status}'. "
                    "Expected 'draft' or 'failed'."
                )

            project_id = model.project_id
            embedding_model_name = model.embedding_model_name
            target_tag_id = model.target_tag_id
            search_session_id = model.search_session_id
            dataset_id = model.dataset_id

            # ------------------------------------------------------------------
            # Step 2: Mark the SamplingRound as running
            # ------------------------------------------------------------------
            from echoroo.repositories.sampling_round import SamplingRoundRepository  # noqa: PLC0415

            round_repo = SamplingRoundRepository(db)
            round_ = await round_repo.get_round(UUID(round_id))
            if round_ is None:
                raise ValueError(f"SamplingRound not found: {round_id}")

            round_.status = "running"
            await db.flush()

            # ------------------------------------------------------------------
            # Step 3: Fetch reference (query) vectors
            # When search_session_id is set, load vectors from search_query_embeddings.
            # Otherwise fall back to the reference_embedding_ids stored in training_config.
            # ------------------------------------------------------------------
            training_config: dict[str, Any] = model.training_config or {}

            if search_session_id is not None:
                ref_sql = text("""
                    SELECT id, vector
                    FROM search_query_embeddings
                    WHERE search_session_id = :session_id
                      AND species_key = :species_key
                """)
                species_key = str(target_tag_id)
                ref_rows = (
                    await db.execute(
                        ref_sql,
                        {"session_id": str(search_session_id), "species_key": species_key},
                    )
                ).fetchall()

                if not ref_rows:
                    raise ValueError(
                        f"No query embeddings found for search_session_id={search_session_id}, "
                        f"species_key={species_key}"
                    )

                logger.info(
                    "Fetching %d query embeddings from search_query_embeddings for model_id=%s",
                    len(ref_rows),
                    model_id,
                )
            else:
                reference_embedding_ids: list[str] = training_config.get(
                    "reference_embedding_ids", []
                )

                if not reference_embedding_ids:
                    raise ValueError(
                        "No reference_embedding_ids found in model.training_config. "
                        "Set reference_embedding_ids before dispatching seed sampling."
                    )

                logger.info(
                    "Fetching %d reference embeddings for model_id=%s",
                    len(reference_embedding_ids),
                    model_id,
                )

                ref_sql = text("""
                    SELECT id, vector
                    FROM embeddings
                    WHERE id = ANY(:embedding_ids)
                      AND model_name = :embedding_model_name
                """)
                ref_rows = (
                    await db.execute(
                        ref_sql,
                        {
                            "embedding_ids": reference_embedding_ids,
                            "embedding_model_name": embedding_model_name,
                        },
                    )
                ).fetchall()

                if not ref_rows:
                    raise ValueError(
                        f"No reference embeddings found for IDs: {reference_embedding_ids}"
                    )

            query_vectors = _parse_vectors([r.vector for r in ref_rows])

            # ------------------------------------------------------------------
            # Step 4: Fetch candidate embeddings
            # ------------------------------------------------------------------
            sampling_config_data: dict[str, Any] = training_config.get(
                "sampling_config", {}
            )
            from echoroo.ml.sampling import SeedSamplingConfig  # noqa: PLC0415

            config = SeedSamplingConfig(
                easy_positive_k=sampling_config_data.get("easy_positive_k", 5),
                boundary_n=sampling_config_data.get("boundary_n", 200),
                boundary_m=sampling_config_data.get("boundary_m", 10),
                others_p=sampling_config_data.get("others_p", 20),
            )

            # Fetch near candidates for easy_positive + boundary: top 205 by similarity
            # We use a single query vector's average as the ordering proxy when multiple
            # query vectors are given.
            top_limit = config.easy_positive_k + config.boundary_n + 5  # small buffer
            avg_query = query_vectors.mean(axis=0).tolist()

            # Build exclude list: ref_rows always have an id column regardless of source
            exclude_ids_for_near: list[str] = [str(r.id) for r in ref_rows]
            dataset_id_param: str | None = str(dataset_id) if dataset_id is not None else None

            near_sql = text("""
                SELECT e.id, e.vector, e.recording_id, e.start_time, e.end_time
                FROM embeddings e
                JOIN recordings r ON e.recording_id = r.id
                JOIN datasets d ON r.dataset_id = d.id
                WHERE d.project_id = :project_id
                  AND e.model_name = :embedding_model_name
                  AND NOT (e.id = ANY(:exclude_ids))
                  AND (CAST(:dataset_id AS uuid) IS NULL OR d.id = CAST(:dataset_id AS uuid))
                ORDER BY e.vector <=> :query_vector
                LIMIT :limit
            """)

            near_rows = (
                await db.execute(
                    near_sql,
                    {
                        "project_id": str(project_id),
                        "embedding_model_name": embedding_model_name,
                        "exclude_ids": exclude_ids_for_near,
                        "dataset_id": dataset_id_param,
                        "query_vector": str(avg_query),
                        "limit": top_limit,
                    },
                )
            ).fetchall()

            # Fetch "others" via TABLESAMPLE for diversity
            # Estimate Bernoulli sample percentage to get ~1000 rows
            count_sql = text("""
                SELECT COUNT(*) FROM embeddings e
                JOIN recordings r ON e.recording_id = r.id
                JOIN datasets d ON r.dataset_id = d.id
                WHERE d.project_id = :project_id
                  AND e.model_name = :embedding_model_name
                  AND (CAST(:dataset_id AS uuid) IS NULL OR d.id = CAST(:dataset_id AS uuid))
            """)
            total_count_result = await db.execute(
                count_sql,
                {
                    "project_id": str(project_id),
                    "embedding_model_name": embedding_model_name,
                    "dataset_id": dataset_id_param,
                },
            )
            total_count = total_count_result.scalar() or 0

            near_row_ids = [str(r.id) for r in near_rows]
            all_exclude_ids = exclude_ids_for_near + near_row_ids

            if total_count > 0:
                # Target ~1000 rows for "others" pool
                target_others = 1000
                bernoulli_pct = min(100.0, (target_others / total_count) * 100.0)
                bernoulli_pct = max(0.01, bernoulli_pct)

                others_sql = text("""
                    SELECT e.id, e.vector, e.recording_id, e.start_time, e.end_time
                    FROM embeddings e TABLESAMPLE BERNOULLI(:pct)
                    JOIN recordings r ON e.recording_id = r.id
                    JOIN datasets d ON r.dataset_id = d.id
                    WHERE d.project_id = :project_id
                      AND e.model_name = :embedding_model_name
                      AND NOT (e.id = ANY(:exclude_ids))
                      AND (CAST(:dataset_id AS uuid) IS NULL OR d.id = CAST(:dataset_id AS uuid))
                    LIMIT 1000
                """)
                others_rows = (
                    await db.execute(
                        others_sql,
                        {
                            "pct": bernoulli_pct,
                            "project_id": str(project_id),
                            "embedding_model_name": embedding_model_name,
                            "exclude_ids": all_exclude_ids,
                            "dataset_id": dataset_id_param,
                        },
                    )
                ).fetchall()
            else:
                others_rows = []

            # Merge candidate rows (near + others, deduplicated by id)
            seen_ids: set[str] = set()
            all_rows = []
            for r in list(near_rows) + list(others_rows):
                rid = str(r.id)
                if rid not in seen_ids:
                    seen_ids.add(rid)
                    all_rows.append(r)

            if not all_rows:
                raise ValueError(
                    f"No candidate embeddings found for project_id={project_id} "
                    f"with embedding_model={embedding_model_name}"
                )

            logger.info(
                "Candidate pool: near=%d, others=%d, total=%d (model_id=%s)",
                len(near_rows),
                len(others_rows),
                len(all_rows),
                model_id,
            )

            # ------------------------------------------------------------------
            # Step 5: Run compute_seed_samples
            # ------------------------------------------------------------------
            import numpy as np  # noqa: PLC0415

            from echoroo.ml.sampling import compute_seed_samples  # noqa: PLC0415

            candidate_ids = np.array([str(r.id) for r in all_rows])
            candidate_recording_ids = np.array([str(r.recording_id) for r in all_rows])
            candidate_vectors = _parse_vectors([r.vector for r in all_rows])

            samples = compute_seed_samples(
                query_vectors=query_vectors,
                candidate_ids=candidate_ids,
                candidate_vectors=candidate_vectors,
                candidate_recording_ids=candidate_recording_ids,
                config=config,
            )

            logger.info(
                "Seed sampling complete: %d samples selected (model_id=%s)",
                len(samples),
                model_id,
            )

            # ------------------------------------------------------------------
            # Step 6: Build a lookup map from embedding_id -> row metadata
            # ------------------------------------------------------------------
            row_map = {str(r.id): r for r in all_rows}

            # ------------------------------------------------------------------
            # Step 7: Create Annotation records + SamplingRoundItem records
            # ------------------------------------------------------------------
            from echoroo.models.enums import DetectionSource, DetectionStatus  # noqa: PLC0415
            from echoroo.models.recording_annotation import (  # noqa: PLC0415
                RecordingAnnotation,
            )

            now = datetime.now(UTC)
            item_dicts: list[dict[str, Any]] = []

            for sample in samples:
                row = row_map[sample.embedding_id]
                annotation = RecordingAnnotation(
                    recording_id=UUID(sample.recording_id),
                    tag_id=target_tag_id,
                    source=DetectionSource.SAMPLING_ROUND,
                    status=DetectionStatus.UNREVIEWED,
                    start_time=float(row.start_time),
                    end_time=float(row.end_time),
                    created_at=now,
                    updated_at=now,
                )
                db.add(annotation)
                await db.flush()
                await db.refresh(annotation)

                item_dicts.append(
                    {
                        "embedding_id": UUID(sample.embedding_id),
                        "sample_type": sample.sample_type,
                        "annotation_id": annotation.id,
                        "similarity": sample.similarity,
                    }
                )

            # Bulk insert SamplingRoundItems
            await round_repo.add_items(UUID(round_id), item_dicts)

            # ------------------------------------------------------------------
            # Step 8: Update round status to completed
            # ------------------------------------------------------------------
            await round_repo.update_round_status(
                round_id=UUID(round_id),
                status="completed",
                sample_count=len(samples),
            )

            await db.commit()

            logger.info(
                "Seed sampling round completed: round_id=%s, model_id=%s, "
                "sample_count=%d",
                round_id,
                model_id,
                len(samples),
            )

            return {
                "status": "completed",
                "model_id": model_id,
                "round_id": round_id,
                "sample_count": len(samples),
            }

    except Exception as exc:
        logger.exception(
            "Seed sampling failed: model_id=%s, round_id=%s", model_id, round_id
        )
        # Mark sampling round as failed
        try:
            engine2, session_factory2 = get_worker_engine_and_session_factory()
            try:
                async with session_factory2() as db2:
                    from echoroo.repositories.sampling_round import (  # noqa: PLC0415
                        SamplingRoundRepository,
                    )

                    repo2 = SamplingRoundRepository(db2)
                    await repo2.update_round_status(
                        round_id=UUID(round_id),
                        status="failed",
                        error_message=str(exc),
                    )
                    await db2.commit()
            finally:
                await engine2.dispose()
        except Exception:
            logger.exception(
                "Failed to persist FAILED status for round_id=%s", round_id
            )
        raise

    finally:
        await engine.dispose()

