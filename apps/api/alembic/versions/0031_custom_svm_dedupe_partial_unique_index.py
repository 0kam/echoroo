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

Index creatability: at migration time the dev DB has 0 custom_svm rows and 0
duplicates, so the unique index builds cleanly. Alembic runs migrations inside a
transaction (``alembic/env.py``), so this uses a plain ``CREATE INDEX`` (NOT
``CONCURRENTLY``).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# Index name + the exact partial predicate. The writers' ``index_where=`` MUST
# match this predicate verbatim or PostgreSQL will not infer the index as the
# ON CONFLICT arbiter.
_INDEX_NAME = "uq_recording_annotations_custom_svm"
_PARTIAL_PREDICATE = "source = 'custom_svm' AND detection_run_id IS NOT NULL"


def upgrade() -> None:
    # PARTIAL UNIQUE index scoped to custom_svm inference rows. The predicate
    # restricts the constraint to that source only, leaving every other writer
    # (sampling_round / birdnet / perch / perch_search / similarity_search /
    # human) unaffected.
    op.create_index(
        _INDEX_NAME,
        "recording_annotations",
        ["recording_id", "tag_id", "start_time", "end_time", "detection_run_id"],
        unique=True,
        postgresql_where=sa.text(_PARTIAL_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="recording_annotations")
