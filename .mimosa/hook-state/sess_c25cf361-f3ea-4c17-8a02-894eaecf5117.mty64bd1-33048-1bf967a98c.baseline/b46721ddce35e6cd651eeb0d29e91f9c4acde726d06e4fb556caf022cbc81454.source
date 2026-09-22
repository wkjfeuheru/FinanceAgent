"""PostgreSQL 运行审计 schema 契约测试。"""

from finance_agent.data.postgres_schema import (
    AGENT_RUNTIME_SCHEMA_SQL,
    BASE_SCHEMA_SQL,
    IDENTITY_MIGRATION_SQL,
    runtime_schema_jsonb_fields,
)


def test_identity_schema_uses_users_as_the_only_business_subject():
    assert ".customers" not in BASE_SCHEMA_SQL
    assert "CREATE TABLE IF NOT EXISTS finance.users" in BASE_SCHEMA_SQL
    assert "REFERENCES finance.users(customer_id)" in BASE_SCHEMA_SQL
    assert "DROP TABLE IF EXISTS finance.customers" in IDENTITY_MIGRATION_SQL
    assert "DELETE FROM finance.agent_runs" in IDENTITY_MIGRATION_SQL


def test_runtime_schema_declares_versioned_jsonb_fields():
    """运行、结果和消息 metadata 必须使用 JSONB 字段。"""
    fields = runtime_schema_jsonb_fields()

    assert fields["agent_runs"] == {
        "task_dispatch": "jsonb NOT NULL DEFAULT '[]'::jsonb",
        "context_summary": "jsonb NOT NULL DEFAULT '{}'::jsonb",
        "fact_manifest": "jsonb NOT NULL DEFAULT '[]'::jsonb",
        "model_usage": "jsonb NOT NULL DEFAULT '{}'::jsonb",
    }
    assert fields["agent_results"] == {
        "result_data": "jsonb NOT NULL DEFAULT '{}'::jsonb",
        "fact_ids": "jsonb NOT NULL DEFAULT '[]'::jsonb",
    }
    assert fields["conversation_messages"]["metadata"].startswith("metadata jsonb")


def test_runtime_schema_declares_idempotency_constraint_and_indexes():
    """专家结果按运行和专家名称幂等，运行查询具备会话与 trace 索引。"""
    assert "trace_id uuid NOT NULL" in AGENT_RUNTIME_SCHEMA_SQL
    assert "UNIQUE (run_id, expert_name)" in AGENT_RUNTIME_SCHEMA_SQL
    assert "idx_agent_runs_conversation_started" in AGENT_RUNTIME_SCHEMA_SQL
    assert "idx_agent_runs_trace" in AGENT_RUNTIME_SCHEMA_SQL
    assert "idx_agent_results_run" in AGENT_RUNTIME_SCHEMA_SQL
    assert "metadata jsonb NOT NULL DEFAULT '{}'::jsonb" in AGENT_RUNTIME_SCHEMA_SQL
