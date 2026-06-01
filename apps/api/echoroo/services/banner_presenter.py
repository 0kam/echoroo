"""Banner summary presenter — spec/011 US7 (T600 / OQ3).

The banner read service (:mod:`echoroo.services.user_banner`) returns raw
audit rows (``action`` + ``detail`` dict). The OpenAPI ``BannerItem``
schema (``contracts/me-banners-activity.yaml``) requires a non-null,
human-readable ``summary`` string suitable for inline display.

This module owns the ``action`` -> ``summary`` formatter. Every string
it produces is A-13 safe: it NEVER interpolates an email address, an API
key secret, a raw IP, or any other PII / secret pulled from ``detail``.
The copy is intentionally generic English text plus, where available, an
ISO-8601 date pulled from the row's ``occurred_at`` (the date itself is
not PII). When an action is unrecognised the formatter falls back to a
generic "security event" line keyed on the action string (which is a
non-PII enum value).

``link`` resolution is deferred — the contract permits ``link = None``
and the frontend deep-link surface (T640-T643) is out of this slice.
"""

from __future__ import annotations

from datetime import datetime

#: A-13-safe English copy per banner-eligible action. The format string
#: receives a single ``{when}`` placeholder bound to the row's
#: ``occurred_at`` date (``YYYY-MM-DD``); it MUST NOT reference any
#: ``detail`` field so no PII / secret can leak into the summary.
_ACTION_SUMMARY_TEMPLATES: dict[str, str] = {
    "auth.login.new_device": (
        "A new sign-in to your account was detected on {when}."
    ),
    "platform.user.email_changed": (
        "The email address on your account was changed on {when}."
    ),
    "platform.user.two_factor_reset_by_superuser": (
        "Your two-factor authentication was reset by an administrator "
        "on {when}."
    ),
    "platform.api_key.revoke": (
        "One of your API keys was revoked on {when}."
    ),
    "platform.user.password_reset_by_superuser": (
        "Your password was reset by an administrator on {when}."
    ),
    "platform.user.password_reset_self": (
        "Your password was reset on {when}."
    ),
    "project.member.invite_accepted_signup": (
        "You joined a project via invitation on {when}."
    ),
    "project.member.invite_accepted": (
        "You accepted a project membership invitation on {when}."
    ),
    "project.trusted_user.invite_accepted": (
        "You accepted a trusted-user invitation on {when}."
    ),
    "project.ownership.bootstrap_transfer": (
        "Ownership of a project was transferred to you on {when}."
    ),
    "auth.trusted_device.revoke_all": (
        "All trusted devices on your account were revoked on {when}."
    ),
}


def _format_when(occurred_at: datetime) -> str:
    """Render an ``occurred_at`` timestamp as a bare ``YYYY-MM-DD`` date.

    A date is not PII and is safe to surface inline. We deliberately drop
    the time-of-day so the summary stays compact and locale-agnostic.
    """
    return occurred_at.date().isoformat()


def summarize_banner(*, action: str, occurred_at: datetime) -> str:
    """Return an A-13-safe one-line summary for a banner-eligible action.

    Args:
        action: The audit-action string (a non-PII enum value mirrored in
            :data:`echoroo.services.user_banner.BANNER_ELIGIBLE_ACTIONS`).
        occurred_at: The row timestamp; only its calendar date is used.

    Returns:
        A short English sentence with no PII / secret content. Unknown
        actions fall back to a generic security-event line keyed on the
        (non-PII) action string.
    """
    when = _format_when(occurred_at)
    template = _ACTION_SUMMARY_TEMPLATES.get(action)
    if template is not None:
        return template.format(when=when)
    return f"A security event ({action}) occurred on {when}."


__all__ = ["summarize_banner"]
