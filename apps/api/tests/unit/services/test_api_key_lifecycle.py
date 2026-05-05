"""Unit tests for echoroo.services.api_key_lifecycle (A-4 Round 2).

Coverage targets:

* Round 1 Fix I-2 — completeness of ``API_KEY_WRITE_PERMISSIONS``.
  Adding a new mutate ``Permission`` enum entry without updating the
  catalogue would silently leave write scope on 180-day-old keys; the
  completeness test pins both the canonical Permission subset and the
  legacy ``<resource>:<verb>`` fixture subset so the regression is loud.
* Round 1 Fix Minor — direct unit coverage for
  :func:`effective_permissions_for_age` exact-day boundaries
  (179 / 180 / 200 / 270) plus the revoked-row and clock-skew (negative
  age) edge cases that the verifier-level tests previously only covered
  transitively.

These tests are pure and run without a DB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from echoroo.core.permissions import Permission
from echoroo.services.api_key_lifecycle import (
    API_KEY_WRITE_PERMISSIONS,
    effective_permissions_for_age,
    filter_to_read_only,
    is_write_scope,
)

# ---------------------------------------------------------------------------
# Fix R1-I2 — API_KEY_WRITE_PERMISSIONS completeness regression net.
# ---------------------------------------------------------------------------

# The canonical mutate subset is enumerated explicitly so a future PR
# that adds a new ``Permission`` enum value MUST update both this set
# and ``API_KEY_WRITE_PERMISSIONS``. The dual-update requirement is the
# safety net — silent drift would mean 180-day-old keys keep mutate
# scope.
EXPECTED_CANONICAL_WRITE: frozenset[str] = frozenset(
    {
        Permission.VOTE.value,
        Permission.COMMENT.value,
        Permission.CREATE_TAG.value,
        Permission.ANNOTATE.value,
        Permission.UPLOAD.value,
        Permission.MANAGE_SITE.value,
        Permission.MANAGE_DATASET.value,
        Permission.RUN_INFERENCE.value,
        Permission.TRAIN_MODEL.value,
        Permission.MANAGE_MEMBERS.value,
        Permission.MANAGE_TRUSTED.value,
        Permission.EDIT_PROJECT.value,
        Permission.MANAGE_LICENSE.value,
        Permission.DELETE_PROJECT.value,
        Permission.TRANSFER_OWNERSHIP.value,
        Permission.OVERRIDE_TAXON_SENSITIVITY.value,
        Permission.MANAGE_API_KEY.value,
        Permission.MANAGE_2FA.value,
    }
)

# Legacy ``<resource>:<verb>`` fixture strings inherited from the
# pre-Phase-15 API key fixtures and the contract suite. These remain in
# the catalogue verbatim so the policy still works against legacy
# granted_permissions arrays in production rows.
EXPECTED_LEGACY_WRITE: frozenset[str] = frozenset(
    {
        "recordings:write",
        "detections:write",
        "datasets:write",
        "projects:write",
        "models:write",
        "tags:write",
        "votes:write",
        "annotations:write",
        "uploads:write",
    }
)


def test_api_key_write_permissions_canonical_subset_matches_expected() -> None:
    """If a new mutate ``Permission`` is added, this test should fail
    until ``API_KEY_WRITE_PERMISSIONS`` is updated.

    Convention: canonical mutate ``Permission`` enum values that grant
    write/create/delete/manage access MUST be listed in
    ``API_KEY_WRITE_PERMISSIONS``. A read-only ``Permission`` MUST be
    excluded so 180-day-old keys can keep it.

    Adding a new ``Permission`` requires updating BOTH
    ``EXPECTED_CANONICAL_WRITE`` here AND ``API_KEY_WRITE_PERMISSIONS``
    in ``services/api_key_lifecycle.py`` — that dual update is the
    safety net.
    """
    permission_values = {e.value for e in Permission}
    canonical_in_set = {
        p for p in API_KEY_WRITE_PERMISSIONS if p in permission_values
    }
    assert canonical_in_set == EXPECTED_CANONICAL_WRITE, (
        f"API_KEY_WRITE_PERMISSIONS canonical subset mismatch.\n"
        f"Missing (in expected, not in catalogue): "
        f"{EXPECTED_CANONICAL_WRITE - canonical_in_set}\n"
        f"Extra (in catalogue, not in expected): "
        f"{canonical_in_set - EXPECTED_CANONICAL_WRITE}\n"
        f"Update both EXPECTED_CANONICAL_WRITE here and "
        f"API_KEY_WRITE_PERMISSIONS in services/api_key_lifecycle.py."
    )


#: Canonical read-only ``Permission`` enum values. Pinned explicitly so
#: that adding a new ``Permission`` to the enum forces a deliberate
#: classification decision (write vs read) — the partition test below
#: fails until the new value is added to either
#: :data:`EXPECTED_CANONICAL_WRITE` (and therefore to
#: :data:`API_KEY_WRITE_PERMISSIONS`) or this set.
#:
#: Without this dual-classification rule, a new mutate-shaped
#: ``Permission`` could ship with the catalogue update forgotten and
#: ``test_api_key_write_permissions_canonical_subset_matches_expected``
#: above would still pass — it only checks the subset that is *already*
#: in the catalogue, not whether the catalogue covers every write.
EXPECTED_CANONICAL_READ: frozenset[str] = frozenset(
    {
        # -- Project viewing (6) --
        Permission.VIEW_PROJECT_METADATA.value,
        Permission.VIEW_DATASET_LIST.value,
        Permission.VIEW_MEDIA.value,
        Permission.VIEW_DETECTION.value,
        Permission.VIEW_PRECISE_LOCATION.value,
        Permission.VIEW_AUDIT_LOG.value,
        # -- Search / output (4) --
        Permission.SEARCH_WITHIN_PROJECT.value,
        Permission.SEARCH_CROSS_PROJECT.value,
        Permission.DOWNLOAD.value,
        Permission.EXPORT.value,
    }
)


def test_permission_enum_fully_partitioned_into_write_or_read() -> None:
    """Every ``Permission`` enum value MUST be classified as either
    write (``EXPECTED_CANONICAL_WRITE``) or read
    (``EXPECTED_CANONICAL_READ``).

    When a new ``Permission`` is added to ``core/permissions.py``, this
    test fails until the new value is added to exactly one of the two
    expected sets:

    * If write: add to :data:`EXPECTED_CANONICAL_WRITE` AND to
      :data:`API_KEY_WRITE_PERMISSIONS` in
      ``services/api_key_lifecycle.py`` so 180-day-old API keys are
      stripped of it.
    * If read: add to :data:`EXPECTED_CANONICAL_READ` so 180-day-old
      API keys keep it.

    This forces an explicit decision on whether the new permission is
    API-key-degradable. The completeness test above only checks that
    permissions ALREADY in the catalogue match the expected write set —
    it cannot detect a new mutate ``Permission`` whose catalogue entry
    was forgotten. This partition test is the missing safety net.
    """
    all_permissions = {p.value for p in Permission}
    classified = EXPECTED_CANONICAL_WRITE | EXPECTED_CANONICAL_READ

    unclassified = all_permissions - classified
    over_classified = classified - all_permissions  # removed Permissions still classified?

    assert not unclassified, (
        f"Permission(s) not classified as write or read: {unclassified}.\n"
        f"For each unclassified Permission, add it to either:\n"
        f"  * EXPECTED_CANONICAL_WRITE (and to API_KEY_WRITE_PERMISSIONS "
        f"in services/api_key_lifecycle.py), or\n"
        f"  * EXPECTED_CANONICAL_READ (here in this test file).\n"
        f"This forces an explicit decision on whether the new permission "
        f"is API-key-degradable at the 180-day threshold."
    )
    assert not over_classified, (
        f"EXPECTED_CANONICAL_WRITE | EXPECTED_CANONICAL_READ contains "
        f"value(s) not in the Permission enum: {over_classified}.\n"
        f"Remove the obsolete classification(s) — the corresponding "
        f"Permission was likely deleted or renamed."
    )

    # Sanity: WRITE and READ are disjoint. A Permission must be one OR
    # the other, never both — otherwise the API key degrade policy is
    # ambiguous for that value.
    overlap = EXPECTED_CANONICAL_WRITE & EXPECTED_CANONICAL_READ
    assert not overlap, (
        f"A Permission must be classified as write OR read, not both: "
        f"{overlap}"
    )


def test_api_key_write_permissions_legacy_fixture_subset_is_stable() -> None:
    """Legacy ``<resource>:<verb>`` style scopes from pre-Phase-15
    API key fixtures are explicitly enumerated.

    Removing or renaming these requires coordinated migration of
    existing API key rows in production (legacy keys may still hold
    these strings in their ``granted_permissions`` array).
    """
    legacy_in_set = {p for p in API_KEY_WRITE_PERMISSIONS if ":" in p}
    assert legacy_in_set == EXPECTED_LEGACY_WRITE, (
        f"API_KEY_WRITE_PERMISSIONS legacy subset drift.\n"
        f"Missing: {EXPECTED_LEGACY_WRITE - legacy_in_set}\n"
        f"Extra: {legacy_in_set - EXPECTED_LEGACY_WRITE}"
    )


def test_api_key_write_permissions_partition_is_total() -> None:
    """Every entry in ``API_KEY_WRITE_PERMISSIONS`` belongs to exactly
    one of the canonical / legacy subsets — no orphan strings sneak in
    via untyped sources.
    """
    canonical = EXPECTED_CANONICAL_WRITE
    legacy = EXPECTED_LEGACY_WRITE
    assert (canonical | legacy) == API_KEY_WRITE_PERMISSIONS, (
        "API_KEY_WRITE_PERMISSIONS should be the disjoint union of the "
        "canonical Permission subset and the legacy fixture subset."
    )


def test_is_write_scope_recognises_canonical_and_legacy() -> None:
    """Sanity check that ``is_write_scope`` agrees with the catalogue."""
    for scope in API_KEY_WRITE_PERMISSIONS:
        assert is_write_scope(scope) is True


def test_is_write_scope_rejects_unknown_scope() -> None:
    """Unknown / future scope strings default to read-only (the safer
    side of the cliff for a degrade-only policy).
    """
    assert is_write_scope("future_scope_we_havent_invented_yet") is False


def test_is_write_scope_rejects_known_read_permissions() -> None:
    """Read-only ``Permission`` enum values MUST NOT be treated as
    write scopes — otherwise 180-day-old keys would lose read access
    they are meant to retain.
    """
    read_permissions = {
        Permission.VIEW_PROJECT_METADATA.value,
        Permission.VIEW_DATASET_LIST.value,
        Permission.VIEW_MEDIA.value,
        Permission.VIEW_DETECTION.value,
        Permission.VIEW_PRECISE_LOCATION.value,
        Permission.VIEW_AUDIT_LOG.value,
        Permission.SEARCH_WITHIN_PROJECT.value,
        Permission.SEARCH_CROSS_PROJECT.value,
        Permission.DOWNLOAD.value,
        Permission.EXPORT.value,
    }
    for scope in read_permissions:
        assert is_write_scope(scope) is False, (
            f"{scope!r} is read-only and MUST NOT be in "
            f"API_KEY_WRITE_PERMISSIONS"
        )


def test_filter_to_read_only_preserves_order_and_strips_writes() -> None:
    granted = (
        Permission.VIEW_DETECTION.value,
        Permission.VOTE.value,
        Permission.DOWNLOAD.value,
        Permission.UPLOAD.value,
    )
    assert filter_to_read_only(granted) == (
        Permission.VIEW_DETECTION.value,
        Permission.DOWNLOAD.value,
    )


# ---------------------------------------------------------------------------
# Fix R1-Minor — effective_permissions_for_age direct boundary tests.
# ---------------------------------------------------------------------------

_WRITE = "recordings:write"
_READ = "recordings:read"
_GRANTED: tuple[str, ...] = (_WRITE, _READ)


def _at(days_ago: int) -> datetime:
    """Build a UTC-aware datetime ``days_ago`` days before ``now``.

    Negative values are accepted so callers can simulate clock-skew
    (a ``created_at`` slightly in the future of the server).
    """
    return datetime.now(UTC) - timedelta(days=days_ago)


def test_age_below_180_returns_granted_unchanged() -> None:
    assert effective_permissions_for_age(
        granted=_GRANTED, created_at=_at(179), revoked_at=None
    ) == _GRANTED


def test_age_exactly_180_strips_write() -> None:
    """Boundary: age == 180 days MUST trigger the write strip.

    The implementation uses ``age >= timedelta(days=degrade_days)``, so
    exactly-at-threshold falls into the degraded window.
    """
    assert effective_permissions_for_age(
        granted=_GRANTED, created_at=_at(180), revoked_at=None
    ) == (_READ,)


def test_age_between_180_and_270_strips_write() -> None:
    assert effective_permissions_for_age(
        granted=_GRANTED, created_at=_at(200), revoked_at=None
    ) == (_READ,)


def test_age_just_below_270_still_in_degraded_window() -> None:
    """Boundary: age == 269 days MUST still return the read-only slice
    (we have not yet crossed the revoke threshold).
    """
    assert effective_permissions_for_age(
        granted=_GRANTED, created_at=_at(269), revoked_at=None
    ) == (_READ,)


def test_age_exactly_270_returns_none() -> None:
    """Boundary: age == 270 days MUST return ``None`` (revoked by age).

    The implementation uses ``age >= timedelta(days=revoke_days)``, so
    exactly-at-threshold is already revoked.
    """
    assert (
        effective_permissions_for_age(
            granted=_GRANTED, created_at=_at(270), revoked_at=None
        )
        is None
    )


def test_age_far_past_revoke_threshold_returns_none() -> None:
    assert (
        effective_permissions_for_age(
            granted=_GRANTED, created_at=_at(900), revoked_at=None
        )
        is None
    )


def test_revoked_at_set_returns_none_regardless_of_age() -> None:
    """A row with ``revoked_at`` set MUST short-circuit to ``None`` even
    if ``created_at`` would otherwise place it in the fresh window.
    """
    assert (
        effective_permissions_for_age(
            granted=_GRANTED, created_at=_at(10), revoked_at=_at(5)
        )
        is None
    )


def test_negative_age_treated_as_fresh() -> None:
    """Clock skew defence: a ``created_at`` in the future of ``now``
    yields a negative age. The function MUST treat this as fresh and
    return ``granted`` unchanged rather than erroneously triggering the
    revoke branch via signed-comparison wrap.
    """
    assert effective_permissions_for_age(
        granted=_GRANTED, created_at=_at(-1), revoked_at=None
    ) == _GRANTED


def test_naive_created_at_is_promoted_to_utc() -> None:
    """SQLAlchemy can hand back naive ``created_at`` from raw text rows
    on some PG / driver combos. The function MUST promote naive values
    to UTC rather than crash on the timezone-aware subtraction.
    """
    naive_180 = (datetime.now(UTC) - timedelta(days=180)).replace(tzinfo=None)
    assert effective_permissions_for_age(
        granted=_GRANTED, created_at=naive_180, revoked_at=None
    ) == (_READ,)


def test_now_override_makes_arithmetic_deterministic() -> None:
    """Tests pin ``now`` to make the age arithmetic deterministic — this
    test verifies that the override actually drives the policy and is
    not silently ignored.
    """
    fixed_now = datetime(2026, 5, 4, tzinfo=UTC)
    fresh_created = fixed_now - timedelta(days=10)
    assert effective_permissions_for_age(
        granted=_GRANTED,
        created_at=fresh_created,
        revoked_at=None,
        now=fixed_now,
    ) == _GRANTED

    aged_created = fixed_now - timedelta(days=181)
    assert effective_permissions_for_age(
        granted=_GRANTED,
        created_at=aged_created,
        revoked_at=None,
        now=fixed_now,
    ) == (_READ,)


def test_custom_thresholds_are_honoured() -> None:
    """Callers may override ``degrade_days`` / ``revoke_days`` (used by
    test fixtures and by the eager beat sweep when the policy curve is
    re-tuned). The override MUST drive the comparison rather than the
    hard-coded defaults.
    """
    # With degrade=30, a 31-day-old key is already degraded.
    assert effective_permissions_for_age(
        granted=_GRANTED,
        created_at=_at(31),
        revoked_at=None,
        degrade_days=30,
        revoke_days=60,
    ) == (_READ,)
    # With revoke=60, a 60-day-old key is already revoked.
    assert (
        effective_permissions_for_age(
            granted=_GRANTED,
            created_at=_at(60),
            revoked_at=None,
            degrade_days=30,
            revoke_days=60,
        )
        is None
    )


def test_empty_granted_returns_empty_tuple_for_fresh_key() -> None:
    """A fresh key whose ``granted_permissions`` array is empty MUST
    return an empty tuple, NOT ``None`` — the caller distinguishes the
    two cases (None == 401, empty == authenticated but no scopes).
    """
    assert (
        effective_permissions_for_age(
            granted=(), created_at=_at(10), revoked_at=None
        )
        == ()
    )


def test_empty_granted_for_aged_key_still_returns_empty_tuple() -> None:
    """A 200-day-old key with empty ``granted_permissions`` returns
    ``()`` (still authenticated, just no scopes) — the degrade filter
    has nothing to strip.
    """
    assert (
        effective_permissions_for_age(
            granted=(), created_at=_at(200), revoked_at=None
        )
        == ()
    )
