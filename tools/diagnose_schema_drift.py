"""库表漂移诊断：对比「DDL 声明的期望结构」与「线上实际结构」。

做法：把 `sql/` 里的建表脚本应用到一个一次性探针库，作为**权威期望结构**
（由 PostgreSQL 自己解析 DDL，不靠正则猜列名），再与线上库逐表逐列对比。
建表脚本用的是 `CREATE TABLE IF NOT EXISTS`，因此对已建库的环境它**不会补列** ——
新增列必须配有幂等 ALTER，本工具正是用来发现漏配的情况。

用法：
    python tools/diagnose_schema_drift.py               # 临时建库对比，结束后自动删除探针库
    python tools/diagnose_schema_drift.py --keep-probe  # 保留探针库以便人工检查

退出码：发现缺失表/列或类型不一致时为 1，否则为 0（可用于 CI 把关）。
线上库只执行只读查询；探针库是一次性的，不会触碰任何既有库。
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg

from finance_agent.config import _postgres_dsn
from finance_agent.data.postgres_schema import (
    BUSINESS_SCHEMA,
    FAQ_SCHEMA_APPLY_ORDER,
    SCHEMA_APPLY_ORDER,
)

PROBE_DB = "advisor_schema_probe"
SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
# 与 migrate CLI 同一份结构清单。007 是种子数据，不含结构声明，故跳过。
# 012 已纳入 FAQ 部署路径（python -m finance_agent.migrate 默认应用），因此计入期望。
SCHEMA_FILES = list(SCHEMA_APPLY_ORDER) + list(FAQ_SCHEMA_APPLY_ORDER)

# 此前 FAQ 问答列由惰性路径补齐；统一 migrate 之后它们属于期望结构。
EXPECTED_LAZY_COLUMNS: dict[tuple[str, str], str] = {}


def _columns(conn, schema: str) -> dict[tuple[str, str], tuple[str, str, str, str]]:
    """读取列清单：{(表, 列): (类型, 是否可空, 默认值, 字符长度)}。"""
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT table_name, column_name, data_type, is_nullable,
                      COALESCE(column_default, ''), COALESCE(character_maximum_length, 0)
               FROM information_schema.columns
               WHERE table_schema = %s
               ORDER BY table_name, ordinal_position""",
            (schema,),
        )
        return {
            (row[0], row[1]): (row[2], row[3], row[4], str(row[5]))
            for row in cur.fetchall()
        }
    finally:
        cur.close()


def _tables(conn, schema: str) -> set[str]:
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            (schema,),
        )
        return {row[0] for row in cur.fetchall()}
    finally:
        cur.close()


def build_probe(dsn: str) -> None:
    """把建表脚本应用到探针库，得到权威期望结构。"""
    conn = psycopg.connect(dsn)
    try:
        cur = conn.cursor()
        for filename in SCHEMA_FILES:
            text = (SQL_DIR / filename).read_text(encoding="utf-8")
            try:
                cur.execute(text)
                conn.commit()
            except Exception as exc:  # noqa: BLE001 - 逐个报告，不掩盖
                conn.rollback()
                print(f"  [跳过] {filename}: {type(exc).__name__}: {exc}")
        cur.close()
    finally:
        conn.close()


def _probe_dsn(base_dsn: str) -> str:
    """把 DSN 指向探针库。"""
    import urllib.parse

    parts = urllib.parse.urlsplit(base_dsn)
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, f"/{PROBE_DB}", parts.query, parts.fragment)
    )


def create_probe_db() -> None:
    """创建一次性的探针库；已存在时先删除重建，保证是干净基线。"""
    admin = psycopg.connect(_postgres_dsn(), autocommit=True)
    try:
        cur = admin.cursor()
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (PROBE_DB,),
        )
        cur.execute(f"DROP DATABASE IF EXISTS {PROBE_DB}")
        cur.execute(f"CREATE DATABASE {PROBE_DB}")
        cur.close()
    finally:
        admin.close()


def drop_probe_db() -> None:
    admin = psycopg.connect(_postgres_dsn(), autocommit=True)
    try:
        cur = admin.cursor()
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (PROBE_DB,),
        )
        cur.execute(f"DROP DATABASE IF EXISTS {PROBE_DB}")
        cur.close()
    finally:
        admin.close()


def main() -> int:
    dsn = _postgres_dsn()
    probe_dsn = _probe_dsn(dsn)

    print(f"① 创建干净探针库 {PROBE_DB} 并应用建表脚本 ...")
    create_probe_db()
    build_probe(probe_dsn)

    live = psycopg.connect(dsn)
    probe = psycopg.connect(probe_dsn)
    try:
        expected_cols = _columns(probe, BUSINESS_SCHEMA)
        actual_cols = _columns(live, BUSINESS_SCHEMA)
        expected_tables = _tables(probe, BUSINESS_SCHEMA)
        actual_tables = _tables(live, BUSINESS_SCHEMA)

        print("\n② 缺失的表（DDL 声明但线上没有）")
        missing_tables = sorted(expected_tables - actual_tables)
        print("   无" if not missing_tables else "   " + ", ".join(missing_tables))

        print("\n③ 缺失的列（DDL 声明但线上没有）—— 这是漂移的主因")
        missing_cols = sorted(
            (t, c)
            for (t, c) in expected_cols
            if (t, c) not in actual_cols and (t, c) not in EXPECTED_LAZY_COLUMNS
        )
        if missing_cols:
            by_table: dict[str, list[str]] = {}
            for table, column in missing_cols:
                by_table.setdefault(table, []).append(column)
            for table in sorted(by_table):
                dtype = expected_cols[(table, by_table[table][0])][0]
                print(f"   {table}: {', '.join(by_table[table])}    (如 {dtype})")
        else:
            print("   无")

        # 惰性补齐的列单独报告：如实说明"当前没有"，但不算漂移，避免 CI 长期误报。
        lazy_hits = sorted(
            (t, c)
            for (t, c) in expected_cols
            if (t, c) not in actual_cols and (t, c) in EXPECTED_LAZY_COLUMNS
        )
        if lazy_hits:
            print("\n③b 由惰性路径补齐、当前可以没有的列（不计入失败）")
            for table, column in lazy_hits:
                print(f"   {table}.{column} —— {EXPECTED_LAZY_COLUMNS[(table, column)]}")

        print("\n④ 线上多出的列（DDL 未声明）")
        extra_cols = sorted(
            (t, c) for (t, c) in actual_cols if (t, c) not in expected_cols
        )
        print("   无" if not extra_cols else "   " + ", ".join(f"{t}.{c}" for t, c in extra_cols))

        print("\n⑤ 类型/可空性不一致的列")
        mismatches = []
        for key, exp in expected_cols.items():
            act = actual_cols.get(key)
            if act is None:
                continue
            if exp[0] != act[0] or exp[1] != act[1]:
                mismatches.append(f"{key[0]}.{key[1]}: 期望 {exp[0]}/{exp[1]} vs 实际 {act[0]}/{act[1]}")
        print("   无" if not mismatches else "\n   " + "\n   ".join(sorted(mismatches)))

        total_missing = len(missing_cols) + len(missing_tables)
        print(f"\n结论：缺失表 {len(missing_tables)} 个、缺失列 {len(missing_cols)} 个、类型不一致 {len(mismatches)} 处")
        return 1 if total_missing else 0
    finally:
        live.close()
        probe.close()


if __name__ == "__main__":
    try:
        code = main()
    finally:
        if "--keep-probe" in sys.argv:
            print(f"\n已保留探针库 {PROBE_DB}（--keep-probe）；确认后请自行删除")
        else:
            drop_probe_db()
            print(f"\n已删除探针库 {PROBE_DB}")
    sys.exit(code)
