"""Remove the legacy AnnotationProject workflow schema.

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-08

This forward-only migration removes the Whombat-derived
``AnnotationProject`` / ``AnnotationTask`` / ``ClipAnnotation`` /
``SoundEventAnnotation`` workflow. The current product workflow uses
``annotation_sets`` / ``annotation_segments`` / ``time_range_annotations``
and detection review tables instead.

Data-loss policy: legacy-only notes attached through ``notes.clip_annotation_id``
or ``notes.sound_event_annotation_id`` are deleted before those parent columns
are dropped. Notes already linked through the current
``annotation_segment_notes`` or ``time_range_annotation_notes`` join tables are
preserved and lose only the legacy parent pointer.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


LEGACY_TABLES: tuple[str, ...] = (
    "sound_event_annotation_tags",
    "clip_annotation_tags",
    "sound_event_annotations",
    "clip_annotations",
    "annotation_tasks",
    "annotation_project_tags",
    "annotation_project_datasets",
    "annotation_projects",
)

LEGACY_ENUM_TYPES: tuple[str, ...] = (
    "annotationprojectvisibility",
    "annotationtaskstatus",
    "reviewstatus",
    "geometrytype",
)


def _drop_constraint_if_exists(table_name: str, constraint_name: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = '{constraint_name}'
                AND conrelid = '{table_name}'::regclass
            ) THEN
                ALTER TABLE "{table_name}" DROP CONSTRAINT "{constraint_name}";
            END IF;
        END
        $$;
        """
    )


def _drop_index_if_exists(index_name: str) -> None:
    op.execute(sa.text(f'DROP INDEX IF EXISTS "{index_name}"'))


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = '{table_name}'
                AND column_name = '{column_name}'
            ) THEN
                ALTER TABLE "{table_name}" DROP COLUMN "{column_name}";
            END IF;
        END
        $$;
        """
    )


def _drop_table_if_exists(table_name: str) -> None:
    op.execute(sa.text(f'DROP TABLE IF EXISTS "{table_name}"'))


def _drop_enum_type_if_unused(type_name: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_type t
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE n.nspname = 'public'
                AND t.typname = '{type_name}'
            )
            AND NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND udt_name = '{type_name}'
            ) THEN
                DROP TYPE "{type_name}";
            END IF;
        END
        $$;
        """
    )


def _remove_legacy_note_parent_columns() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = 'notes'
                AND column_name = 'clip_annotation_id'
            )
            AND EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = 'notes'
                AND column_name = 'sound_event_annotation_id'
            ) THEN
                EXECUTE $SQL$
                    DELETE FROM notes n
                    WHERE (
                        n.clip_annotation_id IS NOT NULL
                        OR n.sound_event_annotation_id IS NOT NULL
                    )
                    AND NOT EXISTS (
                        SELECT 1
                        FROM annotation_segment_notes asn
                        WHERE asn.note_id = n.id
                    )
                    AND NOT EXISTS (
                        SELECT 1
                        FROM time_range_annotation_notes tran
                        WHERE tran.note_id = n.id
                    )
                $SQL$;
            END IF;
        END
        $$;
        """
    )

    _drop_index_if_exists("ix_notes_clip_annotation_id")
    _drop_index_if_exists("ix_notes_sound_event_annotation_id")
    _drop_constraint_if_exists("notes", "ck_note_not_both_parents")
    _drop_constraint_if_exists("notes", "notes_clip_annotation_id_fkey")
    _drop_constraint_if_exists("notes", "notes_sound_event_annotation_id_fkey")
    _drop_column_if_exists("notes", "clip_annotation_id")
    _drop_column_if_exists("notes", "sound_event_annotation_id")


def upgrade() -> None:
    _remove_legacy_note_parent_columns()

    for table_name in LEGACY_TABLES:
        _drop_table_if_exists(table_name)

    for type_name in LEGACY_ENUM_TYPES:
        _drop_enum_type_if_unused(type_name)


def downgrade() -> None:
    raise NotImplementedError(
        "Migration 0025 is forward-only. Legacy AnnotationProject workflow "
        "data and note parent columns are removed; restore from backup if "
        "rollback is required."
    )
