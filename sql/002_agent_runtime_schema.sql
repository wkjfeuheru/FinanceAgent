CREATE SCHEMA IF NOT EXISTS finance;

ALTER TABLE finance.conversation_messages
    ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS finance.agent_runs (
    run_id uuid PRIMARY KEY,
    trace_id uuid NOT NULL,
    customer_id varchar(64) NOT NULL
        REFERENCES finance.users(customer_id) ON DELETE CASCADE,
    conversation_id varchar(128) NOT NULL,
    user_message_id uuid NOT NULL,
    status varchar(32) NOT NULL,
    task_dispatch jsonb NOT NULL DEFAULT '[]'::jsonb,
    context_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    fact_manifest jsonb NOT NULL DEFAULT '[]'::jsonb,
    model_usage jsonb NOT NULL DEFAULT '{}'::jsonb,
    final_message_id uuid,
    error_code varchar(128),
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

CREATE TABLE IF NOT EXISTS finance.agent_results (
    result_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES finance.agent_runs(run_id) ON DELETE CASCADE,
    trace_id uuid NOT NULL,
    expert_name varchar(64) NOT NULL,
    status varchar(32) NOT NULL,
    schema_version varchar(32) NOT NULL DEFAULT '1.0',
    summary text NOT NULL,
    result_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    fact_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    degradation_reason varchar(256),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, expert_name)
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation_started
    ON finance.agent_runs (conversation_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_trace
    ON finance.agent_runs (trace_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_customer_started
    ON finance.agent_runs (customer_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_results_run
    ON finance.agent_results (run_id, expert_name);
