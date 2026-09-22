"""股票领域子图：模式选择、统一 DomainOutcome 与确定性工具执行。"""

from __future__ import annotations

from finance_agent.orchestrator.contracts import DomainTaskContext, PlanTask, BusinessDomain
from finance_agent.orchestrator.domains.stock import StockDeps, build_stock_domain_graph
from finance_agent.research.contracts import Action, AnalysisKind, AnalysisRequest, AnalysisResult


def _context(goal: str) -> DomainTaskContext:
    return DomainTaskContext(
        task=PlanTask(
            task_id="single:run-1:stock_research",
            domain=BusinessDomain.STOCK_RESEARCH,
            goal=goal,
            instruction=goal,
            expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message=goal,
    )


class _FakePipeline:
    def analyze_per_security(self, request: AnalysisRequest, *, user_profile):
        results = [
            AnalysisResult(
                request=AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=[code]),
                action=Action.WATCH,
                data_quality="complete",
                rule_version="research_rules/v1",
                narrative=f"{code} 研究结论：观望。",
            )
            for code in request.stock_codes
        ]
        return results, []


def test_stock_domain_selects_candidate_search_for_recommendation():
    graph = build_stock_domain_graph(StockDeps())

    outcome = graph.invoke({"context": _context("推荐一些股票")})["domain_outcome"]

    assert outcome.structured_data["mode"] == "candidate_search"
    assert outcome.domain == BusinessDomain.STOCK_RESEARCH


def test_stock_domain_returns_uniform_outcome_with_analysis_results():
    graph = build_stock_domain_graph(
        StockDeps(pipeline=_FakePipeline(), injected_pipeline=True)
    )

    outcome = graph.invoke({"context": _context("分析600519")})["domain_outcome"]

    assert outcome.domain == BusinessDomain.STOCK_RESEARCH
    assert outcome.task_id == "single:run-1:stock_research"
    assert outcome.status in {"success", "partial"}
    assert "600519" in outcome.structured_data["stock_analysis"]
    assert outcome.structured_data["mode"] == "single_analysis"


def test_stock_domain_uses_recommendation_intent_for_candidate_search():
    """推荐类请求必须按 stock_recommendation 解析，否则候选发现不会触发。"""
    from finance_agent.orchestrator.domains import stock as stock_domain

    captured: dict[str, Any] = {}
    original = stock_domain.invoke_stock

    def _spy(deps, state):
        captured["intent"] = state.get("current_task_intent")
        return {**state, "agent_response": "", "intent_results": {}}

    stock_domain.invoke_stock = _spy
    try:
        stock_domain._stock_research(StockDeps(), _context("推荐几只消费龙头股"))
    finally:
        stock_domain.invoke_stock = original

    assert captured["intent"] == "stock_recommendation"


def test_stock_domain_uses_analysis_intent_for_single_stock():
    from finance_agent.orchestrator.domains import stock as stock_domain

    captured: dict[str, Any] = {}
    original = stock_domain.invoke_stock

    def _spy(deps, state):
        captured["intent"] = state.get("current_task_intent")
        return {**state, "agent_response": "", "intent_results": {}}

    stock_domain.invoke_stock = _spy
    try:
        stock_domain._stock_research(StockDeps(), _context("分析600519"))
    finally:
        stock_domain.invoke_stock = original

    assert captured["intent"] == "stock_analysis"


def test_codes_in_text_extracts_a_share_codes():
    from finance_agent.orchestrator.domains.stock import _codes_in_text

    assert _codes_in_text("分析600519") == ["600519"]
    assert _codes_in_text("分析贵州茅台") == []
    assert _codes_in_text("比较600519和000858") == ["600519", "000858"]


def test_resolve_stock_request_resolves_name_without_code(monkeypatch):
    """只有名称、没有 6 位代码时必须解析出代码，否则单股请求会被判无法识别。"""
    from finance_agent.orchestrator.domains import stock as stock_domain

    class _Search:
        def invoke(self, payload):
            import json as _json

            return _json.dumps([{"code": "600519", "name": "贵州茅台"}])

    deps = StockDeps(candidate_search=_Search())
    req, err = stock_domain.resolve_stock_request(
        deps,
        {"user_message": "分析贵州茅台", "current_task_intent": "stock_analysis",
         "intent_slots": {}, "user_profile": {}, "resolved_stocks": []},
        "分析贵州茅台",
    )

    assert err is None
    assert req is not None
    assert req.kind.value == "single_stock"
    assert req.stock_codes == ["600519"]


def test_resolve_stock_request_ignores_unrelated_search_hits(monkeypatch):
    """搜索结果里名称未出现在消息中的候选不得被当作本轮标的。"""
    from finance_agent.orchestrator.domains import stock as stock_domain

    class _Search:
        def invoke(self, payload):
            import json as _json

            return _json.dumps([{"code": "000001", "name": "平安银行"}])

    deps = StockDeps(candidate_search=_Search())
    req, err = stock_domain.resolve_stock_request(
        deps,
        {"user_message": "分析贵州茅台", "current_task_intent": "stock_analysis",
         "intent_slots": {}, "user_profile": {}, "resolved_stocks": []},
        "分析贵州茅台",
    )

    assert req is None
    assert err is not None


def _resolve_with_parser_error(monkeypatch, stock_domain, error: Exception):
    """构造仅解析器抛指定异常的解析场景，返回 (req, err)。"""

    def _raise(*args, **kwargs):
        raise error

    monkeypatch.setattr(stock_domain, "parse_analysis_request", _raise)
    return stock_domain.resolve_stock_request(
        StockDeps(),
        {"user_message": "分析贵州茅台", "current_task_intent": "stock_analysis",
         "intent_slots": {}, "user_profile": {}, "resolved_stocks": []},
        "分析贵州茅台",
    )


def test_single_stock_shape_error_triggers_name_resolution(monkeypatch):
    """抛 SingleStockShapeError 时按异常类型判定，走名称→代码补救分支。"""
    from finance_agent.orchestrator.domains import stock as stock_domain
    from finance_agent.research.contracts import SingleStockShapeError

    monkeypatch.setattr(
        stock_domain, "resolve_named_stock_code", lambda deps, message: ["600519"],
    )

    req, err = _resolve_with_parser_error(
        monkeypatch, stock_domain, SingleStockShapeError("单股分析必须且只能包含一只股票"),
    )

    assert err is None
    assert req is not None
    assert req.stock_codes == ["600519"]


def test_plain_value_error_is_not_mistaken_for_single_stock_shape(monkeypatch):
    """普通 ValueError 即使文案与单股形态错误完全一致，也不得被误判并触发补救。"""
    from finance_agent.orchestrator.domains import stock as stock_domain

    called: list[str] = []

    def _spy_resolve_named_stock_code(deps, message):
        called.append(message)
        return ["600519"]

    monkeypatch.setattr(stock_domain, "resolve_named_stock_code", _spy_resolve_named_stock_code)

    # 文案故意与 SingleStockShapeError 相同，唯一区别是异常类型。
    req, err = _resolve_with_parser_error(
        monkeypatch, stock_domain, ValueError("单股分析必须且只能包含一只股票"),
    )

    assert req is None
    assert err is not None
    assert called == []


def _fact(fact_id: str):
    from datetime import datetime, timezone

    from finance_agent.contracts import FactSnapshot

    return FactSnapshot(
        fact_id=fact_id, domain="stock", source="test",
        fetched_at=datetime.now(timezone.utc),
    )


def test_merge_facts_dedupes_by_fact_id_and_keeps_order():
    """统一事实合并：重复 fact_id 不重复追加、新事实追加在后、既有顺序保持。"""
    from finance_agent.orchestrator.domains.base import merge_facts

    existing = [_fact("b"), _fact("a")]
    merged = merge_facts(existing, [_fact("a"), _fact("c"), _fact("c"), _fact("b")])

    assert [fact.fact_id for fact in merged] == ["b", "a", "c"]
    # 既有项本身按原顺序保留，新项追加在尾部
    assert merged[:2] == existing
    # 空新增不改变既有集合
    assert [fact.fact_id for fact in merge_facts(existing, [])] == ["b", "a"]
