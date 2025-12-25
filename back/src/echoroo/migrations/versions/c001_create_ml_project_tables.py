"""Create ML Project tables.

Revision ID: c001_create_ml_project
Revises: b1c2d3e4f5a6
Create Date: 2025-12-06 10:00:00.000000

This migration creates the ML Project feature tables:
- ml_project: Core ML project entity
- ml_project_tag: Junction table for project-tag relationships
- reference_sound: Reference audio clips for similarity search
- search_session: Similarity search operations
- search_session_reference_sound: Junction for session-reference relationships
- search_result: Individual search matches with labels
- custom_model: Trained classifiers
- inference_batch: Batch inference operations
- inference_prediction: Individual model predictions
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c001_create_ml_project"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create ENUM types
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'ml_project_status') THEN
                CREATE TYPE ml_project_status AS ENUM ('setup', 'searching', 'labeling', 'training', 'inference', 'review', 'completed', 'archived');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'reference_sound_source') THEN
                CREATE TYPE reference_sound_source AS ENUM ('xeno_canto', 'custom_upload', 'dataset_clip');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'search_result_label') THEN
                CREATE TYPE search_result_label AS ENUM ('unlabeled', 'positive', 'negative', 'uncertain', 'skipped');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'custom_model_type') THEN
                CREATE TYPE custom_model_type AS ENUM ('logistic_regression', 'svm_linear', 'mlp_small', 'mlp_medium', 'random_forest');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'custom_model_status') THEN
                CREATE TYPE custom_model_status AS ENUM ('draft', 'training', 'trained', 'failed', 'deployed', 'archived');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'inference_batch_status') THEN
                CREATE TYPE inference_batch_status AS ENUM ('pending', 'running', 'completed', 'failed', 'cancelled');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'inference_prediction_review_status') THEN
                CREATE TYPE inference_prediction_review_status AS ENUM ('unreviewed', 'confirmed', 'rejected', 'uncertain');
            END IF;
        END
        $$;
    """)

    # Create ml_project table
    op.execute("""
        CREATE TABLE ml_project (
            id SERIAL PRIMARY KEY,
            uuid UUID NOT NULL UNIQUE,
            name VARCHAR NOT NULL,
            description TEXT,
            dataset_id INTEGER NOT NULL REFERENCES dataset(id) ON DELETE RESTRICT,
            project_id VARCHAR NOT NULL REFERENCES project(project_id) ON DELETE RESTRICT,
            embedding_model_run_id INTEGER REFERENCES model_run(id) ON DELETE SET NULL,
            status ml_project_status NOT NULL DEFAULT 'setup',
            default_similarity_threshold FLOAT NOT NULL DEFAULT 0.7,
            created_by_id UUID NOT NULL REFERENCES "user"(id),
            created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_on TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX ix_ml_project_dataset_id ON ml_project(dataset_id)")
    op.execute("CREATE INDEX ix_ml_project_project_id ON ml_project(project_id)")
    op.execute("CREATE INDEX ix_ml_project_status ON ml_project(status)")
    op.execute("CREATE INDEX ix_ml_project_created_by_id ON ml_project(created_by_id)")

    # Create ml_project_tag junction table
    op.execute("""
        CREATE TABLE ml_project_tag (
            ml_project_id INTEGER NOT NULL REFERENCES ml_project(id) ON DELETE CASCADE,
            tag_id INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
            PRIMARY KEY (ml_project_id, tag_id),
            UNIQUE (ml_project_id, tag_id)
        )
    """)
    op.execute("CREATE INDEX ix_ml_project_tag_ml_project_id ON ml_project_tag(ml_project_id)")
    op.execute("CREATE INDEX ix_ml_project_tag_tag_id ON ml_project_tag(tag_id)")

    # Create reference_sound table
    op.execute("""
        CREATE TABLE reference_sound (
            id SERIAL PRIMARY KEY,
            uuid UUID NOT NULL UNIQUE,
            name VARCHAR NOT NULL,
            description TEXT,
            ml_project_id INTEGER NOT NULL REFERENCES ml_project(id) ON DELETE CASCADE,
            source reference_sound_source NOT NULL,
            xeno_canto_id VARCHAR,
            xeno_canto_url VARCHAR,
            audio_path VARCHAR,
            clip_id INTEGER REFERENCES clip(id) ON DELETE SET NULL,
            tag_id INTEGER NOT NULL REFERENCES tag(id) ON DELETE RESTRICT,
            start_time FLOAT NOT NULL DEFAULT 0.0,
            end_time FLOAT NOT NULL,
            embedding vector(1536),
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_by_id UUID NOT NULL REFERENCES "user"(id),
            created_on TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX ix_reference_sound_ml_project_id ON reference_sound(ml_project_id)")
    op.execute("CREATE INDEX ix_reference_sound_tag_id ON reference_sound(tag_id)")
    op.execute("CREATE INDEX ix_reference_sound_clip_id ON reference_sound(clip_id)")
    op.execute("CREATE INDEX ix_reference_sound_source ON reference_sound(source)")
    op.execute("CREATE INDEX ix_reference_sound_is_active ON reference_sound(is_active)")
    op.execute("CREATE INDEX ix_reference_sound_embedding_hnsw ON reference_sound USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)")

    # Create search_session table
    op.execute("""
        CREATE TABLE search_session (
            id SERIAL PRIMARY KEY,
            uuid UUID NOT NULL UNIQUE,
            name VARCHAR NOT NULL,
            description TEXT,
            ml_project_id INTEGER NOT NULL REFERENCES ml_project(id) ON DELETE CASCADE,
            target_tag_id INTEGER NOT NULL REFERENCES tag(id) ON DELETE RESTRICT,
            similarity_threshold FLOAT NOT NULL DEFAULT 0.7,
            max_results INTEGER NOT NULL DEFAULT 1000,
            filter_config JSONB,
            is_search_complete BOOLEAN NOT NULL DEFAULT false,
            is_labeling_complete BOOLEAN NOT NULL DEFAULT false,
            created_by_id UUID NOT NULL REFERENCES "user"(id),
            created_on TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX ix_search_session_ml_project_id ON search_session(ml_project_id)")
    op.execute("CREATE INDEX ix_search_session_target_tag_id ON search_session(target_tag_id)")
    op.execute("CREATE INDEX ix_search_session_is_search_complete ON search_session(is_search_complete)")
    op.execute("CREATE INDEX ix_search_session_is_labeling_complete ON search_session(is_labeling_complete)")

    # Create search_session_reference_sound junction table
    op.execute("""
        CREATE TABLE search_session_reference_sound (
            search_session_id INTEGER NOT NULL REFERENCES search_session(id) ON DELETE CASCADE,
            reference_sound_id INTEGER NOT NULL REFERENCES reference_sound(id) ON DELETE CASCADE,
            PRIMARY KEY (search_session_id, reference_sound_id),
            UNIQUE (search_session_id, reference_sound_id)
        )
    """)
    op.execute("CREATE INDEX ix_search_session_reference_sound_session_id ON search_session_reference_sound(search_session_id)")
    op.execute("CREATE INDEX ix_search_session_reference_sound_ref_id ON search_session_reference_sound(reference_sound_id)")

    # Create search_result table
    op.execute("""
        CREATE TABLE search_result (
            id SERIAL PRIMARY KEY,
            uuid UUID NOT NULL UNIQUE,
            search_session_id INTEGER NOT NULL REFERENCES search_session(id) ON DELETE CASCADE,
            clip_id INTEGER NOT NULL REFERENCES clip(id) ON DELETE CASCADE,
            similarity FLOAT NOT NULL,
            rank INTEGER NOT NULL,
            label search_result_label NOT NULL DEFAULT 'unlabeled',
            labeled_by_id UUID REFERENCES "user"(id),
            labeled_on TIMESTAMPTZ,
            notes TEXT,
            created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (search_session_id, clip_id)
        )
    """)
    op.execute("CREATE INDEX ix_search_result_search_session_id ON search_result(search_session_id)")
    op.execute("CREATE INDEX ix_search_result_clip_id ON search_result(clip_id)")
    op.execute("CREATE INDEX ix_search_result_label ON search_result(label)")
    op.execute("CREATE INDEX ix_search_result_similarity ON search_result(similarity)")
    op.execute("CREATE INDEX ix_search_result_rank ON search_result(rank)")
    op.execute("CREATE INDEX ix_search_result_session_label_rank ON search_result(search_session_id, label, rank)")

    # Create custom_model table
    op.execute("""
        CREATE TABLE custom_model (
            id SERIAL PRIMARY KEY,
            uuid UUID NOT NULL UNIQUE,
            name VARCHAR NOT NULL,
            description TEXT,
            ml_project_id INTEGER NOT NULL REFERENCES ml_project(id) ON DELETE CASCADE,
            target_tag_id INTEGER NOT NULL REFERENCES tag(id) ON DELETE RESTRICT,
            model_type custom_model_type NOT NULL,
            hyperparameters JSONB,
            status custom_model_status NOT NULL DEFAULT 'draft',
            training_session_ids JSONB,
            training_samples INTEGER,
            validation_samples INTEGER,
            accuracy FLOAT,
            "precision" FLOAT,
            recall FLOAT,
            f1_score FLOAT,
            confusion_matrix JSONB,
            model_path VARCHAR,
            training_started_on TIMESTAMPTZ,
            training_completed_on TIMESTAMPTZ,
            error_message TEXT,
            created_by_id UUID NOT NULL REFERENCES "user"(id),
            created_on TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX ix_custom_model_ml_project_id ON custom_model(ml_project_id)")
    op.execute("CREATE INDEX ix_custom_model_target_tag_id ON custom_model(target_tag_id)")
    op.execute("CREATE INDEX ix_custom_model_status ON custom_model(status)")
    op.execute("CREATE INDEX ix_custom_model_model_type ON custom_model(model_type)")

    # Create inference_batch table
    op.execute("""
        CREATE TABLE inference_batch (
            id SERIAL PRIMARY KEY,
            uuid UUID NOT NULL UNIQUE,
            name VARCHAR NOT NULL,
            description TEXT,
            ml_project_id INTEGER NOT NULL REFERENCES ml_project(id) ON DELETE CASCADE,
            custom_model_id INTEGER NOT NULL REFERENCES custom_model(id) ON DELETE CASCADE,
            filter_config JSONB,
            confidence_threshold FLOAT NOT NULL DEFAULT 0.5,
            batch_size INTEGER NOT NULL DEFAULT 1000,
            status inference_batch_status NOT NULL DEFAULT 'pending',
            progress FLOAT NOT NULL DEFAULT 0.0,
            total_items INTEGER NOT NULL DEFAULT 0,
            processed_items INTEGER NOT NULL DEFAULT 0,
            positive_predictions INTEGER NOT NULL DEFAULT 0,
            started_on TIMESTAMPTZ,
            completed_on TIMESTAMPTZ,
            error_message TEXT,
            created_by_id UUID NOT NULL REFERENCES "user"(id),
            created_on TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX ix_inference_batch_ml_project_id ON inference_batch(ml_project_id)")
    op.execute("CREATE INDEX ix_inference_batch_custom_model_id ON inference_batch(custom_model_id)")
    op.execute("CREATE INDEX ix_inference_batch_status ON inference_batch(status)")

    # Create inference_prediction table
    op.execute("""
        CREATE TABLE inference_prediction (
            id SERIAL PRIMARY KEY,
            uuid UUID NOT NULL UNIQUE,
            inference_batch_id INTEGER NOT NULL REFERENCES inference_batch(id) ON DELETE CASCADE,
            clip_id INTEGER NOT NULL REFERENCES clip(id) ON DELETE CASCADE,
            confidence FLOAT NOT NULL,
            predicted_positive BOOLEAN NOT NULL,
            review_status inference_prediction_review_status NOT NULL DEFAULT 'unreviewed',
            reviewed_by_id UUID REFERENCES "user"(id),
            reviewed_on TIMESTAMPTZ,
            notes TEXT,
            created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (inference_batch_id, clip_id)
        )
    """)
    op.execute("CREATE INDEX ix_inference_prediction_inference_batch_id ON inference_prediction(inference_batch_id)")
    op.execute("CREATE INDEX ix_inference_prediction_clip_id ON inference_prediction(clip_id)")
    op.execute("CREATE INDEX ix_inference_prediction_review_status ON inference_prediction(review_status)")
    op.execute("CREATE INDEX ix_inference_prediction_predicted_positive ON inference_prediction(predicted_positive)")
    op.execute("CREATE INDEX ix_inference_prediction_confidence ON inference_prediction(confidence)")
    op.execute("CREATE INDEX ix_inference_prediction_batch_review_confidence ON inference_prediction(inference_batch_id, review_status, confidence)")


def downgrade() -> None:
    # Drop tables in reverse order
    op.execute("DROP TABLE IF EXISTS inference_prediction CASCADE")
    op.execute("DROP TABLE IF EXISTS inference_batch CASCADE")
    op.execute("DROP TABLE IF EXISTS custom_model CASCADE")
    op.execute("DROP TABLE IF EXISTS search_result CASCADE")
    op.execute("DROP TABLE IF EXISTS search_session_reference_sound CASCADE")
    op.execute("DROP TABLE IF EXISTS search_session CASCADE")
    op.execute("DROP TABLE IF EXISTS reference_sound CASCADE")
    op.execute("DROP TABLE IF EXISTS ml_project_tag CASCADE")
    op.execute("DROP TABLE IF EXISTS ml_project CASCADE")

    # Drop ENUM types
    op.execute("DROP TYPE IF EXISTS inference_prediction_review_status CASCADE")
    op.execute("DROP TYPE IF EXISTS inference_batch_status CASCADE")
    op.execute("DROP TYPE IF EXISTS custom_model_status CASCADE")
    op.execute("DROP TYPE IF EXISTS custom_model_type CASCADE")
    op.execute("DROP TYPE IF EXISTS search_result_label CASCADE")
    op.execute("DROP TYPE IF EXISTS reference_sound_source CASCADE")
    op.execute("DROP TYPE IF EXISTS ml_project_status CASCADE")
