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
from echoroo.models.detection import Detection
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
    ProjectInvitationKind,
    ProjectInvitationStatus,
    ProjectLicense,
    ProjectMemberRole,
    ProjectStatus,
    ProjectTrustedStatus,
    ProjectVisibility,
    ReviewStatus,
    SearchSessionStatus,
    SettingType,
    SignalQuality,
    TagCategory,
    TaxonOverrideApprovalStatus,
    TaxonOverrideDirection,
    TaxonSensitivitySource,
    UploadFileStatus,
    UploadSessionStatus,
    VoteType,
)
from echoroo.models.evaluation import (
    EvaluationResult,
    EvaluationRun,
    EvaluationRunStatus,
)
from echoroo.models.iucn_sync_attempt import IucnSyncAttempt
from echoroo.models.license import License
from echoroo.models.note import Note
from echoroo.models.password_reset_token import PasswordResetToken
from echoroo.models.project import Project, ProjectInvitation, ProjectLicenseHistory, ProjectMember
from echoroo.models.project_taxon_override import ProjectTaxonSensitivityOverride
from echoroo.models.project_trusted_user import ProjectTrustedUser
from echoroo.models.recorder import Recorder
from echoroo.models.recording import Recording
from echoroo.models.recording_annotation import RecordingAnnotation
from echoroo.models.sampling_round import SamplingRound, SamplingRoundItem
from echoroo.models.search_query_embedding import SearchQueryEmbedding
from echoroo.models.search_session import SearchSession
from echoroo.models.site import Site
from echoroo.models.sound_event_annotation import SoundEventAnnotation, sound_event_annotation_tags
from echoroo.models.superuser import Superuser
from echoroo.models.superuser_approval_request import SuperuserApprovalRequest
from echoroo.models.system import SystemSetting
from echoroo.models.tag import Tag
from echoroo.models.taxon import Taxon
from echoroo.models.taxon_sensitivity import TaxonSensitivity
from echoroo.models.taxon_vernacular_name import TaxonVernacularName
from echoroo.models.upload import UploadFile, UploadSession
from echoroo.models.user import User
from echoroo.models.user_login_notification_seen import UserLoginNotificationSeen

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
    "ProjectTaxonSensitivityOverride",
    "ProjectTrustedUser",
    "PasswordResetToken",
    "Recorder",
    "Recording",
    "Site",
    "Superuser",
    "SuperuserApprovalRequest",
    "SystemSetting",
    "User",
    "UserLoginNotificationSeen",
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
    "TaxonSensitivity",
    "TaxonVernacularName",
    # Taxon-driven auto-obscure (Phase 11)
    "IucnSyncAttempt",
    # Detection review models (003-detection-review)
    "Annotation",
    "AnnotationComment",
    "AnnotationVote",
    "ConfirmedRegion",
    "Detection",
    "DetectionRun",
    # Phase 14+ deferred (recording-level annotation review state)
    "RecordingAnnotation",
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
    "ProjectInvitationKind",
    "ProjectInvitationStatus",
    "ProjectLicense",
    "ProjectMemberRole",
    "ProjectStatus",
    "ProjectTrustedStatus",
    "ProjectVisibility",
    "SettingType",
    # Enums (taxon sensitivity)
    "TaxonOverrideApprovalStatus",
    "TaxonOverrideDirection",
    "TaxonSensitivitySource",
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
