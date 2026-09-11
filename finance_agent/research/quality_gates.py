"""确定性数据质量门禁：新鲜度、基本面溯源、来源一致性与跨期检查。

门禁只做判定，不取数、不调用模型、不保存调用状态；交易日计数通过
``TradingDayCounter`` 注入，因此同一输入总能得到同一结论，审计重放只需
回放证据中记录的 ``evaluated_at`` 与阈值版本。

严重度分层（与 ``rules/v1.json`` 的声明保持一致）：

- ``hard_gates`` 违反（报价/K 线超过允许交易日龄）→ 关键缺失，规则层输出“数据不足”。
- 基本面溯源问题（缺报告期、缺披露日、非 TTM、缺估值、跨源混用）→ 警告，
  结论不被阻断，但数据质量不再静默显示 ``complete``。
- 比较请求的标的报告期不一致 → 关键缺失，拒绝出结论。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

# A 股交易日与披露节奏都按市场本地时间判断。
MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")

# 返回值第二项为计数依据："provider" = Provider 交易日历；
# "weekday" = 未配置交易日历的默认估算；"weekday_fallback" = 已配置但取数失败。
TradingDayCounter = Callable[[date, date], "tuple[int, str]"]

_DEFAULT_MAXIMUM_DATA_AGE_TRADING_DAYS = 1
_DEFAULT_MAXIMUM_REPORT_PERIOD_AGE_DAYS = 240
_UNKNOWN_SOURCES = {"unavailable", "unknown", ""}


@dataclass(frozen=True)
class GateConfig:
    """版本化门禁阈值，只能来自规则配置文件。"""

    maximum_data_age_trading_days: int = _DEFAULT_MAXIMUM_DATA_AGE_TRADING_DAYS
    maximum_report_period_age_days: int = _DEFAULT_MAXIMUM_REPORT_PERIOD_AGE_DAYS

    @classmethod
    def from_rules(cls, rules: dict[str, Any]) -> "GateConfig":
        """从规则集读取硬门禁与质量门禁阈值，缺省时退回审定默认值。"""
        source = rules if isinstance(rules, dict) else {}
        hard_gates = source.get("hard_gates", {}) if isinstance(source.get("hard_gates"), dict) else {}
        quality_gates = source.get("quality_gates", {}) if isinstance(source.get("quality_gates"), dict) else {}
        return cls(
            maximum_data_age_trading_days=_positive_int(
                hard_gates.get("maximum_data_age_trading_days"),
                _DEFAULT_MAXIMUM_DATA_AGE_TRADING_DAYS,
            ),
            maximum_report_period_age_days=_positive_int(
                quality_gates.get("maximum_report_period_age_days"),
                _DEFAULT_MAXIMUM_REPORT_PERIOD_AGE_DAYS,
            ),
        )


def _positive_int(value: Any, fallback: int) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return fallback
    return numeric if numeric > 0 else fallback


def market_date(value: Any) -> date | None:
    """把时间戳或日期文本归一到市场本地（Asia/Shanghai）日期。

    naive 时间戳按市场本地时间解释（A 股是唯一市场）；无法解析时返回 ``None``，
    由调用方转为显式质量原因，绝不抛异常。
    """
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=MARKET_TIMEZONE)
        return moment.astimezone(MARKET_TIMEZONE).date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def weekday_trading_days(start: date, end: date) -> tuple[int, str]:
    """纯工作日计数：start 之后（不含）到 end（含）之间的工作日数。

    作为未配置交易日历时的默认估算依据，不访问网络；节假日会被多计，
    因此生产接线应注入 ``data.trading_calendar.trading_days_between``。
    """
    if end <= start:
        return 0, "weekday"
    count = 0
    cursor = start + timedelta(days=1)
    while cursor <= end:
        if cursor.weekday() < 5:
            count += 1
        cursor += timedelta(days=1)
    return count, "weekday"


def _freshness(
    data_date: Any,
    *,
    missing_reason: str,
    stale_reason: str,
    evaluated_at: datetime | date | None,
    config: GateConfig,
    trading_days: TradingDayCounter,
) -> tuple[list[str], dict[str, Any]]:
    """通用新鲜度判定：返回 (关键原因列表, provenance 片段)。"""
    moment = market_date(data_date)
    if moment is None:
        return [missing_reason], {"as_of": None, "age_trading_days": None, "trading_calendar": None}
    provenance: dict[str, Any] = {"as_of": moment.isoformat(), "age_trading_days": None, "trading_calendar": None}
    evaluation = market_date(evaluated_at)
    if evaluation is None:
        return [], provenance
    age, source = trading_days(moment, evaluation)
    provenance.update({"age_trading_days": age, "trading_calendar": source})
    reasons = [stale_reason] if age > config.maximum_data_age_trading_days else []
    return reasons, provenance


def quote_freshness(
    data_date: Any,
    *,
    evaluated_at: datetime | date | None,
    config: GateConfig,
    trading_days: TradingDayCounter = weekday_trading_days,
) -> tuple[list[str], dict[str, Any]]:
    """报价新鲜度：最新原始报价必须落在允许的交易日龄内。"""
    return _freshness(
        data_date,
        missing_reason="quote_as_of_missing",
        stale_reason="stale_quote",
        evaluated_at=evaluated_at,
        config=config,
        trading_days=trading_days,
    )


def history_freshness(
    last_bar_date: Any,
    *,
    evaluated_at: datetime | date | None,
    config: GateConfig,
    trading_days: TradingDayCounter = weekday_trading_days,
) -> tuple[list[str], dict[str, Any]]:
    """K 线新鲜度：最后一根前复权 K 线必须落在允许的交易日龄内。"""
    return _freshness(
        last_bar_date,
        missing_reason="history_as_of_missing",
        stale_reason="stale_history",
        evaluated_at=evaluated_at,
        config=config,
        trading_days=trading_days,
    )


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric


def valuation_basis(indicators: dict[str, Any]) -> str:
    """判断估值依据：ttm（优先）/ static（静态 PE）/ missing（无 PE）。"""
    source = indicators if isinstance(indicators, dict) else {}
    if _number(source.get("pe_ttm")) is not None:
        return "ttm"
    if _number(source.get("pe")) is not None:
        return "static"
    return "missing"


def fundamental_provenance(
    indicators: dict[str, Any],
    *,
    evaluated_at: datetime | date | None,
    config: GateConfig,
) -> tuple[list[str], dict[str, Any]]:
    """基本面溯源校验：报告期、披露日与 TTM 估值依据。

    返回 (警告原因列表, provenance 片段)。报告期/披露日缺失或异常只做披露，
    不阻断结论；TTM 依据与估值可得性同样如此。
    """
    source = indicators if isinstance(indicators, dict) else {}
    warnings: list[str] = []
    end_date = market_date(source.get("end_date"))
    ann_date = market_date(source.get("ann_date"))
    evaluation = market_date(evaluated_at)
    report_lag: int | None = None

    if end_date is None:
        warnings.append("fundamental_report_period_missing")
    elif evaluation is not None:
        report_lag = (evaluation - end_date).days
        if report_lag > config.maximum_report_period_age_days:
            warnings.append("stale_fundamental_report_period")

    if ann_date is None:
        warnings.append("fundamental_disclosure_date_missing")
    else:
        if end_date is not None and ann_date < end_date:
            warnings.append("fundamental_disclosure_before_period")
        if evaluation is not None and ann_date > evaluation:
            warnings.append("fundamental_disclosure_in_future")

    basis = valuation_basis(source)
    if basis == "static":
        warnings.append("valuation_not_ttm")
    elif basis == "missing":
        warnings.append("valuation_metrics_missing")

    return list(dict.fromkeys(warnings)), {
        "end_date": end_date.isoformat() if end_date else None,
        "ann_date": ann_date.isoformat() if ann_date else None,
        "report_period_lag_days": report_lag,
        "valuation_basis": basis,
    }


def source_consistency(sources: dict[str, Any]) -> list[str]:
    """来源一致性：同一个快照的不同数据项不应来自不同 Provider。"""
    distinct = {
        str(value).strip()
        for value in (sources or {}).values()
        if str(value or "").strip() and str(value).strip() not in _UNKNOWN_SOURCES
    }
    return ["mixed_sources"] if len(distinct) > 1 else []


def mixed_report_periods(report_dates: dict[str, Any]) -> list[str]:
    """比较请求中多只标的的报告期必须一致，否则拒绝出结论。"""
    parsed = {
        str(code): market_date(value)
        for code, value in (report_dates or {}).items()
        if market_date(value) is not None
    }
    if len(parsed) < 2:
        return []
    return ["mixed_report_period"] if len(set(parsed.values())) > 1 else []


def calendar_degradation_reasons(*provenances: dict[str, Any]) -> list[str]:
    """交易日历取数失败（已配置但降级为工作日估算）时披露原因。"""
    for provenance in provenances:
        if isinstance(provenance, dict) and provenance.get("trading_calendar") == "weekday_fallback":
            return ["trading_calendar_unavailable"]
    return []


__all__ = [
    "GateConfig",
    "MARKET_TIMEZONE",
    "TradingDayCounter",
    "calendar_degradation_reasons",
    "fundamental_provenance",
    "history_freshness",
    "market_date",
    "mixed_report_periods",
    "quote_freshness",
    "source_consistency",
    "valuation_basis",
    "weekday_trading_days",
]
