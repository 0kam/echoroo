"""Email canonicalisation + keyed-hash helpers (FR-054, FR-055, FR-091b).

Email matching (FR-054):

* The receiver's email is matched against the invitation's stored
  ``email_hash`` using NFKC + casefold on both sides. Mismatch → 403.
* The check applies to both ``current_user.email`` (primary) and any
  authenticated secondary email present on the principal (a future
  feature; today only the primary is consulted).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import unicodedata

from echoroo.models.project import ProjectInvitation

logger = logging.getLogger(__name__)


def canonicalize_email(email: str) -> str:
    """Return the FR-054 / FR-055 canonical form of ``email``.

    Centralised so the legacy Python-HMAC path
    (:func:`hash_email`) and the KMS-backed path
    (:func:`hash_email_dual`) can never disagree on canonicalisation.

    spec/011 NFR-011-003 / FR-011-106 — the public name was added in
    Step 7 (US2 existing-user accept branch) so the auth resolver and
    the accept handlers can compare the authenticated caller's email
    against the invitation's bound email using exactly the same byte
    sequence that the HMAC / KMS pipelines see. The private alias
    ``_canonical_email`` is retained for backward compatibility with
    historical callers (workers, tests).
    """
    return unicodedata.normalize("NFKC", email).strip().casefold()


# Backwards-compatible private alias preserved for historical callers
# (``workers/pii_hash_backfill.py``, security tests). New code MUST use
# :func:`canonicalize_email`.
_canonical_email = canonicalize_email


def hash_email(email: str, *, hmac_secret: str) -> str:
    """Return the canonical ``email_hash`` value.

    The hash is keyed (HMAC-SHA-256) so an attacker who dumps the table
    cannot derive emails by precomputing rainbow tables. The ``email``
    is NFKC + casefolded first so two visually-identical addresses
    collide (FR-054 / FR-055).

    Legacy path (Phase 17 backlog A-2): this helper computes the
    historical ``web_session_secret`` Python-HMAC value persisted in
    the ``email_hash`` column. New rows ALSO populate
    ``email_hash_v2`` via :func:`hash_email_dual`; lookups try the
    KMS-backed v2/v1 path first and fall back to this helper for
    pre-A-2 rows. The signature is intentionally preserved so older
    tests that pass ``hmac_secret=...`` keep working.
    """
    canonical = _canonical_email(email).encode("utf-8")
    return hmac.new(hmac_secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _email_matches_invitation(
    current_user_email: str,
    invitation: ProjectInvitation,
    *,
    hmac_secret: str,
) -> bool:
    """Email match against an invitation row (FR-054).

    Phase 17 backlog A-2 (FR-091b): rows created after migration 0016
    carry a KMS-keyed ``email_hash_v2`` alongside the legacy
    ``email_hash``. We evaluate BOTH paths unconditionally and OR the
    results so the function's runtime profile does not leak which
    branch produced the match (Round 2 R1-I3).

      * KMS path — :func:`echoroo.core.kms.verify_pii_hash` (which
        itself tries v2 then v1 of the rotated CMK). Skipped only
        when ``email_hash_v2`` is NULL (pre-A-2 row); KMS errors are
        swallowed to keep availability over a marginal observability
        win, and the warning log there records the unavailability.
      * Legacy path — Python HMAC against ``email_hash``. Always
        evaluated so the wallclock cost is independent of whether
        the v2 sibling exists.

    Both per-path comparisons use :func:`hmac.compare_digest`. The
    OR-combine is a plain Python ``or`` — given that both operands
    have already been computed, the short-circuit only saves an
    integer test, not a KMS round-trip, so the timing channel here
    is bounded by the small constant-time compare itself.
    """
    # Local import to avoid a heavy KMS module load at service import.
    from echoroo.core.kms import verify_pii_hash

    canonical = _canonical_email(current_user_email)

    matched_kms = False
    if invitation.email_hash_v2:
        try:
            matched_kms = verify_pii_hash(canonical, invitation.email_hash_v2)
        except Exception:  # noqa: BLE001 — KMS unavailable → legacy fallback
            logger.warning(
                "verify_pii_hash failed; relying on legacy hash compare",
                exc_info=True,
            )
            matched_kms = False

    expected_legacy = hash_email(current_user_email, hmac_secret=hmac_secret)
    matched_legacy = hmac.compare_digest(expected_legacy, invitation.email_hash)

    return matched_kms or matched_legacy


def hash_email_dual(email: str) -> dict[str, str]:
    """Return KMS-backed dual-write hashes for ``email`` (FR-091b).

    Single-key mode → ``{"v1": <hex>}``. Rotation in progress →
    ``{"v1": <hex>, "v2": <hex>}``. The canonicalisation matches
    :func:`hash_email` byte-for-byte so the two paths are
    interchangeable for the purposes of the FR-054 email-match
    check (modulo the underlying key, of course).

    The KMS round-trip happens here rather than at column-fill time
    so the writer in :func:`create_invitation` can emit a single
    paired set of inserts.
    """
    # Local import — avoids a circular import at module load time
    # (``echoroo.core.kms`` is otherwise import-light).
    from echoroo.core.kms import compute_pii_hash_dual

    return compute_pii_hash_dual(_canonical_email(email))
