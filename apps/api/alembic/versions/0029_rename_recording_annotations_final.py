"""Finalise the canonical detection/vote table name (drop ``_DEFERRED`` suffix).

Revision ID: 0029
Revises: 0028
Create Date: 2026-06-11

P3 of the annotation-consolidation effort. Migration 0011 materialised the
canonical recording-level annotation table under the *transitional* name
``recording_annotations_DEFERRED`` (double-quoted so PostgreSQL preserved the
mixed-case ``_DEFERRED`` suffix). The ``_DEFERRED`` suffix was always a
placeholder, NOT a marker that the table is absent: it is actively written and
read at runtime (ML classifier, search-session review, detection review grid,
cross-model evaluation, detection export) and the vote / comment FKs were
repointed onto it in migration 0028.

This migration renames the table to its final canonical name
``recording_annotations`` and brings every dependent identifier (PK, the five
outgoing FK constraints, and the one ``deferred``-carrying index) in line with
the names a fresh ``Base.metadata.create_all`` of the updated model produces,
so a fresh-from-migrations DB and an incrementally-upgraded DB land on the same
schema (the R3 parity test is the authoritative check).

Scope is RENAME ONLY. No unique/dedupe constraint is added here (deferred: a
uniqueness constraint risks breaking multi-run ML emits). Column definitions,
FK targets, and behaviour are unchanged.

Identifier note: the source table / PK / FK / index identifiers carry the
mixed-case ``DEFERRED`` token and must be double-quoted in raw SQL so
PostgreSQL matches the case-sensitive names. The ``ix_*deferred*`` index was
created by migration 0011 with an *unquoted* identifier, so PostgreSQL folded
it to all-lowercase ``ix_recording_annotations_deferred_search_session_id``.

``annotation_votes`` / ``annotation_comments`` incoming FKs are NOT recreated
here: ``ALTER TABLE ... RENAME TO`` updates their referenced-table pointer
automatically (the FK follows the table OID), so they transparently come to
reference ``recording_annotations`` after the rename.
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # --- Table rename ---------------------------------------------------- #
    # The incoming FKs from annotation_votes / annotation_comments follow the
    # table OID automatically and need no recreation.
    op.execute(
        'ALTER TABLE "recording_annotations_DEFERRED" '
        "RENAME TO recording_annotations;"
    )

    # --- Primary key ----------------------------------------------------- #
    op.execute(
        "ALTER TABLE recording_annotations "
        'RENAME CONSTRAINT "recording_annotations_DEFERRED_pkey" '
        "TO recording_annotations_pkey;"
    )

    # --- Outgoing foreign keys (5) --------------------------------------- #
    op.execute(
        "ALTER TABLE recording_annotations "
        'RENAME CONSTRAINT "recording_annotations_DEFERRED_recording_id_fkey" '
        "TO recording_annotations_recording_id_fkey;"
    )
    op.execute(
        "ALTER TABLE recording_annotations "
        'RENAME CONSTRAINT "recording_annotations_DEFERRED_tag_id_fkey" '
        "TO recording_annotations_tag_id_fkey;"
    )
    op.execute(
        "ALTER TABLE recording_annotations "
        'RENAME CONSTRAINT '
        '"recording_annotations_DEFERRED_detection_run_id_fkey" '
        "TO recording_annotations_detection_run_id_fkey;"
    )
    op.execute(
        "ALTER TABLE recording_annotations "
        'RENAME CONSTRAINT "recording_annotations_DEFERRED_reviewed_by_id_fkey" '
        "TO recording_annotations_reviewed_by_id_fkey;"
    )
    op.execute(
        "ALTER TABLE recording_annotations "
        'RENAME CONSTRAINT '
        '"recording_annotations_DEFERRED_search_session_id_fkey" '
        "TO recording_annotations_search_session_id_fkey;"
    )

    # --- Deferred-carrying index ----------------------------------------- #
    # Created unquoted in migration 0011, so its stored name is all-lowercase.
    # Rename to the name a fresh create_all of the renamed model produces.
    op.execute(
        "ALTER INDEX ix_recording_annotations_deferred_search_session_id "
        "RENAME TO ix_recording_annotations_search_session_id;"
    )


def downgrade() -> None:
    # Reverse the index rename first, then the constraints, then the table.
    op.execute(
        "ALTER INDEX ix_recording_annotations_search_session_id "
        "RENAME TO ix_recording_annotations_deferred_search_session_id;"
    )

    op.execute(
        "ALTER TABLE recording_annotations "
        "RENAME CONSTRAINT recording_annotations_search_session_id_fkey "
        'TO "recording_annotations_DEFERRED_search_session_id_fkey";'
    )
    op.execute(
        "ALTER TABLE recording_annotations "
        "RENAME CONSTRAINT recording_annotations_reviewed_by_id_fkey "
        'TO "recording_annotations_DEFERRED_reviewed_by_id_fkey";'
    )
    op.execute(
        "ALTER TABLE recording_annotations "
        "RENAME CONSTRAINT recording_annotations_detection_run_id_fkey "
        'TO "recording_annotations_DEFERRED_detection_run_id_fkey";'
    )
    op.execute(
        "ALTER TABLE recording_annotations "
        "RENAME CONSTRAINT recording_annotations_tag_id_fkey "
        'TO "recording_annotations_DEFERRED_tag_id_fkey";'
    )
    op.execute(
        "ALTER TABLE recording_annotations "
        "RENAME CONSTRAINT recording_annotations_recording_id_fkey "
        'TO "recording_annotations_DEFERRED_recording_id_fkey";'
    )

    op.execute(
        "ALTER TABLE recording_annotations "
        "RENAME CONSTRAINT recording_annotations_pkey "
        'TO "recording_annotations_DEFERRED_pkey";'
    )

    op.execute(
        "ALTER TABLE recording_annotations "
        'RENAME TO "recording_annotations_DEFERRED";'
    )
