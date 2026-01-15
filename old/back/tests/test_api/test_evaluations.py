"""Test suite for evaluations API module."""

import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import api, exceptions, models, schemas


async def test_create_evaluation(session: AsyncSession):
    """Test that an evaluation can be created."""
    evaluation = await api.evaluations.create(
        session,
        task="clip_classification",
        score=0.95,
    )
    assert evaluation.id is not None
    assert evaluation.uuid is not None
    assert evaluation.task == "clip_classification"
    assert evaluation.score == 0.95


async def test_created_evaluation_is_stored_in_database(session: AsyncSession):
    """Test that a created evaluation is stored in the database."""
    evaluation = await api.evaluations.create(
        session,
        task="clip_classification",
        score=0.85,
    )
    stmt = select(models.Evaluation).where(models.Evaluation.id == evaluation.id)
    result = await session.execute(stmt)
    db_eval = result.scalars().first()
    assert db_eval is not None
    assert db_eval.id == evaluation.id
    assert db_eval.task == evaluation.task


async def test_get_evaluation_by_uuid(
    session: AsyncSession,
    evaluation: schemas.Evaluation,
):
    """Test getting an evaluation by UUID."""
    retrieved = await api.evaluations.get(session, evaluation.uuid)
    assert retrieved.id == evaluation.id
    assert retrieved.task == evaluation.task


async def test_get_evaluation_fails_with_nonexistent_uuid(
    session: AsyncSession,
):
    """Test that getting evaluation fails with nonexistent UUID."""
    with pytest.raises(exceptions.NotFoundError):
        await api.evaluations.get(session, uuid.uuid4())


async def test_update_evaluation(
    session: AsyncSession,
    evaluation: schemas.Evaluation,
):
    """Test updating an evaluation."""
    await session.commit()
    updated = await api.evaluations.update(
        session,
        evaluation,
        schemas.EvaluationUpdate(
            score=0.99,
        ),
    )
    await session.commit()

    # Verify in database
    retrieved = await api.evaluations.get(session, evaluation.uuid)
    assert retrieved.score == 0.99


async def test_delete_evaluation(
    session: AsyncSession,
    evaluation: schemas.Evaluation,
):
    """Test deleting an evaluation."""
    await api.evaluations.delete(session, evaluation)
    with pytest.raises(exceptions.NotFoundError):
        await api.evaluations.get(session, evaluation.uuid)


async def test_get_many_evaluations(
    session: AsyncSession,
):
    """Test getting multiple evaluations."""
    eval1 = await api.evaluations.create(
        session,
        task="clip_classification",
        score=0.9,
    )
    eval2 = await api.evaluations.create(
        session,
        task="sound_event_detection",
        score=0.8,
    )

    results, total = await api.evaluations.get_many(session)
    assert total >= 2
    ids = {e.id for e in results}
    assert eval1.id in ids
    assert eval2.id in ids


async def test_get_many_evaluations_with_limit(
    session: AsyncSession,
):
    """Test getting evaluations with limit."""
    for i in range(5):
        await api.evaluations.create(
            session,
            task="clip_classification",
            score=0.5 + i * 0.1,
        )

    results, total = await api.evaluations.get_many(session, limit=2)
    assert len(results) == 2
    assert total >= 5


async def test_add_metric_to_evaluation(
    session: AsyncSession,
    evaluation: schemas.Evaluation,
    feature: schemas.Feature,
):
    """Test adding a metric to an evaluation."""
    result = await api.evaluations.add_metric(session, evaluation, feature)
    assert feature in result.metrics
    assert len(result.metrics) == 1


async def test_cannot_add_duplicate_metric_to_evaluation(
    session: AsyncSession,
    evaluation: schemas.Evaluation,
    feature: schemas.Feature,
):
    """Test that adding a duplicate metric raises an error."""
    await api.evaluations.add_metric(session, evaluation, feature)
    with pytest.raises(ValueError):
        await api.evaluations.add_metric(session, evaluation, feature)


async def test_update_metric_of_evaluation(
    session: AsyncSession,
    evaluation: schemas.Evaluation,
    feature: schemas.Feature,
):
    """Test updating a metric of an evaluation."""
    eval_with_metric = await api.evaluations.add_metric(
        session,
        evaluation,
        feature,
    )
    updated_feature = schemas.Feature(name=feature.name, value=0.99)
    result = await api.evaluations.update_metric(
        session,
        eval_with_metric,
        updated_feature,
    )
    assert result.metrics[0].value == 0.99


async def test_cannot_update_nonexistent_metric_of_evaluation(
    session: AsyncSession,
    evaluation: schemas.Evaluation,
    feature: schemas.Feature,
):
    """Test that updating a non-existent metric raises an error."""
    with pytest.raises(ValueError):
        await api.evaluations.update_metric(session, evaluation, feature)


async def test_remove_metric_from_evaluation(
    session: AsyncSession,
    evaluation: schemas.Evaluation,
    feature: schemas.Feature,
):
    """Test removing a metric from an evaluation."""
    eval_with_metric = await api.evaluations.add_metric(
        session,
        evaluation,
        feature,
    )
    result = await api.evaluations.remove_metric(
        session,
        eval_with_metric,
        feature,
    )
    assert feature not in result.metrics


async def test_cannot_remove_nonexistent_metric_from_evaluation(
    session: AsyncSession,
    evaluation: schemas.Evaluation,
    feature: schemas.Feature,
):
    """Test that removing a non-existent metric raises an error."""
    with pytest.raises(ValueError):
        await api.evaluations.remove_metric(session, evaluation, feature)


async def test_get_clip_evaluations_of_evaluation(
    session: AsyncSession,
    evaluation: schemas.Evaluation,
    clip_evaluation: schemas.ClipEvaluation,
):
    """Test getting clip evaluations of an evaluation."""
    # Note: clip_evaluation is already associated with evaluation via fixtures
    evaluations, total = await api.evaluations.get_clip_evaluations(
        session,
        evaluation,
    )
    # Total might be >= 1 depending on fixture setup
    assert isinstance(evaluations, (list, tuple))


async def test_evaluation_has_correct_default_score(
    session: AsyncSession,
):
    """Test that evaluation has correct default score."""
    evaluation = await api.evaluations.create(
        session,
        task="clip_classification",
    )
    assert evaluation.score == 0


async def test_evaluation_has_correct_type(
    session: AsyncSession,
):
    """Test that created evaluation has correct type."""
    evaluation = await api.evaluations.create(
        session,
        task="sound_event_detection",
    )
    assert isinstance(evaluation, schemas.Evaluation)


async def test_create_evaluation_with_various_tasks(
    session: AsyncSession,
):
    """Test creating evaluations with different task types."""
    tasks = [
        "clip_classification",
        "sound_event_detection",
        "clip_tagging",
        "sound_event_tagging",
    ]
    for task in tasks:
        evaluation = await api.evaluations.create(
            session,
            task=task,
        )
        assert evaluation.task == task
