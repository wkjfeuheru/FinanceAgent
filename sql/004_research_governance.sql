-- 主题候选池、审核证据与可重放研究结果。
CREATE TABLE IF NOT EXISTS finance.theme_memberships (
    membership_id uuid PRIMARY KEY,
    lead_id uuid NOT NULL UNIQUE,
    theme_id varchar(128) NOT NULL,
    stock_code varchar(16) NOT NULL,
    industry varchar(128) NOT NULL DEFAULT '',
    status varchar(16) NOT NULL CHECK (status IN ('pending', 'active', 'expired', 'rejected')),
    evidence_expires_at timestamptz NOT NULL,
    activated_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_theme_membership_current
ON finance.theme_memberships(theme_id, stock_code)
WHERE status IN ('pending', 'active');

CREATE TABLE IF NOT EXISTS finance.theme_evidence (
    evidence_id uuid PRIMARY KEY,
    lead_id uuid NOT NULL,
    source_name varchar(128) NOT NULL,
    source_class varchar(32) NOT NULL CHECK (source_class IN ('official', 'licensed_classification', 'public_lead')),
    source_uri text NOT NULL,
    evidence_excerpt text NOT NULL,
    evidence_hash varchar(128) NOT NULL,
    discovered_at timestamptz NOT NULL,
    UNIQUE (lead_id, evidence_hash)
);

CREATE TABLE IF NOT EXISTS finance.theme_reviews (
    review_id uuid PRIMARY KEY,
    lead_id uuid NOT NULL,
    reviewer_id varchar(128) NOT NULL,
    decision varchar(16) NOT NULL CHECK (decision IN ('approve', 'reject')),
    note text NOT NULL DEFAULT '',
    reviewed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS finance.research_feature_snapshots (
    snapshot_id uuid PRIMARY KEY,
    theme_id varchar(128) NOT NULL,
    stock_code varchar(16) NOT NULL,
    rule_version varchar(64) NOT NULL,
    as_of timestamptz NOT NULL,
    payload jsonb NOT NULL,
    UNIQUE (theme_id, stock_code, rule_version, as_of)
);

CREATE TABLE IF NOT EXISTS finance.research_runs (
    research_run_id uuid PRIMARY KEY,
    agent_run_id uuid REFERENCES finance.agent_runs(run_id),
    customer_id varchar(128) NOT NULL,
    conversation_id varchar(128) NOT NULL,
    request_data jsonb NOT NULL,
    snapshot_manifest jsonb NOT NULL DEFAULT '[]'::jsonb,
    rule_version varchar(64) NOT NULL,
    status varchar(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS finance.research_results (
    result_id uuid PRIMARY KEY,
    research_run_id uuid NOT NULL REFERENCES finance.research_runs(research_run_id),
    stock_code varchar(16) NOT NULL,
    action varchar(16) NOT NULL,
    scores jsonb NOT NULL DEFAULT '{}'::jsonb,
    fact_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    exclusion_reason text NOT NULL DEFAULT ''
);
