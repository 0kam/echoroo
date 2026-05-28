"""Project license history service (T322, FR-085 / FR-087).

Spec FR-087 mandates that every license change for a :class:`Project` be
recorded in :class:`echoroo.models.project.ProjectLicenseHistory` so that
historical exports remain immutable and consumers can audit license
provenance via ``GET /web-api/v1/projects/{id}/license-history``.

The service is intentionally minimal: it does **not** mutate
``Project.license`` outside of :func:`change_license`, and it does **not**
touch the audit log or the export pipeline. Past CSV exports
(:mod:`echoroo.services.detection_export`) reference the history URL only —
they read no rows from this service, so the immutability guarantee is held
by the export layer, not here.

Public surface:

* :func:`record_initial_license` — append a single ``(old=None, new=L)``
  history row at project creation (FR-085 + FR-087).
* :func:`change_license` — atomically update ``Project.license`` *and*
  append an ``(old=current, new=L)`` row, returning the new history row.
  The service ALWAYS appends a row, even when ``new_license`` matches the
  current value — Phase 7 polish round 2 (Major 5) deliberately removed
  the same-license short-circuit so each PATCH is observable in the
  history table. Callers that want PATCH idempotency should diff at the
  endpoint layer before invoking this service.
* :func:`list_license_history` — return all history rows for a project,
  sorted ``changed_at ASC`` so the OpenAPI contract's "履歴（昇順）"
  description (``contracts/projects.yaml:357``) is honoured. The DB
  index ``ix_project_license_history_project_changed_at`` is declared
  in the opposite direction for "fetch newest first" lookups; the service
  reverses it because the consumer-facing contract is ascending.

All callers are expected to ``await session.commit()`` themselves so this
service composes cleanly with the existing endpoint commit pattern (see
``apps/api/echoroo/api/v1/projects.py::create_project``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.enums import ProjectLicense
from echoroo.models.project import Project, ProjectLicenseHistory


def _license_short_name(license: ProjectLicense | str) -> str:
    return license.value if isinstance(license, ProjectLicense) else license


async def record_initial_license(
    session: AsyncSession,
    project_id: UUID,
    license: ProjectLicense | str,
    actor_user_id: UUID,
) -> ProjectLicenseHistory:
    """Append the initial ``ProjectLicenseHistory`` row for a new project.

    FR-085 (license required at creation) + FR-087 (changes are recorded
    in a separate table).

    Args:
        session: Open async SQLAlchemy session — the row is added but not
            committed; the caller owns the transaction.
        project_id: Newly-created project's UUID.
        license: License selected at creation. The history row stores it as
            ``new_license``; ``old_license`` is ``None`` to mark the
            "initial" entry.
        actor_user_id: User who performed the creation. Stored on the row
            as the ``changed_by_id`` foreign key.

    Returns:
        The freshly-created (but not yet committed) history row, already
        added to ``session`` so the caller can ``flush`` / ``commit`` it.
    """
    history = ProjectLicenseHistory(
        project_id=project_id,
        old_license=None,
        new_license=_license_short_name(license),
        changed_at=datetime.now(UTC),
        changed_by_id=actor_user_id,
    )
    session.add(history)
    return history


async def change_license(
    session: AsyncSession,
    project_id: UUID,
    new_license: ProjectLicense | str | None,
    actor_user_id: UUID,
) -> ProjectLicenseHistory:
    """Update ``Project.license`` and unconditionally append a history row.

    FR-087: every license PATCH is observable in
    :class:`ProjectLicenseHistory` — including same-license calls. Phase 7
    polish round 2 (Major 5) removed the previous ``return None`` shortcut
    because audit consumers need a row per request, not per logical
    transition.

    The mutation order (``project.license =`` first, ``add(history)``
    second) is intentional: SQLAlchemy will flush both in the same
    transaction so a rollback on either step keeps the rows consistent.

    Concurrency:
        Phase 7 polish round 2 (Major 4) takes a row-level lock via
        ``SELECT ... FOR UPDATE`` to prevent two concurrent PATCHes from
        both reading the same ``project.license`` and emitting two
        history rows whose ``old_license`` chains do not actually
        match. The lock is released when the caller's transaction
        commits / rolls back.

    Args:
        session: Open async SQLAlchemy session — the caller owns the
            transaction and is responsible for ``commit``.
        project_id: Target project UUID.
        new_license: Desired license. The row is appended even if it
            matches the current value — by design, see Major 5 above.
        actor_user_id: User who initiated the change. Stored on the
            history row as ``changed_by_id``.

    Returns:
        The new history row.

    Raises:
        ValueError: If the project does not exist.
    """
    # Major 4: row lock so concurrent PATCHes serialise on the project row
    # — without it two transactions could both read ``CC-BY`` as the
    # current license and emit two history rows whose ``old_license``
    # values disagree with the order they hit the wire.
    #
    # ``of=Project`` keeps the lock on the projects table only — without
    # it asyncpg refuses (``FOR UPDATE cannot be applied to the
    # nullable side of an outer join``) because the default ``Project``
    # mapper eager-loads ``owner`` via a LEFT OUTER JOIN. The history
    # row insert below does not need the locked owner row.
    result = await session.execute(
        select(Project).where(Project.id == project_id).with_for_update(of=Project)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise ValueError(f"Project {project_id} not found")

    if new_license is None:
        raise ValueError("Project license history requires a new license")

    old_license = project.license
    project.license = new_license
    new_license_short_name = _license_short_name(new_license)

    history = ProjectLicenseHistory(
        project_id=project_id,
        old_license=old_license,
        new_license=new_license_short_name,
        changed_at=datetime.now(UTC),
        changed_by_id=actor_user_id,
    )
    session.add(history)
    return history


async def list_license_history(
    session: AsyncSession,
    project_id: UUID,
) -> list[ProjectLicenseHistory]:
    """Return every license-history row for ``project_id`` oldest-first.

    Phase 7 polish round 2 (Major 3): the OpenAPI contract advertises the
    response as "履歴（昇順）" (``contracts/projects.yaml:357``), so the
    service emits ``changed_at ASC``. The DB index
    ``ix_project_license_history_project_changed_at`` is keyed in the
    opposite direction — that index optimises the "latest license"
    look-up path and we deliberately keep it as-is rather than rebuild.

    Args:
        session: Open async SQLAlchemy session.
        project_id: Project UUID.

    Returns:
        List of :class:`ProjectLicenseHistory`, sorted ``changed_at ASC``.
        An empty list when the project has no history rows (e.g. legacy
        rows pre-006 redesign — should not occur for projects created
        through :func:`record_initial_license`).
    """
    result = await session.execute(
        select(ProjectLicenseHistory)
        .where(ProjectLicenseHistory.project_id == project_id)
        .order_by(ProjectLicenseHistory.changed_at.asc())
    )
    return list(result.scalars().all())


__all__ = [
    "change_license",
    "list_license_history",
    "record_initial_license",
]
