"""Round 1 review regression tests (Phase 11 Backend).

Covers the behavioural promises documented in:

* M2 — IUCN fail-safe is fail-CLOSED when both Redis and DB are unreachable.
* M4 — :func:`_close_approval_request` aborts the surrounding TX on a 0-row
  UPDATE so the override status mutation cannot land without an audit
  ticket (FR-111).

The C1 / C2 / C3 fixes are covered by the existing
``tests/unit/services/test_auto_obscure.py`` suite plus the
``tests/integration/test_auto_obscure_integration.py`` end-to-end suite —
they are not duplicated here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from echoroo.services.superuser_approval_service import (
    ApprovalRequestCloseError,
    _close_approval_request,
)
from echoroo.services.taxon_sensitivity_service import is_iucn_fail_safe_active

# ---------------------------------------------------------------------------
# M2: IUCN fail-safe is fail-closed
# ---------------------------------------------------------------------------


class TestIucnFailSafeFailClosed:
    """Round 1 review M2 (2026-04-28): Redis exception MUST not silently
    return False — that would coarsen unknown taxa back to H3_RES_9 (open)
    while the upstream IUCN sync is down.
    """

    @pytest.mark.asyncio
    async def test_redis_failure_falls_back_to_db_no_recent_success(self) -> None:
        """Redis raises; DB has no successful row in the last 14 days → True."""
        # Patch Redis to raise. DB succeeds and returns 0 rows.
        async def _raising_redis():  # type: ignore[no-untyped-def]
            raise RuntimeError("redis down")

        # Build a fake AsyncSessionLocal that returns count=0.
        class _FakeResult:
            def scalar_one(self) -> int:
                return 0

        class _FakeSession:
            async def execute(self, _stmt):  # type: ignore[no-untyped-def]
                return _FakeResult()

            async def __aenter__(self):  # type: ignore[no-untyped-def]
                return self

            async def __aexit__(self, *args):  # type: ignore[no-untyped-def]
                return None

        with (
            patch(
                "echoroo.services.taxon_sensitivity_service.get_redis_connection",
                side_effect=_raising_redis,
            ),
            patch(
                "echoroo.core.database.AsyncSessionLocal",
                return_value=_FakeSession(),
            ),
        ):
            result = await is_iucn_fail_safe_active()
        assert result is True, (
            "When Redis is down and the DB shows no recent IUCN sync success, "
            "fail-safe must activate (return True) so unknown taxa default to "
            "H3_RES_7 (M2 fail-closed contract)."
        )

    @pytest.mark.asyncio
    async def test_redis_failure_falls_back_to_db_recent_success_returns_false(
        self,
    ) -> None:
        """Redis raises; DB has a successful row in last 14 days → False."""
        async def _raising_redis():  # type: ignore[no-untyped-def]
            raise RuntimeError("redis down")

        class _FakeResult:
            def scalar_one(self) -> int:
                return 1  # one recent success

        class _FakeSession:
            async def execute(self, _stmt):  # type: ignore[no-untyped-def]
                return _FakeResult()

            async def __aenter__(self):  # type: ignore[no-untyped-def]
                return self

            async def __aexit__(self, *args):  # type: ignore[no-untyped-def]
                return None

        with (
            patch(
                "echoroo.services.taxon_sensitivity_service.get_redis_connection",
                side_effect=_raising_redis,
            ),
            patch(
                "echoroo.core.database.AsyncSessionLocal",
                return_value=_FakeSession(),
            ),
        ):
            result = await is_iucn_fail_safe_active()
        assert result is False, (
            "Recent IUCN sync success → fail-safe inactive even when Redis "
            "is unreachable (the DB is the source of truth)."
        )

    @pytest.mark.asyncio
    async def test_redis_and_db_both_fail_returns_true_fail_closed(self) -> None:
        """Both Redis and DB fail → True (fail-closed)."""
        async def _raising_redis():  # type: ignore[no-untyped-def]
            raise RuntimeError("redis down")

        class _RaisingSession:
            async def execute(self, _stmt):  # type: ignore[no-untyped-def]
                raise RuntimeError("db down")

            async def __aenter__(self):  # type: ignore[no-untyped-def]
                return self

            async def __aexit__(self, *args):  # type: ignore[no-untyped-def]
                return None

        with (
            patch(
                "echoroo.services.taxon_sensitivity_service.get_redis_connection",
                side_effect=_raising_redis,
            ),
            patch(
                "echoroo.core.database.AsyncSessionLocal",
                return_value=_RaisingSession(),
            ),
        ):
            result = await is_iucn_fail_safe_active()
        assert result is True, (
            "When both the Redis cache and the DB are unreachable, fail-safe "
            "MUST activate (M2 fail-closed contract). Returning False would "
            "silently expose unknown taxa at H3_RES_9 during an outage."
        )


# ---------------------------------------------------------------------------
# M4: _close_approval_request aborts on 0-row UPDATE
# ---------------------------------------------------------------------------


class TestCloseApprovalRequestZeroRowAbort:
    """Round 1 review M4: a 0-row close MUST raise so the override status
    mutation rolls back atomically. Previously the helper only logged a
    warning and proceeded, which let approve_taxon_override / reject_…
    advance the override state without leaving an audit ticket (FR-111).
    """

    @pytest.mark.asyncio
    async def test_zero_row_update_raises_approval_close_error(self) -> None:
        """0-row UPDATE → ApprovalRequestCloseError (callers TX should abort)."""

        class _ZeroRowResult:
            rowcount = 0

        class _FakeSession:
            async def execute(self, _stmt, _params):  # type: ignore[no-untyped-def]
                return _ZeroRowResult()

        with pytest.raises(ApprovalRequestCloseError) as exc_info:
            await _close_approval_request(
                _FakeSession(),  # type: ignore[arg-type]
                override_id=uuid4(),
                terminal_status="approved",
                approver_superuser_id=uuid4(),
                rejected_reason=None,
                now=datetime.now(UTC),
            )
        assert "no pending superuser_approval_requests row" in str(exc_info.value), (
            "Error message should explain that no matching pending row was "
            "found, so an operator can debug the stale state."
        )

    @pytest.mark.asyncio
    async def test_one_row_update_does_not_raise(self) -> None:
        """rowcount=1 → silent success (the happy path)."""

        class _OneRowResult:
            rowcount = 1

        class _FakeSession:
            async def execute(self, _stmt, _params):  # type: ignore[no-untyped-def]
                return _OneRowResult()

        # Should NOT raise.
        await _close_approval_request(
            _FakeSession(),  # type: ignore[arg-type]
            override_id=uuid4(),
            terminal_status="rejected",
            approver_superuser_id=uuid4(),
            rejected_reason="test reject reason",
            now=datetime.now(UTC),
        )


# ---------------------------------------------------------------------------
# C2 / C3: lightweight smoke tests so the rename / removal is exercised here
# too (deeper coverage lives in test_auto_obscure.py + test_no_raw_coordinates.py)
# ---------------------------------------------------------------------------


class TestSiteDetailResponseFieldRemoval:
    """Round 1 review C3: SiteDetailResponse must NOT carry latitude /
    longitude / coordinate_uncertainty fields.
    """

    def test_schema_has_no_latitude_field(self) -> None:
        from echoroo.schemas.site import SiteDetailResponse

        fields = SiteDetailResponse.model_fields
        assert "latitude" not in fields, (
            "SiteDetailResponse.latitude was removed in Round 1 review C3 "
            "(FR-030). Re-adding it would re-introduce the documented privacy "
            "regression."
        )
        assert "longitude" not in fields
        assert "coordinate_uncertainty" not in fields

    def test_schema_still_has_h3_index(self) -> None:
        from echoroo.schemas.site import SiteDetailResponse

        fields = SiteDetailResponse.model_fields
        # Inherited from SiteResponse — the canonical anti-precision contract.
        # Phase 13 P4 / T807 (2026-04-28): the field was renamed to the
        # canonical ``h3_index_member`` to match ORM column + spec data-model
        # §3.10. The legacy ``h3_index`` name is no longer present (full
        # rename, no facade).
        assert "h3_index_member" in fields
        assert "h3_index" not in fields


class TestComputeEffectiveResolutionUsesSensitivityH3Res:
    """Round 1 review C2: compute_effective_resolution reads
    ``override.sensitivity_h3_res`` (real ORM column), not ``override.resolution``
    (legacy doc-drift name). A regression here would silently drop every
    project taxon override.
    """

    def test_override_with_sensitivity_h3_res_attr_is_consumed(self) -> None:
        from echoroo.core.permissions import (
            H3_RES_2,
            H3_RES_9,
            ProjectVisibility,
            compute_effective_resolution,
        )
        from echoroo.models.enums import (
            TaxonOverrideApprovalStatus,
            TaxonOverrideDirection,
        )

        project_id = uuid4()
        taxon_id = "test-taxon-c2"
        project = SimpleNamespace(
            id=project_id,
            visibility=ProjectVisibility.PUBLIC,
            restricted_config={},
        )
        resource = SimpleNamespace(taxon_id=taxon_id, h3_index_member_resolution=15)
        override = SimpleNamespace(
            project_id=project_id,
            taxon_id=taxon_id,
            sensitivity_h3_res=H3_RES_2,  # ORM column name
            direction=TaxonOverrideDirection.STRICTER,
            approval_status=TaxonOverrideApprovalStatus.APPLIED,
        )

        result = compute_effective_resolution(
            resource=resource,
            role="Guest",
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map={taxon_id: H3_RES_9},
            override_map={(project_id, taxon_id): override},
        )
        # min(9, 2) = 2 then HIDDEN clamp returns 2.
        assert result == H3_RES_2, (
            f"Stricter override (sensitivity_h3_res=H3_RES_2) must reduce the "
            f"effective resolution to H3_RES_2. Got {result}. The C2 fix "
            f"renamed the attribute lookup from .resolution to "
            f".sensitivity_h3_res — a regression here re-breaks every override."
        )

    def test_override_with_only_legacy_resolution_attr_is_ignored(self) -> None:
        """A stub that ONLY exposes the old ``resolution`` attribute is
        intentionally ignored — we want the test stub helper and the real
        ORM to converge on the same column name.
        """
        from echoroo.core.permissions import (
            H3_RES_5,
            H3_RES_9,
            ProjectVisibility,
            compute_effective_resolution,
        )
        from echoroo.models.enums import (
            TaxonOverrideApprovalStatus,
            TaxonOverrideDirection,
        )

        project_id = uuid4()
        taxon_id = "legacy-taxon"
        project = SimpleNamespace(
            id=project_id,
            visibility=ProjectVisibility.PUBLIC,
            restricted_config={},
        )
        resource = SimpleNamespace(taxon_id=taxon_id, h3_index_member_resolution=15)
        # Only set the legacy ``resolution`` attribute.
        override = SimpleNamespace(
            project_id=project_id,
            taxon_id=taxon_id,
            resolution=H3_RES_5,  # legacy name — should be ignored
            direction=TaxonOverrideDirection.STRICTER,
            approval_status=TaxonOverrideApprovalStatus.APPLIED,
        )

        result = compute_effective_resolution(
            resource=resource,
            role="Guest",
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map={taxon_id: H3_RES_9},
            override_map={(project_id, taxon_id): override},
        )
        # Override is silently ignored (override_res is None), so the
        # effective_global stays at H3_RES_9 — Public ceiling = 9 → 9.
        assert result == H3_RES_9, (
            "An override stub that only exposes the legacy .resolution "
            "attribute must NOT be applied. compute_effective_resolution "
            "reads .sensitivity_h3_res — drift between code and ORM here "
            "is the very bug C2 was filed against."
        )
