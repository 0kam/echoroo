"""Echoroo REST API routes."""

from fastapi import APIRouter

from echoroo.routes.annotation_projects import get_annotation_projects_router
from echoroo.routes.annotation_tasks import get_annotation_tasks_router
from echoroo.routes.audio import audio_router
from echoroo.routes.auth import get_auth_router
from echoroo.routes.clip_annotations import get_clip_annotations_router
from echoroo.routes.clip_evaluations import clip_evaluations_router
from echoroo.routes.clip_predictions import clip_predictions_router
from echoroo.routes.clips import clips_router
from echoroo.routes.datasets import get_dataset_router
from echoroo.routes.evaluation_sets import evaluation_sets_router
from echoroo.routes.evaluations import evaluations_router
from echoroo.routes.features import features_router
from echoroo.routes.model_runs import model_runs_router
from echoroo.routes.notes import notes_router
from echoroo.routes.plugins import plugin_router
from echoroo.routes.metadata import get_metadata_router
from echoroo.routes.recordings import get_recording_router
from echoroo.routes.sound_event_annotations import (
    get_sound_event_annotations_router,
)
from echoroo.routes.sound_event_evaluations import (
    sound_event_evaluations_router,
)
from echoroo.routes.sound_event_predictions import (
    sound_event_predictions_router,
)
from echoroo.routes.sound_events import sound_events_router
from echoroo.routes.spectrograms import spectrograms_router
from echoroo.routes.tags import tags_router
from echoroo.routes.species import species_router
from echoroo.routes.setup import get_setup_router
from echoroo.routes.user_runs import get_user_runs_router
from echoroo.routes.users import get_admin_users_router, get_users_router
from echoroo.routes.inference import inference_router
from echoroo.system.settings import Settings

__all__ = [
    "get_main_router",
]


def get_main_router(settings: Settings):
    main_router = APIRouter(prefix="/api/v1")

    # Admin
    auth_router = get_auth_router(settings)
    main_router.include_router(
        auth_router,
        prefix="/auth",
        tags=["Auth"],
    )

    # Descriptors
    users_router = get_users_router(settings)
    main_router.include_router(
        users_router,
        prefix="/users",
        tags=["Users"],
    )
    admin_users_router = get_admin_users_router(settings)
    main_router.include_router(
        admin_users_router,
        prefix="/admin/users",
        tags=["Admin Users"],
    )
    metadata_router = get_metadata_router(settings)
    main_router.include_router(
        metadata_router,
        prefix="/metadata",
        tags=["Metadata"],
    )
    main_router.include_router(
        tags_router,
        prefix="/tags",
        tags=["Tags"],
    )
    main_router.include_router(
        species_router,
        prefix="/species",
        tags=["Species"],
    )
    main_router.include_router(
        features_router,
        prefix="/features",
        tags=["Features"],
    )
    main_router.include_router(
        notes_router,
        prefix="/notes",
        tags=["Notes"],
    )

    # Audio Metadata
    recording_router = get_recording_router(settings)
    main_router.include_router(
        recording_router,
        prefix="/recordings",
        tags=["Recordings"],
    )
    datasets_router = get_dataset_router(settings)
    main_router.include_router(
        datasets_router,
        prefix="/datasets",
        tags=["Datasets"],
    )

    # Audio Content
    main_router.include_router(
        audio_router,
        prefix="/audio",
        tags=["Audio"],
    )
    main_router.include_router(
        spectrograms_router,
        prefix="/spectrograms",
        tags=["Spectrograms"],
    )

    # Acoustic Objects
    main_router.include_router(
        sound_events_router,
        prefix="/sound_events",
        tags=["Sound Events"],
    )
    main_router.include_router(
        clips_router,
        prefix="/clips",
        tags=["Clips"],
    )

    # Annotation
    sound_event_annotations_router = get_sound_event_annotations_router(
        settings
    )
    main_router.include_router(
        sound_event_annotations_router,
        prefix="/sound_event_annotations",
        tags=["Sound Event Annotations"],
    )
    clip_annotations_router = get_clip_annotations_router(settings)
    main_router.include_router(
        clip_annotations_router,
        prefix="/clip_annotations",
        tags=["Clip Annotations"],
    )
    annotation_tasks_router = get_annotation_tasks_router(settings)
    main_router.include_router(
        annotation_tasks_router,
        prefix="/annotation_tasks",
        tags=["Annotation Tasks"],
    )
    annotation_projects_router = get_annotation_projects_router(settings)
    main_router.include_router(
        annotation_projects_router,
        prefix="/annotation_projects",
        tags=["Annotation Projects"],
    )

    # Predictions
    main_router.include_router(
        sound_event_predictions_router,
        prefix="/sound_event_predictions",
        tags=["Sound Event Predictions"],
    )
    main_router.include_router(
        clip_predictions_router,
        prefix="/clip_predictions",
        tags=["Clip Predictions"],
    )
    main_router.include_router(
        model_runs_router,
        prefix="/model_runs",
        tags=["Model Runs"],
    )
    user_runs_router = get_user_runs_router(settings)
    main_router.include_router(
        user_runs_router,
        prefix="/user_runs",
        tags=["User Runs"],
    )

    # Evaluation
    main_router.include_router(
        sound_event_evaluations_router,
        prefix="/sound_event_evaluations",
        tags=["Sound Event Evaluations"],
    )
    main_router.include_router(
        clip_evaluations_router,
        prefix="/clip_evaluations",
        tags=["Clip Evaluations"],
    )
    main_router.include_router(
        evaluation_sets_router,
        prefix="/evaluation_sets",
        tags=["Evaluation Sets"],
    )
    main_router.include_router(
        evaluations_router,
        prefix="/evaluations",
        tags=["Evaluations"],
    )

    # Extensions
    main_router.include_router(
        plugin_router,
        prefix="/plugins",
        tags=["Plugins"],
    )

    # Inference / ML
    main_router.include_router(
        inference_router,
        prefix="/inference",
        tags=["Inference"],
    )

    setup_router = get_setup_router(settings)
    main_router.include_router(
        setup_router,
        prefix="/setup",
        tags=["Setup"],
    )

    return main_router
