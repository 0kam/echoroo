"""spec/011 R6 / T543 — DESTRUCTIVE_ACTIONS allowlist security guard.

The SU bootstrap composite audit (FR-011-123) includes a
``pre_transfer_action_summary`` blob produced by
:func:`echoroo.services.audit_service.build_pre_transfer_action_summary`.
Per research R6 the blob preserves the per-row ``target_id`` ONLY for
audit-action strings that are members of :data:`DESTRUCTIVE_ACTIONS`;
every other action surfaces just the ``action`` + ``occurred_at`` keys
so a non-destructive event cannot leak its target identifier through
the summary projection (FR-011-307 activity-view consumer).

This security test fixes the allowlist by:

1. Asserting every entry in :data:`DESTRUCTIVE_ACTIONS` produces a
   ``target_id``-preserved summary entry when the synthesised audit
   row carries the key.
2. Asserting representative non-destructive audit actions surface
   WITHOUT ``target_id`` even when the synthetic detail includes it.
3. Asserting every new spec/011 audit-action string (the constants
   declared service-private under :mod:`echoroo.services.invitation_service`
   and :mod:`echoroo.services.user_banner` BANNER_ELIGIBLE_ACTIONS) is
   recognised by the A-13 PII detector pathway — concretely, every
   constant is a plain ASCII ``verb.noun.verb`` string that
   :func:`echoroo.core.audit.contains_pii` accepts (no PII pattern
   masquerading as an action name).

Note: the A-13 detector test
(``apps/api/tests/unit/core/test_operator_pii_detector.py``) exercises
the regex against free-form operator input. The spec/011 audit-action
strings are NOT operator input — they are service-private constants —
so the relevant "registration" check at this layer is the negative
assertion that they do not themselves trip the PII regex (defence
against a future maintainer naming a constant
``platform.user.email.update_for_jane@example.com``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.audit import contains_pii
from echoroo.services import audit_service
from echoroo.services.admin_password_reset import (
    AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_BY_SUPERUSER,
    AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_SELF,
)
from echoroo.services.api_key_lifecycle import (
    AUDIT_ACTION_PLATFORM_API_KEY_REVOKE,
)
from echoroo.services.audit_service import (
    DESTRUCTIVE_ACTIONS,
    build_pre_transfer_action_summary,
)
from echoroo.services.auth import AUDIT_ACTION_AUTH_LOGIN_NEW_DEVICE
from echoroo.services.invitation_service import (
    AUDIT_ACTION_INVITATION_REVOKE,
    AUDIT_ACTION_MEMBER_INVITE_ACCEPTED,
    AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP,
    AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER,
    AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED,
)
from echoroo.services.trusted_device_service import (
    AUDIT_ACTION_AUTH_TRUSTED_DEVICE_REVOKE_ALL,
)
from echoroo.services.two_factor_reset_service import (
    AUDIT_ACTION_PLATFORM_USER_TWO_FACTOR_RESET_BY_SUPERUSER,
)
from echoroo.services.user import AUDIT_ACTION_PLATFORM_USER_EMAIL_CHANGED
from echoroo.services.user_banner import BANNER_ELIGIBLE_ACTIONS

# ``pytestmark`` is applied per-test below (only the async DB-touching
# cases need the marker; the static-constant checks are sync funcs).


# ---------------------------------------------------------------------------
# Helpers (mirror the unit-test seeding helpers — chain columns stubbed
# because the writer path is not under test here)
# ---------------------------------------------------------------------------


def _stub_pii_hash(value: str) -> str:
    return f"hash:{value}"


@pytest.fixture(autouse=True)
def _patch_pii_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit_service, "compute_pii_hash", _stub_pii_hash)


async def _ensure_project(session: AsyncSession) -> UUID:
    project_id = uuid4()
    owner_id = uuid4()
    await session.execute(
        sa.text(
            """
            INSERT INTO users (id, email, password_hash, security_stamp)
            VALUES (:id, :email, 'x', :stamp)
            """
        ),
        {
            "id": str(owner_id),
            "email": f"owner-{owner_id}@example.com",
            "stamp": "s" * 64,
        },
    )
    await session.execute(
        sa.text(
            """
            INSERT INTO licenses (id, name, short_name, created_at, updated_at)
            VALUES ('cc-by', 'Creative Commons Attribution', 'CC-BY', now(), now())
            ON CONFLICT (id) DO NOTHING
            """
        )
    )
    await session.execute(
        sa.text(
            """
            INSERT INTO projects (id, name, visibility, license_id, status, owner_id)
            VALUES (:id, :name, 'public', 'cc-by', 'active', :owner_id)
            """
        ),
        {
            "id": str(project_id),
            "name": f"r6-allowlist-{project_id}",
            "owner_id": str(owner_id),
        },
    )
    return project_id


async def _insert_audit_row(
    session: AsyncSession,
    *,
    project_id: UUID,
    actor_user_id: UUID,
    action: str,
    occurred_at: datetime,
    detail: dict[str, Any] | None = None,
) -> UUID:
    row_id = uuid4()
    actor_hash = _stub_pii_hash(str(actor_user_id))
    await session.execute(
        sa.text(
            """
            INSERT INTO project_audit_log
              (id, created_at, actor_user_id_hash, project_id, action,
               detail, request_id, ip_hash, user_agent_hash,
               prev_hash, row_hash)
            VALUES
              (:id, :created_at, :actor_hash, :project_id, :action,
               CAST(:detail AS JSONB), 'test-req', 'ip-hash', 'ua-hash',
               :prev_hash, :row_hash)
            """
        ),
        {
            "id": str(row_id),
            "created_at": occurred_at,
            "actor_hash": actor_hash,
            "project_id": str(project_id),
            "action": action,
            "detail": json.dumps(detail or {}),
            "prev_hash": "0" * 64,
            "row_hash": "f" * 64,
        },
    )
    return row_id


# ---------------------------------------------------------------------------
# 1. Each DESTRUCTIVE_ACTIONS entry preserves target_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_each_destructive_action_preserves_target_id(
    db_session: AsyncSession,
) -> None:
    """Every entry in :data:`DESTRUCTIVE_ACTIONS` retains ``target_id``."""
    project_id = await _ensure_project(db_session)
    actor_id = uuid4()
    base_time = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=30)

    # Order DESTRUCTIVE_ACTIONS deterministically so the inserted rows
    # surface in a known order on the summary side.
    ordered_actions = sorted(DESTRUCTIVE_ACTIONS)
    inserted_target_ids: dict[str, str] = {}
    for offset, action in enumerate(ordered_actions):
        target_id = uuid4()
        inserted_target_ids[action] = str(target_id)
        await _insert_audit_row(
            db_session,
            project_id=project_id,
            actor_user_id=actor_id,
            action=action,
            occurred_at=base_time + timedelta(seconds=offset),
            detail={"target_id": str(target_id)},
        )

    result = await build_pre_transfer_action_summary(
        db_session,
        project_id=project_id,
        actor_user_id=actor_id,
        since=base_time - timedelta(seconds=1),
        until=base_time + timedelta(minutes=10),
    )

    summary = result["summary"]
    surfaced_actions = {entry["action"] for entry in summary}
    assert surfaced_actions == set(ordered_actions), (
        f"summary surfaced wrong action set: {surfaced_actions}"
    )
    for entry in summary:
        action = entry["action"]
        assert action in DESTRUCTIVE_ACTIONS
        assert entry.get("target_id") == inserted_target_ids[action], (
            f"destructive action {action!r} lost target_id from summary "
            f"(entry={entry!r})"
        )


# ---------------------------------------------------------------------------
# 2. Non-destructive actions do NOT surface target_id even when detail
#    includes the key (defence against accidental allowlist expansion)
# ---------------------------------------------------------------------------


_NON_DESTRUCTIVE_SAMPLE: tuple[str, ...] = (
    "project.invitation.create",
    "project.invitation.accept",
    "project.invitation.decline",
    AUDIT_ACTION_INVITATION_REVOKE,
    AUDIT_ACTION_MEMBER_INVITE_ACCEPTED,
    AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP,
    AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED,
    AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", _NON_DESTRUCTIVE_SAMPLE)
async def test_non_destructive_action_drops_target_id(
    db_session: AsyncSession, action: str
) -> None:
    """A non-destructive row surfaces without ``target_id`` (R6)."""
    assert action not in DESTRUCTIVE_ACTIONS, (
        f"{action!r} is unexpectedly classified destructive — "
        "update DESTRUCTIVE_ACTIONS and this test together"
    )
    project_id = await _ensure_project(db_session)
    actor_id = uuid4()
    occurred_at = datetime.now(UTC) - timedelta(minutes=5)
    await _insert_audit_row(
        db_session,
        project_id=project_id,
        actor_user_id=actor_id,
        action=action,
        occurred_at=occurred_at,
        detail={"target_id": str(uuid4()), "comment": "synthetic"},
    )

    result = await build_pre_transfer_action_summary(
        db_session,
        project_id=project_id,
        actor_user_id=actor_id,
        since=occurred_at - timedelta(minutes=1),
        until=occurred_at + timedelta(minutes=1),
    )

    summary = result["summary"]
    assert len(summary) == 1
    entry = summary[0]
    assert entry["action"] == action
    assert "target_id" not in entry


# ---------------------------------------------------------------------------
# 3. A-13 PII detector coverage on spec/011 audit-action strings
# ---------------------------------------------------------------------------

#: spec/011 audit-action constants that surface as service-private strings.
#: The set MUST stay in sync with the constants declared across the
#: owning service modules (T020). T023 extends this from the original 5
#: invitation/ownership entries to all 11 NFR-011-005 strings (plus the
#: invitation-revoke string) so the A-13-detector registration check
#: covers every new spec/011 audit-action string.
_SPEC_011_AUDIT_ACTIONS: frozenset[str] = frozenset(
    {
        # invitation_service.py
        AUDIT_ACTION_INVITATION_REVOKE,
        AUDIT_ACTION_MEMBER_INVITE_ACCEPTED,
        AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP,
        AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER,
        AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED,
        # admin_password_reset.py
        AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_BY_SUPERUSER,
        AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_SELF,
        # auth.py
        AUDIT_ACTION_AUTH_LOGIN_NEW_DEVICE,
        # api_key_lifecycle.py
        AUDIT_ACTION_PLATFORM_API_KEY_REVOKE,
        # user.py
        AUDIT_ACTION_PLATFORM_USER_EMAIL_CHANGED,
        # two_factor_reset_service.py
        AUDIT_ACTION_PLATFORM_USER_TWO_FACTOR_RESET_BY_SUPERUSER,
        # trusted_device_service.py
        AUDIT_ACTION_AUTH_TRUSTED_DEVICE_REVOKE_ALL,
    }
)


def test_spec_011_audit_actions_do_not_trip_pii_detector() -> None:
    """No spec/011 audit-action string carries a PII pattern (A-13 safety net).

    The audit-action strings are service-private constants — they are
    not operator input — so the A-13 detector is not enforced at the
    schema layer for them. This regression guard pins the convention so
    a future maintainer cannot land a constant whose literal value
    embeds an email / phone / token (which would otherwise silently
    persist into ``project_audit_log.action`` plaintext).
    """
    for action in _SPEC_011_AUDIT_ACTIONS:
        assert not contains_pii(action), (
            f"audit-action constant {action!r} matches a PII pattern — "
            "rename the constant before merging"
        )


def test_banner_eligible_actions_register_spec_011_constants() -> None:
    """Every spec/011 invite/ownership accept action is banner-eligible.

    The user_banner activity-view consumer (FR-011-307) reads from a
    fixed allowlist. The bootstrap-transfer composite + the three
    accept variants MUST be members so the new owner can see the
    handoff event in their activity timeline.
    """
    required_banner_actions = {
        AUDIT_ACTION_MEMBER_INVITE_ACCEPTED,
        AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP,
        AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED,
        AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER,
    }
    missing = required_banner_actions - BANNER_ELIGIBLE_ACTIONS
    assert not missing, (
        f"banner-eligible actions missing spec/011 entries: {sorted(missing)} "
        "— update echoroo.services.user_banner.BANNER_ELIGIBLE_ACTIONS"
    )
