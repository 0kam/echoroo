"""Align H3 resolution ranges for sites and Restricted public precision.

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-14 00:00:00.000000

Site ``h3_index_member_resolution`` used to be limited to the two legacy
member precision values 9 and 15. The API now stores any H3 resolution in the
valid site range, 5 through 15, while keeping the default at 15.

Restricted ``public_location_precision_h3_res`` also moved away from the old
HIDDEN-like default 2. Existing project JSONB blobs with value 2 are advanced
to the new range minimum, 3.
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE sites
        DROP CONSTRAINT IF EXISTS ck_sites_h3_member_resolution
        """
    )
    op.execute(
        """
        ALTER TABLE sites
        ADD CONSTRAINT ck_sites_h3_member_resolution
        CHECK (h3_index_member_resolution BETWEEN 5 AND 15)
        """
    )
    op.execute(
        """
        UPDATE projects
        SET restricted_config = jsonb_set(
            restricted_config,
            '{public_location_precision_h3_res}',
            '3'::jsonb,
            true
        )
        WHERE restricted_config ? 'public_location_precision_h3_res'
          AND restricted_config->>'public_location_precision_h3_res' = '2'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM sites
                WHERE h3_index_member_resolution IS NOT NULL
                  AND h3_index_member_resolution NOT IN (9, 15)
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade 0018: sites contain H3 member resolutions outside legacy values 9 and 15';
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM projects
                WHERE restricted_config ? 'public_location_precision_h3_res'
                  AND (
                    restricted_config->>'public_location_precision_h3_res' IS NULL
                    OR restricted_config->>'public_location_precision_h3_res'
                        NOT IN ('2', '3', '5', '7', '9', '15')
                  )
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade 0018: projects contain restricted public H3 precision outside legacy values 2, 5, 7, 9, and 15';
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        ALTER TABLE sites
        DROP CONSTRAINT IF EXISTS ck_sites_h3_member_resolution
        """
    )
    op.execute(
        """
        ALTER TABLE sites
        ADD CONSTRAINT ck_sites_h3_member_resolution
        CHECK (h3_index_member_resolution IN (9, 15))
        """
    )
    op.execute(
        """
        UPDATE projects
        SET restricted_config = jsonb_set(
            restricted_config,
            '{public_location_precision_h3_res}',
            '2'::jsonb,
            true
        )
        WHERE restricted_config ? 'public_location_precision_h3_res'
          AND restricted_config->>'public_location_precision_h3_res' = '3'
        """
    )
