"""Shared constants for the ML module.

This module centralizes constants used across multiple ML components
to ensure consistency and reduce duplication.

Constants are organized by category:
- Non-species labels: Environmental sounds that should not be resolved via GBIF
- Default inference parameters: Common defaults for batch processing
- Rate limiting: API call rate limiting defaults
"""

from __future__ import annotations

__all__ = [
    # Non-species labels
    "NON_SPECIES_LABELS",
    "is_non_species_label",
    # Inference defaults
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "DEFAULT_TOP_K",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_FEEDERS",
    "DEFAULT_WORKERS",
    # Rate limiting
    "GBIF_RATE_LIMIT_CALLS",
    "GBIF_RATE_LIMIT_PERIOD",
    # GBIF language codes
    "GBIF_LANG_CODE_MAP",
    # Training validation
    "MIN_POSITIVE_SAMPLES",
    "MIN_NEGATIVE_SAMPLES",
]

# ---------------------------------------------------------------------------
# Non-species labels
# ---------------------------------------------------------------------------
# Labels where the scientific and common name parts are identical or represent
# environmental sounds, not biological species. These should not be resolved
# via GBIF as they can match unrelated species (e.g., "Engine" -> "Enginella").

NON_SPECIES_LABELS: frozenset[str] = frozenset({
    # Background/silence
    "background",
    "no call",
    "nocall",
    "silence",
    # Animals (non-bird)
    "dog",
    # Mechanical sounds
    "engine",
    "power tools",
    "siren",
    # Human sounds
    "human non-vocal",
    "human vocal",
    "human whistle",
    # Environmental
    "environmental",
    "fireworks",
    "gun",
    "noise",
})


def is_non_species_label(scientific_name: str, common_name: str | None = None) -> bool:
    """Check if a label represents a non-species sound.

    BirdNET includes labels for environmental sounds like "Engine_Engine",
    "Dog_Dog", "Noise_Noise", etc. These should not be resolved via GBIF
    as they can match unrelated species.

    Parameters
    ----------
    scientific_name : str
        The parsed scientific name part of the label.
    common_name : str | None
        The parsed common name part of the label.

    Returns
    -------
    bool
        True if this is a non-species environmental sound label.
    """
    # Check if the label follows the "X_X" pattern (same word repeated)
    if common_name and scientific_name.lower() == common_name.lower():
        return True

    # Check against known non-species labels
    if scientific_name.lower().strip() in NON_SPECIES_LABELS:
        return True

    return False


# ---------------------------------------------------------------------------
# Default inference parameters
# ---------------------------------------------------------------------------

DEFAULT_CONFIDENCE_THRESHOLD: float = 0.1
"""Default minimum confidence score for predictions."""

DEFAULT_TOP_K: int = 10
"""Default maximum number of top predictions to return per segment."""

DEFAULT_BATCH_SIZE: int = 16
"""Default batch size for GPU processing."""

DEFAULT_FEEDERS: int = 1
"""Default number of file reading processes."""

DEFAULT_WORKERS: int = 1
"""Default number of GPU inference workers."""


# ---------------------------------------------------------------------------
# Rate limiting defaults
# ---------------------------------------------------------------------------

GBIF_RATE_LIMIT_CALLS: int = 10
"""Maximum number of GBIF API calls per period."""

GBIF_RATE_LIMIT_PERIOD: float = 1.0
"""Rate limit period in seconds."""


# ---------------------------------------------------------------------------
# GBIF language code mapping
# ---------------------------------------------------------------------------

GBIF_LANG_CODE_MAP: dict[str, str] = {
    "ja": "jpn",
    "en": "eng",
    "de": "deu",
    "fr": "fra",
    "es": "spa",
    "it": "ita",
    "pt": "por",
    "nl": "nld",
    "sv": "swe",
    "fi": "fin",
    "da": "dan",
    "no": "nor",
    "pl": "pol",
    "ru": "rus",
    "zh": "zho",
    "ko": "kor",
    "cs": "ces",
    "sk": "slk",
    "hu": "hun",
    "ro": "ron",
    "tr": "tur",
    "th": "tha",
    "uk": "ukr",
    "ar": "ara",
    "af": "afr",
    "sl": "slv",
    "cat": "cat",
    "lav": "lav",
    "lit": "lit",
    "nor": "nor",
    "nld": "nld",
}
"""Mapping from ISO 639-1 (2-letter) to ISO 639-2/3 (3-letter) language codes.

GBIF API uses 3-letter language codes for vernacular names. This mapping
allows users to specify locales using common 2-letter codes (e.g., "ja", "en")
which are then converted to the 3-letter codes expected by GBIF (e.g., "jpn", "eng").
"""


# ---------------------------------------------------------------------------
# Training validation defaults
# ---------------------------------------------------------------------------

MIN_POSITIVE_SAMPLES: int = 3
"""Minimum number of positive samples required for training."""

MIN_NEGATIVE_SAMPLES: int = 3
"""Minimum number of negative samples required for training."""
