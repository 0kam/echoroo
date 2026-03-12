"""Enum types for database models."""

from enum import StrEnum


class ProjectVisibility(StrEnum):
    """Project visibility levels."""

    PRIVATE = "private"
    PUBLIC = "public"


class ProjectRole(StrEnum):
    """Project member roles with different permission levels."""

    ADMIN = "admin"  # Full control: manage members, edit settings, edit data
    MEMBER = "member"  # Can view and edit data
    VIEWER = "viewer"  # Read-only access


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
    HUMAN = "human"


class DetectionStatus(StrEnum):
    """Detection review status."""

    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


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
