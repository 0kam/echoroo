"""Filtersets for the API.

This module defines the ways in which the API can filter the data it
returns and provides some helper functions for the filtersets.
"""

from echoroo.filters.annotation_projects import AnnotationProjectFilter
from echoroo.filters.annotation_tasks import AnnotationTaskFilter
from echoroo.filters.base import Filter
from echoroo.filters.clip_annotation_notes import ClipAnnotationNoteFilter
from echoroo.filters.clip_annotation_tags import ClipAnnotationTagFilter
from echoroo.filters.clip_annotations import ClipAnnotationFilter
from echoroo.filters.clip_evaluations import ClipEvaluationFilter
from echoroo.filters.clip_predictions import ClipPredictionFilter
from echoroo.filters.clips import ClipFilter
from echoroo.filters.datasets import DatasetFilter
from echoroo.filters.evaluation_sets import EvaluationSetFilter
from echoroo.filters.evaluations import EvaluationFilter
from echoroo.filters.feature_names import FeatureNameFilter
from echoroo.filters.model_runs import ModelRunFilter
from echoroo.filters.notes import NoteFilter
from echoroo.filters.recording_notes import RecordingNoteFilter
from echoroo.filters.recording_tags import RecordingTagFilter
from echoroo.filters.recordings import RecordingFilter
from echoroo.filters.sound_event_annotation_notes import (
    SoundEventAnnotationNoteFilter,
)
from echoroo.filters.sound_event_annotation_tags import (
    SoundEventAnnotationTagFilter,
)
from echoroo.filters.sound_event_annotations import SoundEventAnnotationFilter
from echoroo.filters.sound_event_evaluations import SoundEventEvaluationFilter
from echoroo.filters.sound_event_predictions import SoundEventPredictionFilter
from echoroo.filters.sound_events import SoundEventFilter
from echoroo.filters.tags import TagFilter
from echoroo.filters.user_runs import UserRunFilter

__all__ = [
    "AnnotationProjectFilter",
    "AnnotationTaskFilter",
    "ClipAnnotationFilter",
    "ClipAnnotationNoteFilter",
    "ClipAnnotationTagFilter",
    "ClipEvaluationFilter",
    "ClipPredictionFilter",
    "ClipFilter",
    "DatasetFilter",
    "EvaluationSetFilter",
    "EvaluationFilter",
    "FeatureNameFilter",
    "Filter",
    "ModelRunFilter",
    "NoteFilter",
    "RecordingFilter",
    "RecordingNoteFilter",
    "RecordingTagFilter",
    "SoundEventAnnotationFilter",
    "SoundEventAnnotationNoteFilter",
    "SoundEventAnnotationTagFilter",
    "SoundEventEvaluationFilter",
    "SoundEventPredictionFilter",
    "SoundEventFilter",
    "TagFilter",
    "UserRunFilter",
]
