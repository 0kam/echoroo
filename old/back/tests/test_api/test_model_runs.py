"""Test suite for model runs API module."""

import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import api, exceptions, models, schemas


async def test_create_model_run(session: AsyncSession):
    """Test that a model run can be created."""
    model_run = await api.model_runs.create(
        session,
        name="test_model",
        version="1.0.0",
        description="A test model run",
    )
    assert model_run.id is not None
    assert model_run.uuid is not None
    assert model_run.name == "test_model"
    assert model_run.version == "1.0.0"
    assert model_run.description == "A test model run"


async def test_created_model_run_is_stored_in_database(session: AsyncSession):
    """Test that a created model run is stored in the database."""
    model_run = await api.model_runs.create(
        session,
        name="test_model",
        version="1.0.0",
        description="A test model run",
    )
    stmt = select(models.ModelRun).where(models.ModelRun.id == model_run.id)
    result = await session.execute(stmt)
    db_model_run = result.scalars().first()
    assert db_model_run is not None
    assert db_model_run.id == model_run.id
    assert db_model_run.name == model_run.name


async def test_get_model_run_by_uuid(
    session: AsyncSession,
    model_run: schemas.ModelRun,
):
    """Test getting a model run by UUID."""
    retrieved = await api.model_runs.get(session, model_run.uuid)
    assert retrieved.id == model_run.id
    assert retrieved.name == model_run.name


async def test_get_model_run_fails_with_nonexistent_uuid(
    session: AsyncSession,
):
    """Test that getting model run fails with nonexistent UUID."""
    with pytest.raises(exceptions.NotFoundError):
        await api.model_runs.get(session, uuid.uuid4())


async def test_update_model_run(
    session: AsyncSession,
    model_run: schemas.ModelRun,
):
    """Test updating a model run."""
    updated = await api.model_runs.update(
        session,
        model_run,
        schemas.ModelRunUpdate(
            description="updated_description",
        ),
    )
    assert updated.description == "updated_description"

    # Verify in database
    retrieved = await api.model_runs.get(session, model_run.uuid)
    assert retrieved.description == "updated_description"


async def test_delete_model_run(
    session: AsyncSession,
    model_run: schemas.ModelRun,
):
    """Test deleting a model run."""
    await api.model_runs.delete(session, model_run)
    with pytest.raises(exceptions.NotFoundError):
        await api.model_runs.get(session, model_run.uuid)


async def test_get_many_model_runs(
    session: AsyncSession,
):
    """Test getting multiple model runs."""
    model_run1 = await api.model_runs.create(
        session,
        name="model_1",
        version="1.0.0",
    )
    model_run2 = await api.model_runs.create(
        session,
        name="model_2",
        version="2.0.0",
    )

    results, total = await api.model_runs.get_many(session)
    assert total >= 2
    ids = {m.id for m in results}
    assert model_run1.id in ids
    assert model_run2.id in ids


async def test_get_many_model_runs_with_limit(
    session: AsyncSession,
):
    """Test getting model runs with limit."""
    for i in range(5):
        await api.model_runs.create(
            session,
            name=f"model_{i}",
            version=f"{i}.0.0",
        )

    results, total = await api.model_runs.get_many(session, limit=2)
    assert len(results) == 2
    assert total >= 5


async def test_add_clip_prediction_to_model_run(
    session: AsyncSession,
    model_run: schemas.ModelRun,
    clip_prediction: schemas.ClipPrediction,
):
    """Test adding a clip prediction to a model run."""
    result = await api.model_runs.add_clip_prediction(
        session,
        model_run,
        clip_prediction,
    )
    assert result.id == model_run.id

    # Verify in database
    stmt = select(models.ModelRunPrediction).where(
        models.ModelRunPrediction.model_run_id == model_run.id
    )
    db_result = await session.execute(stmt)
    assert db_result.scalars().first() is not None


async def test_get_clip_predictions_of_model_run(
    session: AsyncSession,
    model_run: schemas.ModelRun,
    clip_prediction: schemas.ClipPrediction,
):
    """Test getting clip predictions of a model run."""
    await api.model_runs.add_clip_prediction(
        session,
        model_run,
        clip_prediction,
    )
    predictions, total = await api.model_runs.get_clip_predictions(
        session,
        model_run,
    )
    assert total >= 1
    assert any(p.id == clip_prediction.id for p in predictions)


async def test_cannot_add_duplicate_clip_prediction_to_model_run(
    session: AsyncSession,
    model_run: schemas.ModelRun,
    clip_prediction: schemas.ClipPrediction,
):
    """Test that adding duplicate clip prediction raises error when raise_if_exists=True."""
    await api.model_runs.add_clip_prediction(
        session,
        model_run,
        clip_prediction,
    )
    with pytest.raises(exceptions.DuplicateObjectError):
        await api.model_runs.add_clip_prediction(
            session,
            model_run,
            clip_prediction,
            raise_if_exists=True,
        )


async def test_add_duplicate_clip_prediction_silently_when_raise_if_exists_false(
    session: AsyncSession,
    model_run: schemas.ModelRun,
    clip_prediction: schemas.ClipPrediction,
):
    """Test that adding duplicate clip prediction succeeds when raise_if_exists=False."""
    await api.model_runs.add_clip_prediction(
        session,
        model_run,
        clip_prediction,
    )
    # Should not raise
    result = await api.model_runs.add_clip_prediction(
        session,
        model_run,
        clip_prediction,
        raise_if_exists=False,
    )
    assert result.id == model_run.id


async def test_model_run_has_correct_type(session: AsyncSession):
    """Test that created model run has correct type."""
    model_run = await api.model_runs.create(
        session,
        name="test_model",
        version="1.0.0",
    )
    assert isinstance(model_run, schemas.ModelRun)


async def test_model_run_without_description(session: AsyncSession):
    """Test creating a model run without description."""
    model_run = await api.model_runs.create(
        session,
        name="test_model",
        version="1.0.0",
    )
    assert model_run.description is None


async def test_model_run_with_various_versions(session: AsyncSession):
    """Test creating model runs with different version formats."""
    versions = ["1.0.0", "2.0.0-beta", "1.0.0-rc.1", "0.0.1"]
    for version in versions:
        model_run = await api.model_runs.create(
            session,
            name="test_model",
            version=version,
        )
        assert model_run.version == version


async def test_get_evaluation_of_model_run(
    session: AsyncSession,
    model_run: schemas.ModelRun,
    evaluation_set: schemas.EvaluationSet,
):
    """Test getting evaluation of a model run for an evaluation set."""
    # This test checks the error case when evaluation doesn't exist
    with pytest.raises(exceptions.NotFoundError):
        await api.model_runs.get_evaluation(session, model_run, evaluation_set)
