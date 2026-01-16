"""Unit tests for password validation and hashing."""

import pytest
from pydantic import ValidationError

from echoroo.core.security import hash_password, verify_password
from echoroo.schemas.auth import PasswordResetConfirm, UserRegisterRequest


def test_password_hashing() -> None:
    """Test password hashing and verification."""
    password = "SecurePass123"
    hashed = hash_password(password)

    # Hash should be different from original
    assert hashed != password

    # Hash should start with $argon2id$
    assert hashed.startswith("$argon2id$")

    # Verification should succeed
    assert verify_password(password, hashed) is True

    # Wrong password should fail
    assert verify_password("WrongPass123", hashed) is False


def test_password_complexity_validation() -> None:
    """Test password complexity requirements (T047)."""
    # Valid password
    valid_request = UserRegisterRequest(
        email="user@example.com",
        password="ValidPass123",
    )
    assert valid_request.password == "ValidPass123"

    # Too short
    with pytest.raises(ValidationError) as exc_info:
        UserRegisterRequest(
            email="user@example.com",
            password="short1",
        )
    assert "at least 8 characters" in str(exc_info.value).lower()

    # No letters
    with pytest.raises(ValidationError) as exc_info:
        UserRegisterRequest(
            email="user@example.com",
            password="12345678",
        )
    assert "letter" in str(exc_info.value).lower()

    # No numbers
    with pytest.raises(ValidationError) as exc_info:
        UserRegisterRequest(
            email="user@example.com",
            password="onlyletters",
        )
    assert "number" in str(exc_info.value).lower()


def test_password_reset_validation() -> None:
    """Test password reset confirmation validation."""
    # Valid password reset
    valid_reset = PasswordResetConfirm(
        token="some_token",
        password="NewPass123",
    )
    assert valid_reset.password == "NewPass123"

    # Invalid password (too short)
    with pytest.raises(ValidationError) as exc_info:
        PasswordResetConfirm(
            token="some_token",
            password="short1",
        )
    assert "at least 8 characters" in str(exc_info.value).lower()

    # Invalid password (no numbers)
    with pytest.raises(ValidationError) as exc_info:
        PasswordResetConfirm(
            token="some_token",
            password="onlyletters",
        )
    assert "number" in str(exc_info.value).lower()


def test_argon2_parameters() -> None:
    """Test that Argon2 uses secure parameters."""
    import re

    password = "TestPass123"
    hashed = hash_password(password)

    # Extract parameters from hash
    # Format: $argon2id$v=19$m=19456,t=2,p=1$...
    match = re.search(r"\$argon2id\$v=(\d+)\$m=(\d+),t=(\d+),p=(\d+)\$", hashed)

    assert match is not None
    version, memory, time_cost, parallelism = match.groups()

    # Verify OWASP recommended parameters
    assert int(memory) >= 19456  # 19 MiB minimum
    assert int(time_cost) >= 2  # 2 iterations minimum
    assert int(parallelism) >= 1  # 1 thread minimum
