"""Test suite for evaluation sets API module."""

import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import api, exceptions, models, schemas


async def test_create_evaluation_set(session: AsyncSession):
    """Test that an evaluation set can be created."""
    eval_set = await api.evaluation_sets.create(
        session,
        name="test_eval_set",
        description="A test evaluation set",
    )
    assert eval_set.id is not None
    assert eval_set.uuid is not None
    assert eval_set.name == "test_eval_set"
    assert eval_set.description == "A test evaluation set"


async def test_created_evaluation_set_is_stored_in_database(session: AsyncSession):
    """Test that a created evaluation set is stored in the database."""
    eval_set = await api.evaluation_sets.create(
        session,
        name="test_eval_set",
        description="A test evaluation set",
    )
    stmt = select(models.EvaluationSet).where(
        models.EvaluationSet.id == eval_set.id
    )
    result = await session.execute(stmt)
    db_eval_set = result.scalars().first()
    assert db_eval_set is not None
    assert db_eval_set.id == eval_set.id
    assert db_eval_set.name == eval_set.name


async def test_cannot_create_evaluation_set_with_duplicate_name(
    session: AsyncSession,
):
    """Test that creating an evaluation set with duplicate name fails."""
    from tests.conftest import random_string
    dup_name = f"duplicate_eval_set_{random_string()}"
    eval_set1 = await api.evaluation_sets.create(
        session,
        name=dup_name,
    )
    await session.commit()
    with pytest.raises(exceptions.DuplicateObjectError):
        await api.evaluation_sets.create(
            session,
            name=dup_name,
        )


async def test_get_evaluation_set_by_uuid(
    session: AsyncSession,
    evaluation_set: schemas.EvaluationSet,
):
    """Test getting an evaluation set by UUID."""
    retrieved = await api.evaluation_sets.get(session, evaluation_set.uuid)
    assert retrieved.id == evaluation_set.id
    assert retrieved.name == evaluation_set.name


async def test_get_evaluation_set_fails_with_nonexistent_uuid(
    session: AsyncSession,
):
    """Test that getting evaluation set fails with nonexistent UUID."""
    with pytest.raises(exceptions.NotFoundError):
        await api.evaluation_sets.get(session, uuid.uuid4())


async def test_update_evaluation_set(
    session: AsyncSession,
    evaluation_set: schemas.EvaluationSet,
):
    """Test updating an evaluation set."""
    # Need to commit first to ensure the evaluation set is stored
    await session.commit()
    updated = await api.evaluation_sets.update(
        session,
        evaluation_set,
        schemas.EvaluationSetUpdate(
            name="updated_name",
            description="updated_description",
        ),
    )
    # Refresh the session state
    await session.commit()

    # Verify in database by fetching fresh
    retrieved = await api.evaluation_sets.get(session, evaluation_set.uuid)
    assert retrieved.name == "updated_name"
    assert retrieved.description == "updated_description"


async def test_delete_evaluation_set(
    session: AsyncSession,
    evaluation_set: schemas.EvaluationSet,
):
    """Test deleting an evaluation set."""
    await api.evaluation_sets.delete(session, evaluation_set)
    with pytest.raises(exceptions.NotFoundError):
        await api.evaluation_sets.get(session, evaluation_set.uuid)


async def test_get_many_evaluation_sets(
    session: AsyncSession,
):
    """Test getting multiple evaluation sets."""
    from tests.conftest import random_string
    name1 = f"eval_set_1_{random_string()}"
    name2 = f"eval_set_2_{random_string()}"
    eval_set1 = await api.evaluation_sets.create(
        session,
        name=name1,
    )
    eval_set2 = await api.evaluation_sets.create(
        session,
        name=name2,
    )

    results, total = await api.evaluation_sets.get_many(session)
    assert total >= 2
    ids = {e.id for e in results}
    assert eval_set1.id in ids
    assert eval_set2.id in ids


async def test_get_many_evaluation_sets_with_limit(
    session: AsyncSession,
):
    """Test getting evaluation sets with limit."""
    from tests.conftest import random_string
    for i in range(5):
        await api.evaluation_sets.create(
            session,
            name=f"eval_set_{i}_{random_string()}",
        )

    results, total = await api.evaluation_sets.get_many(session, limit=2)
    assert len(results) == 2
    assert total >= 5


async def test_add_clip_annotation_to_evaluation_set(
    session: AsyncSession,
    evaluation_set: schemas.EvaluationSet,
    clip_annotation: schemas.ClipAnnotation,
):
    """Test adding a clip annotation to an evaluation set."""
    result = await api.evaluation_sets.add_clip_annotation(
        session,
        evaluation_set,
        clip_annotation,
    )
    assert result.id == evaluation_set.id

    # Verify in database
    stmt = select(models.EvaluationSetAnnotation).where(
        models.EvaluationSetAnnotation.evaluation_set_id == evaluation_set.id
    )
    db_result = await session.execute(stmt)
    assert db_result.scalars().first() is not None


async def test_remove_clip_annotation_from_evaluation_set(
    session: AsyncSession,
    evaluation_set: schemas.EvaluationSet,
    clip_annotation: schemas.ClipAnnotation,
):
    """Test removing a clip annotation from an evaluation set."""
    await api.evaluation_sets.add_clip_annotation(
        session,
        evaluation_set,
        clip_annotation,
    )
    result = await api.evaluation_sets.remove_clip_annotation(
        session,
        evaluation_set,
        clip_annotation,
    )
    assert result.id == evaluation_set.id

    # Verify in database
    stmt = select(models.EvaluationSetAnnotation).where(
        models.EvaluationSetAnnotation.evaluation_set_id == evaluation_set.id
    )
    db_result = await session.execute(stmt)
    assert db_result.scalars().first() is None


async def test_add_tag_to_evaluation_set(
    session: AsyncSession,
    evaluation_set: schemas.EvaluationSet,
    tag: schemas.Tag,
):
    """Test adding a tag to an evaluation set."""
    result = await api.evaluation_sets.add_tag(session, evaluation_set, tag)
    assert tag in result.tags
    assert len(result.tags) == 1


async def test_cannot_add_duplicate_tag_to_evaluation_set(
    session: AsyncSession,
    evaluation_set: schemas.EvaluationSet,
    tag: schemas.Tag,
):
    """Test that adding a duplicate tag raises an error."""
    eval_set_with_tag = await api.evaluation_sets.add_tag(session, evaluation_set, tag)
    with pytest.raises(ValueError):
        await api.evaluation_sets.add_tag(session, eval_set_with_tag, tag)


async def test_remove_tag_from_evaluation_set(
    session: AsyncSession,
    evaluation_set: schemas.EvaluationSet,
    tag: schemas.Tag,
):
    """Test removing a tag from an evaluation set."""
    eval_set_with_tag = await api.evaluation_sets.add_tag(
        session,
        evaluation_set,
        tag,
    )
    result = await api.evaluation_sets.remove_tag(session, eval_set_with_tag, tag)
    assert tag not in result.tags


async def test_cannot_remove_nonexistent_tag_from_evaluation_set(
    session: AsyncSession,
    evaluation_set: schemas.EvaluationSet,
    tag: schemas.Tag,
):
    """Test that removing a non-existent tag raises an error."""
    with pytest.raises(ValueError):
        await api.evaluation_sets.remove_tag(session, evaluation_set, tag)


async def test_add_model_run_to_evaluation_set(
    session: AsyncSession,
    evaluation_set: schemas.EvaluationSet,
    model_run: schemas.ModelRun,
):
    """Test adding a model run to an evaluation set."""
    result = await api.evaluation_sets.add_model_run(
        session,
        evaluation_set,
        model_run,
    )
    assert result.id == evaluation_set.id

    # Verify in database
    stmt = select(models.EvaluationSetModelRun).where(
        models.EvaluationSetModelRun.evaluation_set_id == evaluation_set.id
    )
    db_result = await session.execute(stmt)
    assert db_result.scalars().first() is not None


async def test_remove_model_run_from_evaluation_set(
    session: AsyncSession,
    evaluation_set: schemas.EvaluationSet,
    model_run: schemas.ModelRun,
):
    """Test removing a model run from an evaluation set."""
    await api.evaluation_sets.add_model_run(session, evaluation_set, model_run)
    result = await api.evaluation_sets.remove_model_run(
        session,
        evaluation_set,
        model_run,
    )
    assert result.id == evaluation_set.id


async def test_get_model_runs_in_evaluation_set(
    session: AsyncSession,
    evaluation_set: schemas.EvaluationSet,
    model_run: schemas.ModelRun,
):
    """Test getting model runs from an evaluation set."""
    await api.evaluation_sets.add_model_run(session, evaluation_set, model_run)
    runs, total = await api.evaluation_sets.get_model_runs(session, evaluation_set)
    assert total >= 1
    assert any(r.id == model_run.id for r in runs)


async def test_add_user_run_to_evaluation_set(
    session: AsyncSession,
    evaluation_set: schemas.EvaluationSet,
    user_run: schemas.UserRun,
):
    """Test adding a user run to an evaluation set."""
    result = await api.evaluation_sets.add_user_run(
        session,
        evaluation_set,
        user_run,
    )
    assert result.id == evaluation_set.id


async def test_remove_user_run_from_evaluation_set(
    session: AsyncSession,
    evaluation_set: schemas.EvaluationSet,
    user_run: schemas.UserRun,
):
    """Test removing a user run from an evaluation set."""
    await api.evaluation_sets.add_user_run(session, evaluation_set, user_run)
    result = await api.evaluation_sets.remove_user_run(
        session,
        evaluation_set,
        user_run,
    )
    assert result.id == evaluation_set.id


async def test_get_user_runs_in_evaluation_set(
    session: AsyncSession,
    evaluation_set: schemas.EvaluationSet,
    user_run: schemas.UserRun,
):
    """Test getting user runs from an evaluation set."""
    await api.evaluation_sets.add_user_run(session, evaluation_set, user_run)
    runs, total = await api.evaluation_sets.get_user_runs(session, evaluation_set)
    assert total >= 1
    assert any(r.id == user_run.id for r in runs)


async def test_get_clip_annotations_in_evaluation_set(
    session: AsyncSession,
    evaluation_set: schemas.EvaluationSet,
    clip_annotation: schemas.ClipAnnotation,
):
    """Test getting clip annotations from an evaluation set."""
    await api.evaluation_sets.add_clip_annotation(
        session,
        evaluation_set,
        clip_annotation,
    )
    annotations, total = await api.evaluation_sets.get_clip_annotations(
        session,
        evaluation_set,
    )
    assert total >= 1
    assert any(a.id == clip_annotation.id for a in annotations)


async def test_evaluation_set_has_correct_type(session: AsyncSession):
    """Test that created evaluation set has correct type."""
    from tests.conftest import random_string
    eval_set = await api.evaluation_sets.create(
        session,
        name=f"test_eval_set_{random_string()}",
    )
    assert isinstance(eval_set, schemas.EvaluationSet)
