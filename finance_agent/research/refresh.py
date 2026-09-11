"""主题有效成员的日终特征刷新。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import argparse
import json
from typing import Any, Callable, Protocol

from finance_agent.research.theme_repository import ThemeRepository


class FeatureSnapshotStore(Protocol):
    def save_feature_snapshot(
        self, *, theme_id: str, stock_code: str, industry: str, rule_version: str,
        as_of: datetime, payload: dict[str, Any],
    ) -> None: ...


@dataclass(frozen=True)
class RefreshSummary:
    theme_id: str
    refreshed_codes: list[str] = field(default_factory=list)
    skipped_pending: list[str] = field(default_factory=list)
    skipped_expired: list[str] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)


class ThemeFeatureRefresher:
    """刷新器不为失败成员写入占位评分。持久化由调用方仓储适配器处理。"""

    def __init__(
        self,
        themes: ThemeRepository,
        fetch_feature: Callable[[str], dict[str, Any]],
        *,
        feature_store: FeatureSnapshotStore | None = None,
        rule_version: str = "research_rules/v1",
    ):
        self._themes = themes
        self._fetch_feature = fetch_feature
        self._feature_store = feature_store
        self._rule_version = rule_version

    def run(self, theme_id: str, as_of: datetime | None = None) -> RefreshSummary:
        now = as_of or datetime.now(timezone.utc)
        active = self._themes.active_members(theme_id, now)
        active_codes = {member.stock_code for member in active}
        pending = [lead.stock_code for lead in self._themes.pending_leads(theme_id) if lead.stock_code not in active_codes]
        expired = self._themes.expired_member_codes(theme_id, now)
        refreshed: list[str] = []
        failures: dict[str, str] = {}
        for member in active:
            try:
                payload = self._fetch_feature(member.stock_code)
                if not isinstance(payload, dict):
                    raise ValueError("特征刷新结果必须为对象")
                if self._feature_store is not None:
                    self._feature_store.save_feature_snapshot(
                        theme_id=theme_id,
                        stock_code=member.stock_code,
                        industry=member.industry,
                        rule_version=self._rule_version,
                        as_of=now,
                        payload=payload,
                    )
                refreshed.append(member.stock_code)
            except Exception as exc:
                failures[member.stock_code] = str(exc)
        return RefreshSummary(theme_id, refreshed, pending, expired, failures)


def refresh_active_theme_features(
    theme_id: str, as_of: datetime | None = None,
) -> RefreshSummary:
    """使用生产数据网关刷新一个主题的有效成员特征。"""
    from finance_agent.config import get_postgres_connection_factory
    from finance_agent.data.postgres_repository import PostgresRuntimeRepository
    from finance_agent.orchestrator.tools.stockdata import fetch_stock_data
    from finance_agent.research.contracts import AnalysisKind, AnalysisRequest, Action
    from finance_agent.research.pipeline import ResearchPipeline
    from finance_agent.research.rule_engine import RuleEngine
    from finance_agent.research.snapshot_builder import production_builder
    from finance_agent.research.theme_repository import (
        PostgresFeatureSnapshotRepository,
        PostgresThemeRepository,
    )

    class _Gateway:
        def get_security_data(self, stock_code: str) -> dict[str, Any]:
            return fetch_stock_data([stock_code]).get(stock_code, {})

    connection_factory = get_postgres_connection_factory()
    PostgresRuntimeRepository(connection_factory).setup_schema()
    rules = RuleEngine.default()
    pipeline = ResearchPipeline(
        snapshot_builder=production_builder(_Gateway()), rule_engine=rules,
    )

    def fetch_feature(stock_code: str) -> dict[str, Any]:
        result, facts = pipeline.analyze_with_facts(
            AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=[stock_code]),
            user_profile={},
        )
        if result.action is Action.INSUFFICIENT_DATA:
            raise ValueError("关键研究数据不足")
        return {
            "analysis_result": result.model_dump(mode="json"),
            "fact_manifest": [fact.model_dump(mode="json") for fact in facts],
            "total_score": result.scores.get("total"),
        }

    return ThemeFeatureRefresher(
        PostgresThemeRepository(connection_factory),
        fetch_feature,
        feature_store=PostgresFeatureSnapshotRepository(connection_factory),
        rule_version=rules.version,
    ).run(theme_id, as_of)


def main(argv: list[str] | None = None) -> int:
    """输出日终刷新 JSON 汇总，供任务调度器直接记录。"""
    parser = argparse.ArgumentParser(description="刷新主题有效成员的研究特征")
    parser.add_argument("--theme-id", action="append", dest="theme_ids", default=[])
    args = parser.parse_args(argv)
    from finance_agent.config import THEME_REFRESH_IDS

    theme_ids = list(dict.fromkeys([*args.theme_ids, *THEME_REFRESH_IDS]))
    if not theme_ids:
        print(json.dumps({"status": "no_theme_ids_configured", "themes": []}, ensure_ascii=False))
        return 0
    summaries = [refresh_active_theme_features(theme_id) for theme_id in theme_ids]
    print(json.dumps(
        {"status": "completed", "themes": [summary.__dict__ for summary in summaries]},
        ensure_ascii=False,
        default=str,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
