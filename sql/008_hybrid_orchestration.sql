-- 混合编排持久化：FAQ 索引元数据与可恢复的异步任务引用。
-- 本文件**不依赖 pgvector**，可在任何 PostgreSQL 上执行；向量分块见 009。
-- 这样异步任务查询/恢复不会因为缺少 pgvector 而整体不可用。

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

-- 尚未完成的领域结论快照。领域图因异步量化任务（awaiting_quant）中断时，
-- 把该结论连同所属会话信息存下来；状态端点发现任务完成后，据此在原会话上
-- 合并量化结果、重新渲染并过合规，而不是重跑已完成的取数与研究。
-- 以 job_id 为主键：一次领域执行可能提交多个量化任务（每只标的一个），
-- 每个 job 一行、共享同一份结论快照；全部 job 完成后才判定该结论可收尾。
CREATE TABLE IF NOT EXISTS finance.pending_outcomes (
    job_id varchar(128) PRIMARY KEY,
    task_id varchar(160) NOT NULL,
    code varchar(64) NOT NULL DEFAULT '',
    customer_id varchar(128) NOT NULL,
    thread_id varchar(256) NOT NULL,
    run_id varchar(128) NOT NULL,
    conversation_id varchar(128) NOT NULL,
    outcome jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pending_outcomes_task ON finance.pending_outcomes (task_id);
CREATE INDEX IF NOT EXISTS idx_pending_outcomes_customer ON finance.pending_outcomes (customer_id, job_id);
-- 幂等补列：若本表在此列加入前已建，IF NOT EXISTS 不会补列（与 001 同源约束）。
ALTER TABLE finance.pending_outcomes ADD COLUMN IF NOT EXISTS code varchar(64) NOT NULL DEFAULT '';

