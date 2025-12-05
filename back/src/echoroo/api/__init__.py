"""Python API for Echoroo."""

from echoroo.api.annotation_projects import annotation_projects
from echoroo.api.annotation_tasks import annotation_tasks
from echoroo.api.audio import load_audio, load_clip_bytes
from echoroo.api.clip_annotations import clip_annotations
from echoroo.api.clip_evaluations import clip_evaluations
from echoroo.api.clip_predictions import clip_predictions
from echoroo.api.clips import clips
from echoroo.api.datasets import datasets
from echoroo.api.evaluation_sets import evaluation_sets
from echoroo.api.evaluations import evaluations
from echoroo.api.features import features, find_feature, find_feature_value
from echoroo.api.model_runs import model_runs
from echoroo.api.notes import notes
from echoroo.api.recordings import recordings
from echoroo.api.metadata import (
    licenses,
    projects,
    recorders,
    site_images,
    sites,
)
from echoroo.api.sessions import create_session
from echoroo.api.sound_event_annotations import sound_event_annotations
from echoroo.api.sound_event_evaluations import sound_event_evaluations
from echoroo.api.sound_event_predictions import sound_event_predictions
from echoroo.api.sound_events import sound_events
from echoroo.api.species import search_gbif_species
from echoroo.api.spectrograms import compute_spectrogram
from echoroo.api.tags import find_tag, find_tag_value, tags
from echoroo.api.user_runs import user_runs
from echoroo.api.users import users
from echoroo.api.inference_jobs import inference_jobs
from echoroo.api.embeddings import (
    clip_embeddings,
    get_clip_embedding_count,
    get_random_clips_with_embeddings,
    search_similar_clips,
    search_similar_clips_advanced,
    sound_event_embeddings,
)

__all__ = [
    "annotation_projects",
    "annotation_tasks",
    "clip_annotations",
    "clip_evaluations",
    "clip_predictions",
    "clips",
    "compute_spectrogram",
    "create_session",
    "datasets",
    "evaluation_sets",
    "evaluations",
    "features",
    "find_feature",
    "find_feature_value",
    "find_tag",
    "find_tag_value",
    "load_audio",
    "load_clip_bytes",
    "model_runs",
    "notes",
    "recordings",
    "recorders",
    "projects",
    "sites",
    "site_images",
    "licenses",
    "sound_event_annotations",
    "sound_event_evaluations",
    "sound_event_predictions",
    "sound_events",
    "search_gbif_species",
    "tags",
    "user_runs",
    "users",
    "inference_jobs",
    "clip_embeddings",
    "get_clip_embedding_count",
    "get_random_clips_with_embeddings",
    "search_similar_clips",
    "search_similar_clips_advanced",
    "sound_event_embeddings",
]
