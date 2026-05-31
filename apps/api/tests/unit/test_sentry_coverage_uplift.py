"""spec/011 Step 7c coverage uplift — ``echoroo.observability.sentry``.

The existing tests (test_admin_2fa_reset_side_effects.py etc.) exercise
``_before_send`` via the happy path. This suite fills the ~1.4pp gap
introduced by the Step 12 R1 response-side scrub branches:

* ``event["response"]`` with ``body`` key (string and dict variants)
* ``event["response"]`` with ``data`` key
* ``event["response"]`` with ``headers`` (sensitive + non-sensitive)
* ``event["response"]`` with ``cookies``
* ``event["response"]`` absent / non-dict → no-op
* ``event["extra"]`` / ``event["contexts"]`` / ``event["tags"]``
* ``event["breadcrumbs"]`` as list (not just dict)
* ``event["message"]`` as dict with ``params``
* Inner-exception path (malformed event) returns empty dict instead of
  propagating.
* ``init_sentry`` no-op when ``SENTRY_DSN`` is unset.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from echoroo.observability.sentry import (
    REDACTED_MARKER,
    _before_send,
    _scrub_headers,
    _scrub_mapping,
    init_sentry,
)

# ---------------------------------------------------------------------------
# _scrub_mapping tests
# ---------------------------------------------------------------------------


def test_scrub_mapping_replaces_sensitive_keys() -> None:
    """Sensitive keys are replaced; non-sensitive keys are preserved."""
    payload = {
        "temporary_password": "s3cr3t",
        "username": "alice",
        "step_up_token": "token123",
    }
    result = _scrub_mapping(payload)
    assert result["temporary_password"] == REDACTED_MARKER
    assert result["step_up_token"] == REDACTED_MARKER
    assert result["username"] == "alice"


def test_scrub_mapping_nested_dict() -> None:
    """Scrubbing descends recursively into nested dicts."""
    payload: dict[str, Any] = {
        "outer": {
            "invitation_url": "https://example.com/invite/token",
            "safe": "value",
        }
    }
    result = _scrub_mapping(payload)
    assert result["outer"]["invitation_url"] == REDACTED_MARKER
    assert result["outer"]["safe"] == "value"


def test_scrub_mapping_list() -> None:
    """Lists are descended element-wise."""
    items: list[Any] = [
        {"temporary_password": "abc"},
        {"username": "bob"},
    ]
    result = _scrub_mapping(items)
    assert result[0]["temporary_password"] == REDACTED_MARKER
    assert result[1]["username"] == "bob"


def test_scrub_mapping_tuple() -> None:
    """Tuples are descended and returned as tuples."""
    tup: tuple[Any, ...] = ({"temporary_password": "x"},)
    result = _scrub_mapping(tup)
    assert isinstance(result, tuple)
    assert result[0]["temporary_password"] == REDACTED_MARKER


def test_scrub_mapping_primitive_passthrough() -> None:
    """Primitive values pass through unchanged."""
    assert _scrub_mapping("plain string") == "plain string"
    assert _scrub_mapping(42) == 42
    assert _scrub_mapping(None) is None


# ---------------------------------------------------------------------------
# _scrub_headers tests
# ---------------------------------------------------------------------------


def test_scrub_headers_redacts_sensitive_headers_case_insensitive() -> None:
    """Sensitive headers are redacted regardless of case."""
    headers: dict[str, str] = {
        "Authorization": "Bearer token",
        "x-step-up-token": "step123",
        "Content-Type": "application/json",
    }
    result = _scrub_headers(headers)
    assert result["Authorization"] == REDACTED_MARKER
    assert result["x-step-up-token"] == REDACTED_MARKER
    assert result["Content-Type"] == "application/json"


def test_scrub_headers_non_dict_passthrough() -> None:
    """Non-dict values pass through unchanged."""
    assert _scrub_headers("not-a-dict") == "not-a-dict"
    assert _scrub_headers(None) is None


# ---------------------------------------------------------------------------
# _before_send — request side
# ---------------------------------------------------------------------------


def test_before_send_scrubs_request_data() -> None:
    """Request body data is scrubbed."""
    event: dict[str, Any] = {
        "request": {
            "data": {"temporary_password": "secret", "email": "alice@example.com"},
        }
    }
    result = _before_send(event, {})
    assert result["request"]["data"]["temporary_password"] == REDACTED_MARKER
    assert result["request"]["data"]["email"] == "alice@example.com"


def test_before_send_scrubs_request_headers() -> None:
    """Request headers are scrubbed."""
    event: dict[str, Any] = {
        "request": {
            "headers": {
                "X-Step-Up-Token": "abc",
                "Accept": "application/json",
            }
        }
    }
    result = _before_send(event, {})
    assert result["request"]["headers"]["X-Step-Up-Token"] == REDACTED_MARKER
    assert result["request"]["headers"]["Accept"] == "application/json"


def test_before_send_scrubs_request_cookies() -> None:
    """Request cookies are collapsed to the redacted marker."""
    event: dict[str, Any] = {
        "request": {
            "cookies": {"session_id": "abc123", "csrf_token": "xyz"},
        }
    }
    result = _before_send(event, {})
    assert result["request"]["cookies"] == REDACTED_MARKER


# ---------------------------------------------------------------------------
# _before_send — response side (Step 12 R1 new branches)
# ---------------------------------------------------------------------------


def test_before_send_scrubs_response_body() -> None:
    """Response ``body`` key is scrubbed (temporary_password in response body)."""
    event: dict[str, Any] = {
        "response": {
            "body": {"temporary_password": "temp123", "user_id": "uuid"},
        }
    }
    result = _before_send(event, {})
    assert result["response"]["body"]["temporary_password"] == REDACTED_MARKER
    assert result["response"]["body"]["user_id"] == "uuid"


def test_before_send_scrubs_response_body_string() -> None:
    """Response body as a non-dict string passes through unchanged."""
    event: dict[str, Any] = {
        "response": {
            "body": "raw string body",
        }
    }
    result = _before_send(event, {})
    # A plain string has no sensitive keys to scrub
    assert result["response"]["body"] == "raw string body"


def test_before_send_scrubs_response_data() -> None:
    """Response ``data`` key is scrubbed."""
    event: dict[str, Any] = {
        "response": {
            "data": {"signed_token_envelope": "env123", "status": "ok"},
        }
    }
    result = _before_send(event, {})
    assert result["response"]["data"]["signed_token_envelope"] == REDACTED_MARKER
    assert result["response"]["data"]["status"] == "ok"


def test_before_send_scrubs_response_headers() -> None:
    """Response headers are scrubbed via _scrub_headers."""
    event: dict[str, Any] = {
        "response": {
            "headers": {
                "Set-Cookie": "session=abc; HttpOnly",
                "Content-Type": "application/json",
            }
        }
    }
    result = _before_send(event, {})
    # Set-Cookie is in SENSITIVE_HEADERS (added by Step 12 R1)
    assert result["response"]["headers"]["Set-Cookie"] == REDACTED_MARKER
    assert result["response"]["headers"]["Content-Type"] == "application/json"


def test_before_send_scrubs_response_cookies() -> None:
    """Response cookies are collapsed to the redacted marker."""
    event: dict[str, Any] = {
        "response": {
            "cookies": {"session": "abc123"},
        }
    }
    result = _before_send(event, {})
    assert result["response"]["cookies"] == REDACTED_MARKER


def test_before_send_response_absent() -> None:
    """Missing ``response`` key — no-op, event returned unchanged."""
    event: dict[str, Any] = {"request": {"data": {"email": "user@example.com"}}}
    result = _before_send(event, {})
    assert "response" not in result


def test_before_send_response_non_dict() -> None:
    """Non-dict ``response`` value — no-op (no scrubbing attempted)."""
    event: dict[str, Any] = {"response": "not-a-dict"}
    result = _before_send(event, {})
    assert result["response"] == "not-a-dict"


# ---------------------------------------------------------------------------
# _before_send — extra / contexts / tags
# ---------------------------------------------------------------------------


def test_before_send_scrubs_extra() -> None:
    """``event['extra']`` is walked for sensitive keys."""
    event: dict[str, Any] = {
        "extra": {"temporary_password": "leak", "debug_info": "safe"},
    }
    result = _before_send(event, {})
    assert result["extra"]["temporary_password"] == REDACTED_MARKER
    assert result["extra"]["debug_info"] == "safe"


def test_before_send_scrubs_contexts() -> None:
    """``event['contexts']`` is walked for sensitive keys."""
    event: dict[str, Any] = {
        "contexts": {"auth": {"invitation_url": "url", "user": "alice"}},
    }
    result = _before_send(event, {})
    assert result["contexts"]["auth"]["invitation_url"] == REDACTED_MARKER
    assert result["contexts"]["auth"]["user"] == "alice"


def test_before_send_scrubs_tags() -> None:
    """``event['tags']`` is walked for sensitive keys."""
    event: dict[str, Any] = {
        "tags": {"step_up_token": "token", "environment": "production"},
    }
    result = _before_send(event, {})
    assert result["tags"]["step_up_token"] == REDACTED_MARKER
    assert result["tags"]["environment"] == "production"


# ---------------------------------------------------------------------------
# _before_send — breadcrumbs (list form)
# ---------------------------------------------------------------------------


def test_before_send_scrubs_breadcrumbs_list_form() -> None:
    """Breadcrumbs as a top-level list are descended for ``data`` scrubbing."""
    event: dict[str, Any] = {
        "breadcrumbs": [
            {
                "type": "http",
                "data": {"temporary_password": "crumb_secret", "url": "/auth"},
            }
        ]
    }
    result = _before_send(event, {})
    # breadcrumbs is a list — the list branch is exercised
    assert result["breadcrumbs"][0]["data"]["temporary_password"] == REDACTED_MARKER
    assert result["breadcrumbs"][0]["data"]["url"] == "/auth"


def test_before_send_scrubs_breadcrumbs_dict_form() -> None:
    """Breadcrumbs in the SDK ``{"values": [...]}`` dict form are scrubbed."""
    event: dict[str, Any] = {
        "breadcrumbs": {
            "values": [
                {
                    "type": "default",
                    "data": {"invitation_url": "https://app/i/tok"},
                }
            ]
        }
    }
    result = _before_send(event, {})
    assert (
        result["breadcrumbs"]["values"][0]["data"]["invitation_url"] == REDACTED_MARKER
    )


def test_before_send_breadcrumb_without_data_key() -> None:
    """Breadcrumb entry without a ``data`` key is skipped without error."""
    event: dict[str, Any] = {
        "breadcrumbs": {
            "values": [
                {"type": "default", "message": "no data here"},
            ]
        }
    }
    result = _before_send(event, {})
    # No error; the breadcrumb entry is unchanged
    assert result["breadcrumbs"]["values"][0]["message"] == "no data here"


# ---------------------------------------------------------------------------
# _before_send — message.params
# ---------------------------------------------------------------------------


def test_before_send_scrubs_message_params() -> None:
    """Structured ``message.params`` is scrubbed when present."""
    event: dict[str, Any] = {
        "message": {
            "formatted": "reset_password called",
            "params": {"temporary_password": "param_secret", "user": "alice"},
        }
    }
    result = _before_send(event, {})
    assert result["message"]["params"]["temporary_password"] == REDACTED_MARKER
    assert result["message"]["params"]["user"] == "alice"


def test_before_send_message_without_params_key() -> None:
    """Message dict without ``params`` key is a no-op."""
    event: dict[str, Any] = {
        "message": {"formatted": "plain log line"},
    }
    result = _before_send(event, {})
    assert result["message"]["formatted"] == "plain log line"


def test_before_send_message_non_dict() -> None:
    """Non-dict ``message`` value is not descended."""
    event: dict[str, Any] = {"message": "plain string message"}
    result = _before_send(event, {})
    assert result["message"] == "plain string message"


# ---------------------------------------------------------------------------
# _before_send — exception safety (returns {} not raises)
# ---------------------------------------------------------------------------


def test_before_send_exception_returns_empty_dict() -> None:
    """If scrubbing raises unexpectedly, _before_send returns {} to drop event."""
    # Trigger the except clause by making event.get() raise inside the try block.
    # We use an event dict subclass whose .get() method raises for a specific key
    # so the exception happens deep inside the try block.
    class _BrokenEvent(dict):  # type: ignore[type-arg]
        def get(self, key: str, default: Any = None) -> Any:
            if key == "extra":
                raise RuntimeError("simulated redaction failure on extra key")
            return super().get(key, default)

    event: _BrokenEvent = _BrokenEvent(
        {"request": {"data": {"safe": "value"}}, "extra": {"should_not": "reach"}}
    )
    result = _before_send(event, {})  # type: ignore[arg-type]
    assert result == {}


# ---------------------------------------------------------------------------
# init_sentry — no-op paths
# ---------------------------------------------------------------------------


def test_init_sentry_returns_false_when_dsn_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """init_sentry returns False when SENTRY_DSN is unset."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert init_sentry() is False


def test_init_sentry_returns_false_when_dsn_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """init_sentry returns False when SENTRY_DSN is an empty string."""
    monkeypatch.setenv("SENTRY_DSN", "")
    assert init_sentry() is False


def test_init_sentry_returns_false_when_sentry_not_importable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """init_sentry returns False when sentry-sdk is not installed."""
    monkeypatch.setenv("SENTRY_DSN", "https://key@sentry.io/123")
    import builtins

    real_import = builtins.__import__

    def _mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sentry_sdk":
            raise ImportError("no module named sentry_sdk")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_mock_import):
        assert init_sentry() is False
