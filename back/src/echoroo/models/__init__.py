"""Module defining the main database models of echoroo.

We are using SQLAlchemy to define our database models. The models are
defined in separate files, and then imported into this module. This
allows us to keep the models organized, and also allows us to import the
models into other modules without having to import the entire database
module.
"""

from echoroo.models.annotation_project import (
    AnnotationProject,
    AnnotationProjectTag,
)
from echoroo.models.annotation_task import (
    AnnotationStatusBadge,
    AnnotationTask,
)
from echoroo.models.base import Base
from echoroo.models.clip import Clip, ClipFeature
from echoroo.models.clip_annotation import (
    ClipAnnotation,
    ClipAnnotationNote,
    ClipAnnotationTag,
)
from echoroo.models.clip_embedding import ClipEmbedding
from echoroo.models.clip_evaluation import ClipEvaluation, ClipEvaluationMetric
from echoroo.models.clip_prediction import ClipPrediction, ClipPredictionTag
from echoroo.models.custom_model import (
    CustomModel,
    CustomModelStatus,
    CustomModelType,
)
from echoroo.models.dataset import Dataset, DatasetRecording, VisibilityLevel
from echoroo.models.datetime_pattern import (
    DatasetDatetimePattern,
    DatetimePatternType,
)
from echoroo.models.detection_review import DetectionReview, DetectionReviewStatus
from echoroo.models.evaluation import Evaluation, EvaluationMetric
from echoroo.models.evaluation_set import (
    EvaluationSet,
    EvaluationSetAnnotation,
    EvaluationSetModelRun,
    EvaluationSetTag,
    EvaluationSetUserRun,
)
from echoroo.models.feature import FeatureName
from echoroo.models.foundation_model import (
    FoundationModel,
    FoundationModelRun,
    FoundationModelRunSpecies,
    FoundationModelRunStatus,
)
from echoroo.models.inference_batch import (
    InferenceBatch,
    InferenceBatchStatus,
    InferencePrediction,
    InferencePredictionReviewStatus,
)
from echoroo.models.inference_job import InferenceJob, InferenceJobStatus
from echoroo.models.license import License
from echoroo.models.ml_project import (
    MLProject,
    MLProjectStatus,
    MLProjectTag,
)
from echoroo.models.model_run import (
    ModelRun,
    ModelRunEvaluation,
    ModelRunPrediction,
)
from echoroo.models.note import Note
from echoroo.models.project import Project, ProjectMember, ProjectMemberRole
from echoroo.models.recorder import Recorder
from echoroo.models.recording import (
    DatetimeParseStatus,
    Recording,
    RecordingFeature,
    RecordingNote,
    RecordingOwner,
    RecordingTag,
)
from echoroo.models.reference_sound import (
    ReferenceSound,
    ReferenceSoundSource,
)
from echoroo.models.search_session import (
    SearchResult,
    SearchResultLabel,
    SearchSession,
    SearchSessionReferenceSound,
)
from echoroo.models.site import Site, SiteImage
from echoroo.models.sound_event import SoundEvent, SoundEventFeature
from echoroo.models.sound_event_annotation import (
    SoundEventAnnotation,
    SoundEventAnnotationNote,
    SoundEventAnnotationTag,
)
from echoroo.models.sound_event_embedding import SoundEventEmbedding
from echoroo.models.sound_event_evaluation import (
    SoundEventEvaluation,
    SoundEventEvaluationMetric,
)
from echoroo.models.sound_event_prediction import (
    SoundEventPrediction,
    SoundEventPredictionTag,
)
from echoroo.models.species_detection_job import (
    SpeciesDetectionJob,
    SpeciesDetectionJobStatus,
)
from echoroo.models.species_filter import (
    SpeciesFilter,
    SpeciesFilterApplication,
    SpeciesFilterApplicationStatus,
    SpeciesFilterMask,
    SpeciesFilterType,
)
from echoroo.models.species_occurrence_cache import (
    GBIFResolutionStatus,
    SpeciesOccurrenceCache,
)
from echoroo.models.tag import Tag
from echoroo.models.token import AccessToken
from echoroo.models.user import User
from echoroo.models.user_run import (
    UserRun,
    UserRunEvaluation,
    UserRunPrediction,
)

__all__ = [
    "AccessToken",
    "AnnotationProject",
    "AnnotationProjectTag",
    "AnnotationStatusBadge",
    "AnnotationTask",
    "Base",
    "Clip",
    "ClipAnnotation",
    "ClipAnnotationNote",
    "ClipAnnotationTag",
    "ClipEmbedding",
    "ClipEvaluation",
    "ClipEvaluationMetric",
    "ClipFeature",
    "ClipPrediction",
    "ClipPredictionTag",
    "CustomModel",
    "CustomModelStatus",
    "CustomModelType",
    "Dataset",
    "DatasetDatetimePattern",
    "DatasetRecording",
    "DatetimeParseStatus",
    "DatetimePatternType",
    "DetectionReview",
    "DetectionReviewStatus",
    "Evaluation",
    "EvaluationMetric",
    "EvaluationSet",
    "EvaluationSetAnnotation",
    "EvaluationSetModelRun",
    "EvaluationSetTag",
    "EvaluationSetUserRun",
    "FeatureName",
    "FoundationModel",
    "FoundationModelRun",
    "FoundationModelRunSpecies",
    "FoundationModelRunStatus",
    "InferenceBatch",
    "InferenceBatchStatus",
    "InferenceJob",
    "InferenceJobStatus",
    "InferencePrediction",
    "InferencePredictionReviewStatus",
    "License",
    "MLProject",
    "MLProjectStatus",
    "MLProjectTag",
    "ModelRun",
    "ModelRunEvaluation",
    "ModelRunPrediction",
    "Note",
    "Project",
    "ProjectMember",
    "ProjectMemberRole",
    "Recorder",
    "Recording",
    "RecordingFeature",
    "RecordingNote",
    "RecordingOwner",
    "RecordingTag",
    "ReferenceSound",
    "ReferenceSoundSource",
    "SearchResult",
    "SearchResultLabel",
    "SearchSession",
    "SearchSessionReferenceSound",
    "Site",
    "SiteImage",
    "SoundEvent",
    "SoundEventAnnotation",
    "SoundEventAnnotationNote",
    "SoundEventAnnotationTag",
    "SoundEventEmbedding",
    "SoundEventEvaluation",
    "SoundEventEvaluationMetric",
    "SoundEventFeature",
    "SoundEventPrediction",
    "SoundEventPredictionTag",
    "SpeciesDetectionJob",
    "SpeciesDetectionJobStatus",
    "SpeciesFilter",
    "SpeciesFilterApplication",
    "SpeciesFilterApplicationStatus",
    "SpeciesFilterMask",
    "SpeciesFilterType",
    "SpeciesOccurrenceCache",
    "GBIFResolutionStatus",
    "Tag",
    "User",
    "UserRun",
    "UserRunEvaluation",
    "UserRunPrediction",
    "VisibilityLevel",
]
