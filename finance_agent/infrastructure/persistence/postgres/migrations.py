"""结构化 SQL 迁移的唯一事实源（Task 4）。

建表/补列脚本的应用顺序此前散落在 ``postgres_stores._PostgresBaseStore._apply_schema``
与 ``postgres_repository.PostgresRuntimeRepository.setup_schema``（两份清单，
且内容并不一致——store 路径不跑 identity/research/theme 迁移，repo 路径漏跑
admin console 迁移），增删迁移要改两处且容易漂移。这里把顺序集中为 ``MIGRATIONS``：
每项携带脚本名与 SQL 文本，``run_migrations`` 按序在**同一事务**内执行。

不在序列中的脚本：
- ``007_product_seed.sql``：数据种子，非结构；
- ``009/010/012``：FAQ 专用（pgvector 依赖 / 二元组索引 / 问答对列），由 FAQ 仓储
  在自己的惰性路径应用，业务基础库不得强依赖 pgvector；
- ``005_theme_registry.sql``：主题注册表已由 ``014`` 移除，创建后再删除无意义。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from finance_agent.infrastructure.persistence.postgres.schema import (
    ADMIN_CONSOLE_SCHEMA_SQL,
    AGENT_RUNTIME_SCHEMA_SQL,
    BASE_SCHEMA_SQL,
    HYBRID_ORCHESTRATION_SCHEMA_SQL,
    IDENTITY_MIGRATION_SQL,
    PORTFOLIO_SCHEMA_SQL,
    PRODUCTS_SCHEMA_SQL,
    REMOVE_THEME_FEATURES_SCHEMA_SQL,
    RESEARCH_GOVERNANCE_SCHEMA_SQL,
)


@dataclass(frozen=True)
class Migration:
    """一条结构迁移：脚本名 + SQL 文本。"""

    name: str
    sql: str


#: 业务基础库的结构迁移顺序（唯一事实源）。历史脚本保持编号连续、不可变；
#: 新变更追加为新的编号脚本，不改写既有条目。
MIGRATIONS: tuple[Migration, ...] = (
    Migration("001_base_schema.sql", BASE_SCHEMA_SQL),
    Migration("002_agent_runtime_schema.sql", AGENT_RUNTIME_SCHEMA_SQL),
    Migration("003_identity_migration.sql", IDENTITY_MIGRATION_SQL),
    Migration("004_research_governance.sql", RESEARCH_GOVERNANCE_SCHEMA_SQL),
    # 旧库缺列的补齐必须紧跟建表之后（幂等）；按编号顺序执行即满足。
    Migration("006_products_columns.sql", PRODUCTS_SCHEMA_SQL),
    Migration("008_hybrid_orchestration.sql", HYBRID_ORCHESTRATION_SCHEMA_SQL),
    Migration("011_portfolio.sql", PORTFOLIO_SCHEMA_SQL),
    Migration("013_admin_console.sql", ADMIN_CONSOLE_SCHEMA_SQL),
    Migration("014_remove_theme_features.sql", REMOVE_THEME_FEATURES_SCHEMA_SQL),
)


def run_migrations(runner: Any) -> None:
    """在单个事务内按序应用全部结构迁移（幂等）。

    调用方提供带 ``transaction()`` 的 ``TransactionRunner``。整批在同一事务内
    执行：任一脚本失败即整体回滚，避免库停在"迁移到一半"的中间结构。
    """
    with runner.transaction() as connection:
        cursor = connection.cursor()
        try:
            for step in MIGRATIONS:
                cursor.execute(step.sql)
        finally:
            cursor.close()


__all__ = ["MIGRATIONS", "Migration", "run_migrations"]
