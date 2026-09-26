-- FAQ 中文关键词检索：PostgreSQL 的 simple 配置不做中文分词，整段文本会成为
-- 单个 token，导致中文关键词召回完全失效（查询 "定投" 命中 0 行）。这里改用
-- **归一化二元组（bigram）**：去掉空白与标点后切成相邻两字，既能让中文参与
-- 全文检索，又能要求查询字符按序出现（高精度，不相关文本不会误命中）。
-- 仅需 pg_trgm 之外的标准能力，不引入额外扩展。

CREATE OR REPLACE FUNCTION finance.faq_normalize(txt text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT regexp_replace(coalesce(txt, ''), '[[:space:][:punct:]]', '', 'g')
$$;

CREATE OR REPLACE FUNCTION finance.faq_bigrams(txt text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT string_agg(substr(finance.faq_normalize(txt), i, 2), ' ')
    FROM generate_series(1, greatest(length(finance.faq_normalize(txt)) - 1, 0)) AS i
$$;

-- 二元组全文索引列（随内容自动维护，重建索引时无需额外写入）。
ALTER TABLE finance.faq_chunks
    ADD COLUMN IF NOT EXISTS search_bigrams tsvector
    GENERATED ALWAYS AS (to_tsvector('simple', finance.faq_bigrams(content))) STORED;

CREATE INDEX IF NOT EXISTS idx_faq_chunks_bigrams
    ON finance.faq_chunks USING gin (search_bigrams);
