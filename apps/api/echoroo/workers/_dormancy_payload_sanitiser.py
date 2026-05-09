"""Shared payload sanitisation helper for dormancy outbox events.

Extracted from :mod:`echoroo.workers.dormancy_check` so the helper
modules introduced in Phase 17 §D-1-bis (``_dormancy_events``) can
import the same NFKC + control-char + length contract without
re-creating an import cycle through ``dormancy_check`` itself.

Behaviour mirrors the original ``_sanitise_field`` 1:1 (FR-101b parity
with :mod:`echoroo.workers.trusted_expiry_dispatcher`).
"""

from __future__ import annotations

import unicodedata
from typing import Final

from echoroo.core.text import has_control_chars

#: Hard cap for outbox payload string fields. Mirrors the convention
#: used by :mod:`echoroo.workers.trusted_expiry_dispatcher` so the
#: dispatcher side does not have to special-case long values.
MAX_FIELD_LEN: Final[int] = 500


class DormancyPayloadError(ValueError):
    """Raised when a sanitised payload field carries invalid bytes."""


def sanitise_field(value: object, *, field_name: str) -> str:
    """NFKC-normalise, reject control chars, truncate to the hard cap."""
    if value is None:
        return ""
    raw = str(value)
    normalised = unicodedata.normalize("NFKC", raw).strip()
    if has_control_chars(normalised):
        raise DormancyPayloadError(
            f"dormancy notification payload field {field_name!r} "
            "contains control characters",
        )
    if len(normalised) > MAX_FIELD_LEN:
        normalised = normalised[:MAX_FIELD_LEN]
    return normalised


__all__ = [
    "MAX_FIELD_LEN",
    "DormancyPayloadError",
    "sanitise_field",
]
