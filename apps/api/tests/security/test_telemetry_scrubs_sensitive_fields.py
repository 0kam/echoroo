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

import json

from echoroo.middleware.redaction import (
    _scrub_extra_value,
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
        # Step 12 R1 P0-2: ``Authorization`` is now part of the
        # SENSITIVE_HEADERS frozenset so the previously-untouched
        # bearer value must now be scrubbed too.
        event = {
            "request": {
                "headers": {
                    "x-step-up-token": SENSITIVE_HEADER_VALUE,
                    "X-Step-Up-Token": SENSITIVE_HEADER_VALUE,
                    "X-STEP-UP-TOKEN": SENSITIVE_HEADER_VALUE,
                    "User-Agent": "curl/8.0",
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
        assert scrubbed["request"]["headers"]["User-Agent"] == "curl/8.0"
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
        # Step 12 R1 P0-2: SENSITIVE_HEADERS extended to cover
        # ``Authorization`` / ``Cookie`` / ``Set-Cookie`` / ``X-CSRF-Token``
        # — the four credential-bearing headers that previously could
        # land in Sentry events unscathed.
        assert set(SENSITIVE_HEADERS) == {
            "x-step-up-token",
            "authorization",
            "cookie",
            "set-cookie",
            "x-csrf-token",
        }


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


# ---------------------------------------------------------------------------
# Step 12 R1 P0 regression coverage
# ---------------------------------------------------------------------------


class TestStep12R1P0Fixes:
    """Pin the Step 12 R1 P0 telemetry leak fixes.

    Each test corresponds to one P0 from the Codex R1 review:

    * P0-1 — ``event["response"]`` body MUST be scrubbed (the original
      hook only walked ``event["request"]``).
    * P0-2 — ``Authorization`` / ``Cookie`` headers MUST be scrubbed
      (the original frozenset only carried ``x-step-up-token``).
    * P0-3 — JSON-string ``extra`` values MUST be scrubbed (the
      original walker only descended dict / list / tuple structured
      values).
    """

    def test_telemetry_scrubs_response_body(self) -> None:
        # P0-1: a response body carrying ``temporary_password`` (e.g.
        # the admin password-reset endpoint) MUST be redacted by the
        # before_send hook before the event leaves the process.
        event = {
            "response": {
                "status_code": 200,
                "body": {
                    "temporary_password": SENSITIVE_VALUES[
                        "temporary_password"
                    ],
                    "expires_at": "2026-05-24T10:00:00Z",
                },
                "headers": {
                    "Content-Type": "application/json",
                    "Set-Cookie": "session=should-be-scrubbed",
                },
            }
        }
        scrubbed = _before_send(event, {})
        body = scrubbed["response"]["body"]
        assert body["temporary_password"] == REDACTED_MARKER
        # Non-sensitive fields survive.
        assert body["expires_at"] == "2026-05-24T10:00:00Z"
        # Set-Cookie response header is scrubbed via the extended
        # SENSITIVE_HEADERS frozenset (Step 12 R1 P0-2 cross-coverage).
        assert (
            scrubbed["response"]["headers"]["Set-Cookie"] == REDACTED_MARKER
        )
        _assert_no_leak(scrubbed)

    def test_telemetry_scrubs_authorization_header(self) -> None:
        # P0-2: ``Authorization`` bearer tokens MUST be scrubbed from
        # request headers. The original implementation only scrubbed
        # ``X-Step-Up-Token``.
        event = {
            "request": {
                "headers": {
                    "Authorization": "Bearer leaked-session-jwt-do-not-log",
                    "authorization": "Bearer leaked-lowercase-do-not-log",
                    "User-Agent": "curl/8.0",
                }
            }
        }
        scrubbed = _before_send(event, {})
        for variant in ("Authorization", "authorization"):
            assert scrubbed["request"]["headers"][variant] == REDACTED_MARKER
        # Non-sensitive header survives.
        assert scrubbed["request"]["headers"]["User-Agent"] == "curl/8.0"
        # Plain-text rendering of the event must not carry the leaked value.
        assert "leaked-session-jwt-do-not-log" not in str(scrubbed)
        assert "leaked-lowercase-do-not-log" not in str(scrubbed)

    def test_telemetry_scrubs_cookie_header(self) -> None:
        # P0-2: ``Cookie`` request header + ``Set-Cookie`` response
        # header are credential surfaces; both MUST be scrubbed.
        event = {
            "request": {
                "headers": {
                    "Cookie": "echoroo_session=leaked-cookie-do-not-log",
                    "cookie": "csrf=leaked-csrf-do-not-log",
                    "X-CSRF-Token": "leaked-csrf-header-do-not-log",
                }
            },
            "response": {
                "headers": {
                    "Set-Cookie": "echoroo_session=leaked-set-cookie-do-not-log",
                    "set-cookie": "csrf=leaked-set-cookie-lower-do-not-log",
                }
            },
        }
        scrubbed = _before_send(event, {})
        # Request side — all sensitive variants scrubbed.
        for variant in ("Cookie", "cookie", "X-CSRF-Token"):
            assert scrubbed["request"]["headers"][variant] == REDACTED_MARKER
        # Response side — Set-Cookie scrubbed in both case variants.
        for variant in ("Set-Cookie", "set-cookie"):
            assert scrubbed["response"]["headers"][variant] == REDACTED_MARKER
        # No leaked substring survives the round-trip.
        for leaked in (
            "leaked-cookie-do-not-log",
            "leaked-csrf-do-not-log",
            "leaked-csrf-header-do-not-log",
            "leaked-set-cookie-do-not-log",
            "leaked-set-cookie-lower-do-not-log",
        ):
            assert leaked not in str(scrubbed)

    def test_redaction_middleware_scrubs_json_string_extras(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # P0-3: an ``extra={"data": json.dumps(...)}`` payload where
        # the JSON string carries a sensitive key/value pair MUST be
        # scrubbed BEFORE the log record reaches any handler. The
        # original walker skipped string values entirely so this leaked
        # verbatim.
        leaked_token = "stk_leaked_json_string_extra_do_not_log"
        leaked_password = "Tp_leaked_json_string_extra_do_not_log"
        leaked_url = (
            "https://example.org/invite/leaked_json_string_extra_do_not_log"
        )
        # Three distinct JSON shapes the helper must handle:
        # 1. A bare JSON object string (round-trippable).
        # 2. A JSON object embedded as a value inside an outer extras
        #    dict (the canonical ``extra={"data": json.dumps(...)}``
        #    shape).
        # 3. A free-form string with a JSON-style snippet inside
        #    (covers f-string-formatted leaks where the surrounding
        #    text is not itself valid JSON).
        bare_json = json.dumps({"step_up_token": leaked_token})
        embedded_text = (
            "audit emitted, payload was "
            f'{{"temporary_password": "{leaked_password}"}} '
            "(see correlation id)"
        )
        # _scrub_extra_value unit-level coverage — direct invocations
        # so the regression remains pinned even if the filter chain
        # changes shape in a future refactor.
        scrubbed_bare = _scrub_extra_value(bare_json)
        assert leaked_token not in scrubbed_bare
        assert REDACTED_MARKER in scrubbed_bare
        scrubbed_text = _scrub_extra_value(embedded_text)
        assert leaked_password not in scrubbed_text
        assert REDACTED_MARKER in scrubbed_text

        # End-to-end: the actual logging filter must run the same path
        # so a real ``logger.info(..., extra={...})`` invocation never
        # surfaces the leaked value through caplog (caplog captures the
        # POST-filter state).
        logger = logging.getLogger("echoroo.requests")
        with caplog.at_level(logging.INFO, logger="echoroo.requests"):
            logger.info(
                "payload audited",
                extra={
                    "data": json.dumps({"step_up_token": leaked_token}),
                    "embedded": embedded_text,
                    "url_blob": json.dumps({"invitation_url": leaked_url}),
                },
            )
        # caplog text rendering must NOT contain any leaked value.
        assert leaked_token not in caplog.text
        assert leaked_password not in caplog.text
        assert leaked_url not in caplog.text
        # Per-record post-filter state — the extras attributes were
        # rewritten in place.
        for record in caplog.records:
            data_attr = getattr(record, "data", "")
            embedded_attr = getattr(record, "embedded", "")
            url_attr = getattr(record, "url_blob", "")
            assert leaked_token not in data_attr
            assert leaked_password not in embedded_attr
            assert leaked_url not in url_attr
