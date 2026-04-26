"""Regression coverage for ``echoroo.services.email`` log PII discipline.

These tests enforce FR-105: log statements emitted by the unified email
service MUST NOT include the raw recipient email address (PII) on the
warn-and-continue path (missing API key in dev / test) or on the
delivery-error path (Resend SDK raised).

The fix replaced the raw recipient with a ``recipient_hash`` surrogate
computed via :func:`echoroo.core.kms.compute_pii_hash`. We assert on
the captured ``caplog`` records to detect any future regression where
a developer accidentally logs ``to`` / ``recipient`` directly.

Why these paths matter:

* The missing-API-key branch is exercised in every dev / CI run that
  does not provision Resend credentials. Logs there are routinely
  shipped to long-term storage (Datadog, syslog, S3) where the raw
  email would survive the application's PII boundary.
* The delivery-error branch fires on transient SMTP / Resend failures
  in production — exactly the scenario where logs are most valuable
  for debugging *and* most likely to be paged on / forwarded.

The tests run against ``send_login_notification`` (the explicit target
of the codex review) AND the two other helpers (``verification`` and
``password_reset``) which were patched in the same commit for
consistency.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from echoroo.services import email as email_module
from echoroo.services.email import (
    send_login_notification,
    send_password_reset_email,
    send_verification_email,
)

pytestmark = pytest.mark.asyncio


_RECIPIENT = "alice@example.com"
_OTHER_RECIPIENT = "bob+tag@example.org"


#: Deterministic PII-hash stand-ins keyed off the test recipient. The
#: surrogate must NOT echo the input — the whole point of these tests
#: is to catch a regression that leaks the raw value, so a stub that
#: embeds the raw value in its return makes the assertion meaningless.
_HASH_BY_RECIPIENT: dict[str, str] = {
    _RECIPIENT: "deadbeefcafebabe1234567890abcdef" * 2,  # 64-hex
    _OTHER_RECIPIENT: "0123456789abcdef0123456789abcdef" * 2,  # 64-hex
}


def _stub_pii_hash(value: str) -> str:
    """Deterministic PII-hash stub used by the email log-discipline tests.

    Maps known recipients to fixed 64-hex sentinels so we can positively
    assert the surrogate appears in the log AND that the raw recipient
    does NOT. For unknown values (e.g. tokens) we fall back to a fixed
    constant — every test that uses an unknown value asserts on the
    *absence* of the raw value, not on its surrogate.
    """
    return _HASH_BY_RECIPIENT.get(value, "f" * 64)


@pytest.fixture
def stub_kms(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the KMS-backed ``compute_pii_hash`` with a deterministic stub.

    We do not need a real KMS round-trip in a unit test; what we care
    about is that the *value* logged is the surrogate, not the raw
    email.
    """
    monkeypatch.setattr(email_module, "compute_pii_hash", _stub_pii_hash)


@pytest.fixture
def no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate the dev / test "Resend not configured" branch.

    The module-level ``settings`` object is mutated in-place — this
    matches how the helpers themselves read the value (attribute
    access on the cached settings instance).
    """
    monkeypatch.setattr(email_module.settings, "RESEND_API_KEY", "")


def _assert_no_raw_recipient(caplog: pytest.LogCaptureFixture, recipient: str) -> None:
    """Verify NO captured log record contains the raw recipient string.

    We check both the formatted message and each individual ``args``
    entry — a developer who accidentally writes ``logger.warning("...
    %s", to)`` would slip past a message-only check until the lazy
    formatter runs.
    """
    for record in caplog.records:
        formatted = record.getMessage()
        assert recipient not in formatted, (
            f"raw recipient leaked into log message: {formatted!r}"
        )
        # ``record.args`` is either a tuple or a mapping depending on
        # how the caller invoked the logger; coerce to a flat sequence
        # so the assertion is uniform.
        if isinstance(record.args, dict):
            arg_values: list[Any] = list(record.args.values())
        elif record.args is None:
            arg_values = []
        else:
            arg_values = list(record.args)
        for arg in arg_values:
            assert recipient not in str(arg), (
                f"raw recipient leaked into log args: {arg!r}"
            )


# ---------------------------------------------------------------------------
# send_login_notification — the explicit codex review target
# ---------------------------------------------------------------------------


async def test_login_notification_missing_api_key_does_not_log_raw_email(
    caplog: pytest.LogCaptureFixture,
    no_api_key: None,
    stub_kms: None,
) -> None:
    """Missing ``RESEND_API_KEY`` → warn log MUST omit the raw recipient.

    This is the dev / test path. The codex round-3 fix replaced
    ``recipient`` with ``recipient_hash`` in the warn message; if a
    future change reverts that, this test fails.
    """
    caplog.set_level(logging.WARNING, logger=email_module.logger.name)

    await send_login_notification(
        to=_RECIPIENT,
        ip_hash="h:ip",
        ua_hash="h:ua",
        timestamp="2026-04-25T10:00:00+00:00",
    )

    # The warn record must exist (we exercised the skip path)…
    assert any("RESEND_API_KEY" in r.getMessage() for r in caplog.records), (
        "expected the missing-API-key warn record to fire"
    )
    # …and must carry the surrogate hash, not the raw address.
    expected_hash = _HASH_BY_RECIPIENT[_RECIPIENT]
    assert any(expected_hash in r.getMessage() for r in caplog.records), (
        "expected recipient_hash surrogate to appear in the log"
    )
    _assert_no_raw_recipient(caplog, _RECIPIENT)


async def test_login_notification_delivery_error_does_not_log_raw_email(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    stub_kms: None,
) -> None:
    """Resend SDK raise → exception log MUST omit the raw recipient.

    The delivery-error path uses ``logger.exception`` so the traceback
    is captured automatically by ``caplog``. We force the SDK call to
    raise and then re-assert the no-PII invariant.
    """
    # Provide a non-empty key so the function gets past the dev-skip
    # branch and reaches the actual ``resend.Emails.send`` call.
    monkeypatch.setattr(email_module.settings, "RESEND_API_KEY", "test-key")

    def _raise(_payload: dict[str, Any]) -> None:
        raise RuntimeError("resend-down")

    monkeypatch.setattr(email_module.resend.Emails, "send", _raise)

    caplog.set_level(logging.ERROR, logger=email_module.logger.name)

    with pytest.raises(RuntimeError, match="resend-down"):
        await send_login_notification(
            to=_RECIPIENT,
            ip_hash="h:ip",
            ua_hash="h:ua",
            timestamp="2026-04-25T10:00:00+00:00",
        )

    # The error log must reference the failure surface…
    assert any("delivery failed" in r.getMessage() for r in caplog.records), (
        "expected the delivery-failed error record to fire"
    )
    # …and use the surrogate, not the raw email address.
    expected_hash = _HASH_BY_RECIPIENT[_RECIPIENT]
    assert any(expected_hash in r.getMessage() for r in caplog.records)
    _assert_no_raw_recipient(caplog, _RECIPIENT)


# ---------------------------------------------------------------------------
# Sibling helpers — same hardening was applied for consistency. Adding
# coverage here guards against a partial-revert that would re-leak only
# the verification or password-reset path.
# ---------------------------------------------------------------------------


async def test_verification_email_missing_api_key_does_not_log_raw_email(
    caplog: pytest.LogCaptureFixture,
    no_api_key: None,
    stub_kms: None,
) -> None:
    caplog.set_level(logging.WARNING, logger=email_module.logger.name)

    await send_verification_email(_OTHER_RECIPIENT, "verification-token-XYZ")

    # The verification token also must NOT leak — this was the original
    # log line's worst sin (a token in logs = account takeover).
    for record in caplog.records:
        assert "verification-token-XYZ" not in record.getMessage()
    # The surrogate hash MUST appear so the warn record is still useful.
    expected_hash = _HASH_BY_RECIPIENT[_OTHER_RECIPIENT]
    assert any(expected_hash in r.getMessage() for r in caplog.records), (
        "expected recipient_hash surrogate to appear in the log"
    )
    _assert_no_raw_recipient(caplog, _OTHER_RECIPIENT)


async def test_verification_email_delivery_error_does_not_log_raw_email(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    stub_kms: None,
) -> None:
    monkeypatch.setattr(email_module.settings, "RESEND_API_KEY", "test-key")
    monkeypatch.setattr(
        email_module.resend.Emails,
        "send",
        MagicMock(side_effect=RuntimeError("resend-down")),
    )

    caplog.set_level(logging.ERROR, logger=email_module.logger.name)

    # ``send_verification_email`` swallows exceptions by design — we
    # only assert on the resulting log record.
    await send_verification_email(_OTHER_RECIPIENT, "verification-token-XYZ")

    assert any("delivery failed" in r.getMessage() for r in caplog.records)
    # The surrogate hash MUST appear alongside the delivery-failed message.
    expected_hash = _HASH_BY_RECIPIENT[_OTHER_RECIPIENT]
    assert any(expected_hash in r.getMessage() for r in caplog.records), (
        "expected recipient_hash surrogate to appear in the log"
    )
    _assert_no_raw_recipient(caplog, _OTHER_RECIPIENT)


async def test_password_reset_email_missing_api_key_does_not_log_raw_email(
    caplog: pytest.LogCaptureFixture,
    no_api_key: None,
    stub_kms: None,
) -> None:
    caplog.set_level(logging.WARNING, logger=email_module.logger.name)

    await send_password_reset_email(_RECIPIENT, "reset-token-ABC")

    for record in caplog.records:
        assert "reset-token-ABC" not in record.getMessage()
    # The surrogate hash MUST appear so the warn record is still useful.
    expected_hash = _HASH_BY_RECIPIENT[_RECIPIENT]
    assert any(expected_hash in r.getMessage() for r in caplog.records), (
        "expected recipient_hash surrogate to appear in the log"
    )
    _assert_no_raw_recipient(caplog, _RECIPIENT)


async def test_password_reset_email_delivery_error_does_not_log_raw_email(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    stub_kms: None,
) -> None:
    monkeypatch.setattr(email_module.settings, "RESEND_API_KEY", "test-key")
    monkeypatch.setattr(
        email_module.resend.Emails,
        "send",
        MagicMock(side_effect=RuntimeError("resend-down")),
    )

    caplog.set_level(logging.ERROR, logger=email_module.logger.name)

    await send_password_reset_email(_RECIPIENT, "reset-token-ABC")

    assert any("delivery failed" in r.getMessage() for r in caplog.records)
    # The surrogate hash MUST appear alongside the delivery-failed message.
    expected_hash = _HASH_BY_RECIPIENT[_RECIPIENT]
    assert any(expected_hash in r.getMessage() for r in caplog.records), (
        "expected recipient_hash surrogate to appear in the log"
    )
    _assert_no_raw_recipient(caplog, _RECIPIENT)
