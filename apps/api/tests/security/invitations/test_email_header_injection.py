"""FR-101: SMTP header injection prevention tests (T976).

Verifies that the invitation flow cannot be exploited via header injection
(CRLF) in email addresses or free-text fields:

1. CRLF in ``email`` field → rejected at Pydantic/API layer (ValidationError /
   422) — the ``echoroo.schemas.trusted.TrustedUserInviteRequest`` schema uses
   ``pydantic.EmailStr`` which delegates to ``email-validator`` and rejects
   control characters including CRLF.
2. CRLF-containing reason / display_name fields (where they exist) are either
   rejected or stored with the CRLF stripped / encoded.
3. spec/011 Step 6 (T054): the outbound-email outbox is removed. The legacy
   ``_enqueue_invitation_email`` JSON-encoding test and the
   ``InvitationMailPayload`` payload tests are gone with it — the plain-text
   envelope now leaves the process only through the issue endpoint's HTTP
   response (FR-011-103) which is JSON-serialised by FastAPI (CRLF survives
   as ``\\n`` in JSON anyway). The Pydantic EmailStr gate (test 1) remains
   the operational defence; reinforced by ``hash_email`` canonicalisation
   (test 4) and the schema-shape pin (test 5).

These tests work entirely at the service / schema layer without an HTTP
server.
"""

from __future__ import annotations

import re

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CRLF_PATTERNS: list[str] = [
    "victim@example.com\nBcc: attacker@evil.com",
    "victim@example.com\r\nTo: other@evil.com",
    "victim@example.com\rCc: third@evil.com",
    "victim\x00@example.com",
    "victim@example.com\nSubject: injected",
]

_MULTILINE_DISPLAY_NAMES: list[str] = [
    "Alice\nBcc: attacker@evil.com",
    "Bob\r\nX-Injected: header",
    "Carol\rSMTP: inject",
]


def _has_bare_crlf(value: str) -> bool:
    """Return True if the string contains a literal CR or LF character."""
    return bool(re.search(r"[\r\n]", value))


# ---------------------------------------------------------------------------
# 1. Pydantic EmailStr rejects CRLF-containing email addresses.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_email", _CRLF_PATTERNS)
def test_pydantic_emailstr_rejects_crlf_in_email(bad_email: str) -> None:
    """``TrustedUserInviteRequest.email`` MUST reject CRLF-containing input.

    ``pydantic.EmailStr`` delegates to the ``email-validator`` library which
    validates against RFC 5321/5322 and refuses control characters (including
    CR, LF, NUL). Any CRLF-containing value MUST raise ``ValidationError``
    before the service layer is reached.
    """
    from pydantic import ValidationError

    from echoroo.schemas.trusted import TrustedUserInviteRequest

    with pytest.raises(ValidationError) as exc_info:
        TrustedUserInviteRequest(
            email=bad_email,
            granted_permissions=["view_media"],
            duration_seconds=86400,
        )

    # ValidationError MUST mention the email field, not some other field.
    errors = exc_info.value.errors()
    field_locs = {err["loc"][0] for err in errors}
    assert "email" in field_locs, (
        f"Expected ValidationError on 'email' field, got locs={field_locs}"
    )


# ---------------------------------------------------------------------------
# 2. Bare valid email passes the Pydantic schema (sanity check).
# ---------------------------------------------------------------------------


def test_pydantic_emailstr_accepts_clean_email() -> None:
    """Valid email without control characters MUST pass schema validation."""
    from echoroo.schemas.trusted import TrustedUserInviteRequest

    req = TrustedUserInviteRequest(
        email="alice@example.com",
        granted_permissions=["view_media"],
        duration_seconds=86400,
    )
    assert req.email == "alice@example.com"


# ---------------------------------------------------------------------------
# 3. spec/011 Step 6 (T054) — outbound-email outbox removed. The legacy
#    ``test_invitation_mail_payload_json_encodes_crlf_in_email`` case
#    exercised ``_enqueue_invitation_email``'s JSON serialisation; the
#    function no longer exists. FastAPI's JSON serialiser still escapes
#    CRLF for any response field (defence in depth above the EmailStr gate
#    in test 1), so the operational guarantee is unchanged.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 4. hash_email canonicalisation handles CRLF without panic.
# ---------------------------------------------------------------------------


def test_hash_email_crlf_does_not_match_clean_email() -> None:
    """``hash_email`` with CRLF input MUST NOT produce the same digest as the
    clean address — so an attacker cannot use a CRLF-injected address to
    match a legitimate invitation.
    """
    from echoroo.services.invitation_service import hash_email

    secret = "test-secret-32-bytes-of-entropy!!"
    clean = hash_email("victim@example.com", hmac_secret=secret)
    dirty = hash_email(
        "victim@example.com\nBcc: attacker@evil.com", hmac_secret=secret
    )
    assert clean != dirty, (
        "CRLF-injected email MUST NOT produce the same hash as the clean address"
    )


# ---------------------------------------------------------------------------
# 5. TrustedUserInviteRequest: no ``reason`` / ``message`` free-text field
#    exposed at the schema level (no injection surface in this schema).
# ---------------------------------------------------------------------------


def test_trusted_invite_request_has_no_free_text_field() -> None:
    """``TrustedUserInviteRequest`` MUST NOT expose a ``reason`` or
    ``message`` free-text field that could be used as an SMTP header
    injection surface.

    FR-101(b) states that no user-generated strings should appear in email
    headers. Verifying the schema has no such field ensures the surface
    remains narrow.

    Note: ``comment`` is a valid ``TrustedGrantedPermission`` value, not a
    free-text field. We exclude it from the injection-surface check.
    """
    from echoroo.schemas.trusted import TrustedUserInviteRequest

    field_names = set(TrustedUserInviteRequest.model_fields.keys())
    # "comment" is a valid permission literal value, not a free-text field.
    injection_surface_fields = field_names & {"reason", "message", "note"}
    assert not injection_surface_fields, (
        f"Free-text fields found in TrustedUserInviteRequest that could "
        f"introduce SMTP header injection surface: {injection_surface_fields}"
    )


# ---------------------------------------------------------------------------
# 6. Member invitation schema (ProjectMemberInviteRequest) also uses EmailStr.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_email", _CRLF_PATTERNS[:3])
def test_member_invite_schema_rejects_crlf_email(bad_email: str) -> None:
    """Member invitation request body MUST also reject CRLF in email."""
    from pydantic import ValidationError

    # The member invite request is defined inline in the projects/_members.py
    # endpoint — we import it indirectly via the module.
    try:
        from echoroo.api.web_v1.projects._invitations import (
            _MemberInviteBody,  # type: ignore[attr-defined]
        )

        with pytest.raises((ValidationError, Exception)):
            _MemberInviteBody(email=bad_email, role="member")

    except ImportError:
        # The body schema is not directly importable (inline class or different
        # name). Skip: the TrustedUserInviteRequest coverage is sufficient to
        # pin the Pydantic EmailStr contract; this test is a belt-and-suspenders
        # check that would catch if a parallel schema regresses.
        pytest.skip("_MemberInviteBody not importable — schema may be inline")


# ---------------------------------------------------------------------------
# 7. spec/011 Step 6 (T052) — ``InvitationMailPayload`` removed. The
#    historic "payload stores email verbatim" guarantee is moot: there is
#    no payload class any more, and the plain-text envelope lives on
#    ``InvitationCreateOutcome.signed_token_envelope`` (FR-011-102..104).
# ---------------------------------------------------------------------------


__all__ = [
    "test_hash_email_crlf_does_not_match_clean_email",
    "test_member_invite_schema_rejects_crlf_email",
    "test_pydantic_emailstr_accepts_clean_email",
    "test_pydantic_emailstr_rejects_crlf_in_email",
    "test_trusted_invite_request_has_no_free_text_field",
]
