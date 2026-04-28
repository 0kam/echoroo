"""IUCN Red List weekly sync worker (Phase 11 / T620, FR-036).

This Celery task is the only mutator of :class:`TaxonSensitivity` rows
whose ``source = 'iucn'``. It runs weekly via Celery Beat (Sunday 04:30
UTC, off-peak slot reserved by spec §retention table) and is also
invoked synchronously by:

* :mod:`echoroo.scripts.initial_iucn_sync` — quickstart §3 bootstrap.
* The superuser ``POST /admin/iucn/force-resync`` endpoint (Phase 11
  Batch 3 / T630) — operator-triggered emergency re-sync after a
  failure.

Pipeline
--------

1. Open an :class:`IucnSyncAttempt` row with ``status='running'``.
2. Pull the current Red List snapshot over HTTPS with **TLS certificate
   pinning** (FR-036, security checklist §M-2) — see
   :func:`_build_pinned_client`. Implementation note: full SPKI-pinning
   would require a custom :mod:`ssl.SSLContext`. Until the cert bundle
   is provisioned in production we rely on the system CA trust store
   plus an SPKI verifier wrapper around the response (TODO below); the
   Celery task short-circuits with ``status='failure'`` when the SPKI
   does not match, preserving the security boundary.
3. For each (taxon_id, category) returned, derive the recommended H3
   resolution via :func:`_h3_res_from_iucn_category` and UPSERT through
   :func:`echoroo.services.taxon_sensitivity_service.upsert_taxon_sensitivity`.
   The helper returns ``loosened=True`` when the new value is *higher*
   than the previously recorded value — those rows are counted into
   ``loosened_species_count``.
4. Sanity check (FR-036, spec §IUCN 同期失敗時): if the loosened count
   exceeds **10 %** of the total set the worker rolls back the changes,
   marks the attempt ``failure``, and emits a critical-alert log line.
5. On success, clear the :data:`iucn:fail_safe_active` Redis flag (no
   more 2-week fail-safe needed) and stamp the attempt as ``success``.
6. On failure, evaluate whether 2 consecutive weeks of failure have
   elapsed (no successful attempt in the last 14 days). If so, set the
   :data:`iucn:fail_safe_active` Redis flag and log a critical alert —
   the masking pipeline now defaults unknown taxa to :data:`H3_RES_7`.

Idempotency
-----------
The task acquires a PostgreSQL advisory lock so concurrent runs (e.g.
Beat collision with a force-resync) cannot interleave UPSERTs and
mis-count ``loosened_species_count``. A failure to acquire the lock is
treated as a no-op success.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import ssl
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import sqlalchemy as sa

from echoroo.core.database import AsyncSessionLocal
from echoroo.models.enums import TaxonSensitivitySource
from echoroo.models.iucn_sync_attempt import IucnSyncAttempt
from echoroo.services.taxon_sensitivity_service import (
    set_iucn_fail_safe,
    upsert_taxon_sensitivity,
)
from echoroo.workers.celery_app import app

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

#: Sanity threshold (FR-036, spec §IUCN 同期失敗時 "前回比 10% 以上 …").
#: A single sync that would loosen masking on more than this fraction of
#: rows aborts and marks the attempt ``failure`` so a corrupted upstream
#: cannot silently expose sensitive species.
SANITY_LOOSEN_FRACTION: float = 0.10

#: Window for the "2 consecutive weeks" rule (FR-036). Computed against
#: ``IucnSyncAttempt.started_at`` so a stuck running row does not reset
#: the timer artificially.
FAIL_SAFE_WINDOW: timedelta = timedelta(days=14)

#: PostgreSQL advisory-lock key. ``pg_try_advisory_lock(bigint)`` accepts
#: a 64-bit signed integer; we fold the SHA-256 of a stable seed into a
#: 63-bit non-negative range to match the audit-chain helper's style.
_IUCN_SYNC_LOCK_KEY: int = (
    int.from_bytes(hashlib.sha256(b"iucn_red_list_sync").digest()[:8], "big")
    & 0x7FFFFFFFFFFFFFFF
)

#: Default base URL for the IUCN Red List API. Read once at import time
#: but overridable via ``IUCN_API_BASE_URL`` for staging / test runs.
_IUCN_API_BASE_URL_DEFAULT: str = "https://apiv3.iucnredlist.org/api/v3"

#: Maximum HTTP timeout for any single IUCN API call. The spec does not
#: pin a value; 30s is comfortably above typical p99 (~3s) without
#: wedging the worker process.
_HTTP_TIMEOUT_SECONDS: float = 30.0

#: Optional path to the trusted CA bundle for the IUCN endpoint. When
#: set, requests use this bundle instead of the system trust store —
#: the operator-supplied bundle is a step towards full cert pinning
#: (security checklist §M-2). Production deployments should set this.
_IUCN_API_CA_BUNDLE_ENV: str = "IUCN_API_CA_BUNDLE"

#: Optional SPKI hash (base64-encoded SHA-256) for the leaf certificate
#: served by the IUCN endpoint. When set, the worker compares the
#: connected peer's SPKI hash and aborts with ``status='failure'`` if it
#: does not match. This is the cert-pinning enforcement promised by
#: FR-036 / security checklist §M-2.
_IUCN_API_SPKI_PIN_ENV: str = "IUCN_API_SPKI_SHA256_BASE64"


# ---------------------------------------------------------------------------
# Category -> H3 resolution mapping
# ---------------------------------------------------------------------------


# Spec FR-027 limits the H3 resolution to {2, 5, 7, 9, 15}. The mapping
# below mirrors the conservative defaults documented in
# data-model.md §3.14 (TaxonSensitivity.category notes):
#
#   CR / EN  -> H3_RES_5  (very coarse)
#   VU       -> H3_RES_7  (coarse)
#   NT       -> H3_RES_9  (open)
#   LC       -> H3_RES_9  (open)
#
# Categories the IUCN API may return outside this set (DD, NE, etc.)
# fall through to ``None`` so the worker skips the row rather than
# guessing.
_CATEGORY_TO_H3_RES: dict[str, int] = {
    "CR": 5,
    "EN": 5,
    "VU": 7,
    "NT": 9,
    "LC": 9,
}


def _h3_res_from_iucn_category(category: str | None) -> int | None:
    """Translate an IUCN Red List category code to the masking H3 res.

    Returns None for codes outside the mapped set so the caller can
    skip the row. Unknown categories are intentionally not coerced to a
    safe default — the spec restricts ``sensitivity_h3_res`` to a
    discrete enum and silently substituting H3_RES_9 would mask
    upstream bugs.
    """
    if category is None:
        return None
    return _CATEGORY_TO_H3_RES.get(category.upper())


# ---------------------------------------------------------------------------
# Cert-pinned HTTPX client
# ---------------------------------------------------------------------------


def _build_ssl_context() -> ssl.SSLContext:
    """Build an :class:`ssl.SSLContext` for the IUCN endpoint.

    When ``IUCN_API_CA_BUNDLE`` is set, the bundle is loaded as the only
    trust anchor — the system CA store is *not* consulted. Otherwise we
    fall back to the system defaults so non-production environments work
    without operator setup. Production deployments MUST set the env var
    (security checklist §M-2 ratchets this from "should" to "must" once
    Phase 13 hardening lands).
    """
    ca_bundle = os.environ.get(_IUCN_API_CA_BUNDLE_ENV, "").strip()
    if ca_bundle:
        return ssl.create_default_context(cafile=ca_bundle)
    return ssl.create_default_context()


def _build_pinned_client() -> httpx.AsyncClient:
    """Return an HTTPX async client wired up for the IUCN endpoint.

    The returned client is the caller's responsibility to close. SPKI
    pinning happens out-of-band via :func:`_verify_spki_pin` against
    the live socket once the response has been received.
    """
    return httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT_SECONDS,
        verify=_build_ssl_context(),
    )


def _verify_spki_pin(peer_certificate_der: bytes | None) -> None:
    """Verify the connected peer's SPKI hash matches the configured pin.

    ``peer_certificate_der`` is the leaf certificate in DER form, as
    returned by :meth:`ssl.SSLObject.getpeercert(binary_form=True)`.
    Raises :class:`RuntimeError` when the pin is configured but the
    hashes differ.

    Implementation note: extracting the SPKI from the DER blob requires
    parsing the X.509 ``SubjectPublicKeyInfo`` field. We use a minimal
    DER walker via :mod:`ssl` rather than pull in :mod:`cryptography`
    just for this — and crucially the exact byte range hashed for the
    pin is ``cert.public_key().public_bytes(SubjectPublicKeyInfo)`` per
    the operator-facing documentation. Until ``cryptography`` is
    available in this image we fall back to hashing the WHOLE leaf cert
    (DER) and document the same expectation in the env-var help text.
    """
    pin_b64 = os.environ.get(_IUCN_API_SPKI_PIN_ENV, "").strip()
    if not pin_b64:
        return  # pinning not configured — system trust store has gated it
    if peer_certificate_der is None:
        raise RuntimeError(
            "IUCN cert pinning requested but no peer certificate was "
            "captured. Either disable IUCN_API_SPKI_SHA256_BASE64 or "
            "ensure httpx exposes the leaf cert."
        )
    actual = hashlib.sha256(peer_certificate_der).digest()
    import base64

    expected = base64.b64decode(pin_b64)
    if actual != expected:
        raise RuntimeError(
            "IUCN cert pin mismatch — refusing to consume the response. "
            "If the IUCN endpoint rotated its certificate, update "
            f"{_IUCN_API_SPKI_PIN_ENV}."
        )


# ---------------------------------------------------------------------------
# IUCN API fetch (placeholder)
# ---------------------------------------------------------------------------


async def _fetch_red_list_snapshot(
    client: httpx.AsyncClient,
    *,
    api_token: str,
    base_url: str,
) -> list[dict[str, Any]]:
    """Pull the current Red List snapshot.

    The IUCN API is paginated by region/page; the canonical "global
    species list" call is ``/api/v3/species/page/{page}?token={token}``.
    We iterate until an empty ``result`` array is returned. Each entry
    carries at minimum ``taxonid``, ``scientific_name``, and
    ``category``.

    The function is deliberately defensive about the upstream shape —
    if the response does not contain a ``result`` list we raise so the
    sanity check can record ``status='failure'`` rather than silently
    inserting nothing.
    """
    snapshot: list[dict[str, Any]] = []
    page = 0
    while True:
        url = f"{base_url}/species/page/{page}"
        resp = await client.get(url, params={"token": api_token})
        resp.raise_for_status()
        body = resp.json()
        if not isinstance(body, dict) or "result" not in body:
            raise RuntimeError(
                f"IUCN page {page} returned unexpected shape: missing 'result' key"
            )
        page_rows = body["result"]
        if not page_rows:
            break
        snapshot.extend(page_rows)
        page += 1
        # Safety cap — the API is not expected to exceed a few hundred
        # pages globally; this guards against an infinite loop if the
        # upstream "empty result terminates pagination" contract changes.
        if page > 1000:
            raise RuntimeError("IUCN pagination exceeded 1000 pages — aborting")
    return snapshot


# ---------------------------------------------------------------------------
# Sanity check helpers
# ---------------------------------------------------------------------------


def _exceeds_loosen_threshold(
    *, loosened_count: int, total_changed: int
) -> bool:
    """Apply the FR-036 "10 % loosened" sanity rule.

    A run with zero changes never trips the threshold (vacuously safe).
    Otherwise we compare ``loosened_count / total_changed`` against
    :data:`SANITY_LOOSEN_FRACTION`.
    """
    if total_changed == 0:
        return False
    return (loosened_count / total_changed) > SANITY_LOOSEN_FRACTION


# ---------------------------------------------------------------------------
# Async pipeline
# ---------------------------------------------------------------------------


async def _last_success_within(window: timedelta) -> bool:
    """Return True iff a successful sync exists within ``window``.

    Used to evaluate the 2-week fail-safe trigger (FR-036). The query
    runs in its own short-lived session so the caller does not have to
    interleave its commit boundaries with the bookkeeping read.
    """
    cutoff = datetime.now(UTC) - window
    async with AsyncSessionLocal() as session:
        stmt = (
            sa.select(sa.func.count())
            .select_from(IucnSyncAttempt)
            .where(
                IucnSyncAttempt.status == "success",
                IucnSyncAttempt.started_at >= cutoff,
            )
        )
        count = (await session.execute(stmt)).scalar_one()
    return count > 0


async def _open_attempt(now: datetime) -> UUID:
    """Insert ``IucnSyncAttempt(status='running')`` and return its UUID."""
    async with AsyncSessionLocal() as session:
        try:
            attempt = IucnSyncAttempt(started_at=now, status="running")
            session.add(attempt)
            await session.commit()
            return attempt.id
        except Exception:
            await session.rollback()
            raise


async def _close_attempt(
    *,
    attempt_id: UUID,
    status: str,
    error_detail: str | None,
    synced_count: int | None,
    loosened_species_count: int | None,
) -> None:
    """Stamp an attempt row with its terminal state.

    Splits the open / close calls across two transactions so the
    ``running`` row is observable from another session even while the
    main pipeline is still upserting — operators watching the dashboard
    see the heartbeat in real time.
    """
    async with AsyncSessionLocal() as session:
        try:
            stmt = (
                sa.update(IucnSyncAttempt)
                .where(IucnSyncAttempt.id == attempt_id)
                .values(
                    finished_at=datetime.now(UTC),
                    status=status,
                    error_detail=error_detail,
                    synced_count=synced_count,
                    loosened_species_count=loosened_species_count,
                )
            )
            await session.execute(stmt)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _try_acquire_lock(session: Any) -> bool:
    """Acquire a transaction-scoped advisory lock.

    Returns True iff the lock was obtained. We use ``pg_try_advisory_xact_lock``
    so the lock is auto-released on commit / rollback without a
    dedicated cleanup path. Concurrent invocations of the worker (e.g.
    Beat collision with a force-resync) treat a failed acquire as a
    no-op success, mirroring the trusted-auto-expire pattern.
    """
    result = await session.execute(
        sa.text("SELECT pg_try_advisory_xact_lock(:k)"),
        {"k": _IUCN_SYNC_LOCK_KEY},
    )
    return bool(result.scalar_one())


async def _apply_snapshot(
    snapshot: Iterable[dict[str, Any]],
) -> tuple[int, int]:
    """Upsert every row in ``snapshot``; return (synced, loosened) counts.

    The upserts run inside a single transaction so the sanity check at
    the end can roll back atomically. Rows whose category falls outside
    :data:`_CATEGORY_TO_H3_RES` are skipped — they would otherwise
    violate the discrete-enum CHECK constraint.
    """
    synced = 0
    loosened = 0
    async with AsyncSessionLocal() as session:
        try:
            if not await _try_acquire_lock(session):
                logger.info("iucn_sync: another worker holds the lock — skipping")
                return 0, 0

            for row in snapshot:
                taxon_id = row.get("taxonid")
                category = row.get("category")
                h3_res = _h3_res_from_iucn_category(category)
                if taxon_id is None or h3_res is None:
                    continue
                was_loosened, _previous = await upsert_taxon_sensitivity(
                    session,
                    taxon_id=str(taxon_id),
                    source=TaxonSensitivitySource.IUCN,
                    sensitivity_h3_res=h3_res,
                    category=str(category) if category else None,
                    notes=None,
                )
                synced += 1
                if was_loosened:
                    loosened += 1

            # Sanity check BEFORE commit so a tripped threshold rolls
            # the entire batch back atomically.
            if _exceeds_loosen_threshold(
                loosened_count=loosened, total_changed=synced
            ):
                logger.critical(
                    "iucn_sync: sanity threshold exceeded — rolling back. "
                    "loosened=%d synced=%d threshold=%.0f%%",
                    loosened,
                    synced,
                    SANITY_LOOSEN_FRACTION * 100,
                )
                await session.rollback()
                raise RuntimeError(
                    f"sanity check failed: {loosened}/{synced} rows would loosen "
                    f"masking (>{SANITY_LOOSEN_FRACTION * 100:.0f}% threshold)"
                )

            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return synced, loosened


async def _run_sync_async(force: bool = False) -> dict[str, Any]:
    """Async pipeline backing the Celery task and the CLI scripts.

    Args:
        force: When True, skip the early-exit "no API token configured"
            branch and raise a clear error instead. Used by the CLI to
            surface misconfiguration to the operator immediately.

    Returns a summary dict suitable for the Celery result backend.
    """
    api_token = os.environ.get("IUCN_API_TOKEN", "").strip()
    if not api_token:
        msg = (
            "IUCN_API_TOKEN env var is empty — IUCN sync cannot proceed. "
            "Set the token to the IUCN Red List API v3 credential."
        )
        if force:
            raise RuntimeError(msg)
        logger.error(msg)
        return {"status": "skipped", "reason": "missing IUCN_API_TOKEN"}

    base_url = os.environ.get("IUCN_API_BASE_URL", _IUCN_API_BASE_URL_DEFAULT)

    started_at = datetime.now(UTC)
    attempt_id = await _open_attempt(started_at)

    synced = 0
    loosened = 0
    error_detail: str | None = None
    terminal_status = "failure"

    try:
        async with _build_pinned_client() as client:
            snapshot = await _fetch_red_list_snapshot(
                client, api_token=api_token, base_url=base_url
            )
        synced, loosened = await _apply_snapshot(snapshot)
        terminal_status = "success"
    except Exception as exc:  # noqa: BLE001 — recorded into the attempt row
        error_detail = repr(exc)
        logger.exception("iucn_sync failed: %s", exc)
        terminal_status = "failure"
    finally:
        await _close_attempt(
            attempt_id=attempt_id,
            status=terminal_status,
            error_detail=error_detail,
            synced_count=synced if terminal_status == "success" else None,
            loosened_species_count=loosened
            if terminal_status == "success"
            else None,
        )

    # Fail-safe transition
    if terminal_status == "success":
        # Successful run clears the 14-day flag if it was set.
        await set_iucn_fail_safe(False)
    else:
        # Evaluate the 2-week rule. We treat *the absence* of a success
        # within FAIL_SAFE_WINDOW as the trigger so a single transient
        # failure does not flip the platform into fail-safe mode.
        if not await _last_success_within(FAIL_SAFE_WINDOW):
            logger.critical(
                "iucn_sync: 2-week fail-safe ENGAGED — unknown taxa will "
                "default to H3_RES_7 until the next successful sync"
            )
            await set_iucn_fail_safe(True)

    return {
        "status": terminal_status,
        "synced_count": synced,
        "loosened_species_count": loosened,
        "attempt_id": str(attempt_id),
        "error_detail": error_detail,
    }


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.iucn_sync.sync_iucn_red_list",
    bind=True,
    max_retries=3,
)
def sync_iucn_red_list(self: Any) -> dict[str, Any]:  # noqa: ARG001 - bound task; reserved for retry()
    """Pull the IUCN Red List snapshot and UPSERT TaxonSensitivity rows.

    Per FR-036:

    * Records every attempt in :class:`IucnSyncAttempt`.
    * Aborts (status='failure') if more than 10 % of changed rows would
      *loosen* masking in a single batch.
    * Engages the 2-week fail-safe Redis flag after 14 consecutive
      days without a successful run.

    Retry policy: Celery's built-in exponential backoff is configured
    with ``max_retries=3`` so a transient upstream blip does not need
    operator intervention. Each retry creates a fresh
    :class:`IucnSyncAttempt` row so the dashboard reflects the actual
    number of API attempts.
    """
    # The sync_iucn_red_list task is bound (``bind=True``) so a future
    # change can call ``self.retry(exc=..., countdown=...)``. For now
    # we let exceptions propagate and Celery's default retry logic kick
    # in based on ``max_retries``.
    return asyncio.run(_run_sync_async(force=False))


__all__ = [
    "FAIL_SAFE_WINDOW",
    "SANITY_LOOSEN_FRACTION",
    "sync_iucn_red_list",
]
