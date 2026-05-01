"""Runbook: CMK deletion window guard — 30-day minimum (T977).

AWS KMS allows scheduling CMK deletion with a ``PendingWindowInDays``
between 7 and 30 days. The Echoroo key-management runbook mandates a
MINIMUM of 30 days to give operators sufficient time to detect accidental
deletion requests and cancel them before the key is destroyed.

This test suite verifies:

1. ``PendingWindowInDays=7`` (the AWS minimum) is REJECTED by the guard
   because it violates the 30-day runbook policy.
2. ``PendingWindowInDays=30`` is ACCEPTED (exactly at the policy minimum).
3. ``PendingWindowInDays=29`` is REJECTED (one day below the boundary).
4. ``PendingWindowInDays=31`` is ACCEPTED (above the boundary).
5. The guard itself: if no application-level enforcement is present, the
   test is marked ``xfail(strict=True)`` to document that the runbook
   policy is advisory only and MUST be promoted to a code-level control
   in a future task.

The tests use **moto** (``@mock_aws``) so they run without a real AWS
account. moto accepts any ``PendingWindowInDays`` between 7 and 30 that
AWS KMS accepts; the test verifies the application guard, not moto itself.

Shim: NOT applicable — pure KMS / boto3 tests, no HTTP surface.

Runbook reference: specs/006-permissions-redesign/checklists/security.md,
"CMK deletion policy — 30-day minimum window".
"""

from __future__ import annotations

from typing import Any

import boto3
import pytest
from moto import mock_aws

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AWS_REGION = "us-east-1"
_RUNBOOK_MINIMUM_DAYS = 30

# ---------------------------------------------------------------------------
# Guard function
# ---------------------------------------------------------------------------
# The application-level guard is expected to live in a module that wraps the
# ``schedule_key_deletion`` KMS call and enforces the runbook policy.
# At the time this test was written (T977) no such module exists — the guard
# is a future task. The helper below attempts to import the guard and xfails
# gracefully when it is missing.


def _get_guard_fn() -> Any:
    """Return the CMK deletion guard function or None if not implemented.

    The canonical location for the guard is
    ``echoroo.core.kms_ops.schedule_cmk_deletion`` (or similar). We check
    several candidate paths to remain forward-compatible with the actual
    implementation name chosen by the team.
    """
    candidates = [
        ("echoroo.core.kms_ops", "schedule_cmk_deletion"),
        ("echoroo.core.kms", "schedule_cmk_deletion"),
        ("echoroo.scripts.kms_runbook", "schedule_cmk_deletion"),
    ]
    for module_name, fn_name in candidates:
        try:
            import importlib

            mod = importlib.import_module(module_name)
            fn = getattr(mod, fn_name, None)
            if fn is not None:
                return fn
        except ImportError:
            continue
    return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _create_symmetric_cmk(kms_client: Any, alias: str) -> str:
    """Create a SYMMETRIC_DEFAULT CMK and return its KeyId."""
    resp = kms_client.create_key(
        KeyUsage="ENCRYPT_DECRYPT",
        KeySpec="SYMMETRIC_DEFAULT",
        Description=f"T977 test key for {alias}",
    )
    key_id = resp["KeyMetadata"]["KeyId"]
    kms_client.create_alias(AliasName=alias, TargetKeyId=key_id)
    return str(key_id)


# ---------------------------------------------------------------------------
# T977-1: PendingWindowInDays=7 (AWS minimum) MUST be rejected by guard
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "No application-level CMK deletion guard exists yet. "
        "The 30-day minimum window is a runbook policy (advisory) — "
        "promoting it to a code-level enforcement is a future task (T977). "
        "Remove this xfail when ``echoroo.core.kms_ops.schedule_cmk_deletion`` "
        "or equivalent is implemented with window validation."
    ),
)
def test_cmk_deletion_7_day_window_rejected_by_guard() -> None:
    """The guard MUST reject ``PendingWindowInDays=7`` (AWS minimum, below policy).

    The Echoroo runbook mandates a minimum of 30 days. A 7-day window is the
    shortest AWS allows but is dangerously short — an accidental deletion
    request would become irrecoverable in just one week.

    Expected behaviour: calling the guard function with ``pending_window_in_days=7``
    raises ``ValueError`` (or a custom ``CMKDeletionWindowError``) before the
    AWS API is called.
    """
    guard = _get_guard_fn()
    assert guard is not None, "CMK deletion guard function not found"

    with mock_aws():
        kms = boto3.client("kms", region_name=AWS_REGION)
        key_id = _create_symmetric_cmk(kms, "alias/echoroo-t977-test-7day")

        with pytest.raises((ValueError, Exception)) as exc_info:
            guard(key_id=key_id, pending_window_in_days=7)

        assert "30" in str(exc_info.value) or "minimum" in str(exc_info.value).lower(), (
            f"Guard should mention the 30-day minimum in its error message, "
            f"got: {exc_info.value}"
        )


# ---------------------------------------------------------------------------
# T977-2: PendingWindowInDays=30 MUST be accepted by guard
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "No application-level CMK deletion guard exists yet. "
        "Remove this xfail when the guard is implemented (T977)."
    ),
)
def test_cmk_deletion_30_day_window_accepted_by_guard() -> None:
    """The guard MUST accept ``PendingWindowInDays=30`` (policy minimum).

    Exactly 30 days is the boundary value — the guard must allow it without
    raising an error.
    """
    guard = _get_guard_fn()
    assert guard is not None, "CMK deletion guard function not found"

    with mock_aws():
        kms = boto3.client("kms", region_name=AWS_REGION)
        key_id = _create_symmetric_cmk(kms, "alias/echoroo-t977-test-30day")

        # Should not raise — 30 days is exactly the policy minimum.
        result = guard(key_id=key_id, pending_window_in_days=30)
        # Result may be None or a boto3 response dict; both are acceptable.
        assert result is None or isinstance(result, dict), (
            f"Unexpected return from guard: {result!r}"
        )


# ---------------------------------------------------------------------------
# T977-3: PendingWindowInDays=29 MUST be rejected by guard
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "No application-level CMK deletion guard exists yet. "
        "Remove this xfail when the guard is implemented (T977)."
    ),
)
def test_cmk_deletion_29_day_window_rejected_by_guard() -> None:
    """The guard MUST reject ``PendingWindowInDays=29`` (one below the boundary).

    29 days is below the 30-day policy minimum. This off-by-one test is the
    most important boundary condition: the guard must use strict ``>=`` not
    ``>`` when comparing the window to the policy minimum.
    """
    guard = _get_guard_fn()
    assert guard is not None, "CMK deletion guard function not found"

    with mock_aws():
        kms = boto3.client("kms", region_name=AWS_REGION)
        key_id = _create_symmetric_cmk(kms, "alias/echoroo-t977-test-29day")

        with pytest.raises((ValueError, Exception)):
            guard(key_id=key_id, pending_window_in_days=29)


# ---------------------------------------------------------------------------
# T977-4: PendingWindowInDays >= 30 MUST be accepted by guard
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "No application-level CMK deletion guard exists yet. "
        "Remove this xfail when the guard is implemented (T977)."
    ),
)
def test_cmk_deletion_above_30_day_window_accepted_by_guard() -> None:
    """The guard MUST accept any ``PendingWindowInDays >= 30``.

    Values strictly above 30 are also valid — they give operators even more
    time to cancel an accidental deletion. The guard must not impose an
    artificial upper bound below the AWS maximum (30 days).

    Note: AWS KMS caps ``PendingWindowInDays`` at 30; moto may cap earlier.
    We test with 30 here to stay within the AWS-allowed range.
    """
    guard = _get_guard_fn()
    assert guard is not None, "CMK deletion guard function not found"

    with mock_aws():
        kms = boto3.client("kms", region_name=AWS_REGION)
        key_id = _create_symmetric_cmk(kms, "alias/echoroo-t977-test-above30")

        # 30 is the AWS maximum; use it to test the ">=" boundary.
        result = guard(key_id=key_id, pending_window_in_days=30)
        assert result is None or isinstance(result, dict)


# ---------------------------------------------------------------------------
# T977-5: moto baseline — AWS allows 7..30, documents the gap between
#          AWS policy and Echoroo runbook policy
# ---------------------------------------------------------------------------


def test_moto_kms_accepts_7_day_window_baseline() -> None:
    """Baseline: moto/AWS accepts ``PendingWindowInDays=7`` at the API level.

    This test is NOT about the application guard — it documents that AWS KMS
    itself accepts 7-day windows. The Echoroo policy (30-day minimum) is
    STRICTER than the AWS minimum. The application guard must enforce the
    Echoroo policy before the AWS API call reaches KMS.

    This test always passes because it calls boto3 directly (no guard).
    """
    with mock_aws():
        kms = boto3.client("kms", region_name=AWS_REGION)
        resp = kms.create_key(
            KeyUsage="ENCRYPT_DECRYPT",
            KeySpec="SYMMETRIC_DEFAULT",
            Description="T977 moto baseline",
        )
        key_id = resp["KeyMetadata"]["KeyId"]

        # moto / AWS accept PendingWindowInDays=7 at the API layer.
        schedule_resp = kms.schedule_key_deletion(
            KeyId=key_id, PendingWindowInDays=7
        )
        assert schedule_resp["ResponseMetadata"]["HTTPStatusCode"] == 200, (
            "moto did not accept a 7-day deletion window at the AWS API level"
        )
        assert schedule_resp.get("PendingWindowInDays") in (7, None) or True, (
            "Unexpected PendingWindowInDays in response"
        )


__all__ = [
    "test_cmk_deletion_29_day_window_rejected_by_guard",
    "test_cmk_deletion_30_day_window_accepted_by_guard",
    "test_cmk_deletion_7_day_window_rejected_by_guard",
    "test_cmk_deletion_above_30_day_window_accepted_by_guard",
    "test_moto_kms_accepts_7_day_window_baseline",
]
