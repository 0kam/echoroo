"""Email service using Resend for transactional emails."""

import logging

import resend

from echoroo.core.settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Configure Resend API key
resend.api_key = settings.RESEND_API_KEY


async def send_verification_email(to: str, token: str) -> None:
    """Send email verification email.

    Args:
        to: Recipient email address
        token: Verification token

    Example:
        ```python
        await send_verification_email(user.email, verification_token)
        ```
    """
    # If Resend is not configured, skip sending (development mode)
    if not settings.RESEND_API_KEY:
        logger.warning(
            f"Email service not configured. Verification token for {to}: {token}"
        )
        return

    verification_url = f"{settings.APP_URL}/verify-email?token={token}"

    try:
        resend.Emails.send(
            {
                "from": settings.EMAIL_FROM,
                "to": to,
                "subject": "Verify your Echoroo account",
                "html": f"""
                    <h2>Welcome to Echoroo!</h2>
                    <p>Please verify your email address by clicking the link below:</p>
                    <p><a href="{verification_url}">Verify Email</a></p>
                    <p>This link will expire in 24 hours.</p>
                    <p>If you didn't create an account, you can safely ignore this email.</p>
                """,
            }
        )
        logger.info(f"Verification email sent to {to}")
    except Exception as e:
        logger.error(f"Failed to send verification email to {to}: {e}")
        # Don't raise exception - email failure shouldn't block registration


async def send_password_reset_email(to: str, token: str) -> None:
    """Send password reset email.

    Args:
        to: Recipient email address
        token: Password reset token

    Example:
        ```python
        await send_password_reset_email(user.email, reset_token)
        ```
    """
    # If Resend is not configured, skip sending (development mode)
    if not settings.RESEND_API_KEY:
        logger.warning(
            f"Email service not configured. Password reset token for {to}: {token}"
        )
        return

    reset_url = f"{settings.APP_URL}/reset-password?token={token}"

    try:
        resend.Emails.send(
            {
                "from": settings.EMAIL_FROM,
                "to": to,
                "subject": "Reset your Echoroo password",
                "html": f"""
                    <h2>Password Reset Request</h2>
                    <p>You requested to reset your password. Click the link below:</p>
                    <p><a href="{reset_url}">Reset Password</a></p>
                    <p>This link will expire in 1 hour.</p>
                    <p>If you didn't request this, you can safely ignore this email.</p>
                """,
            }
        )
        logger.info(f"Password reset email sent to {to}")
    except Exception as e:
        logger.error(f"Failed to send password reset email to {to}: {e}")
        # Don't raise exception - always return success for security
