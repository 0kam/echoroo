"""Database models."""

from echoroo.models.annotation import Annotation
from echoroo.models.annotation_comment import AnnotationComment
from echoroo.models.annotation_project import (
    AnnotationProject,
    annotation_project_datasets,
    annotation_project_tags,
)
from echoroo.models.annotation_set import (
    AnnotationSegment,
    AnnotationSet,
    TimeRangeAnnotation,
    annotation_segment_notes,
    annotation_set_species_palette,
    time_range_annotation_notes,
)
from echoroo.models.annotation_task import AnnotationTask
from echoroo.models.annotation_vote import AnnotationVote
from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.clip import Clip
from echoroo.models.clip_annotation import ClipAnnotation, clip_annotation_tags
from echoroo.models.confirmed_region import ConfirmedRegion
from echoroo.models.custom_model import CustomModel, CustomModelStatus
from echoroo.models.dataset import Dataset
from echoroo.models.detection_run import DetectionRun
from echoroo.models.embedding import Embedding
from echoroo.models.enums import (
    AnnotationProjectVisibility,
    AnnotationSegmentStatus,
    AnnotationSetStatus,
    AnnotationSource,
    AnnotationTaskStatus,
    AnnotationVoteSource,
    ConsensusStatus,
    DatasetStatus,
    DatasetVisibility,
    DatetimeParseStatus,
    DetectionRunStatus,
    DetectionSource,
    DetectionStatus,
    GeometryType,
    ProjectLicense,
    ProjectMemberRole,
    ProjectStatus,
    ProjectVisibility,
    ReviewStatus,
    SearchSessionStatus,
    SettingType,
    SignalQuality,
    TagCategory,
    UploadFileStatus,
    UploadSessionStatus,
    VoteType,
)
from echoroo.models.evaluation import (
    EvaluationResult,
    EvaluationRun,
    EvaluationRunStatus,
)
from echoroo.models.license import License
from echoroo.models.note import Note
from echoroo.models.project import Project, ProjectInvitation, ProjectLicenseHistory, ProjectMember
from echoroo.models.recorder import Recorder
from echoroo.models.recording import Recording
from echoroo.models.sampling_round import SamplingRound, SamplingRoundItem
from echoroo.models.search_query_embedding import SearchQueryEmbedding
from echoroo.models.search_session import SearchSession
from echoroo.models.site import Site
from echoroo.models.sound_event_annotation import SoundEventAnnotation, sound_event_annotation_tags
from echoroo.models.system import SystemSetting
from echoroo.models.tag import Tag
from echoroo.models.taxon import Taxon
from echoroo.models.taxon_vernacular_name import TaxonVernacularName
from echoroo.models.upload import UploadFile, UploadSession
from echoroo.models.user import APIToken, LoginAttempt, User

__all__ = [
    # Base
    "Base",
    "TimestampMixin",
    "UUIDMixin",
    # Core models
    "Clip",
    "Dataset",
    "License",
    "Project",
    "ProjectInvitation",
    "ProjectLicenseHistory",
    "ProjectMember",
    "Recorder",
    "Recording",
    "Site",
    "SystemSetting",
    "APIToken",
    "LoginAttempt",
    "User",
    # Annotation models (existing)
    "AnnotationProject",
    "AnnotationTask",
    "ClipAnnotation",
    "SoundEventAnnotation",
    "Note",
    "Tag",
    # Ground-truth annotation models (003-annotation)
    "AnnotationSet",
    "AnnotationSegment",
    "TimeRangeAnnotation",
    # Taxon models
    "Taxon",
    "TaxonVernacularName",
    # Detection review models (003-detection-review)
    "Annotation",
    "AnnotationComment",
    "AnnotationVote",
    "ConfirmedRegion",
    "DetectionRun",
    # Custom model (SVM classifier)
    "CustomModel",
    "SamplingRound",
    "SamplingRoundItem",
    # Search session models
    "SearchSession",
    "SearchQueryEmbedding",
    # ML embedding models
    "Embedding",
    # Upload models
    "UploadSession",
    "UploadFile",
    # Association tables
    "annotation_project_datasets",
    "annotation_project_tags",
    "annotation_segment_notes",
    "annotation_set_species_palette",
    "clip_annotation_tags",
    "sound_event_annotation_tags",
    "time_range_annotation_notes",
    # Enums (core)
    "DatasetStatus",
    "DatasetVisibility",
    "DatetimeParseStatus",
    "ProjectLicense",
    "ProjectMemberRole",
    "ProjectStatus",
    "ProjectVisibility",
    "SettingType",
    # Enums (annotation)
    "AnnotationProjectVisibility",
    "AnnotationSegmentStatus",
    "AnnotationSetStatus",
    "AnnotationSource",
    "AnnotationTaskStatus",
    "GeometryType",
    "ReviewStatus",
    "SignalQuality",
    "TagCategory",
    # Enums (detection review)
    "DetectionSource",
    "DetectionStatus",
    "DetectionRunStatus",
    "AnnotationVoteSource",
    "VoteType",
    "ConsensusStatus",
    # Enums (custom model)
    "CustomModelStatus",
    # Evaluation (003-annotation A3)
    "EvaluationRun",
    "EvaluationResult",
    "EvaluationRunStatus",
    # Enums (search session)
    "SearchSessionStatus",
    # Enums (upload)
    "UploadSessionStatus",
    "UploadFileStatus",
]
