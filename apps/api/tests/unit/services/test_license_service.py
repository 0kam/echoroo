"""Unit tests for :class:`echoroo.services.license.LicenseService` (spec/012).

Covers the spec/012 surface added on top of the legacy CRUD service:

* ``list_public`` returns rows sorted by ``short_name`` ASC and surfaces
  an empty list when the master is empty (FR-001 / FR-002 / FR-017).
* ``delete_license`` runs the dependency pre-query and refuses with
  :class:`LicenseInUseError` BEFORE issuing the DELETE when either
  count > 0 (FR-006 / FR-012 / FR-015).
* The FK race window — pre-count returns ``(0, 0)`` but a concurrent
  INSERT lands a referencing row before the DELETE — re-runs the
  dependency count after catching :class:`IntegrityError` and raises
  :class:`LicenseInUseError` with the freshly-recounted values (no
  sentinel). Mirrors ``contracts/admin-licenses-delete.yaml``
  NOTE_race_condition.

The tests use AsyncMock to isolate the service from a live DB so the
suite stays in the ``unit`` tier (the testcontainers-backed coverage
of the same paths lives in ``tests/contract/test_admin_licenses_delete.py``).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from echoroo.models.project import ProjectLicenseHistory
from echoroo.services.license import LicenseInUseError, LicenseService
from echoroo.services.license_service import (
    change_license,
    list_license_history,
    record_initial_license,
    resolve_license_id_for_short_name,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(repo: AsyncMock, db: AsyncMock | None = None) -> LicenseService:
    """Build a :class:`LicenseService` with a mocked repo + session."""
    service = LicenseService.__new__(LicenseService)
    service.db = db if db is not None else AsyncMock()
    service.repo = repo
    return service


def _license_row(*, license_id: str, short_name: str, name: str) -> SimpleNamespace:
    """Return an object Pydantic ``model_validate`` can read via from_attributes."""
    return SimpleNamespace(
        id=license_id,
        short_name=short_name,
        name=name,
        url=None,
        description=None,
    )


def _execute_result(value: object) -> MagicMock:
    """Return a minimal SQLAlchemy Result-like object for scalar lookups."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    return result


def _scalars_result(values: list[object]) -> MagicMock:
    """Return a minimal Result-like object for scalars().all() lookups."""
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=values)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    return result


# ---------------------------------------------------------------------------
# list_public
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListPublic:
    """``LicenseService.list_public`` — FR-001 / FR-002 / FR-017."""

    async def test_returns_sorted_items(self) -> None:
        """``list_all`` returns ASC-sorted rows; ``list_public`` propagates them."""
        repo = AsyncMock()
        repo.list_all.return_value = [
            _license_row(license_id="cc0", short_name="CC0", name="CC Zero"),
            _license_row(license_id="cc-by", short_name="CC-BY", name="CC Attribution"),
        ]
        service = _make_service(repo)

        response = await service.list_public()

        assert [row.id for row in response.items] == ["cc0", "cc-by"]
        assert [row.short_name for row in response.items] == ["CC0", "CC-BY"]
        # Public shape MUST NOT carry timestamps (the schema strips them).
        for row in response.items:
            assert not hasattr(row, "created_at"), row

    async def test_empty_master_returns_empty_list(self) -> None:
        """Empty repo → empty ``items`` list (FR-017 actionable empty state)."""
        repo = AsyncMock()
        repo.list_all.return_value = []
        service = _make_service(repo)

        response = await service.list_public()

        assert response.items == []


# ---------------------------------------------------------------------------
# project license-history helpers in echoroo.services.license_service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestResolveProjectLicenseId:
    """Coverage-gate branches for ``resolve_license_id_for_short_name``."""

    async def test_blank_short_name_raises_before_db_hit(self) -> None:
        session = AsyncMock()

        with pytest.raises(ValueError, match="Project license short_name is required"):
            await resolve_license_id_for_short_name(session, "   ")

        session.execute.assert_not_awaited()

    async def test_unknown_short_name_raises_value_error(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_execute_result(None))

        with pytest.raises(ValueError, match="Unknown project license short_name: MIT"):
            await resolve_license_id_for_short_name(session, "MIT")

        session.execute.assert_awaited_once()

    async def test_known_short_name_returns_license_id(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_execute_result("cc-by"))

        license_id = await resolve_license_id_for_short_name(session, "CC-BY")

        assert license_id == "cc-by"


@pytest.mark.asyncio
class TestChangeProjectLicenseValidation:
    """Coverage-gate validation branches for ``change_license``."""

    async def test_none_new_license_raises_value_error(self) -> None:
        session = AsyncMock()
        project = SimpleNamespace(license="CC-BY", license_id="cc-by")
        session.execute = AsyncMock(return_value=_execute_result(project))

        with pytest.raises(ValueError, match="requires a new license"):
            await change_license(session, uuid4(), None, uuid4())

    async def test_unknown_new_license_raises_fr085_http_exception(self) -> None:
        session = AsyncMock()
        project = SimpleNamespace(license="CC-BY", license_id="cc-by")
        session.execute = AsyncMock(
            side_effect=[
                _execute_result(project),
                _execute_result(None),
            ]
        )

        with pytest.raises(HTTPException) as exc_info:
            await change_license(session, uuid4(), "MIT", uuid4())

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == {
            "error": "ERR_LICENSE_REQUIRED",
            "message": "Project license is required (FR-085)",
        }

    async def test_success_updates_project_and_appends_history(self) -> None:
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.refresh = AsyncMock()
        project = SimpleNamespace(license="CC-BY", license_id="cc-by")
        session.execute = AsyncMock(
            side_effect=[
                _execute_result(project),
                _execute_result("cc-by-sa"),
            ]
        )
        project_id = uuid4()
        actor_id = uuid4()

        row = await change_license(session, project_id, "CC-BY-SA", actor_id)

        assert project.license_id == "cc-by-sa"
        assert row.project_id == project_id
        assert row.old_license == "CC-BY"
        assert row.new_license == "CC-BY-SA"
        assert row.changed_by_id == actor_id
        session.add.assert_called_once_with(row)
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(project, ["license_record"])


@pytest.mark.asyncio
class TestProjectLicenseHistoryHelpers:
    """Coverage-gate branches for history creation and listing."""

    async def test_record_initial_license_accepts_string_input(self) -> None:
        session = AsyncMock()
        session.add = MagicMock()
        project_id = uuid4()
        actor_id = uuid4()

        row = await record_initial_license(session, project_id, "CC0", actor_id)

        assert isinstance(row, ProjectLicenseHistory)
        assert row.project_id == project_id
        assert row.old_license is None
        assert row.new_license == "CC0"
        assert row.changed_by_id == actor_id
        session.add.assert_called_once_with(row)

    async def test_list_license_history_returns_scalars_as_list(self) -> None:
        session = AsyncMock()
        rows = [
            SimpleNamespace(new_license="CC0"),
            SimpleNamespace(new_license="CC-BY"),
        ]
        session.execute = AsyncMock(return_value=_scalars_result(rows))

        result = await list_license_history(session, uuid4())

        assert result == rows
        assert isinstance(result, list)
        session.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# delete_license — happy refusal path (T043)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDeleteLicenseRefusesWhenInUse:
    """``LicenseService.delete_license`` refuses BEFORE issuing the DELETE."""

    async def test_project_only_dependency_raises_without_delete(self) -> None:
        repo = AsyncMock()
        repo.get_by_id.return_value = _license_row(
            license_id="cc-by", short_name="CC-BY", name="CC Attribution"
        )
        repo.count_dependents.return_value = (3, 0)
        # ``repo.delete`` MUST NOT be invoked — assert via call_count below.
        repo.delete = AsyncMock()
        service = _make_service(repo)

        with pytest.raises(LicenseInUseError) as exc_info:
            await service.delete_license("cc-by")

        assert exc_info.value.short_name == "CC-BY"
        assert exc_info.value.project_count == 3
        assert exc_info.value.dataset_count == 0
        repo.delete.assert_not_awaited()

    async def test_dataset_only_dependency_raises_without_delete(self) -> None:
        repo = AsyncMock()
        repo.get_by_id.return_value = _license_row(
            license_id="cc0", short_name="CC0", name="CC Zero"
        )
        repo.count_dependents.return_value = (0, 5)
        repo.delete = AsyncMock()
        service = _make_service(repo)

        with pytest.raises(LicenseInUseError) as exc_info:
            await service.delete_license("cc0")

        assert exc_info.value.short_name == "CC0"
        assert exc_info.value.project_count == 0
        assert exc_info.value.dataset_count == 5
        repo.delete.assert_not_awaited()

    async def test_both_dependencies_raises_with_both_counts(self) -> None:
        repo = AsyncMock()
        repo.get_by_id.return_value = _license_row(
            license_id="cc-by-nc", short_name="CC-BY-NC", name="CC NonCommercial"
        )
        repo.count_dependents.return_value = (2, 7)
        repo.delete = AsyncMock()
        service = _make_service(repo)

        with pytest.raises(LicenseInUseError) as exc_info:
            await service.delete_license("cc-by-nc")

        assert exc_info.value.short_name == "CC-BY-NC"
        assert exc_info.value.project_count == 2
        assert exc_info.value.dataset_count == 7
        repo.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# delete_license — 404 + happy success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDeleteLicenseSuccessAnd404:
    async def test_unknown_id_raises_404(self) -> None:
        repo = AsyncMock()
        repo.get_by_id.return_value = None
        repo.count_dependents = AsyncMock()
        repo.delete = AsyncMock()
        service = _make_service(repo)

        with pytest.raises(HTTPException) as exc_info:
            await service.delete_license("nope")

        assert exc_info.value.status_code == 404
        repo.count_dependents.assert_not_awaited()
        repo.delete.assert_not_awaited()

    async def test_no_dependents_deletes_and_commits(self) -> None:
        db = AsyncMock()
        repo = AsyncMock()
        repo.get_by_id.return_value = _license_row(
            license_id="cc-by", short_name="CC-BY", name="CC Attribution"
        )
        repo.count_dependents.return_value = (0, 0)
        repo.delete.return_value = True
        service = _make_service(repo, db=db)

        await service.delete_license("cc-by")

        repo.delete.assert_awaited_once_with("cc-by")
        db.commit.assert_awaited()


# ---------------------------------------------------------------------------
# delete_license — FK race recovery (T042)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDeleteLicenseFkRaceFallback:
    """Pre-count returns (0,0) but DELETE fires FK violation → re-count.

    The contract NOTE_race_condition in ``contracts/admin-licenses-delete.yaml``
    requires the 409 envelope returned in this branch to be structurally
    identical to the pre-query refusal envelope — no sentinel value. We
    assert the re-count is awaited and the LicenseInUseError carries the
    post-race counts (not the pre-count zeros).
    """

    async def test_race_fallback_recounts_and_raises(self) -> None:
        db = AsyncMock()
        repo = AsyncMock()
        repo.get_by_id.return_value = _license_row(
            license_id="cc-by", short_name="CC-BY", name="CC Attribution"
        )
        # First call returns (0, 0) → service proceeds to DELETE.
        # Second call (after IntegrityError) returns the post-race counts.
        repo.count_dependents.side_effect = [(0, 0), (1, 0)]
        repo.delete.side_effect = IntegrityError(
            statement="DELETE FROM licenses WHERE id=$1",
            params=("cc-by",),
            orig=Exception("FK violation: ON DELETE RESTRICT"),
        )
        service = _make_service(repo, db=db)

        with pytest.raises(LicenseInUseError) as exc_info:
            await service.delete_license("cc-by")

        # Post-race counts surface to the API layer.
        assert exc_info.value.short_name == "CC-BY"
        assert exc_info.value.project_count == 1
        assert exc_info.value.dataset_count == 0
        # The pre-count + re-count are exactly two count_dependents calls.
        assert repo.count_dependents.await_count == 2
        # Rollback was issued before the re-count so the FK violation
        # does not poison the surrounding transaction.
        db.rollback.assert_awaited()

    async def test_race_fallback_handles_dataset_inserts(self) -> None:
        """Concurrent INSERT lands in datasets — counts reflect that side."""
        db = AsyncMock()
        repo = AsyncMock()
        repo.get_by_id.return_value = _license_row(
            license_id="cc0", short_name="CC0", name="CC Zero"
        )
        repo.count_dependents.side_effect = [(0, 0), (0, 4)]
        repo.delete.side_effect = IntegrityError(
            statement="DELETE FROM licenses WHERE id=$1",
            params=("cc0",),
            orig=Exception("FK violation: ON DELETE RESTRICT"),
        )
        service = _make_service(repo, db=db)

        with pytest.raises(LicenseInUseError) as exc_info:
            await service.delete_license("cc0")

        assert exc_info.value.project_count == 0
        assert exc_info.value.dataset_count == 4
