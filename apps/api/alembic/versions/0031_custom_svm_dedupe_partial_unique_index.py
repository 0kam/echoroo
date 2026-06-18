"""Partial unique index deduplicating custom-SVM inference annotations.

Revision ID: 0031
Revises: 0030
Create Date: 2026-06-18

DB-level idempotency guard for custom-SVM model-inference rows in
``recording_annotations``.

Several sources write ``recording_annotations``. The custom-SVM inference
writers (``echoroo.workers.ml.utils._bulk_insert_annotations`` and the two
batch inserts in ``echoroo.workers.classifier_tasks._run_custom_model_inference``)
used ``pg_insert(...).on_conflict_do_nothing()`` WITHOUT a conflict target, so
PostgreSQL arbitrated on the primary key only. Each inference run mints fresh
``uuid4`` ids, so the PK conflict never fired and re-running the same
``detection_run`` DUPLICATED every detection row.

This migration adds a PARTIAL UNIQUE index scoped (via its ``WHERE`` predicate)
to ``source = 'custom_svm'``. The custom-SVM writers are wired to name this
index as their ``ON CONFLICT`` arbiter (``index_elements`` + matching
``index_where``), so a re-run of the same run skips the already-present rows
instead of accumulating them.

The partial predicate scopes the constraint to custom_svm ONLY. Every other
writer (``sampling_round`` / ``birdnet`` / ``perch`` / ``perch_search`` /
``similarity_search`` / ``human``) falls OUTSIDE the predicate and is therefore
completely unaffected — those sources can still create rows with identical
``(recording_id, tag_id, start_time, end_time)`` tuples (e.g. seed-sampling / AL
rows whose ``detection_run_id`` is NULL).

The ``AND detection_run_id IS NOT NULL`` clause is included defensively: every
custom_svm row produced by the inference pipeline already carries a non-null
``detection_run_id`` (``classifier_tasks`` always sets it), so this clause
excludes nothing real. A hypothetical NULL-``detection_run_id`` custom_svm row
would be btree-distinct anyway (NULLs never collide in a unique index), so
constraining it would be pointless; excluding it keeps the predicate explicit
and self-documenting.

Index creatability: a DB that has already run custom_svm inference may carry
EXACT-duplicate rows produced by re-running the same ``detection_run`` before
this guard existed. ``CREATE UNIQUE INDEX`` over those would fail, so the
upgrade FIRST deduplicates the pre-existing custom_svm rows (keeping one
deterministic representative per conflict group) and only then creates the
index. The dedup DELETE is a no-op on a clean DB (e.g. the dev DB at migration
time, which has 0 custom_svm rows). Alembic runs migrations inside a
transaction (``alembic/env.py``), so this uses a plain ``CREATE INDEX`` (NOT
``CONCURRENTLY``).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# FROZEN SNAPSHOT — migration immutability principle.
#
# The index name / columns / partial predicate below are INLINE LITERALS that
# captured the values of ``CUSTOM_SVM_DEDUP_INDEX_NAME`` /
# ``CUSTOM_SVM_DEDUP_INDEX_ELEMENTS`` / ``CUSTOM_SVM_DEDUP_INDEX_WHERE`` at the
# time this migration was authored. They are deliberately NOT imported from
# ``echoroo.models.recording_annotation`` so that a future edit to those model
# constants can never silently change this historical migration's behavior.
#
# The LIVE writers (``workers.ml.utils._bulk_insert_annotations`` and the two
# batch inserts in ``workers.classifier_tasks._run_custom_model_inference``)
# continue to use the shared ``CUSTOM_SVM_DEDUP_INDEX_*`` constants in
# ``echoroo/models/recording_annotation.py`` as their ON CONFLICT arbiter. These
# inline literals MUST stay byte-identical to those constants. Any future change
# to the index definition must be a NEW migration — do NOT edit these literals.

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_INDEX_NAME = "uq_recording_annotations_custom_svm"
_PARTIAL_PREDICATE = "source = 'custom_svm' AND detection_run_id IS NOT NULL"
_INDEX_COLUMNS = [
    "recording_id",
    "tag_id",
    "start_time",
    "end_time",
    "detection_run_id",
]


def upgrade() -> None:
    # Pre-launch: a DB that already ran custom_svm inference can hold EXACT
    # re-run artifact duplicates (same conflict tuple, distinct uuid4 ids)
    # because the old ON CONFLICT DO NOTHING arbitrated on the PK only. Those
    # would make the unique index un-buildable, so delete the duplicates here,
    # keeping ONE deterministic representative per conflict group: the earliest
    # ``created_at`` row, with ``id`` (cast to text) as a deterministic
    # tiebreaker (PostgreSQL has no ``MIN(uuid)`` aggregate, and ties on
    # ``created_at`` are possible). The DELETE is scoped to the EXACT index
    # predicate (custom_svm + non-null detection_run_id) so it touches nothing
    # outside the index's domain, and is a no-op when there are no duplicates
    # (idempotent / safe on a clean DB).
    #
    # FK-cascade note (pre-launch data policy): any annotation_votes / comments
    # attached to a deleted duplicate row cascade away with it. This is accepted
    # — these are exact re-run artifacts, not distinct human-reviewed rows.
    op.execute(
        sa.text(
            """
            DELETE FROM recording_annotations a
            USING (
                SELECT id
                FROM (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY
                                recording_id,
                                tag_id,
                                start_time,
                                end_time,
                                detection_run_id
                            ORDER BY created_at ASC, id::text ASC
                        ) AS rn
                    FROM recording_annotations
                    WHERE source = 'custom_svm'
                      AND detection_run_id IS NOT NULL
                      -- NULL-distinct semantics: the partial UNIQUE index treats
                      -- NULL tag_id rows as DISTINCT (they never collide), so a
                      -- group of NULL-tag_id custom_svm rows is index-legal and
                      -- must NOT be collapsed. Excluding them here makes the
                      -- dedup faithful to the index. Do NOT "simplify" this away.
                      AND tag_id IS NOT NULL
                ) ranked
                WHERE ranked.rn > 1
            ) dup
            WHERE a.id = dup.id
            """
        )
    )

    # PARTIAL UNIQUE index scoped to custom_svm inference rows. The predicate
    # restricts the constraint to that source only, leaving every other writer
    # (sampling_round / birdnet / perch / perch_search / similarity_search /
    # human) unaffected.
    op.create_index(
        _INDEX_NAME,
        "recording_annotations",
        _INDEX_COLUMNS,
        unique=True,
        postgresql_where=sa.text(_PARTIAL_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="recording_annotations")
