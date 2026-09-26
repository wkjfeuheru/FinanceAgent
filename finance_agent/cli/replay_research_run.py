"""从 PostgreSQL 审计记录复算研究结论的 CLI。"""

from __future__ import annotations

import argparse
import json

from finance_agent.infrastructure.persistence.postgres.audit_repository import PostgresAuditStore
from finance_agent.domains.research.replay import ReplayOutcome, replay_research_run


def replay_stored_run(
    research_run_id: str, *, provider_calendar: bool = False,
) -> ReplayOutcome | None:
    """读取持久化审计记录，再通过领域纯函数重放。"""
    record = PostgresAuditStore.from_config().load_research_run(research_run_id)
    if not record:
        return None

    calendar_counter = None
    if provider_calendar:
        from finance_agent.infrastructure.market_data.trading_calendar import trading_days_between

        calendar_counter = trading_days_between
    return replay_research_run(
        research_run_id=str(record.get("research_run_id") or research_run_id),
        request_data=record.get("request_data"),
        results=list(record.get("results") or []),
        snapshot_manifest=list(record.get("snapshot_manifest") or []),
        rule_version=str(record.get("rule_version") or ""),
        provider_calendar=provider_calendar,
        provider_calendar_counter=calendar_counter,
    )


def main(argv: list[str] | None = None) -> int:
    """输出审计重放 JSON，供人工核查与调度记录。"""
    parser = argparse.ArgumentParser(
        prog="finance_agent.domains.research.replay",
        description="从审计记录复算确定性研究结论",
    )
    parser.add_argument("--research-run-id", required=True)
    parser.add_argument(
        "--provider-calendar", action="store_true",
        help="允许使用 Provider 交易日历复现原运行的新鲜度判定",
    )
    args = parser.parse_args(argv)

    outcome = replay_stored_run(args.research_run_id, provider_calendar=args.provider_calendar)
    if outcome is None:
        print(json.dumps(
            {"status": "research_run_not_found", "research_run_id": args.research_run_id},
            ensure_ascii=False,
        ))
        return 1
    print(json.dumps(outcome.__dict__, ensure_ascii=False, default=str))
    return 0 if outcome.matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
