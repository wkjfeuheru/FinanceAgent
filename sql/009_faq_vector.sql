-- FAQ 向量分块：依赖 pgvector 扩展（详见设计 §10）。
-- 只有 FAQ 索引/检索需要本文件；安装命令示例（Debian/Ubuntu）：
--   apt-get install postgresql-15-pgvector
-- 随后在业务库执行 CREATE EXTENSION vector;

CREATE EXTENSION IF NOT EXISTS vector;

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
