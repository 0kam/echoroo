"""W4-2 SFR-6 — HIBP breach-check fail-closed behaviour.

:meth:`echoroo.services.auth_service.HttpHibpChecker.pwned_count`
historically failed OPEN (returned ``0`` on an HIBP outage), so a
previously-breached password could be silently accepted whenever
HaveIBeenPwned was unreachable.

These pure-unit tests pin the new contract:

* On outage, ``pwned_count`` raises :class:`HibpUnavailableError` when the
  fail-closed policy is active (the default).
* The dev-only opt-out (``ECHOROO_HIBP_FAIL_OPEN`` or ``TEST_MODE``)
  restores the historical ``return 0`` behaviour.
* :func:`enforce_password_policy` still raises
  :class:`PasswordPolicyError` for a genuinely weak / breached password
  (the 400/422 path is unchanged) and propagates
  :class:`HibpUnavailableError` untouched so the router can map it to 503.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from echoroo.services import auth_service
from echoroo.services.auth_service import (
    HibpUnavailableError,
    HttpHibpChecker,
    PasswordPolicyError,
    enforce_password_policy,
)

# NOTE: this module mixes async (pwned_count / enforce_password_policy) and
# sync (_hibp_should_fail_open) tests, so the asyncio mark is applied per
# async test rather than module-wide.

# A long, unusual password that no policy length rule would reject — so the
# only thing driving these tests is the injected HIBP behaviour.
_STRONG_UNBREACHED = "correct-horse-battery-staple-w4-2-xyz"


async def _boom_get(url: str) -> object:  # noqa: ARG001
    raise RuntimeError("HIBP outage")


# ---------------------------------------------------------------------------
# HttpHibpChecker.pwned_count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pwned_count_raises_when_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_service, "_hibp_should_fail_open", lambda: False)
    checker = HttpHibpChecker(http_get=_boom_get)

    with pytest.raises(HibpUnavailableError):
        await checker.pwned_count(_STRONG_UNBREACHED)


@pytest.mark.asyncio
async def test_pwned_count_fail_open_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_service, "_hibp_should_fail_open", lambda: True)
    checker = HttpHibpChecker(http_get=_boom_get)

    assert await checker.pwned_count(_STRONG_UNBREACHED) == 0


# ---------------------------------------------------------------------------
# _hibp_should_fail_open — flag OR TEST_MODE
# ---------------------------------------------------------------------------


def _fake_settings(*, fail_open: bool, test_mode: bool) -> SimpleNamespace:
    return SimpleNamespace(ECHOROO_HIBP_FAIL_OPEN=fail_open, TEST_MODE=test_mode)


def test_hibp_should_fail_open_via_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "echoroo.core.settings.get_settings",
        lambda: _fake_settings(fail_open=False, test_mode=True),
    )
    assert auth_service._hibp_should_fail_open() is True


def test_hibp_should_fail_open_via_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "echoroo.core.settings.get_settings",
        lambda: _fake_settings(fail_open=True, test_mode=False),
    )
    assert auth_service._hibp_should_fail_open() is True


def test_hibp_should_fail_closed_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "echoroo.core.settings.get_settings",
        lambda: _fake_settings(fail_open=False, test_mode=False),
    )
    assert auth_service._hibp_should_fail_open() is False


# ---------------------------------------------------------------------------
# enforce_password_policy — weak-pw path unchanged, HIBP outage propagates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enforce_rejects_breached_password() -> None:
    class _Pwned:
        async def pwned_count(self, password: str) -> int:  # noqa: ARG002
            return 42

    with pytest.raises(PasswordPolicyError):
        await enforce_password_policy(_STRONG_UNBREACHED, hibp=_Pwned())


@pytest.mark.asyncio
async def test_enforce_propagates_hibp_unavailable() -> None:
    class _Down:
        async def pwned_count(self, password: str) -> int:  # noqa: ARG002
            raise HibpUnavailableError("HIBP breach-check service unavailable")

    with pytest.raises(HibpUnavailableError):
        await enforce_password_policy(_STRONG_UNBREACHED, hibp=_Down())


@pytest.mark.asyncio
async def test_enforce_accepts_unbreached_password() -> None:
    class _Fresh:
        async def pwned_count(self, password: str) -> int:  # noqa: ARG002
            return 0

    # No exception -> password accepted.
    await enforce_password_policy(_STRONG_UNBREACHED, hibp=_Fresh())
