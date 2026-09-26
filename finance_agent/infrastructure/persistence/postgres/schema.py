"""PostgreSQL schema 契约与集中式 SQL 脚本加载。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


BUSINESS_SCHEMA = "finance"

# 业务结构 DDL（不含 FAQ 专用迁移与 007 种子）。部署 CLI 与业务仓储共用清单。
SCHEMA_APPLY_ORDER = (
    "001_base_schema.sql",
    "002_agent_runtime_schema.sql",
    "003_identity_migration.sql",
    "004_research_governance.sql",
    "006_products_columns.sql",
    "008_hybrid_orchestration.sql",
    "011_portfolio.sql",
    "013_admin_console.sql",
    "014_remove_theme_features.sql",
)

# FAQ 向量分块：依赖 pgvector。migrate 默认会在 CREATE EXTENSION 之后应用。
FAQ_SCHEMA_APPLY_ORDER = (
    "009_faq_vector.sql",
    "010_faq_bigram_search.sql",
    "012_faq_qa_pair_columns.sql",
)

SEED_SCHEMA_FILES = ("007_product_seed.sql",)

VECTOR_EXTENSION_SQL = "CREATE EXTENSION IF NOT EXISTS vector"


def sql_dir() -> Path:
    """定位仓库 ``migrations/`` 目录；容器内可通过 ``FINANCE_SQL_DIR`` 覆盖。"""
    env = os.getenv("FINANCE_SQL_DIR", "").strip()
    if env:
        path = Path(env)
        if not path.is_dir():
            raise RuntimeError(f"FINANCE_SQL_DIR 不是目录: {path}")
        return path
    candidates = (
        Path(__file__).resolve().parents[4] / "migrations",
        Path.cwd() / "migrations",
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise RuntimeError("找不到 migrations/ 目录。请在仓库根目录运行，或设置 FINANCE_SQL_DIR。")


def _load_sql(filename: str) -> str:
    """从仓库根目录的 migrations/ 加载 UTF-8 脚本。"""
    path = sql_dir() / filename
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"无法读取 PostgreSQL SQL 脚本: {path}") from exc
    if not content:
        raise RuntimeError(f"PostgreSQL SQL 脚本为空: {path}")
    return content


def _is_missing_pgvector(exc: BaseException) -> bool:
    message = str(exc)
    lowered = message.lower()
    return "vector" in lowered and (
        "is not available" in message
        or "vector.control" in message
        or "could not open extension control file" in lowered
        or 'extension "vector"' in lowered
        or "extension 'vector'" in lowered
    )


def _execute_sql(cursor: Any, label: str, sql: str) -> None:
    """执行一段 DDL；失败带上脚本名，不吞异常。"""
    try:
        cursor.execute(sql)
    except Exception as exc:
        raise RuntimeError(f"应用 {label} 失败: {exc}") from exc


def apply_postgres_schema(
    connection: Any,
    *,
    include_faq: bool = True,
    include_seed: bool = False,
) -> None:
    """按统一清单幂等应用 schema。失败向上抛出，由调用方决定提交或退出。

    ``include_faq=False`` 时不要求 pgvector，供业务/审计懒建表在无扩展的库上仍能启动。
    部署以 ``python -m finance_agent.cli.migrate`` 为准（默认含 FAQ）。
    """
    cursor = connection.cursor()
    try:
        for filename in SCHEMA_APPLY_ORDER:
            _execute_sql(cursor, filename, _load_sql(filename))
        if include_faq:
            try:
                _execute_sql(cursor, "CREATE EXTENSION vector", VECTOR_EXTENSION_SQL)
                for filename in FAQ_SCHEMA_APPLY_ORDER:
                    _execute_sql(cursor, filename, _load_sql(filename))
            except Exception as exc:
                original = exc.__cause__ if getattr(exc, "__cause__", None) is not None else exc
                if _is_missing_pgvector(original) or _is_missing_pgvector(exc):
                    raise RuntimeError(
                        "PostgreSQL 缺少 pgvector 扩展，FAQ 索引与检索不可用。"
                        "请安装 pgvector（例如 postgresql-16-pgvector）并在业务库执行 "
                        "CREATE EXTENSION vector; 后重试。"
                    ) from exc
                raise
        if include_seed:
            for filename in SEED_SCHEMA_FILES:
                _execute_sql(cursor, filename, _load_sql(filename))
    finally:
        cursor.close()


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
# Drop legacy theme feature tables while retaining research run/result audit tables.
REMOVE_THEME_FEATURES_SCHEMA_SQL = _load_sql("014_remove_theme_features.sql")


def runtime_schema_jsonb_fields() -> dict[str, str]:
    """返回运行审计 JSONB 字段定义的副本，避免调用方修改全局约定。"""
    return {
        "agent_runs": dict(AGENT_RUN_JSONB_FIELDS),
        "agent_results": dict(AGENT_RESULT_JSONB_FIELDS),
        "conversation_messages": {"metadata": MESSAGE_METADATA_JSONB_FIELD},
    }
