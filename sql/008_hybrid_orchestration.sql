-- 混合编排持久化：本地 FAQ 索引与可恢复的异步任务引用。
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS finance.faq_index_versions (
    index_version varchar(128) PRIMARY KEY,
    is_active boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS finance.faq_documents (
    document_id uuid PRIMARY KEY,
    index_version varchar(128) NOT NULL REFERENCES finance.faq_index_versions(index_version),
    faq_id varchar(128) NOT NULL,
    source_path text NOT NULL,
    content_hash varchar(128) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (index_version, faq_id)
);

CREATE TABLE IF NOT EXISTS finance.faq_chunks (
    chunk_id uuid PRIMARY KEY,
    index_version varchar(128) NOT NULL REFERENCES finance.faq_index_versions(index_version),
    faq_id varchar(128) NOT NULL,
    source_path text NOT NULL,
    chunk_ordinal integer NOT NULL,
    content text NOT NULL,
    content_hash varchar(128) NOT NULL,
    embedding vector(512) NOT NULL,
    search_text tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
    is_active boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (index_version, faq_id, chunk_ordinal)
);
CREATE INDEX IF NOT EXISTS idx_faq_chunks_search_text ON finance.faq_chunks USING gin (search_text);
CREATE INDEX IF NOT EXISTS idx_faq_chunks_embedding_cosine
    ON finance.faq_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS finance.async_jobs (
    job_id varchar(128) PRIMARY KEY,
    customer_id varchar(128) NOT NULL,
    thread_id varchar(256) NOT NULL,
    run_id varchar(128) NOT NULL,
    task_id varchar(128) NOT NULL,
    kind varchar(128) NOT NULL,
    status varchar(32) NOT NULL,
    idempotency_key varchar(256) NOT NULL,
    result_ref text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_async_jobs_customer_job ON finance.async_jobs (customer_id, job_id);
