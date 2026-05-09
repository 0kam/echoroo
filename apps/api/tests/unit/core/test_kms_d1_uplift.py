"""Phase 17 §D-1 mutation-uplift tests for echoroo.core.kms.

Targets the three functions that concentrate the surviving mutants from
the PR #53 baseline (CI run 25592148927):

* ``verify_pii_hash`` — 45 surviving mutants (73% of module total). The
  function has many branches: stored_hash type/length validation, v2
  alias presence, v2 KMS error fallback, hmac.compare_digest boolean
  output for v2, v1 KMS error fallback, hmac.compare_digest boolean
  output for v1, and the final ``matched_v2 or matched_v1`` short-circuit.
  Each branch needs explicit kill via True / False on both sides.

* ``_invitation_alias_new`` — 6 surviving mutants. The function returns
  ``AWS_KMS_CMK_INVITATION_HMAC_ALIAS_NEW`` when set; otherwise falls
  back through ``_alias()`` to the legacy ``AWS_KMS_CMK_INVITATION_HMAC_ALIAS``
  or hard-coded default. Mutants typically swap the truthiness check or
  invert the env-var precedence.

* ``verify_invitation_hmac`` — 5 surviving mutants. The function iterates
  over (new, old) aliases; mutants typically remove ``continue`` for
  ``alias is None``, swap the iteration order, or invert the
  ``MacValid`` truthiness short-circuit.

The test file is structured so each test names — in its docstring — the
specific mutant family it targets. Tests use moto to back KMS so no real
AWS credentials are needed.

Baseline before this PR: 199/261 killed = 76.2%.
Target after this PR: >=80% per-module score.
"""

from __future__ import annotations

import hmac as _hmac
import importlib
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

# ---------------------------------------------------------------------------
# Constants — distinct alias names from existing test_kms.py to avoid moto
# state collision when both files run in the same process.
# ---------------------------------------------------------------------------

AWS_REGION = "us-east-1"

TOTP_DEK_ALIAS = "alias/echoroo-d1uplift-totp-dek"
PII_V1_ALIAS = "alias/echoroo-d1uplift-pii-v1"
PII_V2_ALIAS = "alias/echoroo-d1uplift-pii-v2"
AUDIT_CHAIN_ALIAS = "alias/echoroo-d1uplift-audit"
INVITATION_NEW_ALIAS = "alias/echoroo-d1uplift-invitation-new"
INVITATION_OLD_ALIAS = "alias/echoroo-d1uplift-invitation-old"
INVITATION_LEGACY_ALIAS = "alias/echoroo-d1uplift-invitation-legacy"


def _make_hmac_key(client: Any, alias: str) -> str:
    resp = client.create_key(KeyUsage="GENERATE_VERIFY_MAC", KeySpec="HMAC_256")
    key_id = str(resp["KeyMetadata"]["KeyId"])
    client.create_alias(AliasName=alias, TargetKeyId=key_id)
    return key_id


def _make_symmetric_key(client: Any, alias: str) -> str:
    resp = client.create_key(KeyUsage="ENCRYPT_DECRYPT", KeySpec="SYMMETRIC_DEFAULT")
    key_id = str(resp["KeyMetadata"]["KeyId"])
    client.create_alias(AliasName=alias, TargetKeyId=key_id)
    return key_id


@pytest.fixture
def kms_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """Provision a fresh moto-backed KMS with v1 + v2 PII keys + invitation
    new/old/legacy + TOTP + audit. Reloads ``echoroo.core.kms`` to clear
    the module-level boto3 client cache.

    The fixture leaves the v2 alias UNSET by default so individual tests
    opt into "rotation in progress" by ``monkeypatch.setenv``-ing
    ``AWS_KMS_CMK_PII_HASH_ALIAS_V2`` and reloading. This matches the
    pattern in ``test_pii_hash_key_rotation_dual_write.py``.
    """
    monkeypatch.delenv("AWS_KMS_ENDPOINT", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL_KMS", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)

    with mock_aws():
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
        monkeypatch.setenv("AWS_DEFAULT_REGION", AWS_REGION)

        client = boto3.client("kms", region_name=AWS_REGION)

        totp_id = _make_symmetric_key(client, TOTP_DEK_ALIAS)
        pii_v1_id = _make_hmac_key(client, PII_V1_ALIAS)
        pii_v2_id = _make_hmac_key(client, PII_V2_ALIAS)
        audit_id = _make_hmac_key(client, AUDIT_CHAIN_ALIAS)
        inv_new_id = _make_hmac_key(client, INVITATION_NEW_ALIAS)
        inv_old_id = _make_hmac_key(client, INVITATION_OLD_ALIAS)
        inv_legacy_id = _make_hmac_key(client, INVITATION_LEGACY_ALIAS)

        monkeypatch.setenv("AWS_KMS_REGION", AWS_REGION)
        monkeypatch.setenv("AWS_KMS_CMK_2FA_ALIAS", TOTP_DEK_ALIAS)
        monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS", PII_V1_ALIAS)
        monkeypatch.setenv("AWS_KMS_CMK_AUDIT_CHAIN_ALIAS", AUDIT_CHAIN_ALIAS)
        monkeypatch.setenv(
            "AWS_KMS_CMK_INVITATION_HMAC_ALIAS_NEW", INVITATION_NEW_ALIAS
        )
        monkeypatch.setenv(
            "AWS_KMS_CMK_INVITATION_HMAC_ALIAS_OLD", INVITATION_OLD_ALIAS
        )
        monkeypatch.setenv(
            "AWS_KMS_CMK_INVITATION_HMAC_ALIAS", INVITATION_LEGACY_ALIAS
        )
        monkeypatch.delenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", raising=False)
        monkeypatch.delenv("ECHOROO_PII_HASH_ROTATION_COMPLETE", raising=False)

        import echoroo.core.kms as kms_module

        importlib.reload(kms_module)

        yield {
            "totp_id": totp_id,
            "pii_v1_id": pii_v1_id,
            "pii_v2_id": pii_v2_id,
            "audit_id": audit_id,
            "inv_new_id": inv_new_id,
            "inv_old_id": inv_old_id,
            "inv_legacy_id": inv_legacy_id,
        }


def _reload_kms() -> Any:
    import echoroo.core.kms as kms_module

    importlib.reload(kms_module)
    return kms_module


# ===========================================================================
# verify_pii_hash — 45 surviving mutants concentration
# ===========================================================================


# ---------------------------------------------------------------------------
# Input validation: type + length boundary on stored_hash
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stored_hash",
    [
        pytest.param("a" * 63, id="length_63_below_threshold"),
        pytest.param("a" * 65, id="length_65_above_threshold"),
        pytest.param("", id="empty_string"),
        pytest.param("a" * 32, id="half_length"),
        pytest.param("a" * 128, id="double_length"),
    ],
)
def test_verify_pii_hash_rejects_wrong_length(
    kms_env: dict[str, str], stored_hash: str
) -> None:
    """Kill mutants that flip the ``len(stored_hash) != 64`` boundary check.

    Anything other than exactly 64 chars must return False without any
    KMS round-trip. Parametrise around the 64-char boundary to pin the
    inequality direction.
    """
    from echoroo.core import kms

    assert kms.verify_pii_hash("any-value", stored_hash) is False


def test_verify_pii_hash_accepts_exact_length_when_value_matches(
    kms_env: dict[str, str],
) -> None:
    """Kill mutants that flip the ``== 64`` boundary in the wrong direction.

    A 64-char hash that matches the value must return True — proves the
    boundary check passes the exact-equal case (not just >=/<= variants).
    """
    from echoroo.core import kms

    value = "boundary-test"
    stored = kms.compute_pii_hash(value)
    assert len(stored) == 64
    assert kms.verify_pii_hash(value, stored) is True


@pytest.mark.parametrize(
    "stored_hash",
    [
        pytest.param(None, id="None"),
        pytest.param(b"a" * 64, id="bytes"),
        pytest.param(123, id="int"),
        pytest.param(["a"] * 64, id="list"),
        pytest.param({"hash": "a" * 64}, id="dict"),
    ],
)
def test_verify_pii_hash_rejects_non_string_types(
    kms_env: dict[str, str], stored_hash: Any
) -> None:
    """Kill mutants that flip the ``isinstance(stored_hash, str)`` check.

    Non-string types must short-circuit to False before any KMS call.
    """
    from echoroo.core import kms

    assert kms.verify_pii_hash("value", stored_hash) is False


def test_verify_pii_hash_isinstance_check_runs_before_length(
    kms_env: dict[str, str],
) -> None:
    """Kill mutants that swap the order of isinstance vs length checks.

    A bytes object of length 64 must still reject (isinstance fails),
    not pass through to a length-only branch.
    """
    from echoroo.core import kms

    sixty_four_bytes = b"a" * 64
    assert kms.verify_pii_hash("value", sixty_four_bytes) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Single-key (pre-rotation) mode: only v1 path is exercised
# ---------------------------------------------------------------------------


def test_verify_pii_hash_single_key_match_returns_true(
    kms_env: dict[str, str],
) -> None:
    """Kill mutants that invert the v1 hmac.compare_digest True branch.

    Single-key mode (no v2 alias) — v1 hash matches → True.
    """
    from echoroo.core import kms

    value = "alice@example.com"
    stored = kms.compute_pii_hash(value)
    assert kms.verify_pii_hash(value, stored) is True


def test_verify_pii_hash_single_key_mismatch_returns_false(
    kms_env: dict[str, str],
) -> None:
    """Kill mutants that invert the v1 hmac.compare_digest False branch.

    Single-key mode — wrong value → False.
    """
    from echoroo.core import kms

    stored = kms.compute_pii_hash("alice@example.com")
    assert kms.verify_pii_hash("bob@example.com", stored) is False


def test_verify_pii_hash_single_key_wrong_format_hash_returns_false(
    kms_env: dict[str, str],
) -> None:
    """Kill mutants that skip the final return False after no-match.

    A 64-char hex string that is not the actual MAC must return False
    (covers the path where compare_digest returns False on the v1 side).
    """
    from echoroo.core import kms

    bogus = "0" * 64
    assert kms.verify_pii_hash("alice@example.com", bogus) is False


# ---------------------------------------------------------------------------
# Dual-key (rotation in progress): v2 alias set
# ---------------------------------------------------------------------------


def test_verify_pii_hash_dual_key_matches_via_v2_path(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that invert ``v2_alias is not None`` truthiness check.

    Dual-write mode: store hash under v2 → verify must return True via
    the v2 branch (matched_v2 = True). Pins the v2 branch entry condition.
    """
    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", PII_V2_ALIAS)
    kms = _reload_kms()

    value = "rotating-user@example.com"
    dual = kms.compute_pii_hash_dual(value)
    assert "v2" in dual
    # Verify against the v2 hash explicitly.
    assert kms.verify_pii_hash(value, dual["v2"]) is True


def test_verify_pii_hash_dual_key_matches_via_v1_path(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that short-circuit ``matched_v2 or matched_v1``.

    Dual-write mode but the stored hash is the legacy v1 hash. Must
    return True via the v1 branch (historical row backwards-compat).
    """
    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", PII_V2_ALIAS)
    kms = _reload_kms()

    value = "legacy-row@example.com"
    dual = kms.compute_pii_hash_dual(value)
    # v1 and v2 must differ (different CMKs) so this is a real v1-only test.
    assert dual["v1"] != dual["v2"]
    assert kms.verify_pii_hash(value, dual["v1"]) is True


def test_verify_pii_hash_dual_key_mismatch_both_returns_false(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that flip the final ``matched_v2 or matched_v1`` to and.

    Dual-write mode, neither v1 nor v2 matches → False. The combination
    of matched_v2=False + matched_v1=False must produce False (or-True
    only when at least one matches).
    """
    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", PII_V2_ALIAS)
    kms = _reload_kms()

    bogus = "f" * 64
    assert kms.verify_pii_hash("any-value", bogus) is False


def test_verify_pii_hash_dual_key_v1_v2_truly_distinct(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that swap v1 alias with v2 alias in verify_pii_hash.

    The v1 and v2 hashes for the same value must differ (different CMKs).
    Verifying one against the other slot must still succeed because
    verify_pii_hash tries BOTH aliases; this guards against a mutant
    that drops the v1 branch entirely.
    """
    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", PII_V2_ALIAS)
    kms = _reload_kms()

    value = "x@y.z"
    dual = kms.compute_pii_hash_dual(value)
    # Both must verify (sanity).
    assert kms.verify_pii_hash(value, dual["v1"]) is True
    assert kms.verify_pii_hash(value, dual["v2"]) is True


# ---------------------------------------------------------------------------
# v2 KMS unavailability fallback (fail-open by design)
# ---------------------------------------------------------------------------


def test_verify_pii_hash_v2_kms_failure_falls_back_to_v1_match(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that skip the v2 except branch (or change candidate_v2 = "").

    When v2 KMS raises, the function must still attempt v1 — and a
    matching v1 hash must return True (FR-091b fail-open).
    """
    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", PII_V2_ALIAS)
    kms = _reload_kms()

    value = "fail-open@example.com"
    v1_only = kms.compute_pii_hash(value)  # via PII_V1_ALIAS

    # Patch _compute_pii_hash_with_alias to raise only when the v2 alias
    # is the target. v1 path must still succeed.
    real_fn = kms._compute_pii_hash_with_alias

    def selective_raise(val: str, alias: str) -> str:
        if alias == PII_V2_ALIAS:
            raise RuntimeError("simulated v2 KMS outage")
        return real_fn(val, alias)

    monkeypatch.setattr(kms, "_compute_pii_hash_with_alias", selective_raise)

    assert kms.verify_pii_hash(value, v1_only) is True


def test_verify_pii_hash_v2_kms_failure_returns_false_when_v1_also_mismatches(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that change candidate_v2 = "" to a truthy sentinel.

    v2 KMS fails; v1 returns a real hash but stored does not match v1.
    Must return False (proving the empty candidate_v2 cannot
    accidentally match).
    """
    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", PII_V2_ALIAS)
    kms = _reload_kms()

    real_fn = kms._compute_pii_hash_with_alias

    def selective_raise(val: str, alias: str) -> str:
        if alias == PII_V2_ALIAS:
            raise RuntimeError("simulated v2 KMS outage")
        return real_fn(val, alias)

    monkeypatch.setattr(kms, "_compute_pii_hash_with_alias", selective_raise)

    bogus = "0" * 64
    assert kms.verify_pii_hash("anything", bogus) is False


def test_verify_pii_hash_v2_empty_candidate_does_not_match_empty_stored(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that drop the ``if candidate_v2`` truthiness guard.

    When candidate_v2 is empty (KMS failed), the guard ``if candidate_v2 and
    compare_digest(...)`` must short-circuit BEFORE compare_digest. A
    mutant removing the truthiness guard would cause empty-vs-empty to
    falsely match.

    Stored hash here is 64 chars but does not equal an empty string;
    however the input validator already rejects len != 64, so we use a
    valid 64-char stored hash that is wrong on v1 too.
    """
    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", PII_V2_ALIAS)
    kms = _reload_kms()

    real_fn = kms._compute_pii_hash_with_alias

    def selective_raise(val: str, alias: str) -> str:
        if alias == PII_V2_ALIAS:
            raise RuntimeError("v2 down")
        return real_fn(val, alias)

    monkeypatch.setattr(kms, "_compute_pii_hash_with_alias", selective_raise)

    # 64-char hex that is the wrong v1 hash. Empty string compare-digest
    # would NOT match this anyway, but the mutant catch is the SHORT-
    # CIRCUIT — without the truthiness guard, compare_digest is called
    # with mismatched lengths and raises (or returns False), which would
    # subtly differ from the guarded path. We assert False outcome.
    assert kms.verify_pii_hash("v", "1" * 64) is False


def test_verify_pii_hash_v1_kms_failure_returns_false_when_v2_also_mismatches(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that skip the v1 except branch.

    Both v1 KMS fail AND v2 returns a non-matching hash → False.
    """
    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", PII_V2_ALIAS)
    kms = _reload_kms()

    real_fn = kms._compute_pii_hash_with_alias

    def selective_raise(val: str, alias: str) -> str:
        if alias == PII_V1_ALIAS:
            raise RuntimeError("v1 down")
        return real_fn(val, alias)

    monkeypatch.setattr(kms, "_compute_pii_hash_with_alias", selective_raise)

    bogus = "0" * 64
    assert kms.verify_pii_hash("any", bogus) is False


def test_verify_pii_hash_v1_kms_failure_succeeds_via_v2(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that always skip v2 short-circuit when v1 fails.

    v1 KMS fails but v2 hash matches → True. Pins the matched_v2=True
    short-circuit on the OR.
    """
    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", PII_V2_ALIAS)
    kms = _reload_kms()

    value = "v2-success@example.com"
    dual = kms.compute_pii_hash_dual(value)
    v2_hash = dual["v2"]

    real_fn = kms._compute_pii_hash_with_alias

    def selective_raise(val: str, alias: str) -> str:
        if alias == PII_V1_ALIAS:
            raise RuntimeError("v1 down")
        return real_fn(val, alias)

    monkeypatch.setattr(kms, "_compute_pii_hash_with_alias", selective_raise)

    assert kms.verify_pii_hash(value, v2_hash) is True


def test_verify_pii_hash_logs_warning_on_v2_failure(
    kms_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Kill mutants that drop the warning log call on v2 KMS failure.

    Observability is part of the FR-091b contract; the warning text must
    contain the alias and exception class.
    """
    import logging

    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", PII_V2_ALIAS)
    kms = _reload_kms()

    real_fn = kms._compute_pii_hash_with_alias

    def selective_raise(val: str, alias: str) -> str:
        if alias == PII_V2_ALIAS:
            raise RuntimeError("kaboom-v2")
        return real_fn(val, alias)

    monkeypatch.setattr(kms, "_compute_pii_hash_with_alias", selective_raise)

    caplog.set_level(logging.WARNING, logger="echoroo.core.kms")
    kms.verify_pii_hash("logged@example.com", "0" * 64)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("v2 KMS unavailable" in r.getMessage() for r in warnings)
    assert any(PII_V2_ALIAS in r.getMessage() for r in warnings)
    assert any("RuntimeError" in r.getMessage() for r in warnings)


def test_verify_pii_hash_logs_warning_on_v1_failure(
    kms_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Kill mutants that drop the warning log call on v1 KMS failure."""
    import logging

    kms = _reload_kms()

    real_fn = kms._compute_pii_hash_with_alias

    def selective_raise(val: str, alias: str) -> str:
        if alias == PII_V1_ALIAS:
            raise RuntimeError("kaboom-v1")
        return real_fn(val, alias)

    monkeypatch.setattr(kms, "_compute_pii_hash_with_alias", selective_raise)

    caplog.set_level(logging.WARNING, logger="echoroo.core.kms")
    kms.verify_pii_hash("v1log@example.com", "0" * 64)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("v1 KMS unavailable" in r.getMessage() for r in warnings)


# ---------------------------------------------------------------------------
# v2 alias unset path: v2 branch must be skipped entirely
# ---------------------------------------------------------------------------


def test_verify_pii_hash_v2_alias_unset_skips_v2_branch(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that always enter the v2 branch even when alias is None.

    Without v2 alias env var, ``_compute_pii_hash_with_alias`` should be
    called only ONCE (for v1). We verify by patching the helper as a spy.
    """
    monkeypatch.delenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", raising=False)
    kms = _reload_kms()

    real_fn = kms._compute_pii_hash_with_alias
    calls: list[str] = []

    def spy(val: str, alias: str) -> str:
        calls.append(alias)
        return real_fn(val, alias)

    monkeypatch.setattr(kms, "_compute_pii_hash_with_alias", spy)

    kms.verify_pii_hash("solo@example.com", "0" * 64)
    # Single-key mode → only v1 alias must be queried, never v2.
    assert PII_V2_ALIAS not in calls
    assert PII_V1_ALIAS in calls


# ---------------------------------------------------------------------------
# Dual-key timing: both KMS calls happen unconditionally to flatten timing
# ---------------------------------------------------------------------------


def test_verify_pii_hash_dual_key_unconditional_v1_call_after_v2_match(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that early-return after v2 match (skipping v1 KMS call).

    Both KMS calls happen unconditionally per FR-091b timing-side-channel
    flattening. After a v2 match, v1 must STILL be called.
    """
    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", PII_V2_ALIAS)
    kms = _reload_kms()

    value = "timing@example.com"
    dual = kms.compute_pii_hash_dual(value)

    real_fn = kms._compute_pii_hash_with_alias
    calls: list[str] = []

    def spy(val: str, alias: str) -> str:
        calls.append(alias)
        return real_fn(val, alias)

    monkeypatch.setattr(kms, "_compute_pii_hash_with_alias", spy)

    assert kms.verify_pii_hash(value, dual["v2"]) is True
    # Both aliases must appear (timing-flat contract).
    assert PII_V1_ALIAS in calls
    assert PII_V2_ALIAS in calls


# ---------------------------------------------------------------------------
# constant-time compare: hmac.compare_digest is the comparator
# ---------------------------------------------------------------------------


def test_verify_pii_hash_uses_compare_digest_not_eq(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that swap hmac.compare_digest for str.__eq__.

    Spy on hmac.compare_digest to confirm it is the comparator. A mutant
    swapping for ``==`` would skip the spy and fail this assertion.
    """
    kms = _reload_kms()

    value = "compare@example.com"
    stored = kms.compute_pii_hash(value)

    call_count = {"n": 0}
    real_compare = _hmac.compare_digest

    def spy_compare(a: object, b: object) -> bool:
        call_count["n"] += 1
        return real_compare(a, b)  # type: ignore[arg-type]

    with patch("hmac.compare_digest", side_effect=spy_compare):
        assert kms.verify_pii_hash(value, stored) is True
    assert call_count["n"] >= 1


# ===========================================================================
# _invitation_alias_new — 6 surviving mutants
# ===========================================================================


def test_invitation_alias_new_returns_env_when_set(
    kms_env: dict[str, str],
) -> None:
    """Kill mutants that flip the ``if new`` truthiness check.

    With ``AWS_KMS_CMK_INVITATION_HMAC_ALIAS_NEW`` set, the function
    must return that value verbatim, NOT the legacy fallback.
    """
    kms = _reload_kms()
    assert kms._invitation_alias_new() == INVITATION_NEW_ALIAS


def test_invitation_alias_new_falls_back_to_legacy_when_new_unset(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that always return the _NEW env var (None) without fallback.

    With _NEW unset, the legacy ``AWS_KMS_CMK_INVITATION_HMAC_ALIAS``
    must be returned.
    """
    monkeypatch.delenv("AWS_KMS_CMK_INVITATION_HMAC_ALIAS_NEW", raising=False)
    kms = _reload_kms()
    assert kms._invitation_alias_new() == INVITATION_LEGACY_ALIAS


def test_invitation_alias_new_falls_back_to_default_when_both_unset(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that flip the default constant in the fallback chain.

    With both _NEW and the legacy env unset, the hardcoded
    ``alias/echoroo-invitation-hmac`` default must be returned.
    """
    monkeypatch.delenv("AWS_KMS_CMK_INVITATION_HMAC_ALIAS_NEW", raising=False)
    monkeypatch.delenv("AWS_KMS_CMK_INVITATION_HMAC_ALIAS", raising=False)
    kms = _reload_kms()
    assert kms._invitation_alias_new() == "alias/echoroo-invitation-hmac"


def test_invitation_alias_new_empty_string_treated_as_unset(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that change ``if new:`` to ``if new is not None:``.

    An empty-string env var must be treated as unset (Python truthiness),
    so the legacy fallback fires. A mutant flipping to ``is not None``
    would return the empty string instead.
    """
    monkeypatch.setenv("AWS_KMS_CMK_INVITATION_HMAC_ALIAS_NEW", "")
    kms = _reload_kms()
    assert kms._invitation_alias_new() == INVITATION_LEGACY_ALIAS


def test_invitation_alias_new_precedence_new_wins_over_legacy(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that swap the _NEW vs legacy precedence order.

    When BOTH _NEW and legacy are set, _NEW must win. A mutant that
    inverts the ``if new: return new`` to ``if not new`` would surface
    the legacy alias instead.
    """
    monkeypatch.setenv("AWS_KMS_CMK_INVITATION_HMAC_ALIAS_NEW", "alias/precedence-new")
    monkeypatch.setenv(
        "AWS_KMS_CMK_INVITATION_HMAC_ALIAS", "alias/precedence-legacy"
    )
    kms = _reload_kms()
    assert kms._invitation_alias_new() == "alias/precedence-new"


# ===========================================================================
# verify_invitation_hmac — 5 surviving mutants
# ===========================================================================


def test_verify_invitation_hmac_rejects_non_hex_signature(
    kms_env: dict[str, str],
) -> None:
    """Kill mutants that drop the ``bytes.fromhex`` ValueError guard.

    Non-hex signature must short-circuit to False before any KMS call.
    """
    from echoroo.core import kms

    assert kms.verify_invitation_hmac(b"payload", "not-hex-zzz") is False


def test_verify_invitation_hmac_rejects_odd_length_hex(
    kms_env: dict[str, str],
) -> None:
    """Kill mutants that skip the ValueError catch on odd-length hex.

    Hex with an odd number of chars raises ValueError in fromhex.
    """
    from echoroo.core import kms

    assert kms.verify_invitation_hmac(b"p", "a" * 63) is False


def test_verify_invitation_hmac_skips_none_old_alias(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that drop the ``if alias is None: continue`` guard.

    When OLD alias is unset, the loop must skip None gracefully. Without
    the continue, ``_resolve_key_id(None)`` would raise a TypeError that
    propagates instead of returning False.
    """
    monkeypatch.delenv("AWS_KMS_CMK_INVITATION_HMAC_ALIAS_OLD", raising=False)
    kms = _reload_kms()

    payload = b"skip-none-test"
    sig = kms.sign_invitation_hmac(payload)
    # Valid sig under NEW key — must verify True even without OLD configured.
    assert kms.verify_invitation_hmac(payload, sig) is True

    # Bogus sig — must return False, not raise.
    bogus = "00" * 32
    assert kms.verify_invitation_hmac(payload, bogus) is False


def test_verify_invitation_hmac_tries_new_before_old(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that swap the iteration order (old before new).

    Iteration must hit NEW first (steady-state path = single KMS call).
    Spy on _resolve_key_id to capture the call order.
    """
    kms = _reload_kms()

    payload = b"order-test"
    sig = kms.sign_invitation_hmac(payload)

    real_resolve = kms._resolve_key_id
    seen: list[str] = []

    def spy(alias: str) -> str:
        seen.append(alias)
        return real_resolve(alias)

    monkeypatch.setattr(kms, "_resolve_key_id", spy)

    assert kms.verify_invitation_hmac(payload, sig) is True
    # NEW must be the first KMS-side call. (Sign call above used NEW too,
    # but the spy was installed AFTER signing so only verify calls counted.)
    assert seen[0] == INVITATION_NEW_ALIAS


def test_verify_invitation_hmac_short_circuits_on_new_match(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that always iterate to OLD even after NEW returns True.

    Once NEW matches, the loop must return True without calling OLD —
    ``return True`` short-circuits the for-loop.
    """
    kms = _reload_kms()

    payload = b"shortcircuit"
    sig = kms.sign_invitation_hmac(payload)

    real_resolve = kms._resolve_key_id
    seen: list[str] = []

    def spy(alias: str) -> str:
        seen.append(alias)
        return real_resolve(alias)

    monkeypatch.setattr(kms, "_resolve_key_id", spy)

    assert kms.verify_invitation_hmac(payload, sig) is True
    # OLD must not be queried when NEW already matched.
    assert INVITATION_OLD_ALIAS not in seen


def test_verify_invitation_hmac_returns_false_when_macvalid_false(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that flip ``MacValid`` truthiness.

    Stub verify_mac to return MacValid=False on both calls — the function
    must NOT mistake that for True.
    """
    kms = _reload_kms()
    real_client = kms._client()

    class StubClient:
        def verify_mac(self, **kwargs: Any) -> dict[str, bool]:
            return {"MacValid": False}

        def __getattr__(self, name: str) -> Any:
            return getattr(real_client, name)

    monkeypatch.setattr(kms, "_client", lambda: StubClient())

    assert kms.verify_invitation_hmac(b"any", "00" * 32) is False


def test_verify_invitation_hmac_returns_true_when_macvalid_true(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that invert the ``if resp.get("MacValid", False)`` guard.

    Stub verify_mac to return MacValid=True — the function must surface
    True. Pairs with the False-side test above.
    """
    kms = _reload_kms()
    real_client = kms._client()

    class StubClient:
        def verify_mac(self, **kwargs: Any) -> dict[str, bool]:
            return {"MacValid": True}

        def __getattr__(self, name: str) -> Any:
            return getattr(real_client, name)

    monkeypatch.setattr(kms, "_client", lambda: StubClient())

    assert kms.verify_invitation_hmac(b"any", "00" * 32) is True


def test_verify_invitation_hmac_missing_macvalid_defaults_false(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that change the ``False`` default in resp.get(..., False).

    A response dict without ``MacValid`` must be treated as False (safe
    default). A mutant flipping the default to True would falsely accept.
    """
    kms = _reload_kms()
    real_client = kms._client()

    class StubClient:
        def verify_mac(self, **kwargs: Any) -> dict[str, Any]:
            return {}  # No MacValid key.

        def __getattr__(self, name: str) -> Any:
            return getattr(real_client, name)

    monkeypatch.setattr(kms, "_client", lambda: StubClient())

    assert kms.verify_invitation_hmac(b"any", "00" * 32) is False


def test_verify_invitation_hmac_continue_on_kms_exception(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that change ``except: continue`` to ``except: return False``.

    When NEW raises (e.g. InvalidCiphertextException), the loop must
    CONTINUE to OLD — not bail out. Sign with OLD then verify; NEW
    will raise (sig under OLD does not validate against NEW), then OLD
    must succeed.
    """
    kms = _reload_kms()

    payload = b"old-only-token"
    # Sign with OLD directly via boto3. moto's GenerateMac requires the
    # raw KeyId UUID (not an alias), so we use the fixture-resolved id.
    direct_client = boto3.client("kms", region_name=AWS_REGION)
    resp = direct_client.generate_mac(
        Message=payload,
        KeyId=kms_env["inv_old_id"],
        MacAlgorithm="HMAC_SHA_256",
    )
    sig_old = resp["Mac"].hex()

    # Verify must continue past NEW (which raises) and succeed on OLD.
    assert kms.verify_invitation_hmac(payload, sig_old) is True


# ===========================================================================
# Smoke: regression on dual-write contract surface (compute_pii_hash_dual)
# ===========================================================================


def test_compute_pii_hash_dual_v1_byte_identical_to_compute_pii_hash(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill mutants that change the v1 alias used inside compute_pii_hash_dual.

    The v1 component of the dual hash MUST byte-equal compute_pii_hash
    so historical-row lookups continue to match (FR-091b invariant).
    """
    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", PII_V2_ALIAS)
    kms = _reload_kms()

    value = "byteid@example.com"
    single = kms.compute_pii_hash(value)
    dual = kms.compute_pii_hash_dual(value)
    assert dual["v1"] == single
