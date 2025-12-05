"""Custom exceptions for Echoroo."""

__all__ = [
    "NotFoundError",
    "DuplicateObjectError",
    "MissingDatabaseError",
    "InvalidDataError",
    "PermissionDeniedError",
    "DataIntegrityError",
]


class NotFoundError(RuntimeError):
    """Raised when a resource is not found."""


class DuplicateObjectError(RuntimeError):
    """Raised when a duplicate object was tried to be created.

    This is used for tags or for other resources are uniquely identified
    by a set of fields.
    """


class MissingDatabaseError(RuntimeError):
    """Raised when the database is not available."""


class InvalidDataError(RuntimeError):
    """Raised when the provided payload violates business rules."""


class PermissionDeniedError(RuntimeError):
    """Raised when the acting user is not allowed to perform an action."""


class DataIntegrityError(RuntimeError):
    """Raised if the operation is canceled due to database constraints.

    These could be caused by cascading deletes clashing with foreign keys
    restrictions.
    """
