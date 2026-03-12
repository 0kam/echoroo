"""Database models."""

from echoroo.models.annotation import Annotation
from echoroo.models.annotation_project import (
    AnnotationProject,
    annotation_project_datasets,
    annotation_project_tags,
)
from echoroo.models.annotation_task import AnnotationTask
from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.clip import Clip
from echoroo.models.clip_annotation import ClipAnnotation, clip_annotation_tags
from echoroo.models.confirmed_region import ConfirmedRegion
from echoroo.models.dataset import Dataset
from echoroo.models.detection_run import DetectionRun
from echoroo.models.embedding import Embedding
from echoroo.models.enums import (
    AnnotationProjectVisibility,
    AnnotationSource,
    AnnotationTaskStatus,
    DatasetStatus,
    DatasetVisibility,
    DatetimeParseStatus,
    DetectionRunStatus,
    DetectionSource,
    DetectionStatus,
    GeometryType,
    ProjectRole,
    ProjectVisibility,
    ReviewStatus,
    SearchSessionStatus,
    SettingType,
    TagCategory,
    UploadFileStatus,
    UploadSessionStatus,
)
from echoroo.models.license import License
from echoroo.models.note import Note
from echoroo.models.project import Project, ProjectInvitation, ProjectMember
from echoroo.models.recorder import Recorder
from echoroo.models.recording import Recording
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
    # Taxon models
    "Taxon",
    "TaxonVernacularName",
    # Detection review models (003-detection-review)
    "Annotation",
    "ConfirmedRegion",
    "DetectionRun",
    # Search session models
    "SearchSession",
    # ML embedding models
    "Embedding",
    # Upload models
    "UploadSession",
    "UploadFile",
    # Association tables
    "annotation_project_datasets",
    "annotation_project_tags",
    "clip_annotation_tags",
    "sound_event_annotation_tags",
    # Enums (core)
    "DatasetStatus",
    "DatasetVisibility",
    "DatetimeParseStatus",
    "ProjectRole",
    "ProjectVisibility",
    "SettingType",
    # Enums (annotation)
    "AnnotationProjectVisibility",
    "AnnotationSource",
    "AnnotationTaskStatus",
    "GeometryType",
    "ReviewStatus",
    "TagCategory",
    # Enums (detection review)
    "DetectionSource",
    "DetectionStatus",
    "DetectionRunStatus",
    # Enums (search session)
    "SearchSessionStatus",
    # Enums (upload)
    "UploadSessionStatus",
    "UploadFileStatus",
]
