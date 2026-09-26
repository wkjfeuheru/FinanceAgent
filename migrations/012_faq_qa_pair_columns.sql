-- FAQ 问答对显式字段：兼容已有 content 数据，不删除旧列。
ALTER TABLE finance.faq_chunks
    ADD COLUMN IF NOT EXISTS question text;
ALTER TABLE finance.faq_chunks
    ADD COLUMN IF NOT EXISTS answer text;
ALTER TABLE finance.faq_chunks
    ADD COLUMN IF NOT EXISTS embedding_text text;

-- 历史 content 格式为“问题\n\n答案”；同时兼容新 embedding 文本格式。
UPDATE finance.faq_chunks
SET question = CASE
        WHEN content LIKE '问题：%' AND position(E'\n答案：' IN content) > 0
            THEN substring(content FROM 4 FOR position(E'\n答案：' IN content) - 4)
        WHEN position(E'\n\n' IN content) > 0
            THEN split_part(content, E'\n\n', 1)
        ELSE content
    END,
    answer = CASE
        WHEN content LIKE '问题：%' AND position(E'\n答案：' IN content) > 0
            THEN substring(content FROM position(E'\n答案：' IN content) + 4)
        WHEN position(E'\n\n' IN content) > 0
            THEN substring(content FROM position(E'\n\n' IN content) + 2)
        ELSE content
    END,
    embedding_text = content
WHERE question IS NULL OR answer IS NULL OR embedding_text IS NULL;

ALTER TABLE finance.faq_chunks
    ALTER COLUMN question SET NOT NULL;
ALTER TABLE finance.faq_chunks
    ALTER COLUMN answer SET NOT NULL;
ALTER TABLE finance.faq_chunks
    ALTER COLUMN embedding_text SET NOT NULL;

-- 问题权重 A、答案权重 B；旧 search_bigrams 保留用于平滑升级。
ALTER TABLE finance.faq_chunks
    ADD COLUMN IF NOT EXISTS search_qa_bigrams tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('simple', finance.faq_bigrams(question)), 'A') ||
        setweight(to_tsvector('simple', finance.faq_bigrams(answer)), 'B')
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_faq_chunks_qa_bigrams
    ON finance.faq_chunks USING gin (search_qa_bigrams);
