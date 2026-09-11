"""滚动前推回测必须隔离再平衡日之后的特征快照。"""

from datetime import date, datetime, timezone

from finance_agent.research.backtest import (
    FeatureSnapshot,
    InMemoryFeatureSnapshotRepository,
    run_walk_forward_backtest,
)


def test_backtest_never_uses_future_snapshot():
    """防止排序信号错误地读取再平衡日后的高分特征。"""
    repository = InMemoryFeatureSnapshotRepository([
        FeatureSnapshot(
            theme_id="ai_compute", stock_code="600519", industry="白酒",
            rule_version="research_rules/v1", as_of=datetime(2026, 1, 5, tzinfo=timezone.utc),
            payload={"total_score": 75, "realized_return": 0.05},
        ),
        FeatureSnapshot(
            theme_id="ai_compute", stock_code="600519", industry="白酒",
            rule_version="research_rules/v1", as_of=datetime(2026, 2, 5, tzinfo=timezone.utc),
            payload={"total_score": 99, "realized_return": 0.90},
        ),
    ])

    report = run_walk_forward_backtest(
        repository, "ai_compute", date(2026, 1, 1), date(2026, 3, 31),
        "research_rules/v1", rebalance_dates=[date(2026, 1, 31)],
    )

    assert report.rebalance_dates == [date(2026, 1, 31)]
    assert report.used_snapshot_dates == [date(2026, 1, 5)]
    assert report.hit_rate == 1.0
