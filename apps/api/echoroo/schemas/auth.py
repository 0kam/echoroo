"""Authentication request and response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserRegisterRequest(BaseModel):
    """User registration request schema."""

    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(
        ..., min_length=8, max_length=128, description="Password (min 8 chars, max 128 chars, must contain letters and numbers)"
    )
    display_name: str | None = Field(None, max_length=100, description="Display name")
    captcha_token: str | None = Field(
        None, description="Turnstile CAPTCHA token (required after 3 failed attempts)"
    )
    invitation_token: str | None = Field(
        None, description="Invitation token (required in invitation-only mode)"
    )

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        """Validate password complexity requirements."""
        if not any(c.isalpha() for c in v):
            raise ValueError("Password must contain at least one letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one number")
        return v


class LoginRequest(BaseModel):
    """User login request schema."""

    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., max_length=128, description="User's password (max 128 chars)")
    captcha_token: str | None = Field(
        None, description="Turnstile CAPTCHA token (required after 3 failed attempts)"
    )


class TokenResponse(BaseModel):
    """Token response schema."""

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Seconds until token expires")


# spec/011 Step 10 (T126) — ``PasswordResetRequest`` /
# ``PasswordResetConfirm`` / ``EmailVerifyRequest`` schemas were
# removed alongside the deleted self-service password-reset and
# email-verification endpoints (T119/T120). Password recovery is now
# admin-mediated (``services/admin_password_reset.py``) and uses the
# request schemas in ``schemas/web_v1/auth.py``; email verification is
# removed wholesale (FR-011-005).


class UserResponse(BaseModel):
    """User response schema.

    Fields reflect the permissions-redesign User model (006-permissions-redesign).
    Legacy fields ``organization``, ``is_active``, ``is_superuser``, and
    ``is_verified`` are not present on the new User model and are omitted here.
    They are replaced with ``deleted_at`` (soft-delete) semantics.
    """

    id: UUID
    email: str
    display_name: str | None
    created_at: datetime
    last_login_at: datetime | None

    model_config = {"from_attributes": True}


class LogoutResponse(BaseModel):
    """Logout response schema."""

    message: str = Field(default="Logout successful")
