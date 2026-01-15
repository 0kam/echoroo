"""Common fixtures for Echoroo tests."""

import logging
import os
import random
import string
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import AsyncGenerator, Optional

import numpy as np
import pytest
import soundevent
import soundfile as sf
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import api, cache, models, schemas
from echoroo.system import get_database_url, init_database
from echoroo.system.settings import Settings

# Avoid noisy logging during tests.
logging.getLogger("aiosqlite").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("passlib").setLevel(logging.WARNING)


@pytest.fixture(scope="session", autouse=True)
def clear_env_variables():
    """Clear environment variables that might interfere with tests."""
    # Save original values
    original_dev = os.environ.get("ECHOROO_DEV")
    original_db_url = os.environ.get("ECHOROO_DB_URL")

    # Clear the variables
    os.environ.pop("ECHOROO_DEV", None)
    os.environ.pop("ECHOROO_DB_URL", None)

    yield

    # Restore original values
    if original_dev is not None:
        os.environ["ECHOROO_DEV"] = original_dev
    if original_db_url is not None:
        os.environ["ECHOROO_DB_URL"] = original_db_url


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).parent.parent.parent


@pytest.fixture
def example_data_dir(repo_root: Path) -> Path:
    return repo_root / "example_data"


@pytest.fixture
def data_dir() -> Path:
    """Return the path to the data directory."""
    return Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def clear_api_cache() -> None:
    """Clear the api cache before each test."""
    api.users._cache.clear()
    api.notes._cache.clear()
    api.tags._cache.clear()
    api.features._cache.clear()
    api.recordings._cache.clear()
    api.datasets._cache.clear()
    api.sound_events._cache.clear()
    api.clips._cache.clear()
    api.sound_event_annotations._cache.clear()
    api.clip_annotations._cache.clear()
    api.annotation_tasks._cache.clear()
    api.annotation_projects._cache.clear()
    api.sound_event_predictions._cache.clear()
    api.clip_predictions._cache.clear()
    api.model_runs._cache.clear()
    api.user_runs._cache.clear()
    api.evaluations._cache.clear()
    api.clip_evaluations._cache.clear()
    api.sound_event_evaluations._cache.clear()
    api.evaluation_sets._cache.clear()


@pytest.fixture
def audio_dir(tmp_path: Path):
    """Fixture to create a temporary audio directory."""
    path = tmp_path / "audio"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    """Return the path where the test database should be created."""
    return tmp_path / "test.db"


@pytest.fixture(autouse=True)
async def settings(
    audio_dir: Path,
    database_path: Path,
) -> Settings:
    """Fixture to return the settings and initialize the database."""
    settings_obj = Settings(
        dev=False,  # Disable dev mode to prevent using default echoroo.db
        db_url=None,  # Explicitly disable db_url to use db_name instead
        db_dialect="sqlite",
        db_name=str(database_path),
        audio_dir=audio_dir,
        open_on_startup=False,
        log_to_file=False,
        log_to_stdout=True,
    )
    # Initialize the database with the settings
    await init_database(settings_obj)
    return settings_obj


@pytest.fixture
def database_url(settings: Settings) -> URL:
    """Fixture to return the database url."""
    return get_database_url(settings)


@pytest.fixture(autouse=True)
async def clear_cache():
    """Clear the cache before each test."""
    cache.clear_all_caches()
    yield


def random_string():
    """Generate a random string of fixed length."""
    options = string.ascii_uppercase + string.digits
    return "".join(random.choice(options) for _ in range(10))


def write_random_wave(
    path: Path,
    samplerate: int = 22100,
    duration: float = 0.1,
    channels: int = 1,
    fmt: str = "WAV",
    subtype: Optional[str] = None,
):
    """Write a random wave file to disk."""
    frames = int(samplerate * duration)
    shape = (frames, channels)
    wav = np.random.random(size=shape)
    sf.write(path, wav, samplerate, format=fmt, subtype=subtype)


@pytest.fixture
def random_wav_factory(audio_dir: Path):
    """Produce a random wav file."""

    def wav_factory(
        path: Optional[Path] = None,
        samplerate: int = 22100,
        duration: float = 0.1,
        channels: int = 1,
        bit_depth: Optional[int] = None,
        fmt: str = "WAV",
        subtype: Optional[str] = None,
    ) -> Path:
        if path is None:
            path = audio_dir / (random_string() + ".wav")

        dirname = os.path.dirname(path)
        if not os.path.exists(dirname):
            os.makedirs(dirname)

        if bit_depth is not None:
            fmt = "WAV"
            subtype = f"PCM_{bit_depth}"

        write_random_wave(
            path=path,
            samplerate=samplerate,
            duration=duration,
            channels=channels,
            fmt=fmt,
            subtype=subtype,
        )

        return path

    return wav_factory


@pytest.fixture
async def session(
    database_url: URL,
) -> AsyncGenerator[AsyncSession, None]:
    """Create a session for database operations."""
    async with api.create_session(db_url=database_url) as sess:
        yield sess


@pytest.fixture
async def user(session: AsyncSession) -> schemas.SimpleUser:
    """Create a user for tests."""
    user = await api.users.create(
        session,
        username="test",
        password="password",
        email="test@echoroo.com",
        is_active=True,
    )
    await session.commit()
    return user


@pytest.fixture
async def other_user(session: AsyncSession) -> schemas.SimpleUser:
    """Create an additional non-privileged user for tests."""
    user = await api.users.create(
        session,
        username=f"other_{random_string()}",
        password="password",
        email=f"other_{random_string().lower()}@echoroo.com",
        is_active=True,
    )
    await session.commit()
    return user


@pytest.fixture
async def superuser(session: AsyncSession) -> schemas.SimpleUser:
    """Create a superuser for tests."""
    user = await api.users.create(
        session,
        username=f"super_{random_string()}",
        password="password",
        email=f"super_{random_string().lower()}@echoroo.com",
        is_active=True,
        is_superuser=True,
    )
    await session.commit()
    return user


@pytest.fixture
async def tag(session: AsyncSession) -> schemas.Tag:
    """Create a tag for testing."""
    return await api.tags.create(
        session,
        key="species",
        value="12345",
        canonical_name="Test species",
    )


@pytest.fixture
async def tag_factory(
    session: AsyncSession,
) -> Callable[[str, str], Awaitable[schemas.Tag]]:
    async def create_tag(key: str, value: str) -> schemas.Tag:
        return await api.tags.create(
            session,
            key=key,
            value=value,
            canonical_name=value.title(),
        )

    return create_tag


@pytest.fixture
async def feature_name(session: AsyncSession) -> schemas.FeatureName:
    """Create a feature for testing."""
    return await api.features.create(session, name="test_feature")


@pytest.fixture
def feature(feature_name: schemas.FeatureName) -> schemas.Feature:
    """Create a feature for testing."""
    return schemas.Feature(name=feature_name.name, value=0.5)


@pytest.fixture
async def note(
    session: AsyncSession,
    user: schemas.SimpleUser,
) -> schemas.Note:
    """Create a note for testing."""
    note = await api.notes.create(
        session,
        message="test_message",
        created_by=user,
    )
    return note


@pytest.fixture
async def recording(
    session: AsyncSession,
    random_wav_factory: Callable[..., Path],
    audio_dir: Path,
) -> schemas.Recording:
    """Create a recording for testing."""
    return await api.recordings.create(
        session,
        path=random_wav_factory(),
        audio_dir=audio_dir,
    )


@pytest.fixture
async def clip(
    session: AsyncSession,
    recording: schemas.Recording,
) -> schemas.Clip:
    """Create a clip for testing."""
    return await api.clips.create(
        session,
        recording=recording,
        start_time=0.1,
        end_time=0.2,
    )


@pytest.fixture
async def sound_event(
    session: AsyncSession,
    recording: schemas.Recording,
) -> schemas.SoundEvent:
    """Create a sound event for testing."""
    geometry = soundevent.Polygon(
        coordinates=[
            [
                [0.0, 0.0],
                [0.0, 1.0],
                [1.0, 1.0],
                [1.0, 0.0],
            ]
        ]
    )
    return await api.sound_events.create(
        session,
        recording=recording,
        geometry=geometry,
    )


@pytest.fixture
async def project_factory(
    session: AsyncSession,
) -> Callable[[schemas.SimpleUser], Awaitable[schemas.Project]]:
    async def create(manager: schemas.SimpleUser) -> schemas.Project:
        project = await api.projects.create_from_data(
            session,
            schemas.ProjectCreate(
                project_name=f"Project {random_string()}",
                initial_members=[
                    schemas.ProjectMemberCreate(
                        user_id=manager.id,
                        role=models.ProjectMemberRole.MANAGER,
                    )
                ],
            ),
        )
        await session.flush()
        return project

    return create


@pytest.fixture
async def project(
    project_factory: Callable[[schemas.SimpleUser], Awaitable[schemas.Project]],
    user: schemas.SimpleUser,
) -> schemas.Project:
    """Provision a project managed by the default user."""
    return await project_factory(user)


@pytest.fixture
async def dataset_dir(
    audio_dir: Path,
    random_wav_factory: Callable[..., Path],
) -> Path:
    # Use random name to avoid duplicate errors across tests
    dataset_dir = audio_dir / f"test_dataset_{random_string()}"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    random_wav_factory(path=dataset_dir / "initial.wav")
    return dataset_dir


@pytest.fixture
async def dataset(
    session: AsyncSession,
    audio_dir: Path,
    dataset_dir: Path,
    user: schemas.SimpleUser,
    project: schemas.Project,
) -> schemas.Dataset:
    """Create a dataset for testing."""
    db_user = await session.get(models.User, user.id)
    assert db_user is not None
    # Use random name to avoid duplicate errors across tests
    name = f"test_dataset_{random_string()}"
    return await api.datasets.create(
        session,
        name=name,
        description="test_description",
        dataset_dir=dataset_dir,
        audio_dir=audio_dir,
        user=db_user,
        visibility=models.VisibilityLevel.PUBLIC,
        project_id=project.project_id,
    )


@pytest.fixture
async def dataset_recording(
    session: AsyncSession,
    dataset: schemas.Dataset,
    audio_dir: Path,
    dataset_dir: Path,
    random_wav_factory: Callable[..., Path],
):
    recording = await api.recordings.create(
        session,
        path=random_wav_factory(path=dataset_dir / "test_audio.wav"),
        audio_dir=audio_dir,
    )
    await api.datasets.add_recording(session, dataset, recording)
    await session.commit()
    return recording


@pytest.fixture
async def clip_annotation(
    session: AsyncSession,
    clip: schemas.Clip,
) -> schemas.ClipAnnotation:
    """Create a clip annotation for testing."""
    ann = await api.clip_annotations.create(
        session,
        clip=clip,
    )
    await session.commit()
    return ann


@pytest.fixture
async def sound_event_annotation(
    session: AsyncSession,
    clip_annotation: schemas.ClipAnnotation,
    sound_event: schemas.SoundEvent,
    user: schemas.SimpleUser,
) -> schemas.SoundEventAnnotation:
    """Create a sound event annotation for testing."""
    return await api.sound_event_annotations.create(
        session,
        clip_annotation=clip_annotation,
        sound_event=sound_event,
        created_by=user,
    )


@pytest.fixture
async def annotation_project(
    session: AsyncSession,
    dataset: schemas.Dataset,
    user: schemas.SimpleUser,
) -> schemas.AnnotationProject:
    """Create an annotation project for testing."""
    # Use random name to avoid duplicate errors across tests
    name = f"test_annotation_project_{random_string()}"
    return await api.annotation_projects.create(
        session,
        name=name,
        description="test_description",
        annotation_instructions="test_instructions",
        user=user,
        dataset_id=dataset.id,
    )


@pytest.fixture
async def annotation_task(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    clip: schemas.Clip,
    clip_annotation: schemas.ClipAnnotation,
) -> schemas.AnnotationTask:
    """Create a task for testing."""
    return await api.annotation_tasks.create(
        session,
        annotation_project=annotation_project,
        clip=clip,
        clip_annotation_id=clip_annotation.id,
    )


@pytest.fixture
async def clip_prediction(
    session: AsyncSession,
    clip: schemas.Clip,
) -> schemas.ClipPrediction:
    """Create a clip prediction for testing."""
    return await api.clip_predictions.create(
        session,
        clip=clip,
    )


@pytest.fixture
async def sound_event_prediction(
    session: AsyncSession,
    sound_event: schemas.SoundEvent,
    clip_prediction: schemas.ClipPrediction,
) -> schemas.SoundEventPrediction:
    """Create a sound event prediction for testing."""
    return await api.sound_event_predictions.create(
        session,
        clip_prediction=clip_prediction,
        sound_event=sound_event,
        score=0.5,
    )


@pytest.fixture
async def model_run(
    session: AsyncSession,
) -> schemas.ModelRun:
    """Create a model run for testing."""
    return await api.model_runs.create(
        session,
        name="test_model",
        version="0.0.0",
        description="test_description",
    )


@pytest.fixture
async def user_run(
    session: AsyncSession,
    user: schemas.SimpleUser,
) -> schemas.UserRun:
    """Create a user run for testing."""
    return await api.user_runs.create(
        session,
        user=user,
    )


@pytest.fixture
async def evaluation(
    session: AsyncSession,
) -> schemas.Evaluation:
    """Create an evaluation for testing."""
    return await api.evaluations.create(
        session,
        score=0.5,
        task="clip_classification",
    )


@pytest.fixture
async def clip_evaluation(
    session: AsyncSession,
    evaluation: schemas.Evaluation,
    clip_prediction: schemas.ClipPrediction,
    clip_annotation: schemas.ClipAnnotation,
) -> schemas.ClipEvaluation:
    """Create a clip evaluation for testing."""
    return await api.clip_evaluations.create(
        session,
        evaluation=evaluation,
        clip_prediction=clip_prediction,
        clip_annotation=clip_annotation,
        score=0.7,
    )


@pytest.fixture
async def sound_event_evaluation(
    session: AsyncSession,
    clip_evaluation: schemas.ClipEvaluation,
    sound_event_prediction: schemas.SoundEventPrediction,
    sound_event_annotation: schemas.SoundEventAnnotation,
) -> schemas.SoundEventEvaluation:
    """Create a sound event evaluation for testing."""
    return await api.sound_event_evaluations.create(
        session,
        clip_evaluation=clip_evaluation,
        source=sound_event_prediction,
        target=sound_event_annotation,
        affinity=1,
        score=0.7,
    )


@pytest.fixture
async def evaluation_set(
    session: AsyncSession,
) -> schemas.EvaluationSet:
    """Create an evaluation set for testing."""
    return await api.evaluation_sets.create(
        session,
        name="test_evaluation_set",
        description="test_description",
    )
