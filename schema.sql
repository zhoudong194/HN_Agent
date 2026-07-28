-- ============================================================
-- schema.sql - PostgreSQL + pgvector schema for HN_Agent
-- ============================================================
-- Idempotent: safe to run on every container start.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    file_type   TEXT NOT NULL,
    file_size   BIGINT NOT NULL DEFAULT 0,
    file_hash   TEXT,
    category    TEXT,
    uploader    TEXT,
    title       TEXT,
    status      TEXT NOT NULL DEFAULT 'active',
    version     INTEGER NOT NULL DEFAULT 1,
    uploaded_at TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id          TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    text_hash   TEXT NOT NULL,
    header_1    TEXT,
    header_2    TEXT,
    header_3    TEXT,
    source_file TEXT,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    embedding   vector(1024)
);

CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category);
CREATE INDEX IF NOT EXISTS idx_documents_file_hash ON documents(file_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_text_hash ON chunks(text_hash);

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
ON chunks USING hnsw (embedding vector_cosine_ops)
WHERE embedding IS NOT NULL;
