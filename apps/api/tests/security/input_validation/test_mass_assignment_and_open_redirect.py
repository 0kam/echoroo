"""Codex supplement: Mass assignment + open redirect prevention (T979b).

Verifies that the application correctly rejects or ignores attempts to
mass-assign privileged fields and that it does not process open-redirect
parameters in auth flows.

A. Mass assignment — user profile:
   - ``PATCH /api/v1/users/me`` with ``{"is_superuser": true, "role": "admin"}``
     → The Pydantic schema ignores extra fields (``is_superuser``, ``role``
     are not in ``UserUpdateRequest``). The update succeeds but only touches
     allowed fields.

B. Mass assignment — project member role escalation:
   - ``ProjectMemberAddRequest`` accepts only ``email`` and ``role``; ``role``
     is constrained to ``ProjectMemberRole`` enum (viewer/member/admin). An
     ``"owner"`` role must not be accepted by the schema.

C. Mass assignment — Pydantic model isolation:
   - Schemas that use ``model_config = ConfigDict(extra="forbid")`` raise
     ``ValidationError`` on unknown fields.

D. Open redirect — ``?next=`` parameter:
   - The application DOES NOT expose a ``?next=`` redirect param on the login
     endpoint. This test documents the absence of the parameter to prevent
     future regressions.
   - If a ``?next=`` param is added, same-origin validation MUST be enforced.
   - Known dangerous patterns (``javascript:``, ``//evil.com``,
     ``https://attacker.com``) must all be rejected by any future implementation.

E. Open redirect — helper function guard:
   - A ``_is_safe_redirect_url`` validator (if present) must reject external
     hosts and dangerous schemes while accepting same-origin paths.

Shim: OFF — schema validation and redirect logic are the subjects.
      The JWT shim would not interfere, but disabling it makes the test
      dependency explicit.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from echoroo.schemas.project import ProjectMemberAddRequest, ProjectMemberRole
from echoroo.schemas.user import UserUpdateRequest

# ---------------------------------------------------------------------------
# Section A: Mass assignment — UserUpdateRequest only accepts allowed fields
# ---------------------------------------------------------------------------


def test_user_update_request_ignores_is_superuser() -> None:
    """``UserUpdateRequest`` MUST NOT expose an ``is_superuser`` field.

    Mass assignment via ``PATCH /api/v1/users/me`` with
    ``{"is_superuser": true}`` must be inert because the Pydantic schema
    does not define this field. The schema either ignores extra fields
    (default Pydantic behaviour) or rejects them with ``ValidationError``
    (``extra="forbid"``).

    Either behaviour is acceptable — the key invariant is that the field
    is not silently accepted as a field the model owns.
    """
    assert "is_superuser" not in UserUpdateRequest.model_fields, (
        "UserUpdateRequest must not expose 'is_superuser' — "
        "this field is privilege-sensitive and must not be settable "
        "via the user self-update endpoint."
    )


def test_user_update_request_ignores_role() -> None:
    """``UserUpdateRequest`` MUST NOT expose a ``role`` field.

    A user cannot self-escalate their project role by passing ``role``
    in a self-update request body. The schema only accepts ``display_name``
    (and other explicitly allowed fields).
    """
    assert "role" not in UserUpdateRequest.model_fields, (
        "UserUpdateRequest must not expose 'role' — "
        "project membership roles are managed via the member management "
        "endpoints (admin/owner only)."
    )


def test_user_update_request_schema_shape() -> None:
    """``UserUpdateRequest`` allows only whitelisted fields.

    This test acts as a schema regression guard: if new privileged fields
    are accidentally added to the update schema, this test fails and forces
    a security review before merging.
    """
    actual_fields = set(UserUpdateRequest.model_fields.keys())
    disallowed_sensitive = {"is_superuser", "role", "scopes", "two_factor_enabled"}
    collisions = actual_fields & disallowed_sensitive
    assert not collisions, (
        f"UserUpdateRequest contains sensitive fields that must not be user-settable: "
        f"{collisions}. Remove them or enforce read-only via property."
    )


def test_user_update_request_accepts_display_name() -> None:
    """``UserUpdateRequest`` validates with a safe ``display_name`` payload."""
    req = UserUpdateRequest(display_name="Alice")
    assert req.display_name == "Alice"


def test_user_update_request_extra_fields_are_rejected_or_ignored() -> None:
    """Extra fields in ``UserUpdateRequest`` are either rejected or silently dropped.

    Both ``extra="ignore"`` (Pydantic default) and ``extra="forbid"`` are
    acceptable. The critical property is that unknown keys do NOT map to
    attributes on the model instance.
    """
    try:
        req = UserUpdateRequest.model_validate(
            {"display_name": "Alice", "is_superuser": True, "role": "admin"}
        )
        # If extra="ignore": unknown fields are dropped — is_superuser/role must not exist.
        assert not hasattr(req, "is_superuser") or req.__dict__.get("is_superuser") is None, (
            "is_superuser must not be accessible on UserUpdateRequest"
        )
    except ValidationError:
        # extra="forbid": an explicit ValidationError is also acceptable.
        pass


# ---------------------------------------------------------------------------
# Section B: Project member role escalation via schema
# ---------------------------------------------------------------------------


def test_project_member_add_request_rejects_owner_role() -> None:
    """``ProjectMemberAddRequest`` schema MUST NOT accept ``role="owner"``.

    The ``ProjectMemberRole`` enum contains ``viewer``, ``member``, and
    ``admin``. The string ``"owner"`` is not a valid enum value, so Pydantic
    must raise ``ValidationError`` when it appears in the request body.
    """
    with pytest.raises(ValidationError) as exc_info:
        ProjectMemberAddRequest(
            email="attacker@example.com",
            role="owner",  # type: ignore[arg-type]
        )
    errors = exc_info.value.errors()
    role_errors = [e for e in errors if "role" in str(e.get("loc", ""))]
    assert role_errors, (
        "Expected a ValidationError on the 'role' field for value 'owner', "
        "but no role errors found in the error list."
    )


def test_project_member_add_request_accepts_valid_roles() -> None:
    """``ProjectMemberAddRequest`` accepts valid role values without error."""
    for role in ProjectMemberRole:
        req = ProjectMemberAddRequest(email="user@example.com", role=role)
        assert req.role == role


def test_project_member_role_does_not_include_owner() -> None:
    """``ProjectMemberRole`` enum must not contain an ``owner`` value.

    The ``owner`` is a project-level construct managed separately from the
    membership table. Adding ``owner`` to the role enum would create a path
    for privilege escalation via the member-add endpoint.
    """
    role_values = {r.value for r in ProjectMemberRole}
    assert "owner" not in role_values, (
        "ProjectMemberRole must not contain 'owner'. "
        "Project ownership is managed by project.owner_id, not the members table."
    )


# ---------------------------------------------------------------------------
# Section C: Admin schema — extra="forbid" guard
# ---------------------------------------------------------------------------


def test_admin_schema_with_extra_forbid_rejects_unknown_fields() -> None:
    """Admin schemas with ``extra='forbid'`` reject unknown fields.

    Schemas that explicitly configure ``extra="forbid"`` are the primary
    defence against mass-assignment. ``TaxonOverrideRejectRequest`` is one
    such schema — it must raise ``ValidationError`` when an unknown field
    is passed.
    """
    from echoroo.schemas.admin import TaxonOverrideRejectRequest

    with pytest.raises(ValidationError) as exc_info:
        TaxonOverrideRejectRequest.model_validate(
            {"reason": "valid reason", "malicious_field": "payload"}
        )
    errors = exc_info.value.errors()
    assert any("extra" in (e.get("type") or "") for e in errors), (
        f"Expected an 'extra_forbidden' error, got: {errors}"
    )


# ---------------------------------------------------------------------------
# Section D: Open redirect — absence of ?next= on login endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_endpoint_does_not_expose_next_redirect_param(
    client: Any,
) -> None:
    """The login endpoint must NOT silently honour a ``?next=`` redirect.

    An open redirect via ``?next=https://attacker.com`` after login would
    allow phishing attacks. This test posts to the login endpoint with the
    dangerous ``next`` parameter and verifies that:
    1. The response is NOT a redirect (3xx) to an external URL.
    2. The response body / Location header does not reference the attacker URL.
    """
    dangerous_next = "https://attacker.example.com/steal-tokens"
    response = await client.post(
        f"/web-api/v1/auth/login?next={dangerous_next}",
        json={"email": "test@example.com", "password": "Test1234!"},
        follow_redirects=False,
    )
    # The response must not redirect to the attacker's URL.
    location = response.headers.get("location", "")
    assert "attacker.example.com" not in location, (
        f"Open redirect detected: Location header contains attacker URL: {location}"
    )
    if response.status_code in (301, 302, 303, 307, 308):
        assert "attacker.example.com" not in location, (
            f"Login endpoint issued an open redirect to: {location}"
        )


@pytest.mark.asyncio
async def test_login_endpoint_javascript_scheme_in_next_param(
    client: Any,
) -> None:
    """``?next=javascript:alert(1)`` must never appear in a redirect header."""
    response = await client.post(
        "/web-api/v1/auth/login?next=javascript:alert(1)",
        json={"email": "test@example.com", "password": "Test1234!"},
        follow_redirects=False,
    )
    location = response.headers.get("location", "")
    assert "javascript:" not in location, (
        f"XSS-redirect detected: Location contains javascript: scheme: {location}"
    )


@pytest.mark.asyncio
async def test_login_endpoint_protocol_relative_url_in_next_param(
    client: Any,
) -> None:
    """``?next=//evil.com`` (protocol-relative) must not appear in redirect."""
    response = await client.post(
        "/web-api/v1/auth/login?next=//evil.com/phish",
        json={"email": "test@example.com", "password": "Test1234!"},
        follow_redirects=False,
    )
    location = response.headers.get("location", "")
    assert "evil.com" not in location, (
        f"Protocol-relative open redirect detected: Location = {location}"
    )


# ---------------------------------------------------------------------------
# Section E: Open redirect helper validation (unit test)
# ---------------------------------------------------------------------------


def test_safe_redirect_url_helper_rejects_external_host() -> None:
    """A same-origin redirect validator must reject external host names.

    This xfail test is the TDD red phase for the ``_is_safe_redirect_url``
    helper that MUST be implemented before any ``?next=`` redirect support
    is added to the auth flow.
    """
    from echoroo.api.web_v1.auth import _is_safe_redirect_url  # type: ignore[attr-defined]

    assert not _is_safe_redirect_url("https://attacker.com/steal")
    assert not _is_safe_redirect_url("javascript:alert(1)")
    assert not _is_safe_redirect_url("//evil.com")
    assert _is_safe_redirect_url("/dashboard")
    assert _is_safe_redirect_url("/projects/123")


__all__ = [
    "test_admin_schema_with_extra_forbid_rejects_unknown_fields",
    "test_login_endpoint_does_not_expose_next_redirect_param",
    "test_login_endpoint_javascript_scheme_in_next_param",
    "test_login_endpoint_protocol_relative_url_in_next_param",
    "test_project_member_add_request_accepts_valid_roles",
    "test_project_member_add_request_rejects_owner_role",
    "test_project_member_role_does_not_include_owner",
    "test_safe_redirect_url_helper_rejects_external_host",
    "test_user_update_request_accepts_display_name",
    "test_user_update_request_extra_fields_are_rejected_or_ignored",
    "test_user_update_request_ignores_is_superuser",
    "test_user_update_request_ignores_role",
    "test_user_update_request_schema_shape",
]
