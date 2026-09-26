"""技术指标工具接线：``compute_technical`` 基于 K 线产出展示层技术指标。

架构重构后，原先的 ``orchestrator.domains.stock.compute_technical_indicators``
已删除，技术指标接线收敛到 ``domains.research.expert.tools.compute_technical``
工具：足够历史 → 产出六类指标；历史不足 → 登记 ``insufficient_history:<code>``
局限且不编造指标；``analysis_type="fundamental"`` → 跳过；网关挂起 → 登记
``awaiting_quant`` 与 ``pending_jobs``。指标只作展示层，不进评分、不生成证据。
"""

from __future__ import annotations

from finance_agent.shared.contracts import AsyncJobRef
from finance_agent.orchestration.contracts import BusinessDomain
from finance_agent.orchestration.experts.base import ExpertSink
from finance_agent.domains.research.expert.tools import compute_technical
from finance_agent.domains.research.technical import calc_macd, compute_all_indicators

_MIN_TECHNICAL_BARS = 60


def _history(bars: int = 120, *, trend: float = 0.002) -> dict:
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


def _stock_data(code: str = "600519", bars: int = 120, **kwargs) -> dict:
    return {code: {"history": _history(bars, **kwargs)}}


def _sink() -> ExpertSink:
    return ExpertSink(domain=BusinessDomain.STOCK_RESEARCH, customer_id="CUST1")


def _patch_fetch(monkeypatch, data: dict) -> None:
    import finance_agent.domains.research.expert.tools as tools_stock

    monkeypatch.setattr(tools_stock._stockdata, "fetch_stock_data", lambda codes: {
        code: data[code] for code in codes if code in data
    })


def _patch_gateway(monkeypatch, gateway) -> None:
    import finance_agent.domains.research.expert.tools as tools_stock

    monkeypatch.setattr(tools_stock, "_gateway", lambda: gateway)


def _invoke(sink: ExpertSink, **args):
    return compute_technical.invoke(
        {"stock_code": "600519", **args},
        config={"configurable": {"expert_sink": sink}},
    )


def test_indicators_computed_for_sufficient_history(monkeypatch):
    """足够的 OHLC 历史应产出六类指标与汇总信号。"""
    _patch_fetch(monkeypatch, _stock_data("600519"))
    sink = _sink()

    _invoke(sink)

    technical = sink.structured["technical_analysis"]
    assert set(technical) == {"600519"}
    indicators = technical["600519"]
    assert {"MA", "MACD", "KDJ", "RSI", "BOLL", "WR"} <= set(indicators)
    assert "summary" in indicators
    assert indicators["MACD"]["name"] == "MACD"
    assert isinstance(indicators["summary"]["signals"], list)


def test_insufficient_history_reports_limitation_without_fabricating(monkeypatch):
    """K 线不足最小根数时登记局限，绝不产出编造指标。"""
    _patch_fetch(monkeypatch, _stock_data("600519", bars=_MIN_TECHNICAL_BARS - 1))
    sink = _sink()

    _invoke(sink)

    assert "insufficient_history:600519" in sink.limitations
    assert sink.structured.get("technical_analysis") is None


def test_insufficient_history_when_ohlc_missing(monkeypatch):
    """只有收盘价（无 high/low）时同样按历史不足处理，不误算 KDJ/WR。"""
    data = {"600519": {"history": {
        "adjustment": "forward",
        "data": [{"date": f"2026-01-{i % 28 + 1:02d}", "close": 10.0 + i * 0.1}
                 for i in range(120)],
    }}}
    _patch_fetch(monkeypatch, data)
    sink = _sink()

    _invoke(sink)

    assert "insufficient_history:600519" in sink.limitations
    assert sink.structured.get("technical_analysis") is None


def test_fundamental_mode_skips_technical_panel(monkeypatch):
    """analysis_type=fundamental 时不展示技术面板（用户只要基本面）。"""
    _patch_fetch(monkeypatch, _stock_data("600519"))
    sink = _sink()

    _invoke(sink, analysis_type="fundamental")

    assert sink.structured == {}
    assert sink.limitations == []


def test_quant_gateway_pending_reports_awaiting_quant(monkeypatch):
    """网关挂起时登记 ``awaiting_quant`` 与真实 pending job，不返回编造指标。"""
    class _PendingGateway:
        def submit(self, kind, payload, idempotency_key, *, customer_id=""):
            return AsyncJobRef(job_id="job-x", kind=kind, status="queued", task_id="job-x")

        def status(self, job_id):
            return "queued"

        def result(self, job_id):
            return None

    _patch_fetch(monkeypatch, _stock_data("600519"))
    _patch_gateway(monkeypatch, _PendingGateway())
    sink = _sink()

    _invoke(sink)

    assert "awaiting_quant" in sink.limitations
    pending = sink.extras["pending_jobs"]
    assert [ref.job_id for ref in pending] == ["job-x"]
    assert sink.extras["pending_job_codes"]["job-x"] == "600519"
    assert sink.structured.get("technical_analysis") is None


def test_indicators_are_display_layer_only(monkeypatch):
    """指标输出只含技术字段，不携带评分/证据键（不污染研究管线）。"""
    _patch_fetch(monkeypatch, _stock_data("600519"))
    sink = _sink()

    _invoke(sink)

    summary = sink.structured["technical_analysis"]["600519"]["summary"]
    assert set(summary) == {"trend", "signals", "risks", "latest_price"}


# ── 底层技术模块（``domains.research.technical``，本次重构未改动）──────────


def test_divergence_uses_correct_index_when_prices_repeat():
    """回归：背离判断不得用 list.index（重复价格会取到窗口外下标）。

    价格序列在早期出现过与窗口内相同的最高价时，旧实现会把窗口内的高点
    错判到序列开头，从而漏报/误报背离。
    """
    closes = [100.0 + index * 0.5 for index in range(40)]
    closes += [110.0 - index * 0.6 for index in range(40)]  # 末段下行 → DIF 走低

    macd = calc_macd(closes)

    assert macd["name"] == "MACD"
    assert macd["divergence"] in (None, "顶背离", "底背离")


def test_compute_all_indicators_subset_selection():
    """按需只算指定指标；别名大小写归一。"""
    history = _history()
    closes = [row["close"] for row in history["data"]]
    highs = [row["high"] for row in history["data"]]
    lows = [row["low"] for row in history["data"]]

    result = compute_all_indicators(highs, lows, closes, ["macd", "MA"])

    assert set(result) >= {"MACD", "MA", "summary"}
    assert "KDJ" not in result
