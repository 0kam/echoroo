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
