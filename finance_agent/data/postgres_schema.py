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
# 晚于初始建库新增的列必须走幂等 ALTER：001 的 CREATE TABLE IF NOT EXISTS 对已存在的表
# 不会补列，缺少这一步会让旧库缺列（历史上 products.recommended_holding_period 即如此）。
PRODUCTS_SCHEMA_SQL = _load_sql("006_products_columns.sql")
AGENT_RUNTIME_SCHEMA_SQL = _load_sql("002_agent_runtime_schema.sql")
IDENTITY_MIGRATION_SQL = _load_sql("003_identity_migration.sql")
RESEARCH_GOVERNANCE_SCHEMA_SQL = _load_sql("004_research_governance.sql")
THEME_REGISTRY_SCHEMA_SQL = _load_sql("005_theme_registry.sql")
# FAQ 索引元数据与异步任务引用：不依赖 pgvector，可安全用于任意业务库。
HYBRID_ORCHESTRATION_SCHEMA_SQL = _load_sql("008_hybrid_orchestration.sql")
# FAQ 向量分块：依赖 pgvector 扩展，仅 FAQ 索引/检索路径需要。
FAQ_VECTOR_SCHEMA_SQL = _load_sql("009_faq_vector.sql")
# FAQ 中文关键词检索：把分词退化的 simple 配置换成归一化二元组。
FAQ_BIGRAM_SCHEMA_SQL = _load_sql("010_faq_bigram_search.sql")
# 模拟交易：账户资金、资金流水、委托成交与持仓。
PORTFOLIO_SCHEMA_SQL = _load_sql("011_portfolio.sql")
# FAQ 问答对显式字段与加权关键词索引：兼容已有 content 数据。
FAQ_QA_PAIR_SCHEMA_SQL = _load_sql("012_faq_qa_pair_columns.sql")
# 管理后台：users.is_admin 角色列与 products.is_active 上下架列。
ADMIN_CONSOLE_SCHEMA_SQL = _load_sql("013_admin_console.sql")


def runtime_schema_jsonb_fields() -> dict[str, str]:
    """返回运行审计 JSONB 字段定义的副本，避免调用方修改全局约定。"""
    return {
        "agent_runs": dict(AGENT_RUN_JSONB_FIELDS),
        "agent_results": dict(AGENT_RESULT_JSONB_FIELDS),
        "conversation_messages": {"metadata": MESSAGE_METADATA_JSONB_FIELD},
    }
