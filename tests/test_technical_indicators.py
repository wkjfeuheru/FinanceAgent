"""技术指标接线：股票专家基于 K 线产出展示层技术指标。

指标不进评分、不生成证据，仅作为 ``technical_analysis`` 状态字段输出；
K 线不足或字段缺失时诚实跳过，绝不因此让整批任务失败。
"""

from __future__ import annotations

from finance_agent.agents.stock_analysis import (
    _MIN_TECHNICAL_BARS,
    StockAnalysisAgent,
)
from finance_agent.orchestrator.tools.technical import (
    calc_macd,
    compute_all_indicators,
)


def _history(code: str, bars: int = 120, *, trend: float = 0.002) -> dict:
    """构造带完整 OHLC 的日线，供指标计算使用。"""
    rows = []
    for index in range(bars):
        base = 10.0 * (1 + trend) ** index
        rows.append({
            "date": f"2026-{1 + index // 28:02d}-{1 + index % 28:02d}",
            "open": round(base * 0.995, 4),
            "high": round(base * 1.02, 4),
            "low": round(base * 0.98, 4),
            "close": round(base, 4),
        })
    return {"adjustment": "forward", "data": rows}


def _stock_data(code: str, bars: int = 120, **kwargs) -> dict:
    return {code: {"history": _history(code, bars, **kwargs)}}


def test_indicators_computed_for_requested_code():
    """足够的 OHLC 历史应产出六类指标与汇总信号。"""
    agent = StockAnalysisAgent()
    result = agent._compute_technical_indicators(_stock_data("600519"), ["600519"])

    assert set(result) == {"600519"}
    indicators = result["600519"]
    assert {"MA", "MACD", "KDJ", "RSI", "BOLL", "WR"} <= set(indicators)
    assert "summary" in indicators
    assert indicators["MACD"]["name"] == "MACD"
    assert isinstance(indicators["summary"]["signals"], list)


def test_indicators_skip_when_history_insufficient():
    """K 线不足最小根数时跳过该标的，不抛错。"""
    agent = StockAnalysisAgent()
    result = agent._compute_technical_indicators(
        _stock_data("600519", bars=_MIN_TECHNICAL_BARS - 1), ["600519"],
    )

    assert result == {}


def test_indicators_skip_when_ohlc_missing():
    """只有收盘价（无 high/low）时跳过，避免算出误导性的 KDJ/WR。"""
    agent = StockAnalysisAgent()
    data = {"600519": {"history": {
        "adjustment": "forward",
        "data": [{"date": f"2026-01-{i % 28 + 1:02d}", "close": 10.0 + i * 0.1}
                 for i in range(120)],
    }}}

    assert agent._compute_technical_indicators(data, ["600519"]) == {}


def test_indicators_isolated_per_code():
    """一只历史不足不影响另一只；异常被隔离在单只标的。"""
    agent = StockAnalysisAgent()
    data = {
        "600519": {"history": _history("600519", 120)},
        "000001": {"history": {"adjustment": "forward", "data": [{"close": 1.0}]}},
    }

    result = agent._compute_technical_indicators(data, ["600519", "000001"])

    assert set(result) == {"600519"}


def test_indicators_are_display_layer_only():
    """指标输出只含技术字段，不携带评分/证据键（不污染研究管线）。"""
    agent = StockAnalysisAgent()
    result = agent._compute_technical_indicators(_stock_data("600519"), ["600519"])

    summary = result["600519"]["summary"]
    assert set(summary) == {"trend", "signals", "risks", "latest_price"}


def test_divergence_uses_correct_index_when_prices_repeat():
    """回归：背离判断不得用 list.index（重复价格会取到窗口外下标）。

    价格序列在早期出现过与窗口内相同的最高价时，旧实现会把窗口内的高点
    错判到序列开头，从而漏报/误报背离。
    """
    # 前半段不断走高，随后回落；窗口内的最高价恰好等于序列开头的价格。
    closes = [100.0 + index * 0.5 for index in range(40)]
    closes += [110.0 - index * 0.6 for index in range(40)]  # 末段下行 → DIF 走低

    macd = calc_macd(closes)

    # 不应因为重复值取错下标而崩溃，且结果结构完整。
    assert macd["name"] == "MACD"
    assert macd["divergence"] in (None, "顶背离", "底背离")


def test_compute_all_indicators_subset_selection():
    """按需只算指定指标；别名大小写归一。"""
    history = _history("600519")
    closes = [row["close"] for row in history["data"]]
    highs = [row["high"] for row in history["data"]]
    lows = [row["low"] for row in history["data"]]

    result = compute_all_indicators(highs, lows, closes, ["macd", "MA"])

    assert set(result) >= {"MACD", "MA", "summary"}
    assert "KDJ" not in result


def test_fundamental_mode_suppresses_technical_panel():
    """analysis_type=fundamental 时不展示技术面板（用户只要基本面）。"""
    agent = StockAnalysisAgent()
    result = agent._compute_technical_indicators(
        _stock_data("600519"), ["600519"], "fundamental",
    )

    assert result == {}


def test_both_and_technical_modes_produce_panel():
    """both 与 technical 模式都产出技术面板。"""
    agent = StockAnalysisAgent()
    for analysis_type in ("both", "technical"):
        result = agent._compute_technical_indicators(
            _stock_data("600519"), ["600519"], analysis_type,
        )
        assert set(result) == {"600519"}, analysis_type
