"""Schemas for Echoroo data models.

The Echoroo Python API returns these schemas to the user, and they are
the main way that the user interacts with the data.

Schemas are defined using Pydantic, and are used to validate data before
it is inserted into the database, and also to validate data before it is
returned to the user.

Most database models have multiple schemas, a main schema that is used
to return data to the user, and a create and update schema that is used
to validate data before it is inserted into the database.
"""

from echoroo.schemas.annotation_projects import (
    AnnotationProject,
    AnnotationProjectCreate,
    AnnotationProjectUpdate,
)
from echoroo.schemas.annotation_tasks import (
    AnnotationStatusBadge,
    AnnotationStatusBadgeUpdate,
    AnnotationTask,
    AnnotationTaskCreate,
    AnnotationTaskNote,
    AnnotationTaskUpdate,
)
from echoroo.schemas.audio import AudioParameters
from echoroo.schemas.base import BaseSchema, Page
from echoroo.schemas.clip_annotations import (
    ClipAnnotation,
    ClipAnnotationCreate,
    ClipAnnotationNote,
    ClipAnnotationTag,
    ClipAnnotationUpdate,
)
from echoroo.schemas.clip_evaluations import (
    ClipEvaluation,
    ClipEvaluationCreate,
    ClipEvaluationUpdate,
)
from echoroo.schemas.clip_predictions import (
    ClipPrediction,
    ClipPredictionCreate,
    ClipPredictionTag,
    ClipPredictionUpdate,
)
from echoroo.schemas.clips import Clip, ClipCreate, ClipUpdate
from echoroo.schemas.embeddings import (
    AdvancedSearchRequest,
    AdvancedSearchResponse,
    ClipEmbedding,
    EmbeddingSearchRequest,
    EmbeddingSearchResponse,
    EmbeddingSearchResult,
    RandomClipsRequest,
    RandomClipsResponse,
    SearchResultItem,
    SoundEventEmbedding,
)
from echoroo.schemas.datasets import (
    Dataset,
    DatasetCreate,
    DatasetCandidate,
    DatasetCandidateInfo,
    DatasetDatetimePattern,
    DatasetDatetimePatternUpdate,
    DatasetFile,
    DatasetRecording,
    DatasetRecordingCalendarBucket,
    DatasetRecordingCreate,
    DatasetRecordingHeatmapCell,
    DatasetRecordingSite,
    DatasetRecordingTimelineSegment,
    DatasetOverviewStats,
    DatasetUpdate,
    FileState,
)
from echoroo.schemas.evaluation_sets import (
    EvaluationSet,
    EvaluationSetCreate,
    EvaluationSetUpdate,
)
from echoroo.schemas.evaluations import (
    Evaluation,
    EvaluationCreate,
    EvaluationUpdate,
)
from echoroo.schemas.features import (
    Feature,
    FeatureName,
    FeatureNameCreate,
    FeatureNameUpdate,
)
from echoroo.schemas.inference import (
    InferenceConfig,
    InferenceJob,
    InferenceJobCreate,
    InferenceJobUpdate,
    InferenceStatus,
)
from echoroo.schemas.metadata import (
    License,
    LicenseCreate,
    LicenseUpdate,
    Project,
    ProjectCreate,
    ProjectUpdate,
    ProjectMember,
    ProjectMemberCreate,
    ProjectMemberUpdate,
    Recorder,
    RecorderCreate,
    RecorderUpdate,
    Site,
    SiteCreate,
    SiteUpdate,
    SiteImage,
    SiteImageCreate,
    SiteImageUpdate,
)
from echoroo.schemas.model_runs import ModelRun, ModelRunCreate, ModelRunUpdate
from echoroo.schemas.notes import Note, NoteCreate, NoteUpdate
from echoroo.schemas.plugin import PluginInfo
from echoroo.schemas.recordings import (
    Recording,
    RecordingCreate,
    RecordingNote,
    RecordingTag,
    RecordingUpdate,
)
from echoroo.schemas.sound_event_annotations import (
    SoundEventAnnotation,
    SoundEventAnnotationCreate,
    SoundEventAnnotationNote,
    SoundEventAnnotationTag,
    SoundEventAnnotationUpdate,
)
from echoroo.schemas.sound_event_evaluations import (
    SoundEventEvaluation,
    SoundEventEvaluationCreate,
    SoundEventEvaluationUpdate,
)
from echoroo.schemas.sound_event_predictions import (
    SoundEventPrediction,
    SoundEventPredictionCreate,
    SoundEventPredictionTag,
    SoundEventPredictionUpdate,
)
from echoroo.schemas.sound_events import (
    SoundEvent,
    SoundEventCreate,
    SoundEventUpdate,
)
from echoroo.schemas.spectrograms import (
    AmplitudeParameters,
    Scale,
    SpectrogramParameters,
    STFTParameters,
    Window,
)
from echoroo.schemas.tags import (
    PredictedTag,
    Tag,
    TagCount,
    TagCreate,
    TagUpdate,
)
from echoroo.schemas.setup import (
    InstallRequest,
    InstallResponse,
    ModelStatus,
    ModelsStatus,
)
from echoroo.schemas.species import SpeciesCandidate
from echoroo.schemas.user_runs import UserRun, UserRunCreate, UserRunUpdate
from echoroo.schemas.users import (
    SimpleUser,
    User,
    UserAdminUpdate,
    UserCreate,
    UserUpdate,
)

__all__ = [
    "AmplitudeParameters",
    "AnnotationProject",
    "AnnotationProjectCreate",
    "AnnotationProjectUpdate",
    "AnnotationStatusBadge",
    "AnnotationStatusBadgeUpdate",
    "AnnotationTask",
    "AnnotationTaskCreate",
    "AnnotationTaskNote",
    "AnnotationTaskUpdate",
    "AudioParameters",
    "BaseSchema",
    "Clip",
    "ClipAnnotation",
    "ClipAnnotationCreate",
    "ClipAnnotationNote",
    "ClipAnnotationTag",
    "ClipAnnotationUpdate",
    "ClipCreate",
    "ClipEvaluation",
    "ClipEvaluationCreate",
    "ClipEvaluationUpdate",
    "ClipPrediction",
    "ClipPredictionCreate",
    "ClipPredictionTag",
    "ClipPredictionUpdate",
    "ClipUpdate",
    "ClipEmbedding",
    "Dataset",
    "DatasetCreate",
    "DatasetCandidate",
    "DatasetCandidateInfo",
    "DatasetDatetimePattern",
    "DatasetDatetimePatternUpdate",
    "DatasetFile",
    "DatasetRecording",
    "DatasetRecordingCalendarBucket",
    "DatasetRecordingCreate",
    "DatasetRecordingHeatmapCell",
    "DatasetRecordingSite",
    "DatasetRecordingTimelineSegment",
    "DatasetOverviewStats",
    "DatasetUpdate",
    "Evaluation",
    "EvaluationCreate",
    "EvaluationSet",
    "EvaluationSetCreate",
    "EvaluationSetUpdate",
    "EvaluationUpdate",
    "AdvancedSearchRequest",
    "AdvancedSearchResponse",
    "EmbeddingSearchRequest",
    "EmbeddingSearchResponse",
    "EmbeddingSearchResult",
    "RandomClipsRequest",
    "RandomClipsResponse",
    "SearchResultItem",
    "Feature",
    "FeatureName",
    "FeatureNameCreate",
    "FeatureNameUpdate",
    "FileState",
    "InferenceConfig",
    "InferenceJob",
    "InferenceJobCreate",
    "InferenceJobUpdate",
    "InferenceStatus",
    "InstallRequest",
    "InstallResponse",
    "License",
    "LicenseCreate",
    "LicenseUpdate",
    "ModelRun",
    "ModelRunCreate",
    "ModelRunUpdate",
    "ModelStatus",
    "ModelsStatus",
    "Note",
    "NoteCreate",
    "NoteUpdate",
    "Page",
    "Page",
    "PluginInfo",
    "PredictedTag",
    "Project",
    "ProjectCreate",
    "ProjectUpdate",
    "ProjectMember",
    "ProjectMemberCreate",
    "ProjectMemberUpdate",
    "Recording",
    "RecordingCreate",
    "RecordingNote",
    "RecordingTag",
    "RecordingUpdate",
    "STFTParameters",
    "Scale",
    "SimpleUser",
    "Recorder",
    "RecorderCreate",
    "RecorderUpdate",
    "Site",
    "SiteCreate",
    "SiteUpdate",
    "SiteImage",
    "SiteImageCreate",
    "SiteImageUpdate",
    "SpeciesCandidate",
    "SoundEvent",
    "SoundEventAnnotation",
    "SoundEventAnnotationCreate",
    "SoundEventAnnotationNote",
    "SoundEventAnnotationTag",
    "SoundEventAnnotationUpdate",
    "SoundEventCreate",
    "SoundEventEvaluation",
    "SoundEventEvaluationCreate",
    "SoundEventEvaluationUpdate",
    "SoundEventPrediction",
    "SoundEventPredictionCreate",
    "SoundEventPredictionTag",
    "SoundEventPredictionUpdate",
    "SoundEventEmbedding",
    "SoundEventUpdate",
    "SpectrogramParameters",
    "Tag",
    "TagCount",
    "TagCreate",
    "TagUpdate",
    "User",
    "UserCreate",
    "UserRun",
    "UserRunCreate",
    "UserRunUpdate",
    "UserAdminUpdate",
    "UserUpdate",
    "Window",
]
