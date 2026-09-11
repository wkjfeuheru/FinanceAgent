"""PostgreSQL schema 契约与集中式 SQL 脚本加载。"""

from __future__ import annotations

from pathlib import Path


BUSINESS_SCHEMA = "finance"
_SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def _load_sql(filename: str) -> str:
    """从仓库根目录的 sql/ 加载 UTF-8 脚本。"""
    path = _SQL_DIR / filename
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"无法读取 PostgreSQL SQL 脚本: {path}") from exc
    if not content:
        raise RuntimeError(f"PostgreSQL SQL 脚本为空: {path}")
    return content


# 运行审计 JSONB 字段使用显式版本，便于未来读取端按版本兼容。
AGENT_RUN_JSONB_FIELDS = {
    "task_dispatch": "jsonb NOT NULL DEFAULT '[]'::jsonb",
    "context_summary": "jsonb NOT NULL DEFAULT '{}'::jsonb",
    "fact_manifest": "jsonb NOT NULL DEFAULT '[]'::jsonb",
    "model_usage": "jsonb NOT NULL DEFAULT '{}'::jsonb",
}

AGENT_RESULT_JSONB_FIELDS = {
    "result_data": "jsonb NOT NULL DEFAULT '{}'::jsonb",
    "fact_ids": "jsonb NOT NULL DEFAULT '[]'::jsonb",
}

MESSAGE_METADATA_JSONB_FIELD = "metadata jsonb NOT NULL DEFAULT '{}'::jsonb"

# 公开常量保留，调用方只需依赖这里，不再维护内嵌 SQL。
BASE_SCHEMA_SQL = _load_sql("001_base_schema.sql")
AGENT_RUNTIME_SCHEMA_SQL = _load_sql("002_agent_runtime_schema.sql")
IDENTITY_MIGRATION_SQL = _load_sql("003_identity_migration.sql")
RESEARCH_GOVERNANCE_SCHEMA_SQL = _load_sql("004_research_governance.sql")


def runtime_schema_jsonb_fields() -> dict[str, str]:
    """返回运行审计 JSONB 字段定义的副本，避免调用方修改全局约定。"""
    return {
        "agent_runs": dict(AGENT_RUN_JSONB_FIELDS),
        "agent_results": dict(AGENT_RESULT_JSONB_FIELDS),
        "conversation_messages": {"metadata": MESSAGE_METADATA_JSONB_FIELD},
    }
