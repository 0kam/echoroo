"""Shared text safety helpers."""

from __future__ import annotations


def has_control_chars(value: str) -> bool:
    """Return True when ``value`` contains ASCII control characters."""
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
