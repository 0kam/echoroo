"""Structural tests for :mod:`echoroo.core.endpoint_allowlist` (spec/007 AD-5).

Phase 2A.1 smoke test. The full audit lint (AST scan for
``superuser_only`` / ``token_auth_only`` dependencies) lands in Phase 3.2 as
``tests/contract/test_allowlist_metadata.py``.

The structural invariants asserted here are also enforced at module import
time via ``_validate_allowlist`` — these tests duplicate that contract so
test failures surface a single concrete violation rather than an
``ImportError`` cascade.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from echoroo.core.endpoint_allowlist import (
    ALLOWLIST,
    AllowlistCategory,
    AllowlistEntry,
    is_allowlisted,
)


def test_allowlist_is_non_empty() -> None:
    """ALLOWLIST should contain at least the canonical auth + infra entries."""
    assert len(ALLOWLIST) > 0, "ALLOWLIST must contain at least one entry"


def test_every_entry_has_descriptive_reason() -> None:
    """AD-5: ``reason`` must be non-empty and >= 20 chars for auditability."""
    offenders = [
        entry
        for entry in ALLOWLIST
        if not entry.reason or len(entry.reason) < 20
    ]
    assert not offenders, (
        "ALLOWLIST entries with reason < 20 chars (AD-5 lint):\n  - "
        + "\n  - ".join(f"{e.path_pattern} ({len(e.reason)} chars)" for e in offenders)
    )


def test_every_entry_has_owner() -> None:
    """AD-5: ``owner`` is required so review can be routed."""
    offenders = [entry for entry in ALLOWLIST if not entry.owner]
    assert not offenders, (
        "ALLOWLIST entries missing owner (AD-5 lint):\n  - "
        + "\n  - ".join(e.path_pattern for e in offenders)
    )


def test_no_entry_is_past_its_review_by_date() -> None:
    """AD-5 (Rev.3 inverted condition fix per Codex Rev.3 重要-1).

    ``last_reviewed_at + review_interval_days >= today`` — entries past
    their review-by date fail CI so the allowlist cannot rot silently.
    """
    today = date.today()
    offenders: list[tuple[AllowlistEntry, date]] = []
    for entry in ALLOWLIST:
        deadline = entry.last_reviewed_at + timedelta(days=entry.review_interval_days)
        if deadline < today:
            offenders.append((entry, deadline))
    assert not offenders, (
        "ALLOWLIST entries past their review-by date (AD-5 lint):\n  - "
        + "\n  - ".join(
            f"{entry.path_pattern}: last_reviewed={entry.last_reviewed_at}, "
            f"deadline={deadline}, today={today}"
            for entry, deadline in offenders
        )
    )


def test_project_scoped_entries_opt_in_explicitly() -> None:
    """AD-5: paths containing ``{project_id}`` MUST set ``project_scope_allowed=True``.

    This prevents project-scoped endpoints from silently landing in the
    allowlist (Codex Rev.2 Q12).
    """
    offenders = [
        entry
        for entry in ALLOWLIST
        if "{project_id}" in entry.path_pattern and not entry.project_scope_allowed
    ]
    assert not offenders, (
        "ALLOWLIST entries with {project_id} but project_scope_allowed=False:\n  - "
        + "\n  - ".join(e.path_pattern for e in offenders)
    )


def test_every_entry_has_methods() -> None:
    """An empty ``methods`` set would silently match every HTTP verb."""
    offenders = [entry for entry in ALLOWLIST if not entry.methods]
    assert not offenders, (
        "ALLOWLIST entries with empty methods set:\n  - "
        + "\n  - ".join(e.path_pattern for e in offenders)
    )


def test_superuser_only_category_is_empty() -> None:
    """AD-6: admin endpoints are Actions, not allowlist entries.

    ``AllowlistCategory.SUPERUSER_ONLY`` is reserved as an escape hatch
    and is currently unused. Adding an entry there requires an
    accompanying spec amendment.
    """
    superuser_entries = [
        entry for entry in ALLOWLIST if entry.category == AllowlistCategory.SUPERUSER_ONLY
    ]
    assert not superuser_entries, (
        "AllowlistCategory.SUPERUSER_ONLY is reserved per AD-6 — admin "
        "endpoints must be registered as Actions with is_superuser_only=True, "
        "not added to ALLOWLIST."
    )


class TestIsAllowlisted:
    """Smoke tests for the :func:`is_allowlisted` matcher."""

    @pytest.mark.parametrize(
        ("path", "method"),
        [
            ("/web-api/v1/auth/login", "POST"),
            ("/web-api/v1/auth/2fa/challenge", "POST"),
            ("/api/v1/users/me", "GET"),
            ("/api/v1/users/me", "PATCH"),
            ("/api/v1/users/me/password", "PUT"),
            ("/health", "GET"),
            ("/openapi.json", "GET"),
            # W2-3 PR-2: the bootstrap status probe now lives only on the BFF.
            ("/web-api/v1/setup/status", "GET"),
        ],
    )
    def test_known_allowlisted_paths(self, path: str, method: str) -> None:
        assert is_allowlisted(path, method), f"{method} {path} should be allowlisted"

    @pytest.mark.parametrize(
        ("path", "method"),
        [
            ("/api/v1/projects", "GET"),
            ("/api/v1/projects/abc-123/recordings", "GET"),
            ("/api/v1/detections", "GET"),
            ("/web-api/v1/projects/abc-123/members", "GET"),
        ],
    )
    def test_unrelated_paths_are_not_allowlisted(self, path: str, method: str) -> None:
        assert not is_allowlisted(path, method), (
            f"{method} {path} should NOT be allowlisted"
        )

    def test_placeholder_segment_matches_uuid(self) -> None:
        """``{project_id}`` placeholder matches a single non-slash segment."""
        path = (
            "/web-api/v1/projects/8b3a5f12-1234-4abc-9def-0123456789ab/"
            "invitations/abcdef0123456789/accept"
        )
        assert is_allowlisted(path, "POST")

    def test_wrong_method_does_not_match(self) -> None:
        # /web-api/v1/auth/login is POST-only (W2-3 Option C removed the
        # legacy /api/v1 login entry together with its route).
        assert not is_allowlisted("/web-api/v1/auth/login", "GET")

    def test_xeno_canto_search_is_external_proxy(self) -> None:
        path = "/api/v1/projects/8b3a5f12-1234-4abc-9def-0123456789ab/xeno-canto/search"
        assert is_allowlisted(path, "GET")
