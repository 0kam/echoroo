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
* :func:`change_license` — atomically update ``Project.license_id`` *and*
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

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.license import License
from echoroo.models.project import Project, ProjectLicenseHistory


class LicenseNotFoundError(Exception):
    """Raised when a request references a non-existent ``licenses.id``.

    spec/012 Phase 3: project create/update accept a ``license_id`` that
    carries the ``licenses.id`` primary key (e.g. ``cc-by``). An id with
    no matching row is rejected with HTTP 422 ``license_not_found`` (see
    :func:`license_not_found_http_exception`). The error carries the
    offending id so callers can include it in the response if desired.
    """

    def __init__(self, license_id: str) -> None:
        self.license_id = license_id
        super().__init__(f"Unknown project license id: {license_id}")


def _license_short_name(license: str) -> str:
    return license.strip()


def license_required_http_exception() -> HTTPException:
    """Return the FR-085 project-license 422 envelope."""
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "error": "ERR_LICENSE_REQUIRED",
            "message": "Project license is required (FR-085)",
        },
    )


def license_not_found_http_exception() -> HTTPException:
    """Return the spec/012 Phase 3 unknown-license-id 422 envelope.

    The request field changed from the license ``short_name`` to the
    ``licenses.id`` primary key; an id with no matching row is a client
    error surfaced as ``error_code: license_not_found`` (distinct from
    the missing/empty case, which Pydantic enforces as a standard 422).

    The detail dict carries BOTH the legacy ``error`` trigger key AND
    ``error_code``. The global :func:`echoroo.core.exceptions
    .http_exception_handler` unwraps any detail dict containing ``error``
    to the top level, so the client receives ``body["error_code"] ==
    "license_not_found"`` directly. The unwrap is deliberately keyed on
    ``error`` (not ``error_code``) so spec/011's step-up and the audit
    ``META_AUDIT_WRITE_FAILED`` envelopes — which raise
    ``HTTPException(detail={"error_code": ...})`` and contractually keep
    the nested ``{"detail": {...}}`` shape — are left byte-for-byte
    unchanged. Mirroring the legacy ``ERR_*`` convention here keeps the
    license contract self-contained without widening the global handler.
    """
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "error": "license_not_found",
            "error_code": "license_not_found",
            "message": "Unknown project license id (license_not_found)",
        },
    )


async def resolve_license_for_id(
    db: AsyncSession,
    license_id: str,
) -> tuple[str, str]:
    """Resolve a ``licenses.id`` to ``(id, short_name)`` in a single query.

    spec/012 Phase 3: project create/update/PATCH carry the ``licenses.id``
    primary key (e.g. ``cc-by``). The PATCH path needs BOTH the validated
    id (written directly to ``Project.license_id``) and the row's
    ``short_name`` (written to the license-history table + audit log, which
    keep storing the human-facing ``CC-BY`` form). Resolving the row ONCE
    here — mirroring the CREATE path's
    ``services.project._resolve_license_by_id_or_422`` — lets the PATCH
    handlers set ``Project.license_id`` directly via the validated id and
    pass the short_name to the history writer, eliminating the fragile
    ``id -> short_name -> id`` round-trip that previously relied on the
    ``licenses.short_name`` UNIQUE constraint (present only in migration
    0023, not mirrored on the ORM model).

    Returns:
        ``(license_id, short_name)`` for the matched row.

    Raises:
        LicenseNotFoundError: when no ``licenses`` row matches ``license_id``.
    """
    resolved_id = license_id.strip()
    if not resolved_id:
        raise LicenseNotFoundError(license_id)

    result = await db.execute(
        select(License.id, License.short_name)
        .where(License.id == resolved_id)
        .limit(1)
    )
    row = result.one_or_none()
    if row is None:
        raise LicenseNotFoundError(resolved_id)

    return row.id, row.short_name


async def resolve_license_short_name_for_id(
    db: AsyncSession,
    license_id: str,
) -> str:
    """Resolve a ``licenses.id`` to its ``short_name`` row value.

    spec/012 Phase 3: project create/update now carry the ``licenses.id``
    primary key (e.g. ``cc-by``). The license-history table and audit log
    still store the human-facing ``short_name`` (e.g. ``CC-BY``), so every
    write path resolves the id to the row's ``short_name`` ONCE and passes
    that string downstream — never the raw id.

    Thin wrapper over :func:`resolve_license_for_id` kept for callers that
    only need the short_name (legacy callers / tests).

    Raises:
        LicenseNotFoundError: when no ``licenses`` row matches ``license_id``.
    """
    _, short_name = await resolve_license_for_id(db, license_id)
    return short_name


async def resolve_license_id_for_short_name(
    db: AsyncSession,
    short_name: str,
) -> str:
    """Resolve a project license short name to the canonical ``licenses.id``."""
    license_short_name = _license_short_name(short_name)
    if not license_short_name:
        raise ValueError("Project license short_name is required")

    result = await db.execute(
        select(License.id)
        .where(License.short_name == license_short_name)
        .limit(1)
    )
    license_id = result.scalar_one_or_none()
    if license_id is None:
        raise ValueError(f"Unknown project license short_name: {license_short_name}")

    return license_id


async def record_initial_license(
    session: AsyncSession,
    project_id: UUID,
    license: str,
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
    new_license: str | None,
    actor_user_id: UUID,
    *,
    new_license_id: str | None = None,
) -> ProjectLicenseHistory:
    """Update ``Project.license_id`` and unconditionally append a history row.

    FR-087: every license PATCH is observable in
    :class:`ProjectLicenseHistory` — including same-license calls. Phase 7
    polish round 2 (Major 5) removed the previous ``return None`` shortcut
    because audit consumers need a row per request, not per logical
    transition.

    The mutation order (``project.license_id =`` first, ``add(history)``
    second) is intentional: SQLAlchemy flushes both in the same
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
        new_license: Desired license ``short_name`` (e.g. ``CC-BY``). The
            row is appended even if it matches the current value — by
            design, see Major 5 above. Used both for the history row's
            ``new_license`` column and — when ``new_license_id`` is NOT
            supplied — to re-resolve the canonical ``licenses.id``.
        actor_user_id: User who initiated the change. Stored on the
            history row as ``changed_by_id``.
        new_license_id: Pre-resolved ``licenses.id`` (spec/012 Phase 3 FIX
            #5). When supplied (the PATCH endpoints resolve the row ONCE
            via :func:`resolve_license_for_id` and pass both id +
            short_name), it is written directly to ``Project.license_id``
            and the internal ``short_name -> id`` re-resolution is skipped
            entirely — removing the ``id -> short_name -> id`` round-trip
            that previously depended on the DB ``short_name`` UNIQUE
            constraint. When ``None`` (legacy callers / unit tests that
            pass only a short_name), the function falls back to resolving
            the id from ``new_license`` as before.

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
    if new_license_id is None:
        # Legacy / unit-test path: only a short_name was supplied, so
        # re-resolve the canonical id. The PATCH endpoints take the
        # pre-resolved branch below (FIX #5) and never hit this.
        try:
            new_license_id = await resolve_license_id_for_short_name(
                session, new_license
            )
        except ValueError as exc:
            raise license_required_http_exception() from exc

    project.license_id = new_license_id
    new_license_short_name = _license_short_name(new_license)

    history = ProjectLicenseHistory(
        project_id=project_id,
        old_license=old_license,
        new_license=new_license_short_name,
        changed_at=datetime.now(UTC),
        changed_by_id=actor_user_id,
    )
    session.add(history)
    await session.flush()
    await session.refresh(project, ["license_record"])
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
    "LicenseNotFoundError",
    "change_license",
    "license_not_found_http_exception",
    "license_required_http_exception",
    "list_license_history",
    "record_initial_license",
    "resolve_license_for_id",
    "resolve_license_id_for_short_name",
    "resolve_license_short_name_for_id",
]
