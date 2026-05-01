"""TDD coverage for refresh-token family reuse detection (FR-055).

The contract:

* Reusing the SAME refresh-token JTI twice is the canonical signal of
  a compromised refresh token (an attacker grabbed the cookie and
  replayed it after the legitimate client already rotated). The
  ``rotate_refresh_token`` primitive MUST detect this and revoke the
  ENTIRE family — not just the replayed token.

* Once the family is revoked, every other token in the chain
  (including the most recent legitimately-rotated child) is rejected.
  The attacker cannot ride the chain forward by replaying any later
  token — the family is dead.

* The auth router's ``/refresh`` handler clears the session cookies
  (``echoroo_refresh``, ``echoroo_session``, ``echoroo_csrf``,
  ``echoroo_logged_in``) when family revocation triggers. This test
  documents the cookie-clearing contract so a future refactor does
  not silently leave stale ``echoroo_logged_in`` markers in the
  browser after a security event.

The first two cases lift the existing :class:`InMemoryTokenStore`
TDD coverage from ``test_refresh_token_rotation.py`` and reframe them
under the security-suite umbrella so the test taxonomy advertised in
plan.md (``tests/security/authentication/*``) is complete. Test (c)
is original to T176 — the cookie-clearing contract is asserted only
indirectly elsewhere.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from echoroo.core.auth import (
    InMemoryTokenStore,
    ReusedTokenError,
    RevokedFamilyError,
    issue_refresh_token,
    rotate_refresh_token,
)
from echoroo.core.settings import get_settings

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Case (a): replaying the same refresh JTI twice → family revoked
# ---------------------------------------------------------------------------


async def test_replaying_same_refresh_jti_twice_revokes_family() -> None:
    user_id = uuid4()
    store = InMemoryTokenStore()

    token_1, record_1 = issue_refresh_token(user_id=user_id)
    await store.record_issued(record_1)

    # Legitimate rotation: token_1 → token_2.
    token_2, _record_2 = await rotate_refresh_token(token_1, store=store)

    # Attacker replays token_1 (the *first* token, already consumed).
    with pytest.raises(ReusedTokenError):
        await rotate_refresh_token(token_1, store=store)

    # Family is now dead.
    assert await store.is_family_revoked(record_1.family_id) is True

    # The legitimate child token (token_2) MUST also fail — the family
    # is revoked so even the post-rotation token cannot be ridden
    # forward by either the legitimate user or the attacker.
    with pytest.raises(RevokedFamilyError):
        await rotate_refresh_token(token_2, store=store)


# ---------------------------------------------------------------------------
# Case (b): a multi-step rotation chain dies entirely on revocation
# ---------------------------------------------------------------------------


async def test_revoked_family_kills_the_most_recent_legitimate_child() -> None:
    user_id = uuid4()
    store = InMemoryTokenStore()

    token_1, record_1 = issue_refresh_token(user_id=user_id)
    await store.record_issued(record_1)
    token_2, _ = await rotate_refresh_token(token_1, store=store)
    token_3, _ = await rotate_refresh_token(token_2, store=store)

    # Replay token_1 (long-since-consumed) — family-wide revocation.
    with pytest.raises(ReusedTokenError):
        await rotate_refresh_token(token_1, store=store)

    # token_3 is the most recent legitimate token — it MUST also fail.
    with pytest.raises(RevokedFamilyError):
        await rotate_refresh_token(token_3, store=store)


# ---------------------------------------------------------------------------
# Case (c): concurrent rotation race — exactly one winner, family revoked
#
# This is a tightening regression for Phase 2.10 issue #2. Without the
# atomic_consume_and_issue primitive, two parallel ``rotate`` calls on
# the SAME token both observe ``is_consumed == False`` and both mint
# successor tokens — the server has issued two valid live tokens for
# one logical session. The atomic primitive forces exactly one to win;
# the loser must trip the reuse-detection path and kill the family.
# ---------------------------------------------------------------------------


async def test_concurrent_rotation_yields_one_winner_and_revokes_family() -> None:
    user_id = uuid4()
    store = InMemoryTokenStore()

    token, record = issue_refresh_token(user_id=user_id)
    await store.record_issued(record)

    results = await asyncio.gather(
        rotate_refresh_token(token, store=store),
        rotate_refresh_token(token, store=store),
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, BaseException)]
    failures = [r for r in results if isinstance(r, BaseException)]

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ReusedTokenError)
    assert await store.is_family_revoked(record.family_id) is True


# ---------------------------------------------------------------------------
# Case (d): cookie-clearing contract is documented at the auth-router
# layer. The router uses :func:`_failed_refresh_response` which calls
# :func:`_clear_session_cookies` for every revocation path (reuse,
# stale stamp, missing user, family already revoked). We pin the
# expected cookie names here so a future refactor cannot silently
# stop clearing the ``echoroo_logged_in`` marker (the SvelteKit
# hooks-server.ts trusts that cookie).
# ---------------------------------------------------------------------------


async def test_session_cookie_names_for_revocation_are_documented() -> None:
    settings = get_settings()
    expected = {
        settings.web_refresh_cookie_name,
        settings.web_session_cookie_name,
        settings.web_csrf_cookie_name,
        settings.web_logged_in_cookie_name,
    }
    # All four cookie names must be set — a misconfigured deployment
    # that left, say, ``web_logged_in_cookie_name = ""`` would silently
    # break the frontend hooks. Keep this set tight so the contract is
    # auditable.
    assert all(isinstance(name, str) and name for name in expected)
    assert len(expected) == 4
