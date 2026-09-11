"""防未来函数的主题特征滚动前推回测。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class FeatureSnapshot:
    """在给定时点可用的已计算特征及其后续已实现收益。"""

    theme_id: str
    stock_code: str
    industry: str
    rule_version: str
    as_of: datetime
    payload: dict[str, Any]


class FeatureSnapshotRepository(Protocol):
    def snapshots_before(
        self, theme_id: str, rule_version: str, as_of: datetime,
    ) -> list[FeatureSnapshot]: ...


class InMemoryFeatureSnapshotRepository:
    """供回测和单元测试使用的特征快照只读仓储。"""

    def __init__(self, snapshots: list[FeatureSnapshot] | None = None):
        self._snapshots = list(snapshots or [])

    def snapshots_before(
        self, theme_id: str, rule_version: str, as_of: datetime,
    ) -> list[FeatureSnapshot]:
        return [
            snapshot for snapshot in self._snapshots
            if snapshot.theme_id == theme_id
            and snapshot.rule_version == rule_version
            and snapshot.as_of <= as_of
        ]


@dataclass(frozen=True)
class BacktestReport:
    theme_id: str
    rule_version: str
    publication_status: Literal["experimental", "default", "rejected"]
    rebalance_dates: list[date] = field(default_factory=list)
    used_snapshot_dates: list[date] = field(default_factory=list)
    hit_rate: float | None = None
    maximum_drawdown: float | None = None
    turnover_rate: float | None = None
    industry_concentration: float | None = None
    data_missing_rate: float | None = None


def _close_of_day(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=timezone.utc)


def _latest_per_stock(snapshots: list[FeatureSnapshot]) -> list[FeatureSnapshot]:
    latest: dict[str, FeatureSnapshot] = {}
    for snapshot in snapshots:
        current = latest.get(snapshot.stock_code)
        if current is None or snapshot.as_of > current.as_of:
            latest[snapshot.stock_code] = snapshot
    return sorted(latest.values(), key=lambda item: item.stock_code)


def _as_float(payload: dict[str, Any], key: str) -> float | None:
    try:
        return float(payload[key])
    except (KeyError, TypeError, ValueError):
        return None


def run_walk_forward_backtest(
    repository: FeatureSnapshotRepository,
    theme_id: str,
    start: date,
    end: date,
    rule_version: str,
    *,
    rebalance_dates: list[date] | None = None,
    publication_status: Literal["experimental", "default", "rejected"] = "experimental",
) -> BacktestReport:
    """只选择再平衡日及之前的最后一份特征快照，并计算审计指标。"""
    dates = sorted(set(rebalance_dates or [start]))
    dates = [value for value in dates if start <= value <= end]
    selected_by_date: list[list[FeatureSnapshot]] = []
    used_dates: list[date] = []
    returns: list[float] = []
    missing = 0
    total = 0

    for rebalance_date in dates:
        eligible = _latest_per_stock(
            repository.snapshots_before(theme_id, rule_version, _close_of_day(rebalance_date))
        )
        selected_by_date.append(eligible)
        if eligible:
            used_dates.append(max(item.as_of.date() for item in eligible))
        day_returns: list[float] = []
        for snapshot in eligible:
            total += 1
            realized_return = _as_float(snapshot.payload, "realized_return")
            if realized_return is None:
                missing += 1
                continue
            day_returns.append(realized_return)
        if day_returns:
            returns.append(sum(day_returns) / len(day_returns))

    observation_count = len(returns)
    hit_rate = (
        sum(value > 0 for value in returns) / observation_count
        if observation_count else None
    )
    equity = 1.0
    peak = 1.0
    maximum_drawdown = 0.0
    for value in returns:
        equity *= 1 + value
        peak = max(peak, equity)
        maximum_drawdown = min(maximum_drawdown, equity / peak - 1)

    turnover_samples: list[float] = []
    for previous, current in zip(selected_by_date, selected_by_date[1:]):
        before = {item.stock_code for item in previous}
        after = {item.stock_code for item in current}
        denominator = max(len(before), len(after), 1)
        turnover_samples.append(len(before.symmetric_difference(after)) / denominator)

    industries = [item.industry for group in selected_by_date for item in group if item.industry]
    industry_concentration = None
    if industries:
        industry_concentration = max(industries.count(item) for item in set(industries)) / len(industries)

    return BacktestReport(
        theme_id=theme_id,
        rule_version=rule_version,
        publication_status=publication_status,
        rebalance_dates=dates,
        used_snapshot_dates=used_dates,
        hit_rate=hit_rate,
        maximum_drawdown=maximum_drawdown if returns else None,
        turnover_rate=sum(turnover_samples) / len(turnover_samples) if turnover_samples else 0.0,
        industry_concentration=industry_concentration,
        data_missing_rate=missing / total if total else None,
    )
