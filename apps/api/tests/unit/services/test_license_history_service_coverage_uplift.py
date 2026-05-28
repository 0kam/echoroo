"""Unit tests for ``echoroo.services.license_service`` (spec/012 coverage uplift).

The :mod:`echoroo.services.license_service` module is the
*project-level* license-history service (FR-085 / FR-087) — not to be
confused with the unrelated :mod:`echoroo.services.license` module which
hosts the admin license-master CRUD ``LicenseService`` class. The two
share a base name purely for historical reasons; see the module
docstrings for the actual responsibilities.

The contract-level suite (``tests/contract/test_license_required.py``)
exercises the happy paths through real ASGI requests, but it does not
fully cover the *defensive* branches inside the service helpers (empty
short name, unknown short name, ``None`` license at PATCH, project not
found, enum-vs-str input matrix). Those branches are reached only by
direct service-level invocation — exactly the surface this file covers
so ``check_coverage_threshold`` keeps ``license_service.py`` >= 85%.

The tests use ``unittest.mock.AsyncMock`` / ``MagicMock`` to isolate the
helpers from a real Postgres engine so the suite stays in the ``unit``
tier (no testcontainers, no DB fixtures).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.enums import ProjectLicense
from echoroo.models.project import ProjectLicenseHistory
from echoroo.services.license_service import (
    _license_short_name,
    change_license,
    license_required_http_exception,
    list_license_history,
    record_initial_license,
    resolve_license_id_for_short_name,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _execute_result(value: object) -> MagicMock:
    """Build a ``Result``-like object whose ``scalar_one_or_none`` returns value.

    The service code consumes ``await session.execute(...)`` and then calls
    ``.scalar_one_or_none()`` synchronously on the returned ``Result``, so
    only the result wrapper needs to be sync — ``execute`` itself stays
    awaitable via ``AsyncMock(return_value=...)``.
    """
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    return result


def _scalars_result(values: list[object]) -> MagicMock:
    """Build a ``Result``-like object for the ``scalars().all()`` chain.

    ``list_license_history`` calls ``result.scalars().all()`` (both sync
    methods on the underlying ``Result``), so the entire chain stays
    synchronous after the ``await session.execute(...)`` resolves.
    """
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=values)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    return result


def _project_stub(*, license: str = "CC-BY") -> MagicMock:
    """Return a minimal stand-in for :class:`echoroo.models.project.Project`.

    Only the attributes the service touches are populated — ``license``
    (read), ``license_id`` (assigned). ``MagicMock`` is fine here because
    the service never inspects the SQLAlchemy mapping metadata.
    """
    project = MagicMock()
    project.license = license
    project.license_id = None
    return project


# ---------------------------------------------------------------------------
# _license_short_name — enum vs string input matrix
# ---------------------------------------------------------------------------


class TestLicenseShortName:
    """``_license_short_name`` accepts both enum and string inputs."""

    def test_enum_value_is_returned_verbatim(self) -> None:
        """``ProjectLicense`` member → its ``.value`` literal."""
        assert _license_short_name(ProjectLicense.CC_BY) == "CC-BY"
        assert _license_short_name(ProjectLicense.CC0) == "CC0"
        assert _license_short_name(ProjectLicense.CC_BY_NC) == "CC-BY-NC"
        assert _license_short_name(ProjectLicense.CC_BY_SA) == "CC-BY-SA"

    def test_string_input_is_stripped(self) -> None:
        """Whitespace around a literal short name is stripped (defensive)."""
        assert _license_short_name("  CC-BY  ") == "CC-BY"
        assert _license_short_name("CC-BY-SA") == "CC-BY-SA"

    def test_empty_string_returns_empty(self) -> None:
        """Empty / whitespace-only string stays empty — the caller is
        expected to detect and raise (e.g. ``resolve_license_id_for_short_name``).
        """
        assert _license_short_name("") == ""
        assert _license_short_name("   ") == ""


# ---------------------------------------------------------------------------
# license_required_http_exception — FR-085 envelope shape
# ---------------------------------------------------------------------------


class TestLicenseRequiredHttpException:
    """The 422 envelope mirrors ``ERR_LICENSE_REQUIRED`` (FR-085)."""

    def test_envelope_shape(self) -> None:
        exc = license_required_http_exception()
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 422
        assert exc.detail == {
            "error": "ERR_LICENSE_REQUIRED",
            "message": "Project license is required (FR-085)",
        }


# ---------------------------------------------------------------------------
# resolve_license_id_for_short_name — defensive branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestResolveLicenseIdForShortName:
    """Empty / unknown / known input matrix for the resolver helper."""

    async def test_empty_short_name_raises_value_error(self) -> None:
        """Empty short name short-circuits before any DB hit."""
        session = AsyncMock(spec=AsyncSession)
        with pytest.raises(ValueError, match="Project license short_name is required"):
            await resolve_license_id_for_short_name(session, "")
        # No execute call — the guard runs before the query.
        session.execute.assert_not_awaited()

    async def test_whitespace_only_short_name_raises_value_error(self) -> None:
        """``"   "`` is stripped to ``""`` and the same guard fires."""
        session = AsyncMock(spec=AsyncSession)
        with pytest.raises(ValueError, match="Project license short_name is required"):
            await resolve_license_id_for_short_name(session, "   ")
        session.execute.assert_not_awaited()

    async def test_unknown_short_name_raises_value_error_with_label(self) -> None:
        """No matching license row → ``ValueError`` mentioning the short name."""
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(return_value=_execute_result(None))

        with pytest.raises(ValueError, match="Unknown project license short_name: MIT"):
            await resolve_license_id_for_short_name(session, "MIT")
        session.execute.assert_awaited_once()

    async def test_known_short_name_returns_license_id(self) -> None:
        """Repo hit → resolved canonical ``licenses.id``."""
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(return_value=_execute_result("cc-by"))

        license_id = await resolve_license_id_for_short_name(session, "CC-BY")
        assert license_id == "cc-by"

    async def test_accepts_project_license_enum_input(self) -> None:
        """The resolver also accepts a :class:`ProjectLicense` member directly."""
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(return_value=_execute_result("cc0"))

        license_id = await resolve_license_id_for_short_name(session, ProjectLicense.CC0)
        assert license_id == "cc0"


# ---------------------------------------------------------------------------
# record_initial_license — single happy path (FR-087)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRecordInitialLicense:
    """Initial-history row creation has one branch — assert the row shape."""

    async def test_creates_history_row_with_none_old_license(self) -> None:
        session = AsyncMock(spec=AsyncSession)
        session.add = MagicMock()  # ``add`` is sync on the real session
        project_id = uuid4()
        actor_id = uuid4()

        row = await record_initial_license(session, project_id, ProjectLicense.CC_BY, actor_id)

        assert isinstance(row, ProjectLicenseHistory)
        assert row.project_id == project_id
        assert row.old_license is None
        assert row.new_license == "CC-BY"
        assert row.changed_by_id == actor_id
        assert row.changed_at is not None
        session.add.assert_called_once_with(row)

    async def test_accepts_string_license_input(self) -> None:
        """The helper also accepts a raw string license short name."""
        session = AsyncMock(spec=AsyncSession)
        session.add = MagicMock()
        project_id = uuid4()
        actor_id = uuid4()

        row = await record_initial_license(session, project_id, "CC-BY-NC", actor_id)

        assert row.new_license == "CC-BY-NC"


# ---------------------------------------------------------------------------
# change_license — every branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestChangeLicense:
    """``change_license`` covers project-not-found / None / unknown / success."""

    async def test_project_not_found_raises_value_error(self) -> None:
        """``select Project FOR UPDATE`` returns ``None`` → ``ValueError``."""
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(return_value=_execute_result(None))

        with pytest.raises(ValueError, match="not found"):
            await change_license(
                session,
                uuid4(),
                ProjectLicense.CC_BY,
                uuid4(),
            )

    async def test_none_new_license_raises_value_error(self) -> None:
        """Locked project is returned but caller passed ``None`` → ``ValueError``."""
        session = AsyncMock(spec=AsyncSession)
        project = _project_stub(license="CC-BY")
        # First execute returns the locked project; no subsequent execute is
        # expected because the guard fires immediately after the lock.
        session.execute = AsyncMock(return_value=_execute_result(project))

        with pytest.raises(ValueError, match="requires a new license"):
            await change_license(session, uuid4(), None, uuid4())

    async def test_unknown_short_name_raises_license_required_http_exception(self) -> None:
        """Resolver ``ValueError`` is translated into the FR-085 422 envelope."""
        session = AsyncMock(spec=AsyncSession)
        project = _project_stub(license="CC-BY")
        # 1st execute → lock row; 2nd execute (inside the resolver) → None
        session.execute = AsyncMock(
            side_effect=[
                _execute_result(project),  # lock query
                _execute_result(None),  # resolver lookup
            ]
        )

        with pytest.raises(HTTPException) as exc_info:
            await change_license(session, uuid4(), "MIT", uuid4())

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == {
            "error": "ERR_LICENSE_REQUIRED",
            "message": "Project license is required (FR-085)",
        }

    async def test_success_appends_history_and_updates_license_id(self) -> None:
        """Happy path: project.license_id is updated and a row is appended."""
        session = AsyncMock(spec=AsyncSession)
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.refresh = AsyncMock()
        project = _project_stub(license="CC-BY")
        session.execute = AsyncMock(
            side_effect=[
                _execute_result(project),  # lock query
                _execute_result("cc-by-nc"),  # resolver lookup
            ]
        )
        project_id = uuid4()
        actor_id = uuid4()

        row = await change_license(
            session,
            project_id,
            ProjectLicense.CC_BY_NC,
            actor_id,
        )

        assert project.license_id == "cc-by-nc"
        assert isinstance(row, ProjectLicenseHistory)
        assert row.project_id == project_id
        assert row.old_license == "CC-BY"
        assert row.new_license == "CC-BY-NC"
        assert row.changed_by_id == actor_id
        session.add.assert_called_once_with(row)
        session.flush.assert_awaited_once()
        # ``session.refresh(project, ["license_record"])`` is awaited so the
        # response payload sees the freshly-resolved relationship eager-load.
        session.refresh.assert_awaited_once_with(project, ["license_record"])

    async def test_success_with_string_license_input(self) -> None:
        """The same path handles a raw string license short name as input."""
        session = AsyncMock(spec=AsyncSession)
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.refresh = AsyncMock()
        project = _project_stub(license="CC0")
        session.execute = AsyncMock(
            side_effect=[
                _execute_result(project),
                _execute_result("cc-by-sa"),
            ]
        )

        row = await change_license(session, uuid4(), "CC-BY-SA", uuid4())

        assert row.old_license == "CC0"
        assert row.new_license == "CC-BY-SA"


# ---------------------------------------------------------------------------
# list_license_history — empty + populated paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListLicenseHistory:
    """``list_license_history`` returns ASC-sorted rows or an empty list."""

    async def test_empty_history_returns_empty_list(self) -> None:
        """No rows for the project → empty list (legacy / pre-006 projects)."""
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(return_value=_scalars_result([]))

        rows = await list_license_history(session, uuid4())

        assert rows == []

    async def test_populated_history_returns_rows_in_order(self) -> None:
        """Populated path: the service returns whatever the DB hands back —
        the SQL ``ORDER BY changed_at ASC`` is the source of truth for
        ordering (mirrored by the OpenAPI ``履歴（昇順）`` contract).
        """
        session = AsyncMock(spec=AsyncSession)
        row_a = MagicMock(spec=ProjectLicenseHistory)
        row_b = MagicMock(spec=ProjectLicenseHistory)
        session.execute = AsyncMock(return_value=_scalars_result([row_a, row_b]))

        rows = await list_license_history(session, uuid4())

        assert rows == [row_a, row_b]
        # Exactly one query is issued (no per-row N+1 fetch).
        session.execute.assert_awaited_once()
