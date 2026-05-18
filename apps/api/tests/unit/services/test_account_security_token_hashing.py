"""Unit tests for account-security token generation and hashing.

Spec 010 foundational tests intentionally describe the public helper
contract before ``echoroo.services.account_security_tokens`` exists. They
should fail until T013 implements the helper module.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import re

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


def _tokens_module():
    return importlib.import_module("echoroo.services.account_security_tokens")


def test_generate_account_security_token_returns_43_char_base64url_secret() -> None:
    """Generated secrets are 32 random bytes encoded as unpadded base64url."""
    mod = _tokens_module()

    token = mod.generate_account_security_token()

    assert isinstance(token, str)
    assert _TOKEN_RE.fullmatch(token)
    assert "=" not in token
    assert base64.urlsafe_b64decode(token + "=")  # 43 chars requires one pad char
    assert len(base64.urlsafe_b64decode(token + "=")) == 32


def test_generate_account_security_token_uses_fresh_entropy() -> None:
    """The helper should not return reusable or predictable fixed tokens."""
    mod = _tokens_module()

    tokens = {mod.generate_account_security_token() for _ in range(32)}

    assert len(tokens) == 32


def test_hash_account_security_token_is_hmac_sha256_hex() -> None:
    """Stored token values are keyed HMAC-SHA-256 digests, not raw tokens."""
    mod = _tokens_module()
    key = b"test-account-security-hmac-key-32-bytes"
    token = "w7fA1d9YVuq9Rk0CVVqA5caK2p5kaTq6f68pq6JQl7Q"

    digest = mod.hash_account_security_token(token, key=key)
    expected = hmac.new(key, token.encode("ascii"), hashlib.sha256).hexdigest()

    assert digest == expected
    assert len(digest) == 64
    assert all(char in "0123456789abcdef" for char in digest)
    assert token not in digest


def test_hash_account_security_token_is_deterministic_for_same_key_and_token() -> None:
    """The same key/token pair must find the same stored hash on lookup."""
    mod = _tokens_module()
    key = b"lookup-key-for-email-and-trusted-device-tokens"
    token = "M6fEfdvvS3kcCi45QZ3q32_FZD0oxER8mLL6M2wxHPE"

    assert mod.hash_account_security_token(token, key=key) == mod.hash_account_security_token(
        token,
        key=key,
    )


def test_hash_account_security_token_changes_when_key_changes() -> None:
    """A DB-only leak should not permit offline token verification without the key."""
    mod = _tokens_module()
    token = "qxraWfjUuhcmf7M8hcvdxzs7umxb-EfM16dlcf98uCQ"

    assert mod.hash_account_security_token(token, key=b"first-key-32-bytes-or-more") != (
        mod.hash_account_security_token(token, key=b"second-key-32-bytes-or-more")
    )
