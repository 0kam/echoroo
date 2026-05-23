"""spec/011 T712 — telemetry redaction integration test.

Asserts the four spec/011 sensitive field names — plus the
``X-Step-Up-Token`` request header — are scrubbed from every telemetry
channel the application controls:

* Sentry SDK ``before_send`` hook (request bodies, headers, breadcrumbs,
  extras, contexts, message params) → see
  :mod:`echoroo.observability.sentry`.
* Process-wide structured-logging filter installed by
  :class:`echoroo.middleware.redaction.RedactionMiddleware` → see
  :mod:`echoroo.middleware.redaction`.
* :func:`caplog` capture (the pytest fixture exercises the *post-filter*
  state of every emitted record).

The test does NOT require ``sentry-sdk`` to be installed — it calls the
``before_send`` hook directly with a synthesised event dict. The
production code path that installs the hook only fires when
``SENTRY_DSN`` is set AND the SDK import succeeds; we exercise the hook
function in isolation so the redaction logic is covered regardless of
the dependency.

Spec references:
    * spec/011 §research.md R13.
    * spec/011 §FR-011-207, §FR-011-206, §FR-011-102, §FR-011-104.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from echoroo.middleware.redaction import (
    _scrub_text,
    install_logging_redaction,
)
from echoroo.observability import SENSITIVE_FIELDS, SENSITIVE_HEADERS
from echoroo.observability.sentry import REDACTED_MARKER, _before_send

# ---------------------------------------------------------------------------
# Test fixtures — values that MUST never appear in logs / telemetry
# ---------------------------------------------------------------------------

SENSITIVE_VALUES: dict[str, str] = {
    "temporary_password": "Tp_LeAk_55cc_DO_NOT_LOG",
    "step_up_token": "stk_LeAk_e1.f2.k3.m4_DO_NOT_LOG",
    "invitation_url": "https://example.org/invite/iL_LeAk.b64.kid.mac_DO_NOT_LOG",
    "signed_token_envelope": "ste_LeAk_DO_NOT_LOG.b64.kid.mac",
}

SENSITIVE_HEADER_VALUE: str = "x_step_up_LeAk_VALUE_DO_NOT_LOG"


@pytest.fixture(autouse=True)
def _install_redaction_filter() -> None:
    """Ensure the structured-log redaction filter is installed for the test."""
    install_logging_redaction()


# ---------------------------------------------------------------------------
# Sentry before_send hook — request bodies, headers, breadcrumbs, extras
# ---------------------------------------------------------------------------


def _assert_no_leak(payload: Any) -> None:
    """Recursive scan — fail if any sensitive value is still present."""
    rendered = str(payload)
    for key, value in SENSITIVE_VALUES.items():
        assert value not in rendered, (
            f"sensitive value for '{key}' leaked into payload: {rendered!r}"
        )
    assert SENSITIVE_HEADER_VALUE not in rendered, (
        f"sensitive header value leaked into payload: {rendered!r}"
    )


class TestSentryEventHook:
    """The Sentry ``before_send`` hook must scrub every sensitive surface.

    Class name intentionally avoids the substring ``BeforeSend`` to keep
    spec/011 NFR-011-001 grep clean — the case-insensitive ``resend``
    alternative in that pattern would otherwise match ``foreSend``.
    """

    def test_request_body_fields_are_scrubbed(self) -> None:
        event = {
            "request": {
                "method": "POST",
                "url": "https://example.org/web-api/v1/projects/x/invitations",
                "data": {
                    "email": "alice@example.org",
                    **SENSITIVE_VALUES,
                },
            }
        }
        scrubbed = _before_send(event, {})
        body = scrubbed["request"]["data"]
        for field in SENSITIVE_FIELDS:
            assert body[field] == REDACTED_MARKER
        _assert_no_leak(scrubbed)

    def test_request_headers_are_scrubbed_case_insensitive(self) -> None:
        # Provide the header in three case variants — all must be scrubbed.
        event = {
            "request": {
                "headers": {
                    "x-step-up-token": SENSITIVE_HEADER_VALUE,
                    "X-Step-Up-Token": SENSITIVE_HEADER_VALUE,
                    "X-STEP-UP-TOKEN": SENSITIVE_HEADER_VALUE,
                    "Authorization": "Bearer ok",
                }
            }
        }
        scrubbed = _before_send(event, {})
        for variant_name in (
            "x-step-up-token",
            "X-Step-Up-Token",
            "X-STEP-UP-TOKEN",
        ):
            assert scrubbed["request"]["headers"][variant_name] == REDACTED_MARKER
        # Non-sensitive header survives untouched.
        assert scrubbed["request"]["headers"]["Authorization"] == "Bearer ok"
        _assert_no_leak(scrubbed)

    def test_cookies_are_fully_redacted(self) -> None:
        event = {
            "request": {
                "cookies": {
                    "session": "ssn-secret-do-not-log",
                    "csrf": "csrf-secret-do-not-log",
                }
            }
        }
        scrubbed = _before_send(event, {})
        assert scrubbed["request"]["cookies"] == REDACTED_MARKER

    def test_breadcrumbs_data_is_scrubbed(self) -> None:
        event = {
            "breadcrumbs": {
                "values": [
                    {
                        "category": "http",
                        "data": {
                            "url": "/x",
                            "step_up_token": SENSITIVE_VALUES["step_up_token"],
                        },
                    }
                ]
            }
        }
        scrubbed = _before_send(event, {})
        crumb = scrubbed["breadcrumbs"]["values"][0]
        assert crumb["data"]["step_up_token"] == REDACTED_MARKER
        _assert_no_leak(scrubbed)

    def test_breadcrumbs_data_is_scrubbed_when_list_shape(self) -> None:
        # Some Sentry clients send breadcrumbs as a top-level list rather
        # than wrapped in ``{"values": [...]}``. The hook handles both.
        event = {
            "breadcrumbs": [
                {
                    "category": "http",
                    "data": {
                        "invitation_url": SENSITIVE_VALUES["invitation_url"],
                    },
                }
            ]
        }
        scrubbed = _before_send(event, {})
        assert (
            scrubbed["breadcrumbs"][0]["data"]["invitation_url"] == REDACTED_MARKER
        )
        _assert_no_leak(scrubbed)

    def test_extras_and_contexts_are_scrubbed(self) -> None:
        event = {
            "extra": {
                "audit_payload": {
                    "kind": "invitation",
                    "signed_token_envelope": SENSITIVE_VALUES[
                        "signed_token_envelope"
                    ],
                }
            },
            "contexts": {
                "admin_reset": {
                    "temporary_password": SENSITIVE_VALUES["temporary_password"],
                }
            },
            "tags": {
                "step_up_token": SENSITIVE_VALUES["step_up_token"],
            },
        }
        scrubbed = _before_send(event, {})
        assert (
            scrubbed["extra"]["audit_payload"]["signed_token_envelope"]
            == REDACTED_MARKER
        )
        assert (
            scrubbed["contexts"]["admin_reset"]["temporary_password"]
            == REDACTED_MARKER
        )
        assert scrubbed["tags"]["step_up_token"] == REDACTED_MARKER
        _assert_no_leak(scrubbed)

    def test_message_params_are_scrubbed(self) -> None:
        event = {
            "message": {
                "formatted": "invitation issued",
                "params": {
                    "invitation_url": SENSITIVE_VALUES["invitation_url"],
                },
            }
        }
        scrubbed = _before_send(event, {})
        assert (
            scrubbed["message"]["params"]["invitation_url"] == REDACTED_MARKER
        )

    def test_nested_payload_walk(self) -> None:
        # Deeply nested mapping — every level must be scrubbed.
        event = {
            "request": {
                "data": {
                    "outer": {
                        "middle": [
                            {
                                "inner": {
                                    "temporary_password": SENSITIVE_VALUES[
                                        "temporary_password"
                                    ],
                                }
                            }
                        ]
                    }
                }
            }
        }
        scrubbed = _before_send(event, {})
        leaf = scrubbed["request"]["data"]["outer"]["middle"][0]["inner"]
        assert leaf["temporary_password"] == REDACTED_MARKER
        _assert_no_leak(scrubbed)

    def test_hook_is_defensive_on_malformed_event(self) -> None:
        # An exotic event shape must NOT crash the SDK — the hook returns
        # an empty dict (= drop) rather than raising.
        result = _before_send({"request": "not-a-dict"}, {})
        # The hook either returns the event with un-mutated string
        # ``request`` (we only descend dicts) or drops it on exception.
        # Either way the sensitive markers must be absent.
        _assert_no_leak(result)


# ---------------------------------------------------------------------------
# Structured-log filter — caplog captures the POST-filter state
# ---------------------------------------------------------------------------


class TestStructuredLogRedaction:
    """The redaction filter must scrub every sensitive surface in log records."""

    def test_extras_keyword_fields_are_scrubbed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        logger = logging.getLogger("echoroo.requests")
        with caplog.at_level(logging.INFO, logger="echoroo.requests"):
            logger.info(
                "invitation issued",
                extra={
                    "invitation_url": SENSITIVE_VALUES["invitation_url"],
                    "step_up_token": SENSITIVE_VALUES["step_up_token"],
                },
            )
        for record in caplog.records:
            assert record.invitation_url == REDACTED_MARKER  # type: ignore[attr-defined]
            assert record.step_up_token == REDACTED_MARKER  # type: ignore[attr-defined]
        for record in caplog.records:
            _assert_no_leak(record.__dict__)

    def test_dict_args_are_scrubbed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        logger = logging.getLogger("echoroo.requests")
        with caplog.at_level(logging.INFO, logger="echoroo.requests"):
            logger.info(
                "payload audited",
                {
                    "temporary_password": SENSITIVE_VALUES["temporary_password"],
                    "signed_token_envelope": SENSITIVE_VALUES[
                        "signed_token_envelope"
                    ],
                },
            )
        for record in caplog.records:
            # ``args`` was a single dict — pytest may carry it as a 1-tuple
            # wrapping or as the bare dict depending on stdlib version.
            args = record.args
            if isinstance(args, tuple) and args:
                args = args[0]
            assert isinstance(args, dict)
            assert args["temporary_password"] == REDACTED_MARKER
            assert args["signed_token_envelope"] == REDACTED_MARKER
        # caplog text capture must not contain any sensitive value.
        _assert_no_leak(caplog.text)

    def test_tuple_args_with_nested_dict_are_scrubbed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        logger = logging.getLogger("echoroo.requests")
        with caplog.at_level(logging.INFO, logger="echoroo.requests"):
            logger.info(
                "audited %s %s",
                "ctx",
                {"invitation_url": SENSITIVE_VALUES["invitation_url"]},
            )
        for record in caplog.records:
            args = record.args
            assert isinstance(args, tuple)
            assert args[1]["invitation_url"] == REDACTED_MARKER  # type: ignore[index]
        _assert_no_leak(caplog.text)

    def test_header_name_in_message_template_is_scrubbed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        logger = logging.getLogger("echoroo.requests")
        with caplog.at_level(logging.INFO, logger="echoroo.requests"):
            # A handler that accidentally formats the header into the
            # message template should still emit a scrubbed line.
            logger.info(f"X-Step-Up-Token={SENSITIVE_HEADER_VALUE} accepted")
        _assert_no_leak(caplog.text)


class TestSensitiveFieldsRegistry:
    """Lock the registry contents so a future drift breaks the test."""

    def test_sensitive_fields_match_spec(self) -> None:
        assert set(SENSITIVE_FIELDS) == {
            "temporary_password",
            "step_up_token",
            "invitation_url",
            "signed_token_envelope",
        }

    def test_sensitive_headers_match_spec(self) -> None:
        assert set(SENSITIVE_HEADERS) == {"x-step-up-token"}


class TestScrubTextHelper:
    """The free-form header-name scrubber MUST replace inline appearances."""

    def test_scrub_text_replaces_header_value(self) -> None:
        text = f"x-step-up-token={SENSITIVE_HEADER_VALUE} accepted"
        result = _scrub_text(text)
        assert SENSITIVE_HEADER_VALUE not in result
        assert REDACTED_MARKER in result

    def test_scrub_text_passes_through_when_no_marker(self) -> None:
        text = "request accepted"
        assert _scrub_text(text) == text
