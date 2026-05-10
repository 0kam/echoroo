"""Coverage uplift unit tests for ``echoroo.core.jwt``.

Phase 17 §C medium-gap batch: targets ``create_refresh_token`` (lines
58-63) so the module clears the 85% threshold without touching
production code.
"""

from __future__ import annotations

from echoroo.core.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
)


def test_create_access_token_round_trips() -> None:
    """create_access_token + decode_token round trip preserves payload."""
    token = create_access_token({"sub": "user-1"})
    payload = decode_token(token)
    assert payload["sub"] == "user-1"
    assert payload["type"] == "access"
    assert "jti" in payload
    assert "exp" in payload


def test_create_refresh_token_assigns_new_family_when_omitted() -> None:
    """create_refresh_token() with no family_id mints a fresh family (lines 58-63)."""
    token = create_refresh_token({"sub": "user-1"})
    payload = decode_token(token)
    assert payload["sub"] == "user-1"
    assert payload["type"] == "refresh"
    assert isinstance(payload["family"], str) and payload["family"]
    assert isinstance(payload["jti"], str) and payload["jti"]


def test_create_refresh_token_preserves_existing_family() -> None:
    """Passing a family_id keeps the chain intact (line 60 truthy branch)."""
    token = create_refresh_token({"sub": "user-1"}, family_id="fam-existing")
    payload = decode_token(token)
    assert payload["family"] == "fam-existing"


def test_refresh_token_jti_unique_per_call() -> None:
    """Each mint gets a fresh jti even within the same family."""
    t1 = create_refresh_token({"sub": "user-1"}, family_id="fam-1")
    t2 = create_refresh_token({"sub": "user-1"}, family_id="fam-1")
    p1 = decode_token(t1)
    p2 = decode_token(t2)
    assert p1["family"] == p2["family"] == "fam-1"
    assert p1["jti"] != p2["jti"]
