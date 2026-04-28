"""Enum types for database models."""

from enum import StrEnum


class ProjectVisibility(StrEnum):
    """Project visibility levels."""

    PUBLIC = "public"
    RESTRICTED = "restricted"


class ProjectMemberRole(StrEnum):
    """Project member roles with different permission levels."""

    VIEWER = "viewer"
    MEMBER = "member"
    ADMIN = "admin"


class ProjectInvitationKind(StrEnum):
    """Kind of a :class:`ProjectInvitation`.

    FR-047: a single ``project_invitations`` table covers both Member and
    Trusted invitations. The ``kind`` discriminator selects which subset
    of columns is mandatory (see ``ck_project_invitations_kind_fields``).
    """

    MEMBER = "member"
    TRUSTED = "trusted"


class ProjectInvitationStatus(StrEnum):
    """Lifecycle of a :class:`ProjectInvitation`.

    FR-053: ``pending`` is the only state from which ``accept`` may
    transition. Status × timestamp consistency is guarded by
    ``ck_project_invitations_status_timestamps`` in the baseline migration.
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ProjectTrustedStatus(StrEnum):
    """Lifecycle of a :class:`ProjectTrustedUser` overlay.

    FR-041 / FR-044: ``active`` is the only state for which the gate may
    grant overlay permissions. ``expired`` is set by the auto-expire
    worker (T516); ``revoked`` is set explicitly by Owner/Admin via
    :func:`echoroo.services.trusted_service.revoke_trusted_user`.
    """

    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ProjectStatus(StrEnum):
    """Project lifecycle status."""

    ACTIVE = "active"
    DORMANT = "dormant"
    ARCHIVED = "archived"


class ProjectLicense(StrEnum):
    """Project data license."""

    CC0 = "CC0"
    CC_BY = "CC-BY"
    CC_BY_NC = "CC-BY-NC"
    CC_BY_SA = "CC-BY-SA"


class SettingType(StrEnum):
    """System setting value types."""

    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    JSON = "json"


class DatasetVisibility(StrEnum):
    """Dataset visibility levels."""

    PRIVATE = "private"  # Only owner can access
    PUBLIC = "public"  # All authenticated users can view


class DatasetStatus(StrEnum):
    """Dataset import status."""

    PENDING = "pending"  # Created, not yet scanning
    SCANNING = "scanning"  # Discovering audio files
    PROCESSING = "processing"  # Importing recordings
    COMPLETED = "completed"  # Import finished successfully
    FAILED = "failed"  # Import failed with error


class DatetimeParseStatus(StrEnum):
    """Recording datetime parse status."""

    PENDING = "pending"  # Not yet attempted
    SUCCESS = "success"  # Parsed successfully
    FAILED = "failed"  # Parse failed


class TagCategory(StrEnum):
    """Tag classification categories."""

    SPECIES = "species"
    SOUND_TYPE = "sound_type"
    QUALITY = "quality"


class AnnotationProjectVisibility(StrEnum):
    """Annotation project visibility levels."""

    PRIVATE = "private"
    PUBLIC = "public"


class AnnotationTaskStatus(StrEnum):
    """Annotation task workflow status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REVIEW_PENDING = "review_pending"


class ReviewStatus(StrEnum):
    """Clip annotation review status."""

    UNREVIEWED = "unreviewed"
    APPROVED = "approved"
    REJECTED = "rejected"


class AnnotationSource(StrEnum):
    """Source of annotation (human annotator or ML model)."""

    HUMAN = "human"
    MODEL = "model"


class GeometryType(StrEnum):
    """Sound event geometry types."""

    BOUNDING_BOX = "BoundingBox"
    TIME_INTERVAL = "TimeInterval"


class DetectionSource(StrEnum):
    """Source of detection (ML model or human reviewer)."""

    BIRDNET = "birdnet"
    PERCH = "perch"
    PERCH_SEARCH = "perch_search"
    SIMILARITY_SEARCH = "similarity_search"
    CUSTOM_SVM = "custom_svm"
    HUMAN = "human"
    SAMPLING_ROUND = "sampling_round"  # Created by seed sampling or active learning pipeline


class DetectionStatus(StrEnum):
    """Detection review status."""

    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class VoteType(StrEnum):
    """Vote type for annotation voting."""

    AGREE = "agree"
    DISAGREE = "disagree"
    UNSURE = "unsure"


class AnnotationVoteSource(StrEnum):
    """Source classification for annotation votes and comments."""

    MEMBER = "member"
    GUEST_AUTHENTICATED = "guest_authenticated"
    TRUSTED_USER = "trusted_user"


class TaxonSensitivitySource(StrEnum):
    """Source of a global :class:`TaxonSensitivity` row (FR-032).

    The auto-obscure pipeline (FR-029..032) ranks rows so that ``manual`` wins
    over ``moe_rdb`` which wins over ``iucn`` when computing the effective
    masking resolution for a taxon (spec L313-365 ``compute_effective_resolution``).
    """

    IUCN = "iucn"
    MOE_RDB = "moe_rdb"
    MANUAL = "manual"


class TaxonOverrideDirection(StrEnum):
    """Direction of a per-project taxon sensitivity override (FR-033).

    ``stricter`` means the project owner increases masking (lower H3 res);
    these apply immediately. ``looser`` means the owner relaxes masking
    (higher H3 res); these require superuser approval (FR-034) and may be
    rejected, captured by the companion
    :class:`TaxonOverrideApprovalStatus` enum.
    """

    STRICTER = "stricter"
    LOOSER = "looser"


class TaxonOverrideApprovalStatus(StrEnum):
    """Approval lifecycle for a project taxon override (FR-034).

    A ``stricter`` override is always created with ``applied`` (no approval
    needed). A ``looser`` override is created with ``pending_superuser_approval``
    and transitions to ``applied`` once a superuser approves, or ``rejected``
    if denied. The CHECK constraint ``ck_taxon_overrides_direction_vs_approval``
    in the baseline migration enforces these legal combinations.
    """

    APPLIED = "applied"
    PENDING_SUPERUSER_APPROVAL = "pending_superuser_approval"
    REJECTED = "rejected"


class SignalQuality(StrEnum):
    """Signal quality assessment for agree votes.

    Describes how prominently the target species appears in the audio clip.
    Only applicable when the vote is 'agree'.
    """

    SOLO = "solo"          # Only this species, very clear
    DOMINANT = "dominant"  # This species is dominant but others present
    MIXED = "mixed"        # This species present but other species more prominent


class ConsensusStatus(StrEnum):
    """Consensus status computed from annotation votes."""

    NEEDS_VOTES = "needs_votes"  # Not enough votes yet (agree + disagree < min_votes)
    AGREED = "agreed"            # Score > threshold AND agree >= min_votes
    REJECTED = "rejected"        # Score <= (1 - threshold) AND disagree >= min_votes
    DISPUTED = "disputed"        # Has enough votes but no clear consensus


class DetectionRunStatus(StrEnum):
    """Detection run execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class UploadSessionStatus(StrEnum):
    """Upload session lifecycle states."""

    ISSUED = "issued"        # Presigned URLs generated, waiting for upload
    UPLOADED = "uploaded"    # Server verified files exist in S3
    VALIDATING = "validating"  # Worker running ffprobe validation
    VALIDATED = "validated"  # All files validated (some may be invalid)
    IMPORTING = "importing"  # Creating recording records
    IMPORTED = "imported"    # All recordings created
    FAILED = "failed"        # Error at any stage


class UploadFileStatus(StrEnum):
    """Individual file status within an upload session."""

    PENDING = "pending"    # Presigned URL issued, not yet uploaded
    UPLOADED = "uploaded"  # Verified in S3
    VALID = "valid"        # Passed ffprobe validation
    INVALID = "invalid"    # Failed validation
    IMPORTED = "imported"  # Recording record created


class SearchSessionStatus(StrEnum):
    """Search session execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AnnotationSetStatus(StrEnum):
    """Lifecycle status for an AnnotationSet (ground-truth reference collection).

    Values:
        SAMPLING: Background sampling job is materializing segments.
        READY: Sampling finished; segments are available for annotation.
        IN_PROGRESS: At least one segment has been annotated or skipped.
        COMPLETED: Every child segment is either annotated or skipped.
    """

    SAMPLING = "sampling"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class AnnotationSegmentStatus(StrEnum):
    """Lifecycle status for an AnnotationSegment.

    Values:
        UNANNOTATED: Segment has not yet been reviewed by an annotator.
        ANNOTATED: Annotator finalized the segment (with time-range annotations
            or explicitly marked empty).
        SKIPPED: Annotator skipped this segment; it is excluded from evaluation
            denominators.
    """

    UNANNOTATED = "unannotated"
    ANNOTATED = "annotated"
    SKIPPED = "skipped"
