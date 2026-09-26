"""板块筛选工具：定位板块 → 预筛 → 确定性评分排序 → 落结构化产物。

这是"帮我推荐几个AI行业值得关注的股票"的实际执行路径，全部离线（provider 与
``evaluate`` 都注入假实现）。重点钉住：预筛与排序口径、预算收敛、ST/停牌过滤、
停止/数据不可用时的诚实降级，以及清单必须带口径说明与免责。
"""

from __future__ import annotations

import json

import pytest

from finance_agent.domains.research.contracts import (
    Action,
    AnalysisKind,
    AnalysisRequest,
    AnalysisResult,
)
from finance_agent.domains.research.expert import screening
from finance_agent.orchestration.contracts import BusinessDomain
from finance_agent.orchestration.experts.base import ExpertSink, SINK_KEY, STOP_CHECK_KEY

CONCEPT_BOARDS = [
    {"name": "人工智能", "code": "BK0800", "change_pct": 2.34, "up_count": 88, "down_count": 12, "leader": "某科技"},
    {"name": "半导体", "code": "BK1036", "change_pct": -1.2, "up_count": 30, "down_count": 90},
]
INDUSTRY_BOARDS = [{"name": "软件开发", "code": "BK0737", "change_pct": 0.8}]

CONSTITUENTS = [
    {"code": "300308", "name": "中际旭创", "price": 123.4, "change_pct": 5.6, "turnover_amount": 2_000_000_000.0},
    {"code": "002230", "name": "科大讯飞", "price": 55.1, "change_pct": 1.1, "turnover_amount": 1_500_000_000.0},
    {"code": "688111", "name": "金山办公", "price": 300.0, "change_pct": 0.5, "turnover_amount": 1_200_000_000.0},
    {"code": "600519", "name": "贵州茅台", "price": 1700.0, "change_pct": 0.2, "turnover_amount": 900_000_000.0},
    {"code": "000001", "name": "平安银行", "price": 11.0, "change_pct": 0.0, "turnover_amount": 700_000_000.0},
]


class _FakeManager:
    def __init__(self, constituents=None, fail: bool = False, board_fail=None) -> None:
        self.constituents = list(constituents if constituents is not None else CONSTITUENTS)
        self.fail = fail
        #: 让指定板块类型的**列表**取数失败（区分"数据源挂了"与"关键词没匹配到"）。
        self.board_fail = set(board_fail or ())
        self.calls: list[tuple[str, str]] = []

    def get_board_list(self, board_type: str = "concept"):
        if board_type in self.board_fail:
            raise RuntimeError(f"board source down ({board_type})")
        return list(CONCEPT_BOARDS if board_type == "concept" else INDUSTRY_BOARDS)

    def get_board_constituents(self, board_name: str, board_type: str = "concept"):
        self.calls.append((board_type, board_name))
        if self.fail:
            raise RuntimeError("board source down")
        return list(self.constituents)


class _Fact:
    def __init__(self, fact_id: str) -> None:
        self.fact_id = fact_id

    def model_dump(self, mode: str = "json"):
        return {"fact_id": self.fact_id, "payload": {}}


def _result(code: str, total: float | None, action: Action = Action.WATCH, quality: str = "complete"):
    return AnalysisResult(
        request=AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=[code]),
        action=action,
        data_quality=quality,
        rule_version="research_rules/v1.2",
        scores={"fundamental": 1.0, "technical": 1.0, "risk": 1.0, "suitability": 1.0, "total": total},
        evidence_ids=[f"{code}-fact"],
        personalization_status="research_candidate",
        narrative=f"{code} 的确定性结论。",
    )


def _sink() -> ExpertSink:
    return ExpertSink(domain=BusinessDomain.STOCK_RESEARCH)


def _invoke(tool, args, sink, stop=None):
    config: dict = {"configurable": {SINK_KEY: sink}}
    if stop is not None:
        config["configurable"][STOP_CHECK_KEY] = stop
    return json.loads(tool.invoke(args, config=config))


def _patch(monkeypatch, manager, scores: dict[str, float | None], best_action: Action = Action.WATCH):
    """注入假 provider manager 与假确定性评估（按代码给总分）。"""
    evaluated: list[str] = []

    def fake_evaluate(request, *, user_profile, gateway):
        code = request.stock_codes[0]
        evaluated.append(code)
        total = scores.get(code)
        if total is None and code in scores:
            return (
                _result(code, None, Action.INSUFFICIENT_DATA, quality="critical_missing"),
                [_Fact(f"{code}-fact")],
            )
        return _result(code, total, best_action), [_Fact(f"{code}-fact")]

    monkeypatch.setattr(screening, "get_provider_manager", lambda: manager)
    monkeypatch.setattr(screening, "evaluate", fake_evaluate)
    return evaluated


# ── 板块定位 ──────────────────────────────────────────────────────────────────

def test_list_boards_matches_by_name_and_reports_market_data(monkeypatch):
    monkeypatch.setattr(screening, "get_provider_manager", lambda: _FakeManager())

    payload = json.loads(screening.list_boards.invoke({"keyword": "人工智能"}))

    assert payload["status"] == "ok"
    assert payload["boards"][0]["name"] == "人工智能"
    assert payload["boards"][0]["board_type"] == "concept"
    assert payload["boards"][0]["change_pct"] == 2.34


def test_list_boards_expands_ai_alias_then_hints_when_missing(monkeypatch):
    monkeypatch.setattr(screening, "get_provider_manager", lambda: _FakeManager())

    matched = json.loads(screening.list_boards.invoke({"keyword": "AI"}))
    missing = json.loads(screening.list_boards.invoke({"keyword": "量子计算"}))

    assert [board["name"] for board in matched["boards"]] == ["人工智能"]
    assert missing["status"] == "not_found"
    assert missing["hint"] == screening.NO_MATCH_HINT
    # 数据确实取到了：这不是数据源故障，只是关键词没对上。
    assert missing["fetched_types"] == ["concept", "industry"]
    assert missing["unavailable_types"] == []


def test_list_boards_reports_unavailable_when_every_board_type_fails(monkeypatch):
    """板块取数全挂时必须说"数据源不可用"，绝不能把故障说成"没匹配到"。"""
    manager = _FakeManager(board_fail={"concept", "industry"})
    monkeypatch.setattr(screening, "get_provider_manager", lambda: manager)

    payload = json.loads(screening.list_boards.invoke({"keyword": "AI"}))

    assert payload["status"] == "unavailable"
    assert payload["hint"] == screening.BOARD_UNAVAILABLE_HINT
    assert payload["fetched_types"] == []
    assert payload["unavailable_types"] == ["concept", "industry"]
    assert set(payload["reasons"]) == {"concept", "industry"}
    assert payload["retryable"] is True
    # 误导性引导文案一个都不能出现：改关键词对数据源故障毫无帮助。
    assert "未匹配" not in payload["hint"]
    assert payload["hint"] != screening.NO_MATCH_HINT


def test_list_boards_marks_partial_source_failure_as_degraded(monkeypatch):
    """只有一类取到数据时仍可回答，但必须把"只查了一半"标出来。"""
    manager = _FakeManager(board_fail={"concept"})
    monkeypatch.setattr(screening, "get_provider_manager", lambda: manager)

    payload = json.loads(screening.list_boards.invoke({"keyword": "软件"}))

    assert payload["status"] == "ok"
    assert payload["boards"][0]["board_type"] == "industry"
    assert payload["fetched_types"] == ["industry"]
    assert payload["unavailable_types"] == ["concept"]
    assert payload["degraded"] is True


def test_list_boards_not_found_on_partial_data_is_still_degraded(monkeypatch):
    """一半板块表没取到时，``not_found`` 可能是漏查造成的假阴性，必须标 degraded。"""
    manager = _FakeManager(board_fail={"concept"})
    monkeypatch.setattr(screening, "get_provider_manager", lambda: manager)

    payload = json.loads(screening.list_boards.invoke({"keyword": "量子计算"}))

    assert payload["status"] == "not_found"
    assert payload["unavailable_types"] == ["concept"]
    assert payload["degraded"] is True


def test_list_boards_rejects_unknown_board_type():
    payload = json.loads(screening.list_boards.invoke({"keyword": "人工智能", "board_type": "theme"}))

    assert payload["status"] == "error"
    assert "board_type" in payload["error"] or "板块类型" in payload["error"]


# ── 候选筛选 ──────────────────────────────────────────────────────────────────

def test_screen_ranks_by_total_score_and_writes_structured_payload(monkeypatch):
    manager = _FakeManager()
    scores = {"300308": 6.0, "002230": 9.0, "688111": 7.5, "600519": 5.0, "000001": 4.0}
    evaluated = _patch(monkeypatch, manager, scores)
    sink = _sink()

    payload = _invoke(
        screening.screen_board_candidates,
        {"board_name": "人工智能", "board_type": "concept"},
        sink,
    )

    assert payload["status"] == "complete"
    # 排序口径沿用确定性评分（不是涨跌幅）：002230 > 688111 > 300308 …
    assert [item["code"] for item in payload["selected"]] == [
        "002230", "688111", "300308", "600519", "000001",
    ]
    assert payload["selected"][0]["action"] == "关注"
    assert payload["selected"][0]["rule_version"] == "research_rules/v1.2"
    assert payload["prescreen"] == screening.PRESCREEN_NOTE
    assert payload["disclaimer"] == screening.SCREEN_DISCLAIMER
    assert payload["source"]["source"] in {"unavailable", None} or isinstance(payload["source"], dict)
    # 已评估结果落进 sink：确定性内核守卫与前端卡片都靠这两个键。
    assert len(sink.structured["analysis_results"]) == len(evaluated)
    assert set(sink.structured["stock_analysis"]) == set(evaluated)
    assert sink.structured["board_candidates"]["board"] == "人工智能"
    assert manager.calls == [("concept", "人工智能")]


def test_screen_excludes_risk_warning_retired_and_suspended_members(monkeypatch):
    rows = [
        {"code": "300308", "name": "中际旭创", "price": 123.4, "change_pct": 5.6, "turnover_amount": 900.0},
        {"code": "002230", "name": "ST讯飞", "price": 55.1, "change_pct": 1.1, "turnover_amount": 800.0},
        {"code": "688111", "name": "退市办公", "price": 1.0, "change_pct": 0.0, "turnover_amount": 700.0},
        {"code": "600519", "name": "贵州茅台", "price": None, "change_pct": None, "turnover_amount": None},
        {"code": "000001", "name": "平安银行", "price": 11.0, "change_pct": 0.0, "turnover_amount": 600.0},
        {"code": "430047", "name": "诺思兰德", "price": 5.0, "change_pct": 0.0, "turnover_amount": 500.0},
        {"code": "920799", "name": "北交所样例", "price": 5.0, "change_pct": 0.0, "turnover_amount": 400.0},
    ]
    manager = _FakeManager(constituents=rows)
    evaluated = _patch(monkeypatch, manager, {code: 1.0 for code in ("300308", "000001", "430047")})

    _invoke(screening.screen_board_candidates, {"board_name": "人工智能"}, _sink())

    # ST / 退市 / 停牌 / 非注册代码段（920）都不进入评估。
    assert evaluated == ["300308", "000001", "430047"]


def test_screen_prescreens_by_turnover_and_clamps_limits(monkeypatch):
    manager = _FakeManager()
    evaluated = _patch(monkeypatch, manager, {code: 1.0 for code in ("300308", "002230", "688111")})
    sink = _sink()

    payload = _invoke(
        screening.screen_board_candidates,
        {"board_name": "人工智能", "max_evaluations": 3, "max_results": 2},
        sink,
    )

    # 预筛口径 = 成交额降序：只评估前三只，返回前两只。
    assert evaluated == ["300308", "002230", "688111"]
    assert payload["max_evaluations"] == 3
    assert payload["max_results"] == 2
    assert len(payload["selected"]) == 2
    # 合格成分总数与预筛后的评估范围分别上报（回答里要说明评估范围）。
    assert payload["eligible_size"] == len(CONSTITUENTS)
    assert payload["prescreened_size"] == 3


def test_screen_cannot_raise_limits_above_server_budget(monkeypatch):
    manager = _FakeManager()
    _patch(monkeypatch, manager, {code: 1.0 for code in ("300308", "002230", "688111")})

    payload = _invoke(
        screening.screen_board_candidates,
        {"board_name": "人工智能", "max_evaluations": 99, "max_results": 99},
        _sink(),
    )

    from finance_agent.orchestration.budgets import RunBudgets

    budgets = RunBudgets.from_config()
    assert payload["max_evaluations"] == budgets.screen_max_evaluations
    assert payload["max_results"] == budgets.screen_max_results


def test_screen_returns_insufficient_coverage_without_list(monkeypatch):
    manager = _FakeManager(constituents=CONSTITUENTS[:2])
    evaluated = _patch(monkeypatch, manager, {"300308": 1.0, "002230": 1.0})
    sink = _sink()

    payload = _invoke(screening.screen_board_candidates, {"board_name": "人工智能"}, sink)

    assert payload["status"] == "insufficient_coverage"
    assert evaluated == []
    assert "selected" not in payload
    assert "screening_insufficient_coverage" in sink.limitations


def test_screen_excludes_insufficient_data_candidates(monkeypatch):
    manager = _FakeManager()
    scores = {"300308": 6.0, "002230": 9.0, "688111": 7.5, "600519": None, "000001": 4.0}
    _patch(monkeypatch, manager, scores)
    sink = _sink()

    payload = _invoke(screening.screen_board_candidates, {"board_name": "人工智能"}, sink)

    assert [item["code"] for item in payload["selected"]] == ["002230", "688111", "300308", "000001"]
    assert {"code": "600519", "name": "贵州茅台", "reason": "critical_missing"} in payload["exclusions"]


def test_screen_stops_between_candidates_when_host_requests_stop(monkeypatch):
    manager = _FakeManager()
    evaluated = _patch(monkeypatch, manager, {code: 1.0 for code in ("300308", "002230", "688111", "600519", "000001")})
    sink = _sink()
    checks: list[int] = []

    def stop():
        checks.append(1)
        return "turn_deadline_exceeded" if len(checks) > 1 else ""

    payload = _invoke(
        screening.screen_board_candidates,
        {"board_name": "人工智能"},
        sink,
        stop=stop,
    )

    # 每只之前检查一次：第二次命中后不再开始新的评估。
    assert evaluated == ["300308"]
    assert payload["halted"] == "turn_deadline_exceeded"
    assert "turn_deadline_exceeded" in sink.limitations


def test_screen_reports_unavailable_when_board_source_fails(monkeypatch):
    manager = _FakeManager(fail=True)
    _patch(monkeypatch, manager, {})
    sink = _sink()

    payload = _invoke(screening.screen_board_candidates, {"board_name": "人工智能"}, sink)

    assert payload["status"] == "unavailable"
    assert "board_data_unavailable" in sink.limitations
    assert "analysis_results" not in sink.structured


def test_screen_reports_unavailable_when_every_evaluation_fails(monkeypatch):
    manager = _FakeManager()

    def boom(request, *, user_profile, gateway):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(screening, "get_provider_manager", lambda: manager)
    monkeypatch.setattr(screening, "evaluate", boom)
    sink = _sink()

    payload = _invoke(screening.screen_board_candidates, {"board_name": "人工智能"}, sink)

    assert payload["status"] == "unavailable"
    assert "screening_evaluate_failed" in sink.limitations


def test_screen_requires_board_name(monkeypatch):
    monkeypatch.setattr(screening, "get_provider_manager", lambda: _FakeManager())

    payload = _invoke(screening.screen_board_candidates, {"board_name": "  "}, _sink())

    assert payload["status"] == "error"
    assert payload["hint"] == screening.NO_MATCH_HINT


@pytest.mark.parametrize("bad_type", ["theme", "板块"])
def test_screen_rejects_unknown_board_type(monkeypatch, bad_type):
    monkeypatch.setattr(screening, "get_provider_manager", lambda: _FakeManager())

    payload = _invoke(
        screening.screen_board_candidates,
        {"board_name": "人工智能", "board_type": bad_type},
        _sink(),
    )

    assert payload["status"] == "error"
