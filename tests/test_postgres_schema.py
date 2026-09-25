"""PostgreSQL 运行审计 schema 契约测试。"""

from pathlib import Path

import pytest

from finance_agent.data.postgres_schema import (
    AGENT_RUNTIME_SCHEMA_SQL,
    BASE_SCHEMA_SQL,
    FAQ_SCHEMA_APPLY_ORDER,
    IDENTITY_MIGRATION_SQL,
    PORTFOLIO_SCHEMA_SQL,
    PRODUCTS_SCHEMA_SQL,
    SCHEMA_APPLY_ORDER,
    SEED_SCHEMA_FILES,
    runtime_schema_jsonb_fields,
)

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


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


# ── 列漂移回归 ────────────────────────────────────────────────────
#
# 真实发生过的缺陷：某功能提交把新列直接加进 001 的 CREATE TABLE 语句。001 用的是
# `CREATE TABLE IF NOT EXISTS`，对**已存在**的表不会补列，于是线上库缺列
# （products.recommended_holding_period），连带 007 种子脚本无法应用。
# 下面这组测试把规则固化下来：凡晚于初始建库新增的列，必须在某个后续脚本里有幂等 ALTER。

#: 001 建表的列 + 必须由后续脚本以 ADD COLUMN 补齐的列。
#: 新增列时，若该列会出现在已有库中，请同时在此登记并补一条 ALTER。
_LATE_ADDED_COLUMNS = {
    # 表名: (列名, 声明片段)
    "products": (
        "recommended_holding_period",
        "recommended_holding_period varchar(32) NOT NULL DEFAULT ''",
    ),
}

_ALTER_FILES = [
    "002_agent_runtime_schema.sql",
    "005_theme_registry.sql",
    "006_products_columns.sql",
    "008_hybrid_orchestration.sql",
    "010_faq_bigram_search.sql",
    "012_faq_qa_pair_columns.sql",
    "013_admin_console.sql",
]


def _file_text(name: str) -> str:
    return (SQL_DIR / name).read_text(encoding="utf-8")


def test_products_migration_adds_late_columns_idempotently():
    """晚于初始建库新增的 products 列必须由幂等 ALTER 提供。"""
    for table, (column, declaration) in _LATE_ADDED_COLUMNS.items():
        assert declaration in PRODUCTS_SCHEMA_SQL, f"{table}.{column} 的声明片段缺失"
        assert f"ALTER TABLE finance.{table}" in PRODUCTS_SCHEMA_SQL
        assert "ADD COLUMN IF NOT EXISTS" in PRODUCTS_SCHEMA_SQL, (
            f"{table}.{column} 的补列必须是 IF NOT EXISTS，否则重复执行会失败"
        )


def test_late_columns_are_declared_in_base_schema_too():
    """补列脚本与 001 必须一致，否则新库与旧库会收敛到不同结构。"""
    for _table, (column, declaration) in _LATE_ADDED_COLUMNS.items():
        assert declaration in BASE_SCHEMA_SQL, (
            f"{column} 也必须在 001_base_schema.sql 中声明（新库走建表路径）"
        )


def test_every_schema_file_is_idempotent_by_construction():
    """建表/补列脚本必须可重复执行：CREATE 用 IF NOT EXISTS，ALTER 用 IF NOT EXISTS。"""
    for name in _ALTER_FILES:
        text = _file_text(name)
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("ALTER TABLE") and "ADD COLUMN" in stripped.upper():
                assert "IF NOT EXISTS" in stripped.upper(), (
                    f"{name} 中的 ADD COLUMN 缺少 IF NOT EXISTS：{stripped}"
                )


def test_schema_files_are_numbered_without_gaps():
    """建表脚本编号应连续；缺号通常意味着有人把变更内联改进了旧脚本。"""
    numbers = sorted(
        int(path.name[:3])
        for path in SQL_DIR.glob("0*.sql")
        if path.name[:3].isdigit()
    )
    assert numbers == list(range(numbers[0], numbers[-1] + 1)), (
        f"sql/ 脚本编号存在缺号：{numbers}"
    )


def test_schema_apply_order_covers_sql_except_seed():
    """统一清单覆盖 001–013 除 007，且与 sql/ 文件一致。"""
    sql_files = {path.name for path in SQL_DIR.glob("0*.sql")}
    applied = set(SCHEMA_APPLY_ORDER) | set(FAQ_SCHEMA_APPLY_ORDER) | set(SEED_SCHEMA_FILES)
    assert applied == sql_files
    assert "007_product_seed.sql" not in SCHEMA_APPLY_ORDER
    assert "007_product_seed.sql" not in FAQ_SCHEMA_APPLY_ORDER
    numbers = sorted(
        int(name[:3]) for name in (*SCHEMA_APPLY_ORDER, *FAQ_SCHEMA_APPLY_ORDER)
    )
    assert numbers == [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13]
    assert list(SCHEMA_APPLY_ORDER) == [
        "001_base_schema.sql",
        "002_agent_runtime_schema.sql",
        "003_identity_migration.sql",
        "004_research_governance.sql",
        "005_theme_registry.sql",
        "006_products_columns.sql",
        "008_hybrid_orchestration.sql",
        "011_portfolio.sql",
        "013_admin_console.sql",
    ]
    assert list(FAQ_SCHEMA_APPLY_ORDER) == [
        "009_faq_vector.sql",
        "010_faq_bigram_search.sql",
        "012_faq_qa_pair_columns.sql",
    ]


def test_seed_columns_exist_in_schema():
    """种子脚本引用的列必须都在 DDL 里声明，否则应用种子会被数据库拒绝。"""
    seed = _file_text("007_product_seed.sql")
    start = seed.index("INSERT INTO finance.products (")
    columns_block = seed[start : seed.index(")", start)]
    columns = [part.strip() for part in columns_block.split("(", 1)[1].split(",")]
    for column in columns:
        assert column in BASE_SCHEMA_SQL, f"007 引用了未声明的列 products.{column}"


def test_portfolio_schema_cascades_to_users():
    """模拟交易各表必须级联到 users，注销账号才能连带清理。"""
    for table in ("accounts", "cash_transactions", "orders", "positions"):
        assert f"CREATE TABLE IF NOT EXISTS finance.{table}" in PORTFOLIO_SCHEMA_SQL
    assert PORTFOLIO_SCHEMA_SQL.count("ON DELETE CASCADE") >= 4


def test_portfolio_orders_declare_idempotency_unique_index():
    """委托幂等必须有部分唯一索引，否则并发同一键会双花。"""
    assert "uq_orders_idempotency" in PORTFOLIO_SCHEMA_SQL
    assert "uq_cash_transactions_idempotency" in PORTFOLIO_SCHEMA_SQL
    assert "WHERE idempotency_key <> ''" in PORTFOLIO_SCHEMA_SQL

