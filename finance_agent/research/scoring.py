"""将原始财务和价格数据转换为确定性研究评分。"""

from __future__ import annotations

from math import isfinite, sqrt
from statistics import fmean, pstdev
from typing import Any


_SCORE_KEYS = ("fundamental_score", "technical_score", "risk_score")


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None


def _first_number(values: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        numeric = _number(values.get(key))
        if numeric is not None:
            return numeric
    return None


def _bounded(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


def _average(values: list[float]) -> float | None:
    return _bounded(fmean(values)) if values else None


def _roe_score(value: float) -> float:
    if value >= 20:
        return 95.0
    if value >= 15:
        return 85.0
    if value >= 10:
        return 70.0
    if value >= 5:
        return 50.0
    return 30.0 if value > 0 else 10.0


def _growth_score(value: float) -> float:
    if value >= 25:
        return 95.0
    if value >= 10:
        return 80.0
    if value >= 0:
        return 60.0
    if value >= -10:
        return 35.0
    return 15.0


def _pe_score(value: float) -> float | None:
    if value <= 0:
        return None
    if value <= 15:
        return 90.0
    if value <= 25:
        return 80.0
    if value <= 40:
        return 60.0
    if value <= 60:
        return 40.0
    return 20.0


def _pb_score(value: float) -> float | None:
    if value <= 0:
        return None
    if value <= 1.5:
        return 90.0
    if value <= 3:
        return 75.0
    if value <= 5:
        return 55.0
    return 30.0


def _close_prices(history: dict[str, Any]) -> list[float]:
    rows = history.get("data", []) if isinstance(history, dict) else []
    if not isinstance(rows, list):
        return []
    prices: list[float] = []
    for row in rows:
        value = _number(row.get("close")) if isinstance(row, dict) else None
        if value is not None and value > 0:
            prices.append(value)
    return prices


def _volatility(prices: list[float]) -> float:
    returns = [
        prices[index] / prices[index - 1] - 1.0
        for index in range(1, len(prices))
        if prices[index - 1] > 0
    ]
    return pstdev(returns) * sqrt(252) if len(returns) >= 2 else 0.0


def _maximum_drawdown(prices: list[float]) -> float:
    peak = prices[0]
    drawdown = 0.0
    for price in prices:
        peak = max(peak, price)
        drawdown = min(drawdown, price / peak - 1.0)
    return drawdown


def _volatility_score(value: float) -> float:
    if value <= 0.20:
        return 90.0
    if value <= 0.35:
        return 70.0
    if value <= 0.50:
        return 45.0
    return 20.0


def _drawdown_score(value: float) -> float:
    if value >= -0.10:
        return 90.0
    if value >= -0.20:
        return 70.0
    if value >= -0.35:
        return 40.0
    return 15.0


def build_scores(
    indicators: dict[str, Any], history: dict[str, Any],
) -> tuple[dict[str, float | None], list[str]]:
    """从原始财务/估值/K 线构造研究评分及不可计算原因。"""
    raw = indicators if isinstance(indicators, dict) else {}
    restrictions: list[str] = []

    roe = _first_number(raw, "roe", "roe_wa", "roe_dt")
    revenue_growth = _first_number(raw, "revenue_yoy", "or_yoy")
    profit_growth = _first_number(raw, "netprofit_yoy", "profit_yoy")
    pe = _first_number(raw, "pe_ttm", "pe")
    pb = _first_number(raw, "pb")
    fundamental_values = [
        score for score in (
            _roe_score(roe) if roe is not None else None,
            _growth_score(revenue_growth) if revenue_growth is not None else None,
            _growth_score(profit_growth) if profit_growth is not None else None,
            _pe_score(pe) if pe is not None else None,
            _pb_score(pb) if pb is not None else None,
        ) if score is not None
    ]
    fundamental = _average(fundamental_values)
    if fundamental is None:
        restrictions.append("fundamental_metrics")

    prices = _close_prices(history)
    if len(prices) < 60:
        restrictions.extend(("price_history", "risk_history"))
        technical = None
        risk = None
    else:
        ma20 = fmean(prices[-20:])
        ma60 = fmean(prices[-60:])
        trend = ma20 / ma60 - 1.0
        trend_score = 90.0 if trend >= 0.10 else 75.0 if trend >= 0.03 else 60.0 if trend >= 0 else 40.0 if trend >= -0.05 else 20.0
        momentum = prices[-1] / prices[-21] - 1.0
        momentum_score = 90.0 if momentum >= 0.15 else 75.0 if momentum >= 0.05 else 60.0 if momentum >= 0 else 35.0 if momentum >= -0.10 else 15.0
        volatility = _volatility(prices[-21:])
        technical = _average([trend_score, momentum_score, _volatility_score(volatility)])
        risk = _average([
            _volatility_score(_volatility(prices)),
            _drawdown_score(_maximum_drawdown(prices)),
        ])
        if (profit_growth is not None and profit_growth < 0) or (revenue_growth is not None and revenue_growth < 0):
            risk = _bounded((risk or 0.0) - 20.0)
        if pe is not None and pe > 60:
            risk = _bounded((risk or 0.0) - 15.0)

    return {
        "fundamental_score": fundamental,
        "technical_score": technical,
        "risk_score": risk,
    }, restrictions


__all__ = ["build_scores"]
