"""Allow project audit history to outlive hard-deleted projects.

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-14 00:00:00.000000

``project_audit_log`` rows are append-only and their ``project_id`` value is
part of the audit chain hash. The project BFF keeps project deletion semantics
as a hard delete, so project-scoped audit rows must not hold a live FK to
``projects.id`` after the project is deleted.

The historical project id remains in ``project_audit_log.project_id`` and in
``detail.project_id`` for queryability. The FK is removed, while a BEFORE
INSERT trigger preserves the project existence check for new non-genesis rows.
The existing check constraint continues to require non-genesis project audit
rows to carry a project id.
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE project_audit_log
        DROP CONSTRAINT IF EXISTS project_audit_log_project_id_fkey
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_project_audit_log_project_exists()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.action <> 'genesis'
               AND NOT EXISTS (
                   SELECT 1
                   FROM projects p
                   WHERE p.id = NEW.project_id
               )
            THEN
                RAISE EXCEPTION
                    'project_audit_log.project_id must reference an existing project';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS project_audit_log_project_exists
        ON project_audit_log
        """
    )
    op.execute(
        """
        CREATE TRIGGER project_audit_log_project_exists
        BEFORE INSERT ON project_audit_log
        FOR EACH ROW
        EXECUTE FUNCTION validate_project_audit_log_project_exists()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS project_audit_log_project_exists
        ON project_audit_log
        """
    )
    op.execute(
        """
        DROP FUNCTION IF EXISTS validate_project_audit_log_project_exists()
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'project_audit_log'::regclass
                  AND conname = 'project_audit_log_project_id_fkey'
            ) AND NOT EXISTS (
                SELECT 1
                FROM project_audit_log pal
                WHERE pal.project_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM projects p
                      WHERE p.id = pal.project_id
                  )
            ) THEN
                ALTER TABLE project_audit_log
                ADD CONSTRAINT project_audit_log_project_id_fkey
                FOREIGN KEY (project_id)
                REFERENCES projects(id);
            END IF;
        END $$;
        """
    )
    # If audit rows already reference hard-deleted projects, restoring the FK
    # would require deleting or rewriting audit history. In that practical
    # downgrade case the schema remains FK-less to preserve the audit trail.
