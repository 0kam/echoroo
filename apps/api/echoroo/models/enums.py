"""Enum types for database models."""

from enum import Enum


class ProjectVisibility(str, Enum):
    """Project visibility levels."""

    PRIVATE = "private"
    PUBLIC = "public"


class ProjectRole(str, Enum):
    """Project member roles with different permission levels."""

    ADMIN = "admin"  # Full control: manage members, edit settings, edit data
    MEMBER = "member"  # Can view and edit data
    VIEWER = "viewer"  # Read-only access


class SettingType(str, Enum):
    """System setting value types."""

    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    JSON = "json"


class DatasetVisibility(str, Enum):
    """Dataset visibility levels."""

    PRIVATE = "private"  # Only owner can access
    PUBLIC = "public"  # All authenticated users can view


class DatasetStatus(str, Enum):
    """Dataset import status."""

    PENDING = "pending"  # Created, not yet scanning
    SCANNING = "scanning"  # Discovering audio files
    PROCESSING = "processing"  # Importing recordings
    COMPLETED = "completed"  # Import finished successfully
    FAILED = "failed"  # Import failed with error


class DatetimeParseStatus(str, Enum):
    """Recording datetime parse status."""

    PENDING = "pending"  # Not yet attempted
    SUCCESS = "success"  # Parsed successfully
    FAILED = "failed"  # Parse failed
