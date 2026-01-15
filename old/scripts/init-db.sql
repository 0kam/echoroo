-- PostgreSQL initialization script for Whombat
-- This script is executed when the PostgreSQL container is first initialized.
-- It enables the pgvector extension for ML embedding storage and similarity search.

-- Enable pgvector extension for vector similarity search
-- This is required for storing and querying ML model embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- Note: Additional extensions can be added here as needed
-- CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- For trigram similarity search
-- CREATE EXTENSION IF NOT EXISTS btree_gin; -- For GIN index support
