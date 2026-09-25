"""统一、可在容器启动时执行的 schema apply。

``sql/001``–``013`` 已是幂等 DDL 事实源。本模块是部署入口，失败显式退出。

用法::

    python -m finance_agent.migrate
    python -m finance_agent.migrate --seed
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m finance_agent.migrate",
        description="幂等应用 sql/ 结构脚本（含 FAQ / pgvector）；可选种子数据。",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="同时应用 sql/007_product_seed.sql（ON CONFLICT 幂等）",
    )
    return parser


def apply_from_config(*, include_seed: bool) -> None:
    """用应用配置连接数据库并应用 schema。失败抛出，不吞异常。"""
    from finance_agent.config import get_postgres_connection_factory
    from finance_agent.data.postgres_schema import apply_postgres_schema

    connection = get_postgres_connection_factory()()
    try:
        apply_postgres_schema(connection, include_faq=True, include_seed=include_seed)
        connection.commit()
    except Exception:
        try:
            connection.rollback()
        except Exception:
            pass
        raise
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        apply_from_config(include_seed=args.seed)
    except Exception as exc:
        print(f"schema apply 失败: {exc}", file=sys.stderr)
        return 1
    print("schema apply 完成" + ("（含产品种子）" if args.seed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
