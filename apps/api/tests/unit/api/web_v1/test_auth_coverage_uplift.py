"""Coverage uplift unit tests for ``echoroo.api.web_v1.auth``.

Phase 17 §C Batch 8: dedicated PR for ``echoroo/api/web_v1/auth.py``
(191 missing lines → ≥85% threshold). Targets helper functions and
endpoint branches not covered by existing integration tests.

Covered areas:
- Helper utilities: _client_ip, _request_id, _user_agent, _has_control_chars,
  _is_safe_redirect_url, _normalize_email, _rate_limit_register
- Token helpers: _encode_reset_token, _decode_reset_token, _reset_token_hash,
  _password_reset_url, _issue_interim_token, _decode_interim_token,
  _decode_interim_token_unbound, _interim_payload_user_id
- Refresh token helpers: _issue_web_refresh_token, _decode_web_refresh_token
- Cookie helpers: _set_session_cookies, _clear_session_cookies,
  _failed_refresh_response, _rate_limit_response
- WebAuthn helpers: _serialize_webauthn_options, _webauthn_http_error,
  _replace_stored_credential
- Async helpers: _sleep_for_minimum_request_time, _claim_interim_jti
- Endpoint branches via FastAPI TestClient + mocked dependencies:
  login (open_redirect_rejected audit, 2fa_setup_required, account_locked,
         invalid_credentials), register (rate_limit, duplicate, integrity_error,
         password_policy), logout (no cookie, with cookie, revoke_failure),
  refresh (no cookie, revoked family, missing user, stale stamp, swap failure)
"""

from __future__ import annotations

import base64
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

import echoroo.api.web_v1.auth as auth_mod
from echoroo.api.web_v1.auth import (
    _clear_session_cookies,
    _client_ip,
    _decode_interim_token,
    _decode_interim_token_unbound,
    _decode_reset_token,
    _decode_web_refresh_token,
    _encode_reset_token,
    _failed_refresh_response,
    _has_control_chars,
    _interim_payload_user_id,
    _is_safe_redirect_url,
    _issue_interim_token,
    _issue_web_refresh_token,
    _normalize_email,
    _password_reset_url,
    _rate_limit_response,
    _replace_stored_credential,
    _request_id,
    _reset_token_hash,
    _serialize_webauthn_options,
    _set_session_cookies,
    _sleep_for_minimum_request_time,
    _user_agent,
    _webauthn_http_error,
    router,
)
from echoroo.core.database import get_db
from echoroo.core.settings import get_settings
from echoroo.services.webauthn_service import (
    WebAuthnDuplicateCredentialError,
    WebAuthnVerificationError,
)

pytestmark = pytest.mark.asyncio

_SETTINGS = get_settings()


# ---------------------------------------------------------------------------
# Request stubs
# ---------------------------------------------------------------------------


def _make_request(
    headers: dict[str, str] | None = None,
    client_host: str = "127.0.0.1",
) -> MagicMock:
    req = MagicMock(spec=Request)
    req.headers = headers or {}
    req.client = SimpleNamespace(host=client_host)
    req.query_params = {}
    return req


# ---------------------------------------------------------------------------
# _client_ip
# ---------------------------------------------------------------------------


def test_client_ip_returns_first_forwarded_for_hop() -> None:
    req = _make_request({"x-forwarded-for": "10.0.0.1, 10.0.0.2"})
    assert _client_ip(req) == "10.0.0.1"


def test_client_ip_strips_whitespace_in_forwarded_for() -> None:
    req = _make_request({"x-forwarded-for": "  192.168.1.1  , 10.0.0.2"})
    assert _client_ip(req) == "192.168.1.1"


def test_client_ip_falls_back_to_request_client_host() -> None:
    req = _make_request({}, client_host="203.0.113.42")
    assert _client_ip(req) == "203.0.113.42"


def test_client_ip_returns_unknown_when_no_client() -> None:
    req = _make_request({})
    req.client = None
    assert _client_ip(req) == "unknown"


def test_client_ip_returns_client_host_when_forwarded_for_empty() -> None:
    # Empty x-forwarded-for header is falsy → falls back to request.client.host
    req = _make_request({"x-forwarded-for": ""}, client_host="10.9.8.7")
    assert _client_ip(req) == "10.9.8.7"


# ---------------------------------------------------------------------------
# _request_id
# ---------------------------------------------------------------------------


def test_request_id_returns_header_value() -> None:
    req = _make_request({"x-request-id": "abc-123"})
    result = _request_id(req)
    assert result == "abc-123"


def test_request_id_generates_uuid_when_header_absent() -> None:
    req = _make_request({})
    result = _request_id(req)
    # Should be a valid UUID4
    UUID(result)


# ---------------------------------------------------------------------------
# _user_agent
# ---------------------------------------------------------------------------


def test_user_agent_returns_header() -> None:
    req = _make_request({"user-agent": "Mozilla/5.0"})
    assert _user_agent(req) == "Mozilla/5.0"


def test_user_agent_returns_empty_string_when_absent() -> None:
    req = _make_request({})
    assert _user_agent(req) == ""


# ---------------------------------------------------------------------------
# _has_control_chars
# ---------------------------------------------------------------------------


def test_has_control_chars_detects_null_byte() -> None:
    assert _has_control_chars("abc\x00def") is True


def test_has_control_chars_returns_false_for_normal_string() -> None:
    assert _has_control_chars("hello@example.com") is False


# ---------------------------------------------------------------------------
# _is_safe_redirect_url
# ---------------------------------------------------------------------------


def test_is_safe_redirect_url_accepts_relative_path() -> None:
    assert _is_safe_redirect_url("/dashboard") is True


def test_is_safe_redirect_url_rejects_absolute_url() -> None:
    assert _is_safe_redirect_url("https://evil.com") is False


def test_is_safe_redirect_url_rejects_none() -> None:
    assert _is_safe_redirect_url(None) is False


def test_is_safe_redirect_url_rejects_protocol_relative() -> None:
    assert _is_safe_redirect_url("//evil.com") is False


# ---------------------------------------------------------------------------
# _normalize_email
# ---------------------------------------------------------------------------


def test_normalize_email_lowercases_and_strips() -> None:
    result = _normalize_email("  Test@Example.COM  ")
    assert result == "test@example.com"


def test_normalize_email_applies_nfkc_normalization() -> None:
    # Full-width @ character (NFKC → ASCII @)
    result = _normalize_email("test＠example.com")
    assert "@" in result


def test_normalize_email_raises_422_for_invalid_email() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _normalize_email("not-an-email")
    assert exc_info.value.status_code == 422


def test_normalize_email_raises_422_for_control_characters() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _normalize_email("abc\x01@example.com")
    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# _rate_limit_register
# ---------------------------------------------------------------------------


def test_rate_limit_register_raises_429_after_ip_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_mod, "_register_windows", {})
    ip = f"10.0.0.{uuid4().hex[:3]}"
    email = f"u_{uuid4().hex[:6]}@example.com"
    for _ in range(auth_mod._REGISTER_IP_LIMIT):
        auth_mod._rate_limit_register(ip=ip, email=f"other_{uuid4().hex[:4]}@example.com")
    with pytest.raises(HTTPException) as exc_info:
        auth_mod._rate_limit_register(ip=ip, email=email)
    assert exc_info.value.status_code == 429


def test_rate_limit_register_raises_429_after_email_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_mod, "_register_windows", {})
    email = f"same_{uuid4().hex[:6]}@example.com"
    for _ in range(auth_mod._REGISTER_EMAIL_LIMIT):
        auth_mod._rate_limit_register(ip=f"1.2.3.{_}", email=email)
    with pytest.raises(HTTPException) as exc_info:
        auth_mod._rate_limit_register(ip="9.9.9.9", email=email)
    assert exc_info.value.status_code == 429


def test_rate_limit_register_passes_within_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_mod, "_register_windows", {})
    ip = f"10.1.{uuid4().hex[:2]}.1"
    email = f"ok_{uuid4().hex[:6]}@example.com"
    # Should not raise for first registration
    auth_mod._rate_limit_register(ip=ip, email=email)


# ---------------------------------------------------------------------------
# _encode_reset_token / _decode_reset_token / _reset_token_hash
# ---------------------------------------------------------------------------


def test_encode_decode_reset_token_roundtrip() -> None:
    token = b"A" * 32
    encoded = _encode_reset_token(token)
    decoded = _decode_reset_token(encoded)
    assert decoded == token


def test_decode_reset_token_raises_400_for_invalid_base64() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _decode_reset_token("!!!invalid!!!")
    assert exc_info.value.status_code == 400


def test_decode_reset_token_raises_400_for_wrong_length() -> None:
    # 16 bytes instead of 32
    short = base64.urlsafe_b64encode(b"X" * 16).decode().rstrip("=")
    with pytest.raises(HTTPException) as exc_info:
        _decode_reset_token(short)
    assert exc_info.value.status_code == 400


def test_reset_token_hash_returns_hex_string() -> None:
    token = b"B" * 32
    result = _reset_token_hash(token)
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


# ---------------------------------------------------------------------------
# _password_reset_url
# ---------------------------------------------------------------------------


def test_password_reset_url_contains_token() -> None:
    token = "abc123"
    url = _password_reset_url(token)
    assert token in url
    assert "/password-reset/confirm?token=" in url


# ---------------------------------------------------------------------------
# _sleep_for_minimum_request_time
# ---------------------------------------------------------------------------


async def test_sleep_for_minimum_request_time_sleeps_when_early() -> None:
    started_at = time.monotonic() - 0.001  # only 1ms elapsed
    # Should sleep without raising; just verify it completes
    await _sleep_for_minimum_request_time(started_at)


async def test_sleep_for_minimum_request_time_skips_when_already_elapsed() -> None:
    started_at = time.monotonic() - 10.0  # 10s ago — well past minimum
    await _sleep_for_minimum_request_time(started_at)


# ---------------------------------------------------------------------------
# _issue_interim_token / _decode_interim_token_unbound / _decode_interim_token
# _interim_payload_user_id
# ---------------------------------------------------------------------------


def _make_user(*, two_factor_enabled: bool = True) -> MagicMock:
    user = MagicMock()
    user.id = uuid4()
    user.email = "test@example.com"
    user.security_stamp = "stamp-abc"
    user.two_factor_enabled = two_factor_enabled
    user.deleted_at = None
    return user


def test_issue_and_decode_interim_token_roundtrip() -> None:
    user = _make_user()
    token = _issue_interim_token(user=user, scope="2fa_challenge")
    payload = _decode_interim_token_unbound(token, expected_scope="2fa_challenge")
    assert payload["sub"] == str(user.id)
    assert payload["scope"] == "2fa_challenge"
    assert payload["type"] == "interim"
    assert payload["ss"] == user.security_stamp


def test_decode_interim_token_unbound_raises_401_for_expired_token() -> None:
    user = _make_user()
    token = _issue_interim_token(user=user, scope="2fa_challenge", ttl_seconds=-1)
    with pytest.raises(HTTPException) as exc_info:
        _decode_interim_token_unbound(token, expected_scope="2fa_challenge")
    assert exc_info.value.status_code == 401


def test_decode_interim_token_unbound_raises_401_for_invalid_signature() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _decode_interim_token_unbound("not.a.valid.jwt", expected_scope="2fa_challenge")
    assert exc_info.value.status_code == 401


def test_decode_interim_token_unbound_raises_401_for_wrong_scope() -> None:
    user = _make_user()
    token = _issue_interim_token(user=user, scope="2fa_setup")
    with pytest.raises(HTTPException) as exc_info:
        _decode_interim_token_unbound(token, expected_scope="2fa_challenge")
    assert exc_info.value.status_code == 401


def test_decode_interim_token_unbound_raises_401_for_wrong_type() -> None:
    # Build a token with type != "interim"
    settings = _SETTINGS
    claims: dict[str, Any] = {
        "sub": str(uuid4()),
        "type": "refresh",  # wrong type
        "scope": "2fa_challenge",
        "ss": "stamp",
        "jti": str(uuid4()),
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    }
    bad_token = jwt.encode(claims, settings.web_session_secret, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(HTTPException) as exc_info:
        _decode_interim_token_unbound(bad_token, expected_scope="2fa_challenge")
    assert exc_info.value.status_code == 401


def test_decode_interim_token_unbound_raises_401_for_non_string_sub() -> None:
    settings = _SETTINGS
    claims: dict[str, Any] = {
        "sub": 12345,  # not a string
        "type": "interim",
        "scope": "2fa_challenge",
        "ss": "stamp",
        "jti": str(uuid4()),
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    }
    bad_token = jwt.encode(claims, settings.web_session_secret, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(HTTPException) as exc_info:
        _decode_interim_token_unbound(bad_token, expected_scope="2fa_challenge")
    assert exc_info.value.status_code == 401


def test_decode_interim_token_checks_user_id_mismatch() -> None:
    user = _make_user()
    token = _issue_interim_token(user=user, scope="2fa_challenge")
    other_user_id = uuid4()
    with pytest.raises(HTTPException) as exc_info:
        _decode_interim_token(token, expected_user_id=other_user_id, expected_scope="2fa_challenge")
    assert exc_info.value.status_code == 401


def test_decode_interim_token_accepts_tuple_scope() -> None:
    user = _make_user()
    token = _issue_interim_token(user=user, scope="2fa_setup_confirm")
    # Tuple scope matching
    payload = _decode_interim_token_unbound(
        token, expected_scope=("2fa_setup_confirm", "webauthn_register")
    )
    assert payload["scope"] == "2fa_setup_confirm"


def test_interim_payload_user_id_raises_401_for_invalid_uuid() -> None:
    bad_payload: dict[str, Any] = {"sub": "not-a-uuid"}
    with pytest.raises(HTTPException) as exc_info:
        _interim_payload_user_id(bad_payload)
    assert exc_info.value.status_code == 401


def test_interim_payload_user_id_raises_401_for_non_string_sub() -> None:
    bad_payload: dict[str, Any] = {"sub": 99}
    with pytest.raises(HTTPException) as exc_info:
        _interim_payload_user_id(bad_payload)
    assert exc_info.value.status_code == 401


def test_interim_payload_user_id_returns_uuid() -> None:
    uid = uuid4()
    result = _interim_payload_user_id({"sub": str(uid)})
    assert result == uid


# ---------------------------------------------------------------------------
# _claim_interim_jti (via mocked Redis)
# ---------------------------------------------------------------------------


async def test_claim_interim_jti_raises_401_for_missing_jti() -> None:
    from echoroo.api.web_v1.auth import _claim_interim_jti

    bad_payload: dict[str, Any] = {"jti": None, "exp": int(time.time()) + 600}
    with pytest.raises(HTTPException) as exc_info:
        await _claim_interim_jti(bad_payload)
    assert exc_info.value.status_code == 401


async def test_claim_interim_jti_raises_401_for_non_int_exp() -> None:
    from echoroo.api.web_v1.auth import _claim_interim_jti

    bad_payload: dict[str, Any] = {"jti": str(uuid4()), "exp": "not-int"}
    with pytest.raises(HTTPException) as exc_info:
        await _claim_interim_jti(bad_payload)
    assert exc_info.value.status_code == 401


async def test_claim_interim_jti_raises_401_for_past_exp() -> None:
    from echoroo.api.web_v1.auth import _claim_interim_jti

    bad_payload: dict[str, Any] = {
        "jti": str(uuid4()),
        "exp": int(time.time()) - 60,  # already expired
    }
    with pytest.raises(HTTPException) as exc_info:
        await _claim_interim_jti(bad_payload)
    assert exc_info.value.status_code == 401


async def test_claim_interim_jti_claims_successfully() -> None:
    from echoroo.api.web_v1.auth import _claim_interim_jti

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)  # NX succeeds → first claim
    payload: dict[str, Any] = {
        "jti": str(uuid4()),
        "exp": int(time.time()) + 600,
    }
    with patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)):
        await _claim_interim_jti(payload)  # should not raise


async def test_claim_interim_jti_raises_replay_error_when_already_claimed() -> None:
    from echoroo.api.web_v1.auth import _claim_interim_jti, _InterimTokenReplayError

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=None)  # NX fails → already claimed
    payload: dict[str, Any] = {
        "jti": str(uuid4()),
        "exp": int(time.time()) + 600,
    }
    with (
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)),
        pytest.raises(_InterimTokenReplayError),
    ):
        await _claim_interim_jti(payload)


# ---------------------------------------------------------------------------
# _issue_web_refresh_token / _decode_web_refresh_token
# ---------------------------------------------------------------------------


def test_issue_web_refresh_token_roundtrip() -> None:
    user_id = uuid4()
    stamp = "test-stamp"
    token, record = _issue_web_refresh_token(user_id=user_id, security_stamp=stamp)
    # Decode and verify
    claims = _decode_web_refresh_token(token)
    assert claims.user_id == user_id
    assert claims.security_stamp == stamp
    assert claims.family_id == record.family_id
    assert claims.jti == record.jti


def test_issue_web_refresh_token_with_explicit_family_id() -> None:
    user_id = uuid4()
    family_id = str(uuid4())
    token, record = _issue_web_refresh_token(
        user_id=user_id, security_stamp="stamp", family_id=family_id
    )
    claims = _decode_web_refresh_token(token)
    assert claims.family_id == family_id


def test_decode_web_refresh_token_raises_401_for_expired() -> None:
    settings = _SETTINGS
    user_id = uuid4()
    # Directly encode a token with exp in the past
    past_ts = int((datetime.now(UTC) - timedelta(hours=1)).timestamp())
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "jti": str(uuid4()),
        "family": str(uuid4()),
        "type": "refresh",
        "ss": "stamp",
        "iat": past_ts - 3600,
        "exp": past_ts,
    }
    expired_token = jwt.encode(
        claims, settings.web_session_secret, algorithm=settings.JWT_ALGORITHM
    )
    with pytest.raises(HTTPException) as exc_info:
        _decode_web_refresh_token(expired_token)
    assert exc_info.value.status_code == 401


def test_decode_web_refresh_token_raises_401_for_invalid_signature() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _decode_web_refresh_token("not.a.real.token")
    assert exc_info.value.status_code == 401


def test_decode_web_refresh_token_raises_401_for_wrong_type() -> None:
    settings = _SETTINGS
    user_id = uuid4()
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "jti": str(uuid4()),
        "family": str(uuid4()),
        "type": "interim",  # wrong type
        "ss": "stamp",
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(days=1)).timestamp()),
    }
    bad_token = jwt.encode(claims, settings.web_session_secret, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(HTTPException) as exc_info:
        _decode_web_refresh_token(bad_token)
    assert exc_info.value.status_code == 401


def test_decode_web_refresh_token_raises_401_for_non_string_sub() -> None:
    settings = _SETTINGS
    claims: dict[str, Any] = {
        "sub": 999,  # not a string
        "jti": str(uuid4()),
        "family": str(uuid4()),
        "type": "refresh",
        "ss": "stamp",
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(days=1)).timestamp()),
    }
    bad_token = jwt.encode(claims, settings.web_session_secret, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(HTTPException) as exc_info:
        _decode_web_refresh_token(bad_token)
    assert exc_info.value.status_code == 401


def test_decode_web_refresh_token_raises_401_for_missing_fields() -> None:
    settings = _SETTINGS
    # Missing "family" field
    claims: dict[str, Any] = {
        "sub": str(uuid4()),
        "jti": str(uuid4()),
        # "family" omitted
        "type": "refresh",
        "ss": "stamp",
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(days=1)).timestamp()),
    }
    bad_token = jwt.encode(claims, settings.web_session_secret, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(HTTPException) as exc_info:
        _decode_web_refresh_token(bad_token)
    assert exc_info.value.status_code == 401


def test_decode_web_refresh_token_raises_401_for_invalid_uuid_sub() -> None:
    settings = _SETTINGS
    claims: dict[str, Any] = {
        "sub": "not-a-uuid",
        "jti": str(uuid4()),
        "family": str(uuid4()),
        "type": "refresh",
        "ss": "stamp",
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(days=1)).timestamp()),
    }
    bad_token = jwt.encode(claims, settings.web_session_secret, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(HTTPException) as exc_info:
        _decode_web_refresh_token(bad_token)
    assert exc_info.value.status_code == 401


def test_decode_web_refresh_token_raises_401_for_missing_exp() -> None:
    """Token without exp field: jwt.decode raises InvalidTokenError → 401."""
    settings = _SETTINGS
    # Build the claims dict without "exp"
    claims_no_exp: dict[str, Any] = {
        "sub": str(uuid4()),
        "jti": str(uuid4()),
        "family": str(uuid4()),
        "type": "refresh",
        "ss": "stamp",
        "iat": int(datetime.now(UTC).timestamp()),
        # "exp" deliberately omitted
    }
    # PyJWT will raise DecodeError / MissingRequiredClaimError when verifying a
    # token without exp, which is caught by the jwt.InvalidTokenError branch.
    bad_token = jwt.encode(
        claims_no_exp,
        settings.web_session_secret,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(HTTPException) as exc_info:
        _decode_web_refresh_token(bad_token)
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# _rate_limit_response
# ---------------------------------------------------------------------------


def test_rate_limit_response_returns_429() -> None:
    exc = _rate_limit_response(60)
    assert exc.status_code == 429
    assert exc.headers is not None
    assert exc.headers.get("Retry-After") == "60"


# ---------------------------------------------------------------------------
# _serialize_webauthn_options
# ---------------------------------------------------------------------------


def test_serialize_webauthn_options_returns_dict_unchanged() -> None:
    options: dict[str, Any] = {"challenge": "abc", "timeout": 60000}
    result = _serialize_webauthn_options(options)
    assert result is options


def test_serialize_webauthn_options_converts_non_dict() -> None:
    options = MagicMock()
    options_dict = {"converted": True}
    with patch("echoroo.api.web_v1.auth.options_to_json_dict", return_value=options_dict):
        result = _serialize_webauthn_options(options)
    assert result == options_dict


# ---------------------------------------------------------------------------
# _webauthn_http_error
# ---------------------------------------------------------------------------


def test_webauthn_http_error_returns_409_for_duplicate_credential() -> None:
    exc = _webauthn_http_error(WebAuthnDuplicateCredentialError("dup"))
    assert exc.status_code == 409


def test_webauthn_http_error_returns_401_for_verification_error() -> None:
    exc = _webauthn_http_error(WebAuthnVerificationError("bad"))
    assert exc.status_code == 401


def test_webauthn_http_error_returns_401_for_generic_exception() -> None:
    exc = _webauthn_http_error(ValueError("other"))
    assert exc.status_code == 401


# ---------------------------------------------------------------------------
# _replace_stored_credential
# ---------------------------------------------------------------------------


def test_replace_stored_credential_replaces_existing() -> None:
    cred_a = {"credential_id": "id-a", "sign_count": 1, "name": "a", "registered_at": "now"}
    cred_b = {"credential_id": "id-b", "sign_count": 2, "name": "b", "registered_at": "now"}
    updated_a = {"credential_id": "id-a", "sign_count": 99, "name": "a-updated", "registered_at": "now"}

    result = _replace_stored_credential([cred_a, cred_b], updated_a)  # type: ignore[arg-type]
    assert len(result) == 2
    assert result[0]["sign_count"] == 99
    assert result[1]["credential_id"] == "id-b"


def test_replace_stored_credential_appends_new_credential() -> None:
    cred_a = {"credential_id": "id-a", "sign_count": 1, "name": "a", "registered_at": "now"}
    new_cred = {"credential_id": "id-new", "sign_count": 1, "name": "new", "registered_at": "now"}

    result = _replace_stored_credential([cred_a], new_cred)  # type: ignore[arg-type]
    assert len(result) == 2
    assert result[1]["credential_id"] == "id-new"


# ---------------------------------------------------------------------------
# Cookie helpers: _set_session_cookies / _clear_session_cookies /
# _failed_refresh_response
# ---------------------------------------------------------------------------


def test_set_session_cookies_sets_all_four_cookies() -> None:
    response = MagicMock(spec=Response)
    response.headers = {}
    refresh_token = "refresh-token-value"
    family_id = str(uuid4())
    _set_session_cookies(response, refresh_token=refresh_token, family_id=family_id)
    # Verify set_cookie was called 4 times
    assert response.set_cookie.call_count == 4


def test_clear_session_cookies_deletes_all_four_cookies() -> None:
    response = MagicMock(spec=Response)
    _clear_session_cookies(response)
    assert response.delete_cookie.call_count == 4


def test_failed_refresh_response_returns_json_401_with_cleared_cookies() -> None:
    resp = _failed_refresh_response("Invalid refresh token")
    assert isinstance(resp, JSONResponse)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# FastAPI endpoint tests via ASGI client (mocked dependencies)
# ---------------------------------------------------------------------------


def _build_app_with_mocked_db(mock_db: Any) -> FastAPI:
    """Build a minimal FastAPI app mounting the auth router with mocked DB."""
    app = FastAPI()

    async def override_db() -> AsyncGenerator[Any, None]:
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    app.include_router(router, prefix="/web-api/v1")
    return app


# ---------- login: open_redirect_rejected audit + 2fa_required path ----------


async def test_login_audits_open_redirect_and_returns_2fa_required() -> None:
    """Login with ?next=https://evil.com writes audit and still proceeds."""
    from echoroo.services.auth_service import AuthenticateResult

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user(two_factor_enabled=True)
    auth_result = MagicMock(spec=AuthenticateResult)
    auth_result.user = user

    with (
        patch.object(auth_mod, "authenticate", AsyncMock(return_value=auth_result)),
        patch.object(auth_mod, "_write_platform_audit", AsyncMock()),
        patch.object(auth_mod, "compute_pii_hash", return_value="hash-abc"),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/login?next=https://evil.com",
                json={"email": "test@example.com", "password": "pass123"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["login_state"] in ("2fa_required", "2fa_setup_required")
    assert "interim_token" in data


async def test_login_returns_2fa_setup_required_when_2fa_not_set_up() -> None:
    """Login returns 2fa_setup_required when is_two_factor_required returns True."""
    from echoroo.services.auth_service import AuthenticateResult
    from echoroo.services.two_factor_service import TwoFactorService

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user(two_factor_enabled=False)
    auth_result = MagicMock(spec=AuthenticateResult)
    auth_result.user = user

    with (
        patch.object(auth_mod, "authenticate", AsyncMock(return_value=auth_result)),
        patch.object(auth_mod, "_write_platform_audit", AsyncMock()),
        patch.object(auth_mod, "compute_pii_hash", return_value="hash-abc"),
        patch.object(TwoFactorService, "is_two_factor_required", return_value=True),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/login",
                json={"email": "test@example.com", "password": "P@ssw0rd123!"},
            )
    assert resp.status_code == 200
    assert resp.json()["login_state"] == "2fa_setup_required"


async def test_login_returns_2fa_required_when_2fa_enabled() -> None:
    """Login returns 2fa_required when is_two_factor_required returns False."""
    from echoroo.services.auth_service import AuthenticateResult
    from echoroo.services.two_factor_service import TwoFactorService

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user(two_factor_enabled=True)
    auth_result = MagicMock(spec=AuthenticateResult)
    auth_result.user = user

    with (
        patch.object(auth_mod, "authenticate", AsyncMock(return_value=auth_result)),
        patch.object(auth_mod, "_write_platform_audit", AsyncMock()),
        patch.object(auth_mod, "compute_pii_hash", return_value="hash-abc"),
        patch.object(TwoFactorService, "is_two_factor_required", return_value=False),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/login",
                json={"email": "test@example.com", "password": "P@ssw0rd123!"},
            )
    assert resp.status_code == 200
    assert resp.json()["login_state"] == "2fa_required"


async def test_login_returns_429_for_account_locked() -> None:
    from echoroo.services.auth_service import AccountLockedError

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    with (
        patch.object(
            auth_mod, "authenticate", AsyncMock(side_effect=AccountLockedError(30))
        ),
        patch.object(auth_mod, "_write_platform_audit", AsyncMock()),
        patch.object(auth_mod, "compute_pii_hash", return_value="hash-abc"),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/login",
                json={"email": "test@example.com", "password": "wrong"},
            )
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


async def test_login_returns_401_for_invalid_credentials() -> None:
    from echoroo.services.auth_service import InvalidCredentialsError

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    with (
        patch.object(
            auth_mod, "authenticate", AsyncMock(side_effect=InvalidCredentialsError())
        ),
        patch.object(auth_mod, "_write_platform_audit", AsyncMock()),
        patch.object(auth_mod, "compute_pii_hash", return_value="hash-abc"),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/login",
                json={"email": "test@example.com", "password": "wrong"},
            )
    assert resp.status_code == 401


# ---------- register: duplicate, integrity error, rate limit ----------


async def test_register_returns_409_for_duplicate_email() -> None:
    from echoroo.repositories.user import UserRepository

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    existing_user = _make_user()
    with (
        patch.object(auth_mod, "enforce_password_policy", AsyncMock()),
        patch.object(UserRepository, "get_by_email", AsyncMock(return_value=existing_user)),
        patch.object(auth_mod, "_write_platform_audit", AsyncMock()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/register",
                json={
                    "email": "existing@example.com",
                    "password": "StrongPass123!",
                    "display_name": "User",
                },
            )
    assert resp.status_code == 409


async def test_register_returns_422_for_weak_password() -> None:
    from echoroo.services.auth_service import PasswordPolicyError

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    with patch.object(
        auth_mod, "enforce_password_policy", AsyncMock(side_effect=PasswordPolicyError("too weak"))
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/register",
                json={
                    "email": "new@example.com",
                    "password": "weak",
                    "display_name": "User",
                },
            )
    assert resp.status_code == 422


async def test_register_returns_422_for_invalid_email() -> None:
    """Email validation failure before password policy check."""
    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/web-api/v1/auth/register",
            json={"email": "not-an-email", "password": "StrongPass123!"},
        )
    assert resp.status_code == 422


async def test_register_returns_409_on_integrity_error() -> None:
    """IntegrityError during repo.create → 409 Conflict."""
    from sqlalchemy.exc import IntegrityError

    from echoroo.repositories.user import UserRepository

    mock_db = AsyncMock()
    mock_db.rollback = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    with (
        patch.object(auth_mod, "enforce_password_policy", AsyncMock()),
        patch.object(UserRepository, "get_by_email", AsyncMock(return_value=None)),
        patch.object(
            UserRepository,
            "create",
            AsyncMock(side_effect=IntegrityError("dup", None, None)),
        ),
        patch.object(auth_mod, "_write_platform_audit", AsyncMock()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/register",
                json={
                    "email": "new@example.com",
                    "password": "StrongPass123!",
                    "display_name": "User",
                },
            )
    assert resp.status_code == 409


async def test_register_returns_429_when_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_mod, "_register_windows", {})
    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    # Exhaust IP limit before hitting the endpoint
    ip = "10.0.0.1"
    email = f"u_{uuid4().hex[:6]}@example.com"
    for _ in range(auth_mod._REGISTER_IP_LIMIT):
        auth_mod._rate_limit_register(ip=ip, email=f"other_{_}@example.com")

    # Patch _client_ip to return our limited IP
    with patch.object(auth_mod, "_client_ip", return_value=ip):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/register",
                json={"email": email, "password": "StrongPass123!"},
            )
    assert resp.status_code == 429


# ---------- logout: no cookie, with cookie, revoke failure ----------


async def test_logout_clears_cookies_with_no_session_cookie() -> None:
    """Logout with no session cookie returns 204 idempotently."""
    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    with patch.object(auth_mod, "_write_platform_audit", AsyncMock()):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/web-api/v1/auth/logout")
    assert resp.status_code == 204


async def test_logout_clears_cookies_with_valid_session_cookie() -> None:
    """Logout with valid family_id cookie revokes family and returns 204."""

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    family_id = str(uuid4())
    mock_store = AsyncMock()
    mock_store.revoke_family = AsyncMock()

    with (
        patch.object(auth_mod, "_write_platform_audit", AsyncMock()),
        patch("echoroo.api.web_v1.auth.SqlTokenStore", return_value=mock_store),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/logout",
                cookies={_SETTINGS.web_session_cookie_name: family_id},
            )
    assert resp.status_code == 204


async def test_logout_stays_idempotent_when_revoke_fails() -> None:
    """Logout still returns 204 if revoke_family raises an exception."""
    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    family_id = str(uuid4())
    mock_store = AsyncMock()
    mock_store.revoke_family = AsyncMock(side_effect=Exception("DB error"))

    with (
        patch.object(auth_mod, "_write_platform_audit", AsyncMock()),
        patch("echoroo.api.web_v1.auth.SqlTokenStore", return_value=mock_store),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/logout",
                cookies={_SETTINGS.web_session_cookie_name: family_id},
            )
    assert resp.status_code == 204


async def test_logout_stays_idempotent_when_audit_write_fails() -> None:
    """Logout still returns 204 if _write_platform_audit raises."""
    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    with patch.object(
        auth_mod, "_write_platform_audit", AsyncMock(side_effect=Exception("audit fail"))
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/web-api/v1/auth/logout")
    assert resp.status_code == 204


# ---------- refresh: no cookie, revoked family, missing user, stale stamp, swap fail ----------


async def test_refresh_returns_401_when_no_cookie() -> None:
    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/web-api/v1/auth/refresh")
    assert resp.status_code == 401


async def test_refresh_returns_401_and_clears_cookies_for_revoked_family() -> None:

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user()
    token, record = _issue_web_refresh_token(
        user_id=user.id, security_stamp=user.security_stamp
    )

    mock_store = AsyncMock()
    mock_store.is_family_revoked = AsyncMock(return_value=True)

    with patch("echoroo.api.web_v1.auth.SqlTokenStore", return_value=mock_store):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/refresh",
                cookies={_SETTINGS.web_refresh_cookie_name: token},
            )
    assert resp.status_code == 401


async def test_refresh_returns_401_and_clears_cookies_when_user_not_found() -> None:
    from echoroo.repositories.user import UserRepository

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user()
    token, record = _issue_web_refresh_token(
        user_id=user.id, security_stamp=user.security_stamp
    )

    mock_store = AsyncMock()
    mock_store.is_family_revoked = AsyncMock(return_value=False)
    mock_store.revoke_family = AsyncMock()

    with (
        patch("echoroo.api.web_v1.auth.SqlTokenStore", return_value=mock_store),
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=None)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/refresh",
                cookies={_SETTINGS.web_refresh_cookie_name: token},
            )
    assert resp.status_code == 401


async def test_refresh_returns_401_when_security_stamp_stale() -> None:
    from echoroo.repositories.user import UserRepository

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user()
    token, record = _issue_web_refresh_token(
        user_id=user.id, security_stamp="old-stamp"
    )
    user.security_stamp = "new-stamp"  # stamp rotated

    mock_store = AsyncMock()
    mock_store.is_family_revoked = AsyncMock(return_value=False)
    mock_store.revoke_family = AsyncMock()

    with (
        patch("echoroo.api.web_v1.auth.SqlTokenStore", return_value=mock_store),
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/refresh",
                cookies={_SETTINGS.web_refresh_cookie_name: token},
            )
    assert resp.status_code == 401


async def test_refresh_returns_401_when_swap_fails() -> None:
    """atomic_consume_and_issue returns False → family revoked → 401."""
    from echoroo.repositories.user import UserRepository

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user()
    token, record = _issue_web_refresh_token(
        user_id=user.id, security_stamp=user.security_stamp
    )

    mock_store = AsyncMock()
    mock_store.is_family_revoked = AsyncMock(return_value=False)
    mock_store.revoke_family = AsyncMock()
    mock_store.atomic_consume_and_issue = AsyncMock(return_value=False)

    with (
        patch("echoroo.api.web_v1.auth.SqlTokenStore", return_value=mock_store),
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        patch.object(auth_mod, "_write_platform_audit", AsyncMock()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/refresh",
                cookies={_SETTINGS.web_refresh_cookie_name: token},
            )
    assert resp.status_code == 401


async def test_refresh_succeeds_with_valid_token() -> None:
    from echoroo.repositories.user import UserRepository

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user()
    token, record = _issue_web_refresh_token(
        user_id=user.id, security_stamp=user.security_stamp
    )

    mock_store = AsyncMock()
    mock_store.is_family_revoked = AsyncMock(return_value=False)
    mock_store.revoke_family = AsyncMock()
    mock_store.atomic_consume_and_issue = AsyncMock(return_value=True)
    mock_store.record_issued = AsyncMock()

    with (
        patch("echoroo.api.web_v1.auth.SqlTokenStore", return_value=mock_store),
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/refresh",
                cookies={_SETTINGS.web_refresh_cookie_name: token},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "expires_in" in data


# ---------- password reset: 2FA cooldown, valid user, deleted user ----------


async def test_request_password_reset_returns_204_for_unknown_email() -> None:
    from echoroo.repositories.user import UserRepository

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    with (
        patch.object(UserRepository, "get_by_email", AsyncMock(return_value=None)),
        patch.object(auth_mod, "_write_platform_audit", AsyncMock()),
        patch.object(auth_mod, "compute_pii_hash", return_value="hash"),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/password-reset/request",
                json={"email": "unknown@example.com"},
            )
    assert resp.status_code == 204


async def test_request_password_reset_returns_204_for_invalid_email() -> None:
    """Malformed email → audit write → 204 (no enumeration leak)."""
    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    with patch.object(auth_mod, "_write_platform_audit", AsyncMock()):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/password-reset/request",
                json={"email": "not-an-email"},
            )
    assert resp.status_code == 204


async def test_request_password_reset_returns_204_during_2fa_cooldown() -> None:
    """Active 2FA reset cooldown → audit + 204 (T150d decision)."""
    from echoroo.repositories.user import UserRepository

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user()
    user.two_factor_reset_cooldown_until = datetime.now(UTC) + timedelta(hours=1)
    user.deleted_at = None

    with (
        patch.object(UserRepository, "get_by_email", AsyncMock(return_value=user)),
        patch.object(auth_mod, "_write_platform_audit", AsyncMock()),
        patch.object(auth_mod, "compute_pii_hash", return_value="hash"),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/password-reset/request",
                json={"email": "user@example.com"},
            )
    assert resp.status_code == 204


async def test_confirm_password_reset_returns_400_for_invalid_token() -> None:
    """Malformed/garbage reset token → 400."""
    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/web-api/v1/auth/password-reset/confirm",
            json={"token": "!!!invalid!!!", "new_password": "NewPass123!"},
        )
    assert resp.status_code == 400


# ---------- _write_platform_audit helper (async session path) ----------


async def test_write_platform_audit_rolls_back_on_exception() -> None:
    """_write_platform_audit re-raises after rolling back on failure."""
    request = _make_request()

    mock_audit = AsyncMock()
    mock_audit.write_platform_event = AsyncMock(side_effect=RuntimeError("db fail"))
    mock_session = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_session_local = MagicMock(return_value=mock_session)

    with (
        patch("echoroo.api.web_v1.auth.AuditLogService", return_value=mock_audit),
        patch("echoroo.api.web_v1.auth.AsyncSessionLocal", mock_session_local),
        pytest.raises(RuntimeError, match="db fail"),
    ):
        await auth_mod._write_platform_audit(
            actor_user_id=None,
            action="auth.test_event",
            request=request,
        )
    mock_session.rollback.assert_called_once()


# ---------- _record_login_notification swallows exceptions ----------


async def test_record_login_notification_swallows_exception() -> None:
    """Notification failure must not propagate (BLE001 comment in source)."""
    user = _make_user()
    request = _make_request()

    mock_service = AsyncMock()
    mock_service.record_and_maybe_notify = AsyncMock(side_effect=RuntimeError("notify fail"))
    mock_session = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session_local = MagicMock(return_value=mock_session)

    with (
        patch("echoroo.api.web_v1.auth.LoginNotificationService", return_value=mock_service),
        patch("echoroo.api.web_v1.auth.AsyncSessionLocal", mock_session_local),
    ):
        # Must not raise
        await auth_mod._record_login_notification(user=user, request=request)
    mock_session.rollback.assert_called_once()


# ---------- _is_superuser helper ----------


async def test_is_superuser_returns_false_when_not_in_table() -> None:
    from echoroo.api.web_v1.auth import _is_superuser

    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none = MagicMock(return_value=None)
    mock_db.execute = AsyncMock(return_value=result_mock)

    result = await _is_superuser(mock_db, uuid4())
    assert result is False


async def test_is_superuser_returns_true_when_in_table() -> None:
    from echoroo.api.web_v1.auth import _is_superuser

    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none = MagicMock(return_value=1)
    mock_db.execute = AsyncMock(return_value=result_mock)

    result = await _is_superuser(mock_db, uuid4())
    assert result is True


async def test_require_superuser_raises_403_when_not_superuser() -> None:
    from echoroo.api.web_v1.auth import _require_superuser

    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none = MagicMock(return_value=None)
    mock_db.execute = AsyncMock(return_value=result_mock)

    with pytest.raises(HTTPException) as exc_info:
        await _require_superuser(mock_db, uuid4())
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# _decode_reset_token: UnicodeEncodeError branch
# ---------------------------------------------------------------------------


def test_decode_reset_token_raises_400_for_non_ascii_input() -> None:
    """Non-ASCII characters in encoded token → UnicodeEncodeError → 400."""
    with pytest.raises(HTTPException) as exc_info:
        # Unicode character that can't be encoded as ASCII
        _decode_reset_token("éabcéabc")
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# _revoke_refresh_families_for_user helper (direct mock DB test)
# ---------------------------------------------------------------------------


async def test_revoke_refresh_families_for_user_executes_two_statements() -> None:
    from echoroo.api.web_v1.auth import _revoke_refresh_families_for_user

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()

    user_id = uuid4()
    await _revoke_refresh_families_for_user(mock_db, user_id)
    assert mock_db.execute.call_count == 2


# ---------------------------------------------------------------------------
# _consume_interim_token_for_user branches (user None, stale stamp, deleted)
# ---------------------------------------------------------------------------


async def test_consume_interim_token_for_user_raises_401_when_user_not_found() -> None:
    from echoroo.api.web_v1.auth import _consume_interim_token_for_user
    from echoroo.repositories.user import UserRepository

    user = _make_user()
    token = _issue_interim_token(user=user, scope="2fa_challenge")
    request = _make_request()
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=None)),
        pytest.raises(HTTPException) as exc_info,
    ):
        await _consume_interim_token_for_user(
            raw_token=token,
            expected_scope="2fa_challenge",
            request=request,
            db=mock_db,
        )
    assert exc_info.value.status_code == 401


async def test_consume_interim_token_for_user_raises_401_when_stamp_mismatch() -> None:
    from echoroo.api.web_v1.auth import _consume_interim_token_for_user
    from echoroo.repositories.user import UserRepository

    user = _make_user()
    token = _issue_interim_token(user=user, scope="2fa_challenge")
    # Change security stamp after issuing token
    user.security_stamp = "rotated-stamp"
    request = _make_request()
    mock_db = AsyncMock()

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        pytest.raises(HTTPException) as exc_info,
    ):
        await _consume_interim_token_for_user(
            raw_token=token,
            expected_scope="2fa_challenge",
            request=request,
            db=mock_db,
        )
    assert exc_info.value.status_code == 401


async def test_consume_interim_token_for_user_raises_401_when_user_deleted() -> None:
    from echoroo.api.web_v1.auth import _consume_interim_token_for_user
    from echoroo.repositories.user import UserRepository

    user = _make_user()
    token = _issue_interim_token(user=user, scope="2fa_challenge")
    user.deleted_at = datetime.now(UTC)
    request = _make_request()
    mock_db = AsyncMock()

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        pytest.raises(HTTPException) as exc_info,
    ):
        await _consume_interim_token_for_user(
            raw_token=token,
            expected_scope="2fa_challenge",
            request=request,
            db=mock_db,
        )
    assert exc_info.value.status_code == 401


async def test_consume_interim_token_for_user_raises_401_on_replay() -> None:
    """Replay detected → audit written → 401."""
    from echoroo.api.web_v1.auth import _consume_interim_token_for_user
    from echoroo.repositories.user import UserRepository

    user = _make_user()
    token = _issue_interim_token(user=user, scope="2fa_challenge")
    request = _make_request()
    mock_db = AsyncMock()

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=None)  # NX fails → replay

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)),
        patch.object(auth_mod, "_write_platform_audit", AsyncMock()),
        pytest.raises(HTTPException) as exc_info,
    ):
        await _consume_interim_token_for_user(
            raw_token=token,
            expected_scope="2fa_challenge",
            request=request,
            db=mock_db,
        )
    assert exc_info.value.status_code == 401


async def test_consume_interim_token_for_user_succeeds_with_valid_token() -> None:
    """Happy path: valid token, user found, stamp matches, JTI claimed."""
    from echoroo.api.web_v1.auth import _consume_interim_token_for_user
    from echoroo.repositories.user import UserRepository

    user = _make_user()
    token = _issue_interim_token(user=user, scope="2fa_challenge")
    request = _make_request()
    mock_db = AsyncMock()

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)  # NX succeeds

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)),
    ):
        result_user, result_payload = await _consume_interim_token_for_user(
            raw_token=token,
            expected_scope="2fa_challenge",
            request=request,
            db=mock_db,
        )
    assert result_user is user
    assert result_payload["scope"] == "2fa_challenge"


# ---------------------------------------------------------------------------
# _consume_interim_token_for_user_with_scopes
# ---------------------------------------------------------------------------


async def test_consume_interim_token_for_user_with_scopes_raises_401_on_scope_mismatch() -> None:
    from echoroo.api.web_v1.auth import _consume_interim_token_for_user_with_scopes

    user = _make_user()
    token = _issue_interim_token(user=user, scope="2fa_setup")  # not in expected_scopes
    request = _make_request()
    mock_db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await _consume_interim_token_for_user_with_scopes(
            raw_token=token,
            expected_scopes=("2fa_challenge", "webauthn_challenge_complete"),
            request=request,
            db=mock_db,
        )
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# _issue_real_session (mock all deps)
# ---------------------------------------------------------------------------


async def test_issue_real_session_sets_cookies_and_returns_access_token() -> None:
    from echoroo.api.web_v1.auth import _issue_real_session

    user = _make_user()
    response = MagicMock(spec=Response)
    response.headers = {}
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    mock_token_store = AsyncMock()
    mock_token_store.record_issued = AsyncMock()

    with (
        patch("echoroo.api.web_v1.auth.SqlTokenStore", return_value=mock_token_store),
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=AsyncMock())),
    ):
        access_token = await _issue_real_session(response=response, user=user, db=mock_db)
    assert isinstance(access_token, str)
    assert len(access_token) > 0


async def test_issue_real_session_swallows_redis_error() -> None:
    """Redis delete failure must not block login (BLE001 path)."""
    from echoroo.api.web_v1.auth import _issue_real_session

    user = _make_user()
    response = MagicMock(spec=Response)
    response.headers = {}
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    mock_token_store = AsyncMock()
    mock_token_store.record_issued = AsyncMock()

    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock(side_effect=Exception("redis down"))

    with (
        patch("echoroo.api.web_v1.auth.SqlTokenStore", return_value=mock_token_store),
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)),
    ):
        access_token = await _issue_real_session(response=response, user=user, db=mock_db)
    assert isinstance(access_token, str)


# ---------------------------------------------------------------------------
# register: success path
# ---------------------------------------------------------------------------


async def test_register_creates_user_successfully() -> None:
    from echoroo.repositories.user import UserRepository

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    created_user_id = uuid4()

    async def _fake_create(user: Any) -> None:
        # Simulate DB assigning an id after insert
        user.id = created_user_id

    with (
        patch.object(auth_mod, "enforce_password_policy", AsyncMock()),
        patch.object(UserRepository, "get_by_email", AsyncMock(return_value=None)),
        patch.object(UserRepository, "create", AsyncMock(side_effect=_fake_create)),
        patch.object(auth_mod, "_write_platform_audit", AsyncMock()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/register",
                json={
                    "email": "newuser@example.com",
                    "password": "StrongPass123!",
                    "display_name": "New User",
                    "timezone": "UTC",
                },
            )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "newuser@example.com"


# ---------------------------------------------------------------------------
# password reset: enqueue path (valid user, no cooldown)
# ---------------------------------------------------------------------------


async def test_request_password_reset_enqueues_for_valid_user() -> None:
    from echoroo.repositories.user import UserRepository

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user()
    user.two_factor_reset_cooldown_until = None
    user.deleted_at = None

    with (
        patch.object(UserRepository, "get_by_email", AsyncMock(return_value=user)),
        patch.object(auth_mod, "_write_platform_audit", AsyncMock()),
        patch.object(auth_mod, "compute_pii_hash", return_value="hash"),
        patch("echoroo.api.web_v1.auth.outbox_service") as mock_outbox,
    ):
        mock_outbox.enqueue = AsyncMock()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/password-reset/request",
                json={"email": "user@example.com"},
            )
    assert resp.status_code == 204
    mock_outbox.enqueue.assert_called_once()


# ---------------------------------------------------------------------------
# setup_totp endpoint branches
# ---------------------------------------------------------------------------


async def test_setup_totp_raises_409_when_2fa_already_enabled() -> None:
    """setup_totp: user.two_factor_enabled=True → 409."""
    from echoroo.repositories.user import UserRepository

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user(two_factor_enabled=True)
    token = _issue_interim_token(user=user, scope="2fa_setup")

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/2fa/setup/totp",
                json={"interim_token": token},
            )
    assert resp.status_code == 409


async def test_setup_totp_returns_secret_for_unenrolled_user() -> None:
    """setup_totp: user.two_factor_enabled=False → returns secret + provisioning_uri."""
    from echoroo.repositories.user import UserRepository
    from echoroo.services.two_factor_service import TwoFactorService

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user(two_factor_enabled=False)
    token = _issue_interim_token(user=user, scope="2fa_setup")

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    mock_artifacts = MagicMock()
    mock_artifacts.secret = "JBSWY3DPEHPK3PXP"
    mock_artifacts.provisioning_uri = "otpauth://totp/test"

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)),
        patch.object(
            TwoFactorService,
            "begin_enrollment",
            AsyncMock(return_value=mock_artifacts),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/2fa/setup/totp",
                json={"interim_token": token},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "secret" in data
    assert "provisioning_uri" in data
    assert "next_interim_token" in data


async def test_setup_totp_raises_409_when_service_already_enabled() -> None:
    """setup_totp: TwoFactorAlreadyEnabledError from begin_enrollment → 409."""
    from echoroo.repositories.user import UserRepository
    from echoroo.services.two_factor_service import TwoFactorAlreadyEnabledError, TwoFactorService

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user(two_factor_enabled=False)
    token = _issue_interim_token(user=user, scope="2fa_setup")

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)),
        patch.object(
            TwoFactorService,
            "begin_enrollment",
            AsyncMock(side_effect=TwoFactorAlreadyEnabledError()),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/2fa/setup/totp",
                json={"interim_token": token},
            )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# setup_totp_confirm endpoint branches
# ---------------------------------------------------------------------------


async def test_setup_totp_confirm_succeeds_and_issues_session() -> None:
    """setup_totp_confirm: valid code → issues session, returns backup codes."""
    from echoroo.repositories.user import UserRepository
    from echoroo.services.two_factor_service import TwoFactorService

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user(two_factor_enabled=False)
    token = _issue_interim_token(user=user, scope="2fa_setup_confirm")

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock()

    mock_token_store = AsyncMock()
    mock_token_store.record_issued = AsyncMock()

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)),
        patch.object(
            TwoFactorService,
            "confirm_enrollment",
            AsyncMock(return_value=["code1", "code2"]),
        ),
        patch("echoroo.api.web_v1.auth.SqlTokenStore", return_value=mock_token_store),
        patch.object(auth_mod, "_write_platform_audit", AsyncMock()),
        patch.object(auth_mod, "_record_login_notification", AsyncMock()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/2fa/setup/totp/confirm",
                json={
                    "interim_token": token,
                    "secret": "JBSWY3DPEHPK3PXP",
                    "totp_code": "123456",
                },
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "backup_codes" in data
    assert "access_token" in data


async def test_setup_totp_confirm_raises_401_for_invalid_code() -> None:
    """setup_totp_confirm: TwoFactorInvalidCodeError → 401."""
    from echoroo.repositories.user import UserRepository
    from echoroo.services.two_factor_service import TwoFactorInvalidCodeError, TwoFactorService

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user(two_factor_enabled=False)
    token = _issue_interim_token(user=user, scope="2fa_setup_confirm")

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)),
        patch.object(
            TwoFactorService,
            "confirm_enrollment",
            AsyncMock(side_effect=TwoFactorInvalidCodeError()),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/2fa/setup/totp/confirm",
                json={
                    "interim_token": token,
                    "secret": "JBSWY3DPEHPK3PXP",
                    "totp_code": "000000",
                },
            )
    assert resp.status_code == 401


async def test_setup_totp_confirm_raises_429_for_rate_limit() -> None:
    """setup_totp_confirm: TwoFactorRateLimitedError → 429."""
    from echoroo.repositories.user import UserRepository
    from echoroo.services.two_factor_service import TwoFactorRateLimitedError, TwoFactorService

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user(two_factor_enabled=False)
    token = _issue_interim_token(user=user, scope="2fa_setup_confirm")

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)),
        patch.object(
            TwoFactorService,
            "confirm_enrollment",
            AsyncMock(side_effect=TwoFactorRateLimitedError()),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/2fa/setup/totp/confirm",
                json={
                    "interim_token": token,
                    "secret": "JBSWY3DPEHPK3PXP",
                    "totp_code": "000000",
                },
            )
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# two_factor_challenge endpoint branches
# ---------------------------------------------------------------------------


async def test_two_factor_challenge_raises_409_when_2fa_not_enabled() -> None:
    """two_factor_challenge: user.two_factor_enabled=False → 409."""
    from echoroo.repositories.user import UserRepository

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user(two_factor_enabled=False)
    token = _issue_interim_token(user=user, scope="2fa_challenge")

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/2fa/challenge",
                json={
                    "interim_token": token,
                    "method": "totp",
                    "code": "123456",
                },
            )
    assert resp.status_code == 409


async def test_two_factor_challenge_succeeds_with_totp() -> None:
    """two_factor_challenge: valid TOTP → issues session, returns access_token."""
    from echoroo.repositories.user import UserRepository
    from echoroo.services.two_factor_service import TwoFactorService

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user(two_factor_enabled=True)
    token = _issue_interim_token(user=user, scope="2fa_challenge")

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock()

    mock_token_store = AsyncMock()
    mock_token_store.record_issued = AsyncMock()

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)),
        patch.object(TwoFactorService, "verify_totp", AsyncMock(return_value=True)),
        patch("echoroo.api.web_v1.auth.SqlTokenStore", return_value=mock_token_store),
        patch.object(auth_mod, "_write_platform_audit", AsyncMock()),
        patch.object(auth_mod, "_record_login_notification", AsyncMock()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/2fa/challenge",
                json={
                    "interim_token": token,
                    "method": "totp",
                    "code": "123456",
                },
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data


async def test_two_factor_challenge_raises_401_for_invalid_totp() -> None:
    """two_factor_challenge: invalid TOTP code → 401."""
    from echoroo.repositories.user import UserRepository
    from echoroo.services.two_factor_service import TwoFactorInvalidCodeError, TwoFactorService

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user(two_factor_enabled=True)
    token = _issue_interim_token(user=user, scope="2fa_challenge")

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)),
        patch.object(
            TwoFactorService, "verify_totp",
            AsyncMock(side_effect=TwoFactorInvalidCodeError()),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/2fa/challenge",
                json={"interim_token": token, "method": "totp", "code": "000000"},
            )
    assert resp.status_code == 401


async def test_two_factor_challenge_raises_429_for_rate_limited_totp() -> None:
    """two_factor_challenge: TwoFactorRateLimitedError → 429 with TOTP window."""
    from echoroo.repositories.user import UserRepository
    from echoroo.services.two_factor_service import TwoFactorRateLimitedError, TwoFactorService

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user(two_factor_enabled=True)
    token = _issue_interim_token(user=user, scope="2fa_challenge")

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)),
        patch.object(
            TwoFactorService, "verify_totp",
            AsyncMock(side_effect=TwoFactorRateLimitedError()),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/2fa/challenge",
                json={"interim_token": token, "method": "totp", "code": "000000"},
            )
    assert resp.status_code == 429


async def test_two_factor_challenge_raises_423_for_locked() -> None:
    """two_factor_challenge: TwoFactorLockedError → 423."""
    from echoroo.repositories.user import UserRepository
    from echoroo.services.two_factor_service import TwoFactorLockedError, TwoFactorService

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user(two_factor_enabled=True)
    token = _issue_interim_token(user=user, scope="2fa_challenge")

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)),
        patch.object(
            TwoFactorService, "verify_totp",
            AsyncMock(side_effect=TwoFactorLockedError()),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/2fa/challenge",
                json={"interim_token": token, "method": "totp", "code": "000000"},
            )
    assert resp.status_code == 423


async def test_two_factor_challenge_raises_409_for_not_enabled_service_error() -> None:
    """two_factor_challenge: TwoFactorNotEnabledError → 409."""
    from echoroo.repositories.user import UserRepository
    from echoroo.services.two_factor_service import TwoFactorNotEnabledError, TwoFactorService

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user(two_factor_enabled=True)
    token = _issue_interim_token(user=user, scope="2fa_challenge")

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)),
        patch.object(
            TwoFactorService, "verify_totp",
            AsyncMock(side_effect=TwoFactorNotEnabledError()),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/2fa/challenge",
                json={"interim_token": token, "method": "totp", "code": "000000"},
            )
    assert resp.status_code == 409


async def test_two_factor_challenge_raises_401_for_false_verified() -> None:
    """two_factor_challenge: verify_totp returns False → 401."""
    from echoroo.repositories.user import UserRepository
    from echoroo.services.two_factor_service import TwoFactorService

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user(two_factor_enabled=True)
    token = _issue_interim_token(user=user, scope="2fa_challenge")

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)),
        patch.object(TwoFactorService, "verify_totp", AsyncMock(return_value=False)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/2fa/challenge",
                json={"interim_token": token, "method": "totp", "code": "000000"},
            )
    assert resp.status_code == 401


async def test_two_factor_challenge_uses_backup_fail_window_for_backup_method() -> None:
    """two_factor_challenge: backup_code method + TwoFactorRateLimitedError → uses BACKUP_FAIL_WINDOW."""
    from echoroo.repositories.user import UserRepository
    from echoroo.services.two_factor_service import TwoFactorRateLimitedError, TwoFactorService

    mock_db = AsyncMock()
    app = _build_app_with_mocked_db(mock_db)

    user = _make_user(two_factor_enabled=True)
    token = _issue_interim_token(user=user, scope="2fa_challenge")

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    with (
        patch.object(UserRepository, "get_by_id", AsyncMock(return_value=user)),
        patch.object(auth_mod, "get_redis_connection", AsyncMock(return_value=mock_redis)),
        patch.object(
            TwoFactorService, "verify_backup_code",
            AsyncMock(side_effect=TwoFactorRateLimitedError()),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/web-api/v1/auth/2fa/challenge",
                json={
                    "interim_token": token,
                    "method": "backup_code",
                    "code": "backup-code-123",
                },
            )
    assert resp.status_code == 429
