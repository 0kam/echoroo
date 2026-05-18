"""Helpers for account-security token generation and hashing."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from echoroo.core.settings import get_settings

_TOKEN_BYTES = 32


def generate_account_security_token() -> str:
    """Return a 256-bit random token as unpadded base64url text."""
    return base64.urlsafe_b64encode(secrets.token_bytes(_TOKEN_BYTES)).rstrip(b"=").decode("ascii")


def hash_account_security_token(token: str, *, key: bytes | str | None = None) -> str:
    """Return the HMAC-SHA-256 hex digest used for token storage."""
    resolved_key = key if key is not None else get_settings().web_session_secret
    if isinstance(resolved_key, str):
        resolved_key = resolved_key.encode("utf-8")
    return hmac.new(resolved_key, token.encode("ascii"), hashlib.sha256).hexdigest()
