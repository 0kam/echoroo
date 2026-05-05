"""PII hash key rotation dual-write tests (T975, FR-091b, v1/v2 90-day window).

Verifies the PII hash key rotation contract for audit log rows:

  FR-091b contract:
  * During a rotation from key v1 → v2 a new audit row is hashed under
    BOTH v1 and v2 (dual-write). This allows:
      - Existing rows (hashed only with v1) to remain searchable via v1.
      - New rows to be immediately searchable via v2.
  * After 90 days (the backfill window), all historical rows have been
    migrated to v2. At that point the system switches to v2-only writes
    and v1 is retired.

Current implementation status:
  ``echoroo.core.kms.compute_pii_hash`` uses a SINGLE key
  (``alias/echoroo-pii-hash-hmac``). There is no concept of v1/v2
  dual-write for PII hashes; the KMS module does not expose a
  ``compute_pii_hash_dual`` or ``compute_pii_hash_v2`` function. The
  audit service calls ``compute_pii_hash`` once per field and stores a
  single hash value. The ``project_audit_log`` / ``platform_audit_log``
  tables have no ``actor_user_id_hash_v2`` or ``pii_hash_version`` column.

  The dual-write + 90-day backfill logic has not yet been implemented.

All tests that require the dual-write contract are therefore marked
``xfail(strict=True)`` with a forward reference to indicate they represent
the TDD red phase for the FR-091b implementation.

The single test that verifies the current single-key behaviour (positive
smoke test) passes today and is NOT marked xfail.

Shim: NOT applicable (pure KMS service-layer tests, no HTTP).
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AWS_REGION = "us-east-1"

PII_HASH_V1_ALIAS = "alias/echoroo-t975-pii-hash-v1"
PII_HASH_V2_ALIAS = "alias/echoroo-t975-pii-hash-v2"
TOTP_DEK_ALIAS = "alias/echoroo-t975-totp-dek"
AUDIT_CHAIN_ALIAS = "alias/echoroo-t975-audit-chain"
INVITATION_HMAC_ALIAS = "alias/echoroo-t975-invitation-hmac"


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def kms_env_pii_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, str]]:
    """Provision moto KMS with v1 and v2 PII hash CMKs.

    The module env vars initially point only at v1 (simulating the state
    before rotation starts). Individual tests that want to simulate
    rotation-in-progress or post-rotation may monkeypatch the v2 alias
    env var and reload ``echoroo.core.kms``.
    """
    monkeypatch.delenv("AWS_KMS_ENDPOINT", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL_KMS", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)

    with mock_aws():
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
        monkeypatch.setenv("AWS_DEFAULT_REGION", AWS_REGION)

        kms = boto3.client("kms", region_name=AWS_REGION)

        # Symmetric key for TOTP DEK
        totp_resp = kms.create_key(
            KeyUsage="ENCRYPT_DECRYPT", KeySpec="SYMMETRIC_DEFAULT"
        )
        totp_id = totp_resp["KeyMetadata"]["KeyId"]
        kms.create_alias(AliasName=TOTP_DEK_ALIAS, TargetKeyId=totp_id)

        # HMAC keys
        def _hmac_key(alias: str) -> str:
            resp = kms.create_key(
                KeyUsage="GENERATE_VERIFY_MAC", KeySpec="HMAC_256"
            )
            key_id = resp["KeyMetadata"]["KeyId"]
            kms.create_alias(AliasName=alias, TargetKeyId=key_id)
            return str(key_id)

        pii_v1_id = _hmac_key(PII_HASH_V1_ALIAS)
        pii_v2_id = _hmac_key(PII_HASH_V2_ALIAS)
        audit_id = _hmac_key(AUDIT_CHAIN_ALIAS)
        inv_id = _hmac_key(INVITATION_HMAC_ALIAS)

        # Start with v1 only (no dual-write yet).
        monkeypatch.setenv("AWS_KMS_REGION", AWS_REGION)
        monkeypatch.setenv("AWS_KMS_CMK_2FA_ALIAS", TOTP_DEK_ALIAS)
        monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS", PII_HASH_V1_ALIAS)
        monkeypatch.setenv("AWS_KMS_CMK_AUDIT_CHAIN_ALIAS", AUDIT_CHAIN_ALIAS)
        monkeypatch.setenv(
            "AWS_KMS_CMK_INVITATION_HMAC_ALIAS", INVITATION_HMAC_ALIAS
        )
        # Ensure _NEW / _OLD not set so legacy single-alias path is used.
        monkeypatch.delenv("AWS_KMS_CMK_INVITATION_HMAC_ALIAS_NEW", raising=False)
        monkeypatch.delenv("AWS_KMS_CMK_INVITATION_HMAC_ALIAS_OLD", raising=False)

        import echoroo.core.kms as kms_module
        importlib.reload(kms_module)

        yield {
            "pii_v1_id": pii_v1_id,
            "pii_v2_id": pii_v2_id,
            "audit_id": audit_id,
            "inv_id": inv_id,
        }


# ---------------------------------------------------------------------------
# T975-1: single-key hash is deterministic (positive smoke test — passes today)
# ---------------------------------------------------------------------------


def test_pii_hash_single_key_deterministic(
    kms_env_pii_rotation: dict[str, str],
) -> None:
    """compute_pii_hash with a single configured key is deterministic.

    This test verifies current (v1-only) behaviour passes. It is NOT xfail.
    """
    from echoroo.core import kms

    value = "user@example.com"
    h1 = kms.compute_pii_hash(value)
    h2 = kms.compute_pii_hash(value)

    assert h1 == h2, "PII hash must be deterministic"
    assert len(h1) == 64, "PII hash must be 64-char hex (HMAC-SHA256)"


# ---------------------------------------------------------------------------
# T975-2: dual-write produces v1 hash on existing rows (rotation start)
# ---------------------------------------------------------------------------


def test_dual_write_rotation_start_v1_hash_matches_existing(
    kms_env_pii_rotation: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At rotation start, the v1 hash of new rows matches existing v1 rows.

    When rotation begins (v2 alias introduced), new rows are dual-written:
    the v1 hash must equal what would have been stored before rotation started
    so that lookups using v1 (for existing rows) still work against new rows.
    """
    from echoroo.core import kms

    value = "actor-123"
    # Existing row hash (computed before rotation).
    existing_v1_hash = kms.compute_pii_hash(value)

    # Introduce v2 alias to simulate rotation start.
    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", PII_HASH_V2_ALIAS)
    importlib.reload(kms)

    # After dual-write implementation, the function must return both hashes.
    # The v1 component must equal the existing_v1_hash.
    # This call is expected to fail (xfail) until dual-write is implemented.
    result = kms.compute_pii_hash_dual(value)  # type: ignore[attr-defined]  # not yet impl
    v1_component = result["v1"]
    assert v1_component == existing_v1_hash, (
        "Dual-write v1 hash must match pre-rotation hash for same input"
    )


# ---------------------------------------------------------------------------
# T975-3: dual-write produces v2 hash on new rows
# ---------------------------------------------------------------------------


def test_dual_write_rotation_start_v2_hash_differs_from_v1(
    kms_env_pii_rotation: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dual-write must produce a distinct v2 hash (different key → different MAC).

    The v2 hash is computed against the new CMK. Since the keys are distinct,
    the same input must produce different MACs under v1 and v2. This is the
    defence-in-depth property that justifies using two separate CMKs rather
    than re-using the same key with a domain separator.
    """
    from echoroo.core import kms

    value = "actor-456"

    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", PII_HASH_V2_ALIAS)
    importlib.reload(kms)

    result = kms.compute_pii_hash_dual(value)  # type: ignore[attr-defined]
    assert result["v1"] != result["v2"], (
        "v1 and v2 hashes must differ (distinct CMKs → distinct MACs)"
    )


# ---------------------------------------------------------------------------
# T975-4: after 90-day backfill, v2-only mode stops writing v1
# ---------------------------------------------------------------------------


def test_post_backfill_v2_only_mode(
    kms_env_pii_rotation: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-90-day backfill: v2-only mode produces a hash tagged as v2.

    After all historical rows have been back-filled to v2, operators
    retire the v1 alias by removing ``AWS_KMS_CMK_PII_HASH_ALIAS`` (or
    pointing it at the same CMK as v2). New writes must produce only the
    v2 hash AND must be marked with pii_hash_version=2 so the audit
    service can distinguish them from v1-only rows.

    This test requires a ``get_pii_hash_version()`` function in kms.py
    that returns the current active version (1 during pre-rotation / single
    key, 2 after rotation completes). The function does not currently exist
    — xfail until implemented.
    """
    from echoroo.core import kms

    # Simulate post-backfill: operator has retired the v1 alias by
    # re-pointing AWS_KMS_CMK_PII_HASH_ALIAS at the v2 CMK and
    # unsetting AWS_KMS_CMK_PII_HASH_ALIAS_V2. The
    # ``ECHOROO_PII_HASH_ROTATION_COMPLETE`` flag is the explicit
    # operator signal that "we are now generation 2"; without it the
    # module cannot distinguish post-rotation from a fresh single-key
    # deployment that happens to use a different alias name.
    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS", PII_HASH_V2_ALIAS)
    monkeypatch.delenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", raising=False)
    monkeypatch.setenv("ECHOROO_PII_HASH_ROTATION_COMPLETE", "true")
    importlib.reload(kms)

    active_version = kms.get_pii_hash_version()
    assert active_version == 2, (
        "After retiring v1 alias, pii hash version must be 2 "
        "(v2-only mode active)"
    )


# ---------------------------------------------------------------------------
# T975-5: hash lookup using v1 still works for pre-rotation rows
# ---------------------------------------------------------------------------


def test_pre_rotation_row_searchable_via_v1_during_dual_write(
    kms_env_pii_rotation: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A v1-hashed row remains searchable during the dual-write window.

    After rotation starts, audit log lookups must still match existing
    rows that were hashed under v1. A ``verify_pii_hash(value, stored_hash)``
    helper (or equivalent service-layer logic) must try v1 first, then v2,
    mirroring the invitation HMAC k_new/k_old fallback pattern.
    """
    from echoroo.core import kms

    value = "lookup-target@example.com"

    # Store a v1 hash (pre-rotation).
    stored_v1_hash = kms.compute_pii_hash(value)

    # Simulate rotation in progress.
    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", PII_HASH_V2_ALIAS)
    importlib.reload(kms)

    # The lookup helper must be able to match the stored v1 hash.
    match = kms.verify_pii_hash(value, stored_v1_hash)  # type: ignore[attr-defined]
    assert match is True, (
        "Pre-rotation v1 hash must remain searchable during dual-write window"
    )


# ---------------------------------------------------------------------------
# Round 2 regression tests (Phase 17 backlog A-2)
# ---------------------------------------------------------------------------


def test_compute_dual_consistent_with_get_version(
    kms_env_pii_rotation: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 2 R1-C2: ``compute_pii_hash_dual`` agrees with the version flag.

    The single source of truth for "are we in rotation?" is
    :func:`get_pii_hash_version`. Whenever it reports 2, the dual helper
    MUST emit a ``v2`` component — even in the post-rotation state where
    the v2 alias is unset and the v1 alias has been re-pointed at the
    rotated CMK. Otherwise writers would stamp ``pii_hash_version = 2``
    while leaving the ``*_v2`` columns NULL, and bulk lookups using the
    designed ``WHERE *_v2 = ? OR legacy = ?`` predicate would silently
    miss the post-rotation row family.
    """
    from echoroo.core import kms

    # Pre-rotation: version 1, no v2 component.
    pre = kms.compute_pii_hash_dual("subject@example.com")
    assert kms.get_pii_hash_version() == 1
    assert "v2" not in pre

    # Rotation in progress (v2 alias set).
    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", PII_HASH_V2_ALIAS)
    importlib.reload(kms)
    mid = kms.compute_pii_hash_dual("subject@example.com")
    assert kms.get_pii_hash_version() == 2
    assert "v2" in mid
    assert mid["v1"] != mid["v2"]

    # Post-rotation: v2 alias unset, v1 alias re-pointed, COMPLETE flag set.
    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS", PII_HASH_V2_ALIAS)
    monkeypatch.delenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", raising=False)
    monkeypatch.setenv("ECHOROO_PII_HASH_ROTATION_COMPLETE", "true")
    importlib.reload(kms)
    post = kms.compute_pii_hash_dual("subject@example.com")
    assert kms.get_pii_hash_version() == 2
    assert "v2" in post, (
        "post-rotation must still expose a v2 component so writers and "
        "the version metadata column never disagree"
    )
    # In the post-rotation collapsed-key mode v1 and v2 are byte-identical
    # (both computed under the now-canonical alias).
    assert post["v1"] == post["v2"]


def test_invitation_v2_only_when_rotation_active(
    kms_env_pii_rotation: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 2 R1-C1: single-key invitations leave ``email_hash_v2`` NULL.

    The daily backfill worker selects on ``email_hash_v2 IS NULL``. If
    the writer stuffed the v1 hash into the v2 column when rotation was
    inactive, the row would never be picked up once the v2 alias was
    actually flipped on, and the rotation would never complete. This
    test exercises ``hash_email_dual`` to confirm the writer's branch
    behaviour.
    """
    # NOTE: ``invitation_service`` is intentionally NOT reloaded — doing
    # so creates a fresh ``InvitationInfraUnavailableError`` class object
    # which would break any sibling test that captured the original
    # symbol via ``from ... import ...`` (test pollution observed in
    # Round 2 development). ``hash_email_dual`` defers its KMS import
    # to the function body so a kms reload alone is sufficient to pick
    # up the new env var.
    from echoroo.core import kms
    from echoroo.services import invitation_service

    importlib.reload(kms)

    # Pre-rotation — single key, no v2 component.
    pre = invitation_service.hash_email_dual("alice@example.com")
    assert "v2" not in pre, (
        "pre-rotation hash_email_dual must NOT emit a v2 component; "
        "the writer relies on its absence to leave email_hash_v2 NULL "
        "so the daily backfill task can find the row later"
    )

    # Activate rotation and re-confirm the writer's contract.
    monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", PII_HASH_V2_ALIAS)
    importlib.reload(kms)
    mid = invitation_service.hash_email_dual("alice@example.com")
    assert "v2" in mid, "rotation-active hash_email_dual must emit v2"
    assert mid["v1"] != mid["v2"]


def test_audit_lookup_or_clause_filter_is_used() -> None:
    """Round 2 R1-I1: audit page helper SQL contains the v1 OR v2 predicate.

    The runtime SQL is constructed by :func:`_project_audit_page` and
    :func:`_platform_audit_page` from filter fragments that are joined
    with `` AND ``. Asserting on a normalised view of the helper source
    protects against a regression where the OR clause is accidentally
    collapsed back to a single-column equality (which would silently
    exclude post-rotation rows from any actor-filtered query).
    """
    import inspect
    import re

    from echoroo.api.web_v1 import audit as audit_module

    def _normalise(text: str) -> str:
        # Collapse adjacent Python string-literal joints so we can match
        # the logical SQL fragment regardless of how the multi-line
        # literal was reformatted by ruff / black. ``"foo " "bar"`` in
        # the source reads as ``foo " "bar`` after whitespace collapse;
        # stripping the inter-literal ``" "`` recovers ``foo bar``.
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r'"\s*"', "", text)
        return text

    proj_src = _normalise(inspect.getsource(audit_module._project_audit_page))
    plat_src = _normalise(inspect.getsource(audit_module._platform_audit_page))

    or_clause = (
        "(actor_user_id_hash = :actor_hash "
        "OR actor_user_id_hash_v2 = :actor_hash)"
    )
    assert or_clause in proj_src, (
        "_project_audit_page must filter actor with the v1 OR v2 predicate"
    )
    assert or_clause in plat_src, (
        "_platform_audit_page must filter actor with the v1 OR v2 predicate"
    )
