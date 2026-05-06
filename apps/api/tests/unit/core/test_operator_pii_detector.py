"""Phase 17 backlog A-13 — operator PII detector unit tests.

Verifies that :func:`echoroo.core.operator_pii_detector.reject_if_pii`
(invoked through the :data:`OperatorReasonText` /
:data:`OperatorSupportTicketId` Annotated types) rejects every PII
class catalogued in :mod:`echoroo.core.audit` and accepts realistic
benign operator inputs without false positives.

The Annotated types are exercised through a throw-away Pydantic model
so the validation path matches what FastAPI runs at request time
(Pydantic ``AfterValidator`` chain).
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from echoroo.core.operator_pii_detector import (
    OperatorReasonText,
    OperatorSupportTicketId,
    reject_if_pii,
)


class _ReasonModel(BaseModel):
    """Throw-away model that exercises the Annotated reason validator."""

    model_config = ConfigDict(extra="forbid")
    reason: OperatorReasonText


class _TicketModel(BaseModel):
    """Throw-away model that exercises the Annotated support-ticket validator."""

    model_config = ConfigDict(extra="forbid")
    support_ticket_id: OperatorSupportTicketId


# ---------------------------------------------------------------------------
# Reject — direct PII patterns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pii_value",
    [
        # Email
        "Contact user at jane.doe@example.com for confirmation",
        # International phone (E.164-ish)
        "Reached operator on +81-90-1234-5678 last night",
        # Japanese domestic phone
        "Phone 090-1234-5678 verified out-of-band",
        # US SSN
        "Verified SSN 123-45-6789 against support form",
        # Japanese My Number (12 digits)
        "Verified personal number 1234 5678 9012 against ID",
        # Credit card (16 digits)
        "Charged card 4111 1111 1111 1111 for refund",
        # JWT
        (
            "Pasted token "
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "abcdefghij1234567890QwErTyUiOpAsDfGhJkLzXcV"
        ),
        # AWS access key id
        "Rotated AKIAIOSFODNN7EXAMPLE this morning",
    ],
)
def test_reason_rejects_pii(pii_value: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _ReasonModel(reason=pii_value)
    # Educational message must be present and must not name which
    # specific PII pattern matched (regex-oracle defence on the *msg*;
    # Pydantic's ``input`` field unavoidably echoes back the operator's
    # own input, which is acceptable since the operator already knows
    # what they submitted).
    #
    # Round 2 R1-I2: do NOT pin the assertion to a specific PII
    # *category* name (e.g. ``"email"``) — Codex flagged that as
    # over-specifying the contract. The only contractual guarantees
    # are (a) the upper-case ``"PII"`` token appears so the operator
    # knows why their request was rejected, and (b) the matching
    # regex / pattern itself is not echoed back (oracle-defence).
    # An informational hint about structured alternatives
    # (``user_id`` / ``ticket``) is allowed but not required.
    errors = excinfo.value.errors()
    assert len(errors) == 1
    msg = errors[0]["msg"]
    assert "PII" in msg
    # The error context must not name the specific regex that matched.
    assert "regex" not in msg.lower()


def test_reason_rejects_email_inside_long_text() -> None:
    """A single embedded email in otherwise-benign prose still trips the gate."""
    long_value = (
        "User reported losing access to their device after a recent "
        "office relocation. The replacement device has been configured. "
        "Operator confirmed identity at jane@example.com via callback. "
        "Awaiting M-of-N quorum from co-signing superuser."
    )
    with pytest.raises(ValidationError):
        _ReasonModel(reason=long_value)


def test_reason_rejects_url_encoded_email() -> None:
    """URL-decoded variant must also be scanned (audit-pipeline parity)."""
    encoded = "Reference%20user%20jane%40example.com%20in%20Zendesk%20ticket"
    with pytest.raises(ValidationError):
        _ReasonModel(reason=encoded)


def test_reason_rejects_fullwidth_homoglyph_email() -> None:
    """NFKC normalisation must catch fullwidth homoglyph email bypass."""
    # Fullwidth "user@example.com" — collapses to ASCII under NFKC.
    fullwidth = "Contact ｕｓｅｒ＠ｅｘａｍｐｌｅ．ｃｏｍ for confirmation"
    with pytest.raises(ValidationError):
        _ReasonModel(reason=fullwidth)


# ---------------------------------------------------------------------------
# Accept — realistic benign operator inputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "benign_value",
    [
        "User reported lost device, requesting reset",
        "Insufficient identity proof from support agent",
        "Operator confirmed identity via internal directory lookup",
        "Quorum reached after 24h delay window",
        "Project archived after owner dormancy timeout",
        "Reject — duplicate ticket, see referenced approval-request id",
        "Looser override unjustified given current IUCN status",
    ],
)
def test_reason_accepts_benign_operator_text(benign_value: str) -> None:
    model = _ReasonModel(reason=benign_value)
    assert model.reason == benign_value


def test_reason_accepts_uuid_only_string() -> None:
    """FR-091a §c — bare UUIDs are explicitly allowed (cross-reference target)."""
    uuid_value = "550e8400-e29b-41d4-a716-446655440000"
    model = _ReasonModel(reason=uuid_value)
    assert model.reason == uuid_value


def test_reason_rejects_uuid_inside_text_due_to_my_number_overlap() -> None:
    """Document conservative behaviour at the UUID-substring boundary.

    FR-091a §c only allows **exact-match** UUIDs (the entire field IS a
    UUID). When a UUID appears inside free-form prose the audit regex
    catalogue's My-Number / SSN patterns can match the numeric tail of
    the UUID (e.g. ``446655440000`` is 12 digits → My Number trip).
    The audit module deliberately favours false positives, and the
    operator-PII validator inherits that catalogue, so the conservative
    outcome is HTTP 422. Operators must reference user ids in a
    structured field (``target_user_id``), not embed them in
    free-form ``reason``.
    """
    embedded = "Reset for user 550e8400-e29b-41d4-a716-446655440000 approved"
    with pytest.raises(ValidationError):
        _ReasonModel(reason=embedded)


# ---------------------------------------------------------------------------
# Length / required guards (Pydantic Field constraints)
# ---------------------------------------------------------------------------


def test_reason_rejects_empty_string() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _ReasonModel(reason="")
    # Length error fires before PII scan — confirms min_length=1 is wired.
    assert "at least 1" in str(excinfo.value).lower() or "min" in str(
        excinfo.value
    ).lower()


def test_reason_rejects_value_exceeding_2000_chars() -> None:
    too_long = "a" * 2_001
    with pytest.raises(ValidationError):
        _ReasonModel(reason=too_long)


def test_reason_accepts_value_at_2000_char_boundary() -> None:
    boundary = "x" * 2_000
    model = _ReasonModel(reason=boundary)
    assert len(model.reason) == 2_000


# ---------------------------------------------------------------------------
# Support ticket id — narrower length, same PII gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ticket_id",
    [
        "ZD-12345",
        "JIRA-OPS-987",
        "SUP_2026_04_001",
        "ticket-7f2c8d1e",
        "INC0123456",
    ],
)
def test_support_ticket_id_accepts_alphanumeric(ticket_id: str) -> None:
    model = _TicketModel(support_ticket_id=ticket_id)
    assert model.support_ticket_id == ticket_id


def test_support_ticket_id_rejects_email_disguised_as_ticket() -> None:
    with pytest.raises(ValidationError):
        _TicketModel(support_ticket_id="contact-jane@example.com")


def test_support_ticket_id_rejects_phone() -> None:
    with pytest.raises(ValidationError):
        _TicketModel(support_ticket_id="+1-555-123-4567")


def test_support_ticket_id_rejects_value_exceeding_200_chars() -> None:
    too_long = "ZD-" + "1" * 200
    with pytest.raises(ValidationError):
        _TicketModel(support_ticket_id=too_long)


# ---------------------------------------------------------------------------
# Direct callable smoke test
# ---------------------------------------------------------------------------


def test_reject_if_pii_returns_value_unchanged_on_clean_input() -> None:
    """The validator MUST NOT mutate accepted input (audit fidelity)."""
    clean = "User confirmed identity in office"
    assert reject_if_pii(clean) is clean


def test_reject_if_pii_raises_value_error_on_pii() -> None:
    with pytest.raises(ValueError, match="PII"):
        reject_if_pii("forward to ops@example.com please")
