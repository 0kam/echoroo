"""Phase 17 backlog A-2 — PII hash dual-write columns (FR-091b).

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-04 18:00:00.000000

Background
==========
The audit log + invitation hash columns are MAC outputs of the
``alias/echoroo-pii-hash-hmac`` CMK. Rotating that CMK without
downtime requires a dual-write window where every new row records
hashes under BOTH the v1 and v2 keys; lookups try v2 first then
fall back to v1. See ``apps/api/echoroo/core/kms.py`` (functions
``compute_pii_hash_dual`` / ``verify_pii_hash``) and the FR-091b
xfail tests in ``tests/security/key_rotation``.

This migration adds the sibling ``*_v2`` columns + a
``pii_hash_version`` discriminator + helper indexes. Existing v1
columns are *not* touched (the audit chain hash inputs include
``actor_user_id_hash``/``ip_hash``/``user_agent_hash`` and
re-writing them would break chain integrity for every historical
row). v2 columns are nullable so the schema deploys cleanly before
the dual-write code is enabled.

Affected tables
---------------
* ``platform_audit_log``    — actor / ip / user-agent hash siblings.
* ``project_audit_log``     — actor / ip / user-agent hash siblings.
* ``project_invitations``   — email_hash sibling.

Affected indexes
----------------
Only the actor lookup is hot-path on the audit logs (operator audit
search by user) — we add a partial index keyed on the v2 column
filtered to ``WHERE actor_user_id_hash_v2 IS NOT NULL`` so the index
is empty in single-key deployments and the planner ignores it. The
``email_hash_v2`` invitation lookup is also hot-path (FR-054 accept /
decline) and gets the same partial-index treatment. ``ip_hash_v2``
and ``user_agent_hash_v2`` get no index — neither column is used as
a search key today (T020, FR-091).

Privileges
----------
``ADD COLUMN`` inherits the table-level GRANTs already issued in
``0001_baseline_permissions_redesign`` (Codex Round-7 fix in 0015
documents the same invariant). No additional GRANT statement is
needed; partial indexes are not first-class privilege objects.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # -- platform_audit_log -------------------------------------------------
    op.add_column(
        "platform_audit_log",
        sa.Column("actor_user_id_hash_v2", sa.String(64), nullable=True),
    )
    op.add_column(
        "platform_audit_log",
        sa.Column("ip_hash_v2", sa.String(64), nullable=True),
    )
    op.add_column(
        "platform_audit_log",
        sa.Column("user_agent_hash_v2", sa.String(64), nullable=True),
    )
    op.add_column(
        "platform_audit_log",
        sa.Column("pii_hash_version", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_platform_audit_log_actor_v2",
        "platform_audit_log",
        ["actor_user_id_hash_v2", sa.text("created_at DESC")],
        postgresql_where=sa.text("actor_user_id_hash_v2 IS NOT NULL"),
    )

    # -- project_audit_log --------------------------------------------------
    op.add_column(
        "project_audit_log",
        sa.Column("actor_user_id_hash_v2", sa.String(64), nullable=True),
    )
    op.add_column(
        "project_audit_log",
        sa.Column("ip_hash_v2", sa.String(64), nullable=True),
    )
    op.add_column(
        "project_audit_log",
        sa.Column("user_agent_hash_v2", sa.String(64), nullable=True),
    )
    op.add_column(
        "project_audit_log",
        sa.Column("pii_hash_version", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_project_audit_log_actor_v2",
        "project_audit_log",
        ["actor_user_id_hash_v2", sa.text("created_at DESC")],
        postgresql_where=sa.text("actor_user_id_hash_v2 IS NOT NULL"),
    )

    # -- project_invitations -----------------------------------------------
    op.add_column(
        "project_invitations",
        sa.Column("email_hash_v2", sa.String(64), nullable=True),
    )
    op.add_column(
        "project_invitations",
        sa.Column("pii_hash_version", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_project_invitations_email_hash_v2",
        "project_invitations",
        ["email_hash_v2"],
        postgresql_where=sa.text("email_hash_v2 IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_invitations_email_hash_v2",
        table_name="project_invitations",
    )
    op.drop_column("project_invitations", "pii_hash_version")
    op.drop_column("project_invitations", "email_hash_v2")

    op.drop_index(
        "ix_project_audit_log_actor_v2",
        table_name="project_audit_log",
    )
    op.drop_column("project_audit_log", "pii_hash_version")
    op.drop_column("project_audit_log", "user_agent_hash_v2")
    op.drop_column("project_audit_log", "ip_hash_v2")
    op.drop_column("project_audit_log", "actor_user_id_hash_v2")

    op.drop_index(
        "ix_platform_audit_log_actor_v2",
        table_name="platform_audit_log",
    )
    op.drop_column("platform_audit_log", "pii_hash_version")
    op.drop_column("platform_audit_log", "user_agent_hash_v2")
    op.drop_column("platform_audit_log", "ip_hash_v2")
    op.drop_column("platform_audit_log", "actor_user_id_hash_v2")
