"""Phase 13 P0a: schema reconcile (ORM-only tables + 17 new enums + detections).

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-28 00:00:00.000000

This migration is the **static** product of Phase 13's three-way diff between
``Base.metadata.tables`` and the live ``information_schema``. It performs the
following idempotent operations to bring the live database in line with the
ORM canonical schema **without** disturbing the existing rows in the 19
already-common tables (which Phase 13 P1.5 reconciles separately):

1. Create the 17 ORM-only PostgreSQL ``ENUM`` types that the ORM-only tables
   need to reference (per the v5-final plan §0.2 & §2.1, names match the
   ``Enum(name=...)`` parameter on each ``mapped_column`` exactly).
2. Create the 32 ORM-only tables emitted directly by the ORM via
   ``Base.metadata`` (rendered once by ``scripts/gen_phase13_migration.py``;
   future ORM evolution must go into a new migration revision).
3. Re-emit ``detections`` (the only DB-only table that the ORM adopts as
   canonical in Phase 13) using ``CREATE TABLE IF NOT EXISTS`` so the live
   rows survive intact. Phase 14+ will rebind ``detections.taxon_id`` to a
   UUID FK to ``taxa.id``; the legacy stringified GBIF key column is
   preserved in this migration.

All ``CREATE TABLE`` and ``CREATE INDEX`` statements are guarded with
``IF NOT EXISTS`` so a fresh database that completes ``0001`` and replays
``0002..0009`` ends up in the same final shape as a long-lived dev database
that arrives at this revision starting from ``0005``.

The companion revision ``0006a`` (separate file, autocommit-required) widens
``detectionsource`` with the four new values.

Downgrade is a *partial* drop: only the ORM-only tables and the 17 ORM-only
enums are removed. ``detections`` is preserved on downgrade because its rows
predate this migration. A full schema teardown lives in ``scripts/wipe_database``.

Phase 13 inventory artifact: ``/tmp/phase13-inventory.md`` (T800).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# --------------------------------------------------------------------------- #
# Enum type definitions (Phase 13 P0a — 17 ORM-only enums)
# --------------------------------------------------------------------------- #
# Names MUST match the ``Enum(name=...)`` parameter on each ORM mapped column;
# see ``apps/api/echoroo/models/*.py``. The v5-final plan §0.2 captures the
# canonical snake_case names verified via the Phase 13 inventory (T800).
_PHASE13_ENUMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("datetimeparsestatus", ("pending", "success", "failed")),
    ("annotation_set_status", ("sampling", "ready", "in_progress", "completed")),
    ("annotation_segment_status", ("unannotated", "annotated", "skipped")),
    (
        "annotationtaskstatus",
        ("pending", "in_progress", "completed", "review_pending"),
    ),
    ("annotationprojectvisibility", ("private", "public")),
    ("reviewstatus", ("unreviewed", "approved", "rejected")),
    ("geometrytype", ("BoundingBox", "TimeInterval")),
    ("signalquality", ("solo", "dominant", "mixed")),
    (
        "consensusstatus",
        ("needs_votes", "agreed", "rejected", "disputed"),
    ),
    ("detectionrunstatus", ("pending", "running", "completed", "failed")),
    (
        "uploadsessionstatus",
        (
            "issued",
            "uploaded",
            "validating",
            "validated",
            "importing",
            "imported",
            "failed",
        ),
    ),
    (
        "uploadfilestatus",
        ("pending", "uploaded", "valid", "invalid", "imported"),
    ),
    ("searchsessionstatus", ("pending", "running", "completed", "failed")),
    ("setting_type", ("string", "number", "boolean", "json")),
    ("votetype", ("agree", "disagree", "unsure")),
    (
        "custommodelstatus",
        ("draft", "training", "trained", "deployed", "failed", "archived"),
    ),
    (
        "evaluation_run_status",
        ("pending", "running", "completed", "failed"),
    ),
)


def _create_enums(enums: tuple[tuple[str, tuple[str, ...]], ...]) -> None:
    bind = op.get_bind()
    for name, values in enums:
        sa.Enum(*values, name=name, create_type=True).create(bind, checkfirst=True)


def _drop_enums(enums: tuple[tuple[str, tuple[str, ...]], ...]) -> None:
    bind = op.get_bind()
    for name, _ in enums:
        sa.Enum(name=name).drop(bind, checkfirst=True)


# --------------------------------------------------------------------------- #
# Upgrade
# --------------------------------------------------------------------------- #


def upgrade() -> None:  # noqa: PLR0915 — generated DDL block, long by nature
    # Ensure the legacy crypto extension exists for ``gen_random_uuid()``
    # (also called from baseline 0001; harmless if already present).
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # Step 1 — create the 17 ORM-only enum types.
    _create_enums(_PHASE13_ENUMS)

    # Step 2 — create the ORM-only tables and the canonical ``detections``
    # table. Generated from ``Base.metadata`` via
    # ``scripts/gen_phase13_migration.py``. All statements are wrapped in
    # ``CREATE TABLE/INDEX IF NOT EXISTS`` so fresh-from-baseline DBs (where
    # 0001 will create everything in its final shape) and incrementally
    # upgraded dev DBs both reach the same final state.
    # ----- ORM-only tables (T801, generated from Base.metadata) -----
    # Total tables: 33

    # --- licenses ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS licenses (
	id VARCHAR(50) NOT NULL,
	name VARCHAR(200) NOT NULL,
	short_name VARCHAR(50) NOT NULL,
	url VARCHAR(500),
	description TEXT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id)
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_licenses_created_at ON licenses (created_at)
    """))

    # --- recorders ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS recorders (
	id VARCHAR(50) NOT NULL,
	manufacturer VARCHAR(100) NOT NULL,
	recorder_name VARCHAR(100) NOT NULL,
	version VARCHAR(50),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id)
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_recorders_created_at ON recorders (created_at)
    """))

    # --- taxa ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS taxa (
	scientific_name VARCHAR(300) NOT NULL,
	gbif_taxon_key INTEGER,
	rank VARCHAR(50),
	is_non_biological BOOLEAN NOT NULL,
	gbif_metadata JSONB,
	gbif_resolved_at TIMESTAMP WITH TIME ZONE,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (scientific_name)
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_taxa_scientific_name ON taxa (scientific_name)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_taxa_created_at ON taxa (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_taxa_is_non_biological ON taxa (is_non_biological)
    """))
    op.execute(sa.text("""
CREATE UNIQUE INDEX IF NOT EXISTS ix_taxa_gbif_taxon_key ON taxa (gbif_taxon_key) WHERE gbif_taxon_key IS NOT NULL
    """))

    # --- taxon_vernacular_names ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS taxon_vernacular_names (
	taxon_id UUID NOT NULL,
	locale VARCHAR(10) NOT NULL,
	name VARCHAR(300) NOT NULL,
	source VARCHAR(20) NOT NULL,
	is_primary BOOLEAN NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_taxon_vernacular_locale_source UNIQUE (taxon_id, locale, source),
	FOREIGN KEY(taxon_id) REFERENCES taxa (id) ON DELETE CASCADE
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_taxon_vernacular_names_locale_taxon_id ON taxon_vernacular_names (locale, taxon_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_taxon_vernacular_names_created_at ON taxon_vernacular_names (created_at)
    """))

    # --- annotation_projects ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS annotation_projects (
	project_id UUID NOT NULL,
	created_by_id UUID NOT NULL,
	name VARCHAR(200) NOT NULL,
	description TEXT,
	instructions TEXT,
	visibility annotationprojectvisibility NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_annotation_project_project_name UNIQUE (project_id, name),
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE,
	FOREIGN KEY(created_by_id) REFERENCES users (id)
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_annotation_projects_created_at ON annotation_projects (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_annotation_projects_project_id ON annotation_projects (project_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_annotation_projects_created_by_id ON annotation_projects (created_by_id)
    """))

    # --- search_sessions ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS search_sessions (
	project_id UUID NOT NULL,
	user_id UUID,
	name VARCHAR(200),
	status searchsessionstatus NOT NULL,
	model_name VARCHAR(100) NOT NULL,
	parameters JSONB,
	species_config JSONB,
	results JSONB,
	result_count INTEGER NOT NULL,
	confirmed_count INTEGER NOT NULL,
	rejected_count INTEGER NOT NULL,
	celery_job_id VARCHAR(100),
	reference_audio_keys JSONB,
	started_at TIMESTAMP WITH TIME ZONE,
	completed_at TIMESTAMP WITH TIME ZONE,
	error_message TEXT,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_search_sessions_created_at ON search_sessions (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_search_sessions_project_id ON search_sessions (project_id)
    """))
    op.execute(sa.text("""
CREATE UNIQUE INDEX IF NOT EXISTS ix_search_sessions_celery_job_id ON search_sessions (celery_job_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_search_sessions_user_id ON search_sessions (user_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_search_sessions_status ON search_sessions (status)
    """))

    # --- annotation_project_tags ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS annotation_project_tags (
	annotation_project_id UUID NOT NULL,
	tag_id UUID NOT NULL,
	PRIMARY KEY (annotation_project_id, tag_id),
	FOREIGN KEY(annotation_project_id) REFERENCES annotation_projects (id) ON DELETE CASCADE,
	FOREIGN KEY(tag_id) REFERENCES tags (id) ON DELETE CASCADE
)
    """))

    # --- search_query_embeddings ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS search_query_embeddings (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	search_session_id UUID NOT NULL,
	species_key TEXT,
	source_label TEXT,
	vector VECTOR(1536) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(search_session_id) REFERENCES search_sessions (id) ON DELETE CASCADE
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_search_query_embeddings_search_session_id ON search_query_embeddings (search_session_id)
    """))

    # --- annotation_project_datasets ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS annotation_project_datasets (
	annotation_project_id UUID NOT NULL,
	dataset_id UUID NOT NULL,
	PRIMARY KEY (annotation_project_id, dataset_id),
	FOREIGN KEY(annotation_project_id) REFERENCES annotation_projects (id) ON DELETE CASCADE,
	FOREIGN KEY(dataset_id) REFERENCES datasets (id) ON DELETE CASCADE
)
    """))

    # --- annotation_sets ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS annotation_sets (
	project_id UUID NOT NULL,
	dataset_id UUID NOT NULL,
	created_by_id UUID NOT NULL,
	name VARCHAR(200) NOT NULL,
	filter_date_range JSONB,
	filter_time_of_day_range JSONB,
	segment_length_sec INTEGER NOT NULL,
	num_segments INTEGER NOT NULL,
	status annotation_set_status DEFAULT 'sampling' NOT NULL,
	sampling_warning TEXT,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_annotation_sets_project_name UNIQUE (project_id, name),
	CONSTRAINT ck_annotation_sets_segment_length_min CHECK (segment_length_sec >= 10),
	CONSTRAINT ck_annotation_sets_num_segments_min CHECK (num_segments >= 1),
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE,
	FOREIGN KEY(dataset_id) REFERENCES datasets (id) ON DELETE CASCADE,
	FOREIGN KEY(created_by_id) REFERENCES users (id)
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_annotation_sets_status ON annotation_sets (status)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_annotation_sets_dataset_id ON annotation_sets (dataset_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_annotation_sets_created_at ON annotation_sets (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_annotation_sets_project_status ON annotation_sets (project_id, status)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_annotation_sets_project_id ON annotation_sets (project_id)
    """))

    # --- custom_models ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS custom_models (
	project_id UUID NOT NULL,
	user_id UUID,
	name VARCHAR(200) NOT NULL,
	description TEXT,
	target_tag_id UUID NOT NULL,
	model_type VARCHAR(100) NOT NULL,
	status custommodelstatus NOT NULL,
	training_config JSONB,
	hyperparameters JSONB,
	metrics JSONB,
	training_stats JSONB,
	model_artifact_key VARCHAR(500),
	embedding_model_name VARCHAR(100) NOT NULL,
	error_message TEXT,
	started_at TIMESTAMP WITH TIME ZONE,
	completed_at TIMESTAMP WITH TIME ZONE,
	search_session_id UUID,
	dataset_id UUID,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL,
	FOREIGN KEY(target_tag_id) REFERENCES tags (id) ON DELETE RESTRICT,
	FOREIGN KEY(search_session_id) REFERENCES search_sessions (id) ON DELETE SET NULL,
	FOREIGN KEY(dataset_id) REFERENCES datasets (id) ON DELETE SET NULL
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_custom_models_target_tag_id ON custom_models (target_tag_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_custom_models_project_id ON custom_models (project_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_custom_models_user_id ON custom_models (user_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_custom_models_search_session_id ON custom_models (search_session_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_custom_models_created_at ON custom_models (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_custom_models_status ON custom_models (status)
    """))

    # --- detection_runs ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS detection_runs (
	project_id UUID NOT NULL,
	dataset_id UUID,
	model_name VARCHAR(100) NOT NULL,
	model_version VARCHAR(50) NOT NULL,
	parameters JSONB,
	status detectionrunstatus NOT NULL,
	annotation_count INTEGER NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	completed_at TIMESTAMP WITH TIME ZONE,
	error_message TEXT,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE,
	FOREIGN KEY(dataset_id) REFERENCES datasets (id) ON DELETE SET NULL
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_detection_runs_project_id ON detection_runs (project_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_detection_runs_status ON detection_runs (status)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_detection_runs_created_at ON detection_runs (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_detection_runs_dataset_id ON detection_runs (dataset_id)
    """))

    # --- upload_sessions ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS upload_sessions (
	dataset_id UUID NOT NULL,
	created_by_id UUID NOT NULL,
	status uploadsessionstatus NOT NULL,
	total_files INTEGER NOT NULL,
	total_bytes BIGINT NOT NULL,
	validated_files INTEGER NOT NULL,
	imported_files INTEGER NOT NULL,
	error TEXT,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(dataset_id) REFERENCES datasets (id) ON DELETE CASCADE,
	FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE CASCADE
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_upload_sessions_created_at ON upload_sessions (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_upload_sessions_dataset_id ON upload_sessions (dataset_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_upload_sessions_status ON upload_sessions (status)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_upload_sessions_expires_at ON upload_sessions (expires_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_upload_sessions_dataset_id_status ON upload_sessions (dataset_id, status)
    """))

    # --- annotation_segments ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS annotation_segments (
	annotation_set_id UUID NOT NULL,
	recording_id UUID NOT NULL,
	start_time_sec FLOAT NOT NULL,
	end_time_sec FLOAT NOT NULL,
	is_empty BOOLEAN DEFAULT 'false' NOT NULL,
	status annotation_segment_status DEFAULT 'unannotated' NOT NULL,
	annotated_by_id UUID,
	annotated_at TIMESTAMP WITH TIME ZONE,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_annotation_segments_start_nonneg CHECK (start_time_sec >= 0),
	CONSTRAINT ck_annotation_segments_end_after_start CHECK (end_time_sec > start_time_sec),
	FOREIGN KEY(annotation_set_id) REFERENCES annotation_sets (id) ON DELETE CASCADE,
	FOREIGN KEY(recording_id) REFERENCES recordings (id) ON DELETE CASCADE,
	FOREIGN KEY(annotated_by_id) REFERENCES users (id) ON DELETE SET NULL
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_annotation_segments_created_at ON annotation_segments (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_annotation_segments_status ON annotation_segments (status)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_annotation_segments_set_status ON annotation_segments (annotation_set_id, status)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_annotation_segments_set_id ON annotation_segments (annotation_set_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_annotation_segments_recording_id ON annotation_segments (recording_id)
    """))

    # --- annotation_set_species_palette ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS annotation_set_species_palette (
	annotation_set_id UUID NOT NULL,
	taxon_id UUID NOT NULL,
	position INTEGER DEFAULT '0' NOT NULL,
	PRIMARY KEY (annotation_set_id, taxon_id),
	FOREIGN KEY(annotation_set_id) REFERENCES annotation_sets (id) ON DELETE CASCADE,
	FOREIGN KEY(taxon_id) REFERENCES taxa (id) ON DELETE CASCADE
)
    """))

    # --- clips ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS clips (
	recording_id UUID NOT NULL,
	start_time FLOAT NOT NULL,
	end_time FLOAT NOT NULL,
	note TEXT,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_clip_recording_time UNIQUE (recording_id, start_time, end_time),
	CONSTRAINT ck_clip_valid_time_range CHECK (end_time > start_time),
	FOREIGN KEY(recording_id) REFERENCES recordings (id) ON DELETE CASCADE
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_clips_recording_id ON clips (recording_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_clips_created_at ON clips (created_at)
    """))

    # --- confirmed_regions ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS confirmed_regions (
	recording_id UUID NOT NULL,
	start_time FLOAT NOT NULL,
	end_time FLOAT NOT NULL,
	reviewed_by_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(recording_id) REFERENCES recordings (id) ON DELETE CASCADE,
	FOREIGN KEY(reviewed_by_id) REFERENCES users (id) ON DELETE CASCADE
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_confirmed_regions_recording_id ON confirmed_regions (recording_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_confirmed_regions_created_at ON confirmed_regions (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_confirmed_regions_reviewed_by_id ON confirmed_regions (reviewed_by_id)
    """))

    # --- detections ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS detections (
	recording_id UUID NOT NULL,
	project_id UUID NOT NULL,
	taxon_id VARCHAR(64),
	source detectionsource NOT NULL,
	status detectionstatus DEFAULT 'unreviewed'::detectionstatus NOT NULL,
	start_time FLOAT NOT NULL,
	end_time FLOAT NOT NULL,
	confidence FLOAT,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(recording_id) REFERENCES recordings (id) ON DELETE CASCADE,
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_detections_created_at ON detections (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_detections_recording ON detections (recording_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_detections_project_taxon ON detections (project_id, taxon_id)
    """))

    # --- embeddings ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS embeddings (
	id UUID NOT NULL,
	recording_id UUID NOT NULL,
	detection_run_id UUID,
	model_name VARCHAR(100) NOT NULL,
	model_version VARCHAR(50),
	start_time FLOAT NOT NULL,
	end_time FLOAT NOT NULL,
	vector VECTOR(1536) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(recording_id) REFERENCES recordings (id) ON DELETE CASCADE,
	FOREIGN KEY(detection_run_id) REFERENCES detection_runs (id) ON DELETE SET NULL
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_embeddings_detection_run_id ON embeddings (detection_run_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_embeddings_recording_id ON embeddings (recording_id)
    """))

    # --- evaluation_runs ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS evaluation_runs (
	annotation_set_id UUID NOT NULL,
	created_by_id UUID NOT NULL,
	status evaluation_run_status DEFAULT 'pending' NOT NULL,
	requested_model_refs JSONB NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	completed_at TIMESTAMP WITH TIME ZONE,
	error_message TEXT,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(annotation_set_id) REFERENCES annotation_sets (id) ON DELETE CASCADE,
	FOREIGN KEY(created_by_id) REFERENCES users (id)
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_evaluation_runs_annotation_set_id ON evaluation_runs (annotation_set_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_evaluation_runs_created_at ON evaluation_runs (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_evaluation_runs_status ON evaluation_runs (status)
    """))

    # --- sampling_rounds ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS sampling_rounds (
	custom_model_id UUID NOT NULL,
	round_number INTEGER NOT NULL,
	round_type VARCHAR(20) NOT NULL,
	sampling_config JSONB,
	sample_count INTEGER NOT NULL,
	status VARCHAR(20) NOT NULL,
	job_id VARCHAR(255),
	error_message TEXT,
	completed_at TIMESTAMP WITH TIME ZONE,
	score_distribution JSONB,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(custom_model_id) REFERENCES custom_models (id) ON DELETE CASCADE
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_sampling_rounds_round_type ON sampling_rounds (round_type)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_sampling_rounds_created_at ON sampling_rounds (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_sampling_rounds_status ON sampling_rounds (status)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_sampling_rounds_custom_model_id ON sampling_rounds (custom_model_id)
    """))

    # --- upload_files ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS upload_files (
	session_id UUID NOT NULL,
	original_filename VARCHAR(255) NOT NULL,
	object_key VARCHAR(500) NOT NULL,
	file_size BIGINT NOT NULL,
	checksum_sha256 VARCHAR(64),
	status uploadfilestatus NOT NULL,
	content_type VARCHAR(100),
	duration FLOAT,
	samplerate INTEGER,
	channels INTEGER,
	bit_depth INTEGER,
	validation_error TEXT,
	recording_id UUID,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(session_id) REFERENCES upload_sessions (id) ON DELETE CASCADE,
	UNIQUE (object_key),
	FOREIGN KEY(recording_id) REFERENCES recordings (id) ON DELETE SET NULL
)
    """))
    op.execute(sa.text("""
CREATE UNIQUE INDEX IF NOT EXISTS ix_upload_files_object_key ON upload_files (object_key)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_upload_files_status ON upload_files (status)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_upload_files_recording_id ON upload_files (recording_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_upload_files_created_at ON upload_files (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_upload_files_session_id ON upload_files (session_id)
    """))

    # --- annotation_tasks ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS annotation_tasks (
	annotation_project_id UUID NOT NULL,
	clip_id UUID NOT NULL,
	assigned_to_id UUID,
	status annotationtaskstatus NOT NULL,
	priority INTEGER NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_annotation_task_project_clip UNIQUE (annotation_project_id, clip_id),
	FOREIGN KEY(annotation_project_id) REFERENCES annotation_projects (id) ON DELETE CASCADE,
	FOREIGN KEY(clip_id) REFERENCES clips (id) ON DELETE CASCADE,
	FOREIGN KEY(assigned_to_id) REFERENCES users (id) ON DELETE SET NULL
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_annotation_tasks_assigned_to_id ON annotation_tasks (assigned_to_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_annotation_tasks_created_at ON annotation_tasks (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_annotation_tasks_project_status ON annotation_tasks (annotation_project_id, status)
    """))

    # --- evaluation_results ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS evaluation_results (
	evaluation_run_id UUID NOT NULL,
	model_ref JSONB NOT NULL,
	taxon_id UUID,
	tp_precision INTEGER NOT NULL,
	fp INTEGER NOT NULL,
	tp_recall INTEGER NOT NULL,
	fn INTEGER NOT NULL,
	precision FLOAT NOT NULL,
	recall FLOAT NOT NULL,
	f1 FLOAT NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(evaluation_run_id) REFERENCES evaluation_runs (id) ON DELETE CASCADE,
	FOREIGN KEY(taxon_id) REFERENCES taxa (id) ON DELETE RESTRICT
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_evaluation_results_created_at ON evaluation_results (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_evaluation_results_run_id ON evaluation_results (evaluation_run_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_evaluation_results_run_taxon ON evaluation_results (evaluation_run_id, taxon_id)
    """))

    # --- sampling_round_items ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS sampling_round_items (
	sampling_round_id UUID NOT NULL,
	embedding_id UUID NOT NULL,
	sample_type VARCHAR(20) NOT NULL,
	similarity FLOAT,
	decision_distance FLOAT,
	annotation_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(sampling_round_id) REFERENCES sampling_rounds (id) ON DELETE CASCADE,
	FOREIGN KEY(embedding_id) REFERENCES embeddings (id) ON DELETE CASCADE,
	FOREIGN KEY(annotation_id) REFERENCES annotations (id) ON DELETE CASCADE
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_sampling_round_items_annotation_id ON sampling_round_items (annotation_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_sampling_round_items_sample_type ON sampling_round_items (sample_type)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_sampling_round_items_sampling_round_id ON sampling_round_items (sampling_round_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_sampling_round_items_created_at ON sampling_round_items (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_sampling_round_items_embedding_id ON sampling_round_items (embedding_id)
    """))

    # --- time_range_annotations ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS time_range_annotations (
	segment_id UUID NOT NULL,
	start_time_sec FLOAT NOT NULL,
	end_time_sec FLOAT NOT NULL,
	taxon_id UUID NOT NULL,
	confidence FLOAT,
	created_by_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_time_range_annotations_start_nonneg CHECK (start_time_sec >= 0),
	CONSTRAINT ck_time_range_annotations_end_after_start CHECK (end_time_sec > start_time_sec),
	CONSTRAINT ck_time_range_annotations_confidence_unit CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
	FOREIGN KEY(segment_id) REFERENCES annotation_segments (id) ON DELETE CASCADE,
	FOREIGN KEY(taxon_id) REFERENCES taxa (id) ON DELETE RESTRICT,
	FOREIGN KEY(created_by_id) REFERENCES users (id)
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_time_range_annotations_created_at ON time_range_annotations (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_time_range_annotations_segment_id ON time_range_annotations (segment_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_time_range_annotations_taxon_id ON time_range_annotations (taxon_id)
    """))

    # --- clip_annotations ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS clip_annotations (
	task_id UUID NOT NULL,
	clip_id UUID NOT NULL,
	created_by_id UUID NOT NULL,
	review_status reviewstatus NOT NULL,
	reviewed_by_id UUID,
	reviewed_at TIMESTAMP WITH TIME ZONE,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (task_id),
	FOREIGN KEY(task_id) REFERENCES annotation_tasks (id) ON DELETE CASCADE,
	FOREIGN KEY(clip_id) REFERENCES clips (id) ON DELETE CASCADE,
	FOREIGN KEY(created_by_id) REFERENCES users (id),
	FOREIGN KEY(reviewed_by_id) REFERENCES users (id) ON DELETE SET NULL
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_clip_annotations_created_at ON clip_annotations (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_clip_annotations_review_status ON clip_annotations (review_status)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_clip_annotations_clip_id ON clip_annotations (clip_id)
    """))

    # --- clip_annotation_tags ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS clip_annotation_tags (
	clip_annotation_id UUID NOT NULL,
	tag_id UUID NOT NULL,
	PRIMARY KEY (clip_annotation_id, tag_id),
	FOREIGN KEY(clip_annotation_id) REFERENCES clip_annotations (id) ON DELETE CASCADE,
	FOREIGN KEY(tag_id) REFERENCES tags (id) ON DELETE CASCADE
)
    """))

    # --- sound_event_annotations ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS sound_event_annotations (
	clip_annotation_id UUID NOT NULL,
	created_by_id UUID NOT NULL,
	geometry JSONB NOT NULL,
	source annotationsource NOT NULL,
	confidence FLOAT,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_sea_confidence_range CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
	FOREIGN KEY(clip_annotation_id) REFERENCES clip_annotations (id) ON DELETE CASCADE,
	FOREIGN KEY(created_by_id) REFERENCES users (id)
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_sound_event_annotations_created_at ON sound_event_annotations (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_sound_event_annotations_clip_annotation_id ON sound_event_annotations (clip_annotation_id)
    """))

    # --- notes ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS notes (
	created_by_id UUID NOT NULL,
	clip_annotation_id UUID,
	sound_event_annotation_id UUID,
	content TEXT NOT NULL,
	is_review BOOLEAN NOT NULL,
	is_issue BOOLEAN DEFAULT 'false' NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_note_not_both_parents CHECK (NOT (clip_annotation_id IS NOT NULL AND sound_event_annotation_id IS NOT NULL)),
	FOREIGN KEY(created_by_id) REFERENCES users (id),
	FOREIGN KEY(clip_annotation_id) REFERENCES clip_annotations (id) ON DELETE CASCADE,
	FOREIGN KEY(sound_event_annotation_id) REFERENCES sound_event_annotations (id) ON DELETE CASCADE
)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_notes_sound_event_annotation_id ON notes (sound_event_annotation_id)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_notes_created_at ON notes (created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX IF NOT EXISTS ix_notes_clip_annotation_id ON notes (clip_annotation_id)
    """))

    # --- sound_event_annotation_tags ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS sound_event_annotation_tags (
	sound_event_annotation_id UUID NOT NULL,
	tag_id UUID NOT NULL,
	PRIMARY KEY (sound_event_annotation_id, tag_id),
	FOREIGN KEY(sound_event_annotation_id) REFERENCES sound_event_annotations (id) ON DELETE CASCADE,
	FOREIGN KEY(tag_id) REFERENCES tags (id) ON DELETE CASCADE
)
    """))

    # --- annotation_segment_notes ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS annotation_segment_notes (
	segment_id UUID NOT NULL,
	note_id UUID NOT NULL,
	PRIMARY KEY (segment_id, note_id),
	FOREIGN KEY(segment_id) REFERENCES annotation_segments (id) ON DELETE CASCADE,
	FOREIGN KEY(note_id) REFERENCES notes (id) ON DELETE CASCADE
)
    """))

    # --- time_range_annotation_notes ---
    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS time_range_annotation_notes (
	annotation_id UUID NOT NULL,
	note_id UUID NOT NULL,
	PRIMARY KEY (annotation_id, note_id),
	FOREIGN KEY(annotation_id) REFERENCES time_range_annotations (id) ON DELETE CASCADE,
	FOREIGN KEY(note_id) REFERENCES notes (id) ON DELETE CASCADE
)
    """))


# --------------------------------------------------------------------------- #
# Downgrade — drop ORM-only tables only; keep ``detections`` and 17 enums
# untouched if anything else still depends on them.
# --------------------------------------------------------------------------- #


_ORM_ONLY_TABLES_REVERSE: tuple[str, ...] = (
    # Drop in reverse FK-dependency order. ``detections`` is intentionally
    # excluded — its rows predate Phase 13.
    "time_range_annotation_notes",
    "annotation_segment_notes",
    "sound_event_annotation_tags",
    "notes",
    "evaluation_results",
    "evaluation_runs",
    "custom_models",
    "search_query_embeddings",
    "search_sessions",
    "embeddings",
    "sampling_round_items",
    "sampling_rounds",
    "detection_runs",
    "confirmed_regions",
    "clip_annotation_tags",
    "clip_annotations",
    "clips",
    "sound_event_annotations",
    "time_range_annotations",
    "annotation_segments",
    "annotation_set_species_palette",
    "annotation_sets",
    "annotation_tasks",
    "annotation_project_tags",
    "annotation_project_datasets",
    "annotation_projects",
    "upload_files",
    "upload_sessions",
    "taxon_vernacular_names",
    "taxa",
    "recorders",
    "licenses",
)


def downgrade() -> None:
    for tname in _ORM_ONLY_TABLES_REVERSE:
        op.execute(sa.text(f'DROP TABLE IF EXISTS "{tname}" CASCADE'))
    _drop_enums(_PHASE13_ENUMS)
