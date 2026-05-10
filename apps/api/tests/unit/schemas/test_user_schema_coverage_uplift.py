"""Coverage uplift unit tests for ``echoroo.schemas.user``.

Phase 17 §C medium-gap batch: targets the ``validate_password_complexity``
field validator (lines 41-45) so the module clears the 85% threshold
without touching production code.
"""

from __future__ import annotations

import pytest

from echoroo.schemas.user import (
    PasswordChangeRequest,
    PasswordChangeResponse,
    UserUpdateRequest,
)


def test_password_change_request_accepts_alpha_and_digit() -> None:
    """A password with at least one letter + one digit is accepted (lines 41-45)."""
    req = PasswordChangeRequest(
        current_password="oldpw",
        new_password="abcdefg1",
    )
    assert req.new_password == "abcdefg1"


def test_password_change_request_rejects_no_letter() -> None:
    """A digit-only password fails the alpha check (line 42)."""
    with pytest.raises(ValueError, match="must contain at least one letter"):
        PasswordChangeRequest(
            current_password="x",
            new_password="12345678",
        )


def test_password_change_request_rejects_no_digit() -> None:
    """An alpha-only password fails the digit check (line 44)."""
    with pytest.raises(ValueError, match="must contain at least one number"):
        PasswordChangeRequest(
            current_password="x",
            new_password="abcdefgh",
        )


def test_password_change_response_default_message() -> None:
    """Default message is provided when none is set."""
    resp = PasswordChangeResponse()
    assert resp.message == "Password changed successfully"


def test_user_update_request_accepts_none_display_name() -> None:
    """display_name defaults to None and is allowed."""
    req = UserUpdateRequest()
    assert req.display_name is None
