"""S3 PutObject metadata sanitizer (FR-028e).

This module provides a preprocessor that strips raw GPS / latitude / longitude
metadata from boto3 ``s3.put_object(...)`` keyword arguments before they are
sent to the storage backend. It exists to enforce spec FR-028e, which mandates
that S3 object metadata never carries raw lat/lng coordinates so that an S3
bucket compromise (or an internal log pipeline that mirrors object metadata)
cannot leak observation locations.

Strip target keys (case-insensitive, applied to ``Metadata`` dict keys only):

* ``lat``, ``latitude``
* ``lng``, ``lon``, ``longitude``
* ``gps`` and any key with prefix ``gps_`` / ``gps-``
* ``geo`` and any key with prefix ``geo_`` / ``geo-``
* ``coord``, ``coords`` and any key with prefix ``coord_`` / ``coord-``
* ``location`` and any key with prefix ``location_`` / ``location-``

The sanitizer never modifies non-``Metadata`` kwargs (``Bucket``, ``Key``,
``Body``, ``ContentType``, ``ACL``, ...). When a key is removed, a structured
log entry is emitted at INFO level::

    event="s3_metadata_gps_stripped" keys=[<list of removed keys>]

Usage (callers must thread their PutObject kwargs through this function)::

    from echoroo.services.s3_upload_sanitizer import sanitize_put_object_kwargs

    kwargs = sanitize_put_object_kwargs({
        "Bucket": "echoroo-uploads",
        "Key": object_key,
        "Body": payload,
        "Metadata": user_supplied_metadata,
    })
    s3_client.put_object(**kwargs)

A future utility ``wrap_s3_client`` may monkey-patch ``put_object`` to invoke
this sanitizer transparently; that is intentionally out of scope for this
module to keep the surface small and easy to audit.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ["sanitize_put_object_kwargs"]

logger = logging.getLogger(__name__)

# Exact lowercase key names that must be removed.
_GPS_EXACT_KEYS: frozenset[str] = frozenset(
    {
        "lat",
        "latitude",
        "lng",
        "lon",
        "longitude",
        "gps",
        "geo",
        "coord",
        "coords",
        "location",
    }
)

# Prefixes (lowercase) that must be removed when followed by "_" or "-".
_GPS_PREFIXES: tuple[str, ...] = (
    "gps_",
    "gps-",
    "geo_",
    "geo-",
    "coord_",
    "coord-",
    "location_",
    "location-",
)


def _is_gps_key(key: str) -> bool:
    """Return True if ``key`` (case-insensitive) refers to GPS-derived data."""
    lowered = key.strip().lower()
    if lowered in _GPS_EXACT_KEYS:
        return True
    return any(lowered.startswith(prefix) for prefix in _GPS_PREFIXES)


def sanitize_put_object_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Strip GPS-bearing metadata keys from ``s3.put_object`` kwargs.

    Args:
        kwargs: Keyword arguments destined for ``boto3 s3.put_object(...)``.
            The ``Metadata`` entry, if present, must be a ``dict[str, str]``
            (S3 object metadata convention). Non-``Metadata`` keys are passed
            through untouched.

    Returns:
        A new dict with the same shape as ``kwargs``. The ``Metadata`` dict
        (if present) has GPS-bearing keys removed. The original ``kwargs``
        and its nested ``Metadata`` dict are not mutated.

    Notes:
        * If ``Metadata`` is absent, the function returns a shallow copy.
        * If ``Metadata`` is present but contains no GPS keys, the returned
          ``Metadata`` is a new dict with identical contents (defensive copy).
        * Removed keys are logged once per call at INFO level under the
          ``s3_metadata_gps_stripped`` event for security observability
          (FR-028e + FR-028c log-redaction guarantees).
    """
    sanitized: dict[str, Any] = dict(kwargs)
    metadata = sanitized.get("Metadata")
    if not isinstance(metadata, dict):
        return sanitized

    cleaned: dict[str, Any] = {}
    removed: list[str] = []
    for key, value in metadata.items():
        # Only string keys are valid S3 object metadata; leave non-str keys
        # for boto3 to reject downstream rather than silently masking them.
        if isinstance(key, str) and _is_gps_key(key):
            removed.append(key)
            continue
        cleaned[key] = value

    if removed:
        logger.info(
            "s3_metadata_gps_stripped",
            extra={"event": "s3_metadata_gps_stripped", "keys": removed},
        )

    sanitized["Metadata"] = cleaned
    return sanitized
