"""US5 redaction tests for spec 010 auth security events.

spec/011 Step 10 removed the
``test_email_verification_outbox_payload_does_not_include_raw_token_or_pii``
case alongside the deleted ``services/email_verification_service.py``
producer (FR-011-001..010). The sanitizer-level test below is retained
because it exercises the generic ``core.audit.sanitize_value`` helper
which still feeds the audit log even in the zero-email regime.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from echoroo.core.audit import sanitize_value

pytestmark = pytest.mark.asyncio


_RAW_EMAIL = "redaction-target@example.com"
_RAW_IP = "198.51.100.44"
_RAW_USER_AGENT = "Mozilla/5.0 EchorooRedactionTest/010"
_RAW_EMAIL_TOKEN = "emailVerificationTokenSecretValue010abcXYZ_"
_RAW_TRUSTED_DEVICE_SECRET = "trustedDeviceCookieSecretValue010abcXYZ_123"


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _assert_no_raw_values(payload: Any, *raw_values: str) -> None:
    serialized = _stable_json(payload)
    leaked = [value for value in raw_values if value in serialized]
    assert leaked == [], f"auth event payload leaked raw values: {leaked!r}"


async def test_auth_event_sanitizer_redacts_spec_010_token_cookie_and_client_fields() -> None:
    payload = {
        "email": _RAW_EMAIL,
        "verification_token": _RAW_EMAIL_TOKEN,
        "trusted_device_cookie_secret": _RAW_TRUSTED_DEVICE_SECRET,
        "ip": _RAW_IP,
        "user_agent": _RAW_USER_AGENT,
        "nested": {
            "trusted_device": {
                "secret": _RAW_TRUSTED_DEVICE_SECRET,
                "last_ip": _RAW_IP,
                "last_user_agent": _RAW_USER_AGENT,
            },
        },
    }

    sanitized = sanitize_value(payload, hash_fn=lambda value: f"hash:{len(value)}")

    _assert_no_raw_values(
        sanitized,
        _RAW_EMAIL,
        _RAW_EMAIL_TOKEN,
        _RAW_TRUSTED_DEVICE_SECRET,
        _RAW_IP,
        _RAW_USER_AGENT,
    )
    assert "redacted" in _stable_json(sanitized)
