"""Restricted-config toggle service (T401, FR-014 / FR-020-022 / FR-024 / FR-025a).

Spec FR-024 mandates that a Restricted project's capability toggles be
mutated through a single transactional service that:

* takes a row-level lock on :class:`echoroo.models.project.Project` so two
  concurrent PATCHes serialise on the project row;
* persists the new ``restricted_config`` JSONB blob and bumps
  ``restricted_config_version`` monotonically;
* emits a ``project.restricted_config.update`` row to ``project_audit_log``
  carrying the **diff** (before / after) so reviewers can replay every
  toggle flip from the audit chain alone (FR-088);
* enqueues an asynchronous search-index rebuild Celery task whenever
  ``allow_detection_view`` flips ``True → False`` so the cross-project
  search results stop returning detections from the project (FR-025a step 2).

Atomicity contract (Phase 8 polish round 2 致命 1)
=================================================

The service mutates the Project row inside the caller's session and
returns a :class:`RestrictedConfigUpdateOutcome` describing the change.
It **does NOT** write the audit row or enqueue the Celery task while the
main transaction is still open — both side-effects MUST be triggered by
the endpoint layer **after** ``db.commit()`` succeeds. This mirrors the
license-service pattern in ``api/web_v1/projects/_license.py``: a main-TX
rollback would otherwise leave a phantom audit row + a phantom Celery
job referring to a toggle change that never persisted.

The endpoint flow is therefore:

1. ``await update_restricted_config(...)`` → flushes the Project mutation
   and returns the diff / before / after snapshots.
2. ``await db.commit()`` — main TX commits the project mutation.
3. ``await trigger_post_commit_side_effects(outcome, ...)`` — fires the
   audit write (fresh session, FR-093 SERIALIZABLE) and Celery enqueue.
   Failures here are logged as WARNINGs (FR-088 soft alert) without
   undoing the persisted toggle change.

Public surface:

* :class:`RestrictedConfigUpdateOutcome` — bag of values the endpoint
  needs for the post-commit side-effects.
* :func:`update_restricted_config` — flips the toggles inside the
  caller's transaction.
* :func:`trigger_post_commit_side_effects` — runs after
  ``db.commit()`` succeeds.

The synchronous permission gate in :mod:`echoroo.core.permissions`
already sees the new ``restricted_config`` immediately (step 1 of the
two-stage commit in FR-025a), so the asynchronous Celery rebuild is
purely a stale-cache cleanup. Phase 11 will wire the actual rebuild
logic; until then the worker task is a logged stub
(``echoroo.workers.search_tasks.rebuild_search_index_for_project``).

FR-025a step 1 (immediate exclusion via SearchGate)
---------------------------------------------------

``SearchGate.filter_by_allow_detection_view`` (services/search_gate.py)
implements the synchronous filter, but the wire-up into
:class:`echoroo.services.search.SimilaritySearchService.search_by_vector`
is intentionally deferred to Phase 11 / T091. Until then,
``allow_detection_view: True → False`` causes immediate exclusion at
the **permission gate** level (the canonical
``check_project_access`` / ``gate_action`` chain reads the freshly
written ``restricted_config`` for every request), and the search index
rebuild remains async (FR-025a step 2 below).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from echoroo.core.database import AsyncSessionLocal
from echoroo.models.project import Project
from echoroo.schemas.project import RestrictedConfigUpdateRequest
from echoroo.services.audit_service import AuditLogService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Outcome type — the values the endpoint needs to fire post-commit hooks.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RestrictedConfigUpdateOutcome:
    """Snapshot of a successful in-session toggle update.

    The endpoint commits the main transaction first, then passes this
    object to :func:`trigger_post_commit_side_effects` so the audit
    write (fresh session) and Celery enqueue only fire if the persisted
    toggle change actually committed (Phase 8 polish round 2 致命 1).

    Attributes:
        project: The mutated :class:`Project` row pinned by the row-level
            lock. The endpoint reads from it for the response shape (the
            in-memory state matches the freshly-flushed DB row).
        actor_user_id: Who initiated the PATCH; recorded in the audit row.
        request_id: Request id for the audit chain ("" when absent).
        ip: Client IP (hashed downstream by the audit writer).
        user_agent: User-Agent header (hashed downstream).
        diff: ``{key: {"old": ..., "new": ...}}`` for keys that actually
            changed value.
        before: Pre-PATCH ``restricted_config`` blob.
        after: Post-PATCH ``restricted_config`` blob (same shape as the
            request body but typed as plain ``dict``).
        before_version: ``restricted_config_version`` before the mutation.
        after_version: ``restricted_config_version`` after the mutation
            (always ``before_version + 1``).
        detection_view_flipped_off: ``True`` when ``allow_detection_view``
            transitioned ``True → False``; used to decide whether to fire
            the FR-025a search-index rebuild Celery task post-commit.
    """

    project: Project
    actor_user_id: UUID
    request_id: str
    ip: str
    user_agent: str
    diff: dict[str, dict[str, Any]]
    before: dict[str, Any]
    after: dict[str, Any]
    before_version: int
    after_version: int
    detection_view_flipped_off: bool


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def update_restricted_config(
    *,
    session: AsyncSession,
    project_id: UUID,
    new_config: RestrictedConfigUpdateRequest,
    actor_user_id: UUID,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> RestrictedConfigUpdateOutcome:
    """Atomically replace ``restricted_config`` in the caller's transaction.

    Phase 8 / T401 (FR-014, FR-020-022, FR-024, FR-025a):

    1. ``SELECT ... FOR UPDATE`` on the project row so two concurrent PATCHes
       cannot interleave their version bumps (mirrors
       :func:`echoroo.services.license_service.change_license`).
    2. Compute the before / after diff so the audit row carries only the
       fields that actually changed (the full new config is also recorded
       in ``after`` for replay purposes).
    3. Replace ``project.restricted_config`` in-place and increment
       ``project.restricted_config_version`` by 1.
    4. Detect the FR-025a synchronous-then-asynchronous transition
       (``allow_detection_view`` flips ``True → False``) and surface the
       fact through :class:`RestrictedConfigUpdateOutcome` so the endpoint
       can fire the Celery enqueue **after** ``db.commit()`` succeeds.
    5. Return the outcome bag — the endpoint owns the commit + the
       post-commit side-effects (audit + Celery), per the atomicity
       contract documented at the top of this module.

    Args:
        session: Open async SQLAlchemy session — the caller owns the
            transaction and is responsible for ``await session.commit()``
            on the Project mutation.
        project_id: Target project UUID.
        new_config: Validated request body. Must be the
            :class:`RestrictedConfigUpdateRequest` (already enforces
            ``Extra.forbid`` + the 3-15 H3 resolution range).
        actor_user_id: User who initiated the PATCH; recorded as the audit
            ``actor_user_id`` (hashed at the audit layer per FR-091).
        request_id: Optional request id for the audit chain.
        ip: Client IP for the audit row (hashed downstream).
        user_agent: User-Agent header for the audit row (hashed downstream).

    Returns:
        :class:`RestrictedConfigUpdateOutcome` carrying the mutated project
        plus everything :func:`trigger_post_commit_side_effects` needs.

    Raises:
        ValueError: If the project does not exist.
    """
    # 1. Row lock — ``of=Project`` keeps the lock on the projects table only
    # because the default ``Project`` mapper eager-loads ``owner`` via a
    # LEFT OUTER JOIN. Mirrors :func:`change_license`.
    #
    # ``populate_existing=True`` forces the SELECT result to overwrite any
    # stale attributes on the same identity-mapped instance — without it
    # an upstream ``gate_action`` call would have already loaded the
    # Project, and the ``with_for_update`` SELECT would not refresh the
    # cached ``restricted_config`` dict (the JSONB column would keep its
    # pre-PATCH value on the in-memory object even after we assign the
    # new dict, because the post-commit ``db.refresh(project)`` in the
    # endpoint reuses the same ORM instance).
    result = await session.execute(
        select(Project)
        .where(Project.id == project_id)
        .with_for_update(of=Project)
        .execution_options(populate_existing=True)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise ValueError(f"Project {project_id} not found")

    before_config: dict[str, Any] = dict(project.restricted_config or {})
    before_version = int(project.restricted_config_version)

    after_config: dict[str, Any] = new_config.model_dump()

    # 2. Diff — record only the keys whose value changed so the audit
    # consumer can render a compact "X changed from foo to bar" log entry.
    # The full ``after`` blob is also recorded so replay does not need to
    # walk the audit history forwards / backwards.
    diff: dict[str, dict[str, Any]] = {}
    for key, new_value in after_config.items():
        if before_config.get(key) != new_value:
            diff[key] = {
                "old": before_config.get(key),
                "new": new_value,
            }

    # 3. Mutate the project row + bump the version. Replace the whole
    # config dict so SQLAlchemy detects the JSONB change (a partial
    # mutation in-place would not flag the column as dirty). We also
    # invoke :func:`flag_modified` defensively because JSONB columns
    # under ``expire_on_commit=False`` can occasionally be skipped during
    # flush when the previous attribute state was loaded with
    # ``populate_existing`` — the SELECT result overwrites the
    # in-memory dict and the subsequent assignment compares equal at
    # the unit-of-work level even when the dict identity differs.
    project.restricted_config = after_config
    flag_modified(project, "restricted_config")
    after_version = before_version + 1
    project.restricted_config_version = after_version
    # Force the unit-of-work to flush the JSONB mutation NOW so the row
    # in PostgreSQL reflects the new config before any subsequent SELECT
    # (e.g. the audit fresh-session FK probe) can race with it. Without
    # the explicit flush the test fixture's ``override_get_db`` ends up
    # returning a stale ORM image to ``model_validate`` because the
    # autoflush trigger never fires (no further SELECT statements run on
    # the session before commit).
    await session.flush()

    # 4. FR-025a: surface the ON->OFF transition so the endpoint can
    # enqueue the async search-index rebuild AFTER db.commit(). Firing
    # the Celery task before commit would create a phantom worker job if
    # the main TX rolled back (Phase 8 polish round 2 致命 1).
    detection_view_was_on = bool(before_config.get("allow_detection_view", False))
    detection_view_is_off = not after_config["allow_detection_view"]
    detection_view_flipped_off = detection_view_was_on and detection_view_is_off

    return RestrictedConfigUpdateOutcome(
        project=project,
        actor_user_id=actor_user_id,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
        diff=diff,
        before=before_config,
        after=after_config,
        before_version=before_version,
        after_version=after_version,
        detection_view_flipped_off=detection_view_flipped_off,
    )


async def trigger_post_commit_side_effects(
    outcome: RestrictedConfigUpdateOutcome,
) -> None:
    """Fire audit + Celery enqueue after the main transaction has committed.

    Phase 8 polish round 2 致命 1 — atomicity contract: the endpoint MUST
    call this **after** ``await db.commit()`` succeeds. Doing it before
    would leave a phantom audit row / Celery job if the main TX rolled
    back.

    Both side-effects are best-effort. Failures are logged as WARNINGs
    (FR-088 soft alert) and do NOT raise — the persisted toggle change
    is the security-critical path; observability is secondary.

    Args:
        outcome: Bag of values returned from :func:`update_restricted_config`.
    """
    # 1. Audit row — fresh session because the audit writer issues
    # ``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` which PostgreSQL
    # rejects on a session that already issued statements. Mirrors the
    # license-service / meta-audit pattern.
    try:
        await _write_restricted_config_audit(
            actor_user_id=outcome.actor_user_id,
            project_id=outcome.project.id,
            request_id=outcome.request_id,
            ip=outcome.ip,
            user_agent=outcome.user_agent,
            diff=outcome.diff,
            before=outcome.before,
            after=outcome.after,
            before_version=outcome.before_version,
            after_version=outcome.after_version,
        )
    except Exception as exc:  # noqa: BLE001 — audit must never block the mutation.
        logger.warning(
            "project.restricted_config.update audit write failed (FR-088 soft alert): "
            "project_id=%s actor=%s diff_keys=%s error=%r",
            outcome.project.id,
            outcome.actor_user_id,
            sorted(outcome.diff.keys()),
            exc,
        )

    # 2. FR-025a step 2: enqueue the async search-index rebuild. The
    # synchronous permission gate already excludes detections from the
    # project (the gate reads the freshly-committed ``restricted_config``
    # for every request), so this enqueue is purely a stale-cache
    # cleanup.
    if outcome.detection_view_flipped_off:
        _enqueue_search_index_rebuild(
            project_id=outcome.project.id,
            new_version=outcome.after_version,
        )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _enqueue_search_index_rebuild(
    *,
    project_id: UUID,
    new_version: int,
) -> None:
    """Enqueue the FR-025a search-index rebuild Celery task.

    The dedicated Celery task lives in
    :mod:`echoroo.workers.search_tasks` (registered as
    ``echoroo.workers.search_tasks.rebuild_search_index_for_project``).
    The Phase 8 stub task body is a no-op + log; Phase 11 will wire the
    actual OpenSearch / pgvector / FTS rebuild logic.

    Failures here are swallowed (logged) because the synchronous
    permission gate already enforces the new toggle; the worker rebuild
    is purely a stale-cache cleanup. A failed enqueue means the next
    Beat tick or explicit operator re-run will pick it up.
    """
    try:
        # Imported lazily so unit tests that mock the Celery app do not need
        # to seed the full module graph just to call ``update_restricted_config``.
        from echoroo.workers.celery_app import app as celery_app

        celery_app.send_task(
            "echoroo.workers.search_tasks.rebuild_search_index_for_project",
            kwargs={
                "project_id": str(project_id),
                "version": new_version,
            },
        )
    except Exception as exc:  # noqa: BLE001 — best effort; soft alert only.
        logger.warning(
            "FR-025a search index rebuild enqueue failed for project_id=%s "
            "version=%s: %r",
            project_id,
            new_version,
            exc,
        )


async def _write_restricted_config_audit(
    *,
    actor_user_id: UUID,
    project_id: UUID,
    request_id: str,
    ip: str,
    user_agent: str,
    diff: dict[str, dict[str, Any]],
    before: dict[str, Any],
    after: dict[str, Any],
    before_version: int,
    after_version: int,
) -> None:
    """Append a ``project.restricted_config.update`` row to ``project_audit_log``.

    Uses a fresh :class:`AsyncSessionLocal` so the audit row's serialisable
    transaction cannot piggy-back on the request-scoped session (which has
    already issued non-isolation-level statements). Mirrors the pattern in
    :func:`echoroo.api.web_v1.projects._license._write_license_audit`.
    """
    async with AsyncSessionLocal() as audit_session:
        try:
            service = AuditLogService(audit_session)
            await service.write_project_event(
                actor_user_id=actor_user_id,
                project_id=project_id,
                action="project.restricted_config.update",
                request_id=request_id,
                ip=ip,
                user_agent=user_agent,
                detail={
                    "diff": diff,
                    "before_version": before_version,
                    "after_version": after_version,
                },
                before={"restricted_config": before},
                after={"restricted_config": after},
            )
            await audit_session.commit()
        except Exception:
            await audit_session.rollback()
            raise


__all__ = [
    "RestrictedConfigUpdateOutcome",
    "trigger_post_commit_side_effects",
    "update_restricted_config",
]
