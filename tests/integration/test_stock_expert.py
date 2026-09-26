"""股票研究专家（LangGraph ReAct）测试：工具白名单隔离与确定性工具的诚实降级。

从旧的 ``test_stock_domain_graph.py`` 迁移：模式选择 / ``_codes_in_text`` /
``resolve_stock_request`` / 意图槽位等测试随确定性领域管线（``StockDeps``、
``build_*_domain_graph`` 等）一并删除——那些函数已不存在。保留的是对**仍存在**的
行为断言：工具白名单组成、名称解析（歧义不猜）、技术指标历史不足的诚实降级、
量化网关卸载语义，以及对已删除的 ``merge_facts``（随 ``domains/base.py`` 删除）的
测试直接移除。
"""

from __future__ import annotations

import json

from finance_agent.shared.contracts import AsyncJobRef
from finance_agent.orchestration.contracts import (
    BusinessDomain,
    DomainTaskContext,
    PlanTask,
)
from finance_agent.orchestration.experts import build_expert
from finance_agent.domains.research.expert import stock_tools
from finance_agent.domains.research.expert import tools as tools_stock
from finance_agent.orchestration.experts.base import ExpertSink, SINK_KEY

from tests.conftest import final_message, make_fake_tool_model, tool_call


def _context(domain=BusinessDomain.STOCK_RESEARCH, goal: str = "分析600519"):
    return DomainTaskContext(
        task=PlanTask(
            task_id="t-1", domain=domain,
            goal=goal, instruction=goal, expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message=goal,
    )


def _run_tool(tool, args, sink):
    """直接调用工具函数并注入 per-run sink（绕过模型的单元级验证）。"""
    return tool.invoke(args, config={"configurable": {SINK_KEY: sink}})


# ── 工具白名单组成与隔离 ──────────────────────────────────────────────

def test_stock_expert_tool_whitelist_composition():
    names = [tool.name for tool in stock_tools()]
    expected = [
        "resolve_stock_names",
        "get_stock_quote",
        "get_stock_history",
        "get_financial_indicators",
        "get_stock_basic_info",
        "get_valuation_indicators",
        "get_income_statement",
        "search_candidates",
        "compute_technical",
        "evaluate_research",
    ]
    assert names == expected


def test_stock_expert_tool_whitelist_is_isolated_from_other_domains():
    """股票专家不得携带产品/市场/账户工具，避免跨域误取数。"""
    names = {tool.name for tool in stock_tools()}
    foreign = {
        "query_product", "list_products",
        "get_market_overview", "get_market_sentiment", "get_capital_flow",
        "get_policy_impact", "get_positions", "review_allocation",
    }
    assert names.isdisjoint(foreign)


def test_stock_expert_refuses_foreign_task():
    """股票专家拿到市场领域任务必须安全失败，且不调用任何工具/模型。"""
    # 空消息序列：一旦模型被调用就会 StopIteration，从而暴露"越权执行"。
    graph = build_expert(BusinessDomain.STOCK_RESEARCH, model=make_fake_tool_model([]))
    outcome = graph.invoke(
        {"context": _context(domain=BusinessDomain.MARKET_INSIGHT, goal="今天大盘怎么样")}
    )["domain_outcome"]

    assert outcome.status == "failed"
    assert outcome.limitations == ["domain_mismatch"]


# ── 名称解析：歧义列出候选、绝不猜测 ─────────────────────────────────

class _FakeNameSource:
    """替换股票工具包里的名称源，按注入载荷返回候选。"""

    def __init__(self, payload: dict):
        self._payload = payload

    def invoke(self, payload=None):
        return json.dumps(self._payload, ensure_ascii=False)


def test_stock_name_source_uses_shared_matcher_for_abbreviations(monkeypatch):
    from finance_agent.domains.research.expert import stockdata

    class _Provider:
        def get_stock_basic(self):
            return [
                {"code": "600519", "name": "贵州茅台"},
                {"code": "600036", "name": "招商银行"},
                {"code": "600999", "name": "招商证券"},
            ]

    monkeypatch.setattr(stockdata, "get_provider_manager", lambda: _Provider())

    unique = json.loads(stockdata.match_stock_names.invoke({"user_query": "茅台"}))
    ambiguous = json.loads(stockdata.match_stock_names.invoke({"user_query": "招商"}))

    assert unique["codes"] == ["600519"]
    assert ambiguous["codes"] == []
    assert ambiguous["ambiguous_tokens"] == ["招商"]
    assert {candidate["code"] for candidate in ambiguous["candidates"]} == {
        "600036", "600999",
    }


def test_resolve_stock_names_resolves_full_name(monkeypatch):
    monkeypatch.setattr(
        tools_stock._stockdata, "match_stock_names",
        _FakeNameSource({
            "candidates": [{"code": "600519", "name": "贵州茅台"}],
            "ambiguous_tokens": [],
        }),
    )
    sink = ExpertSink(domain=BusinessDomain.STOCK_RESEARCH)
    result = json.loads(_run_tool(
        tools_stock.resolve_stock_names, {"user_query": "分析贵州茅台"}, sink,
    ))

    assert result["codes"] == ["600519"]


def test_resolve_stock_names_lists_ambiguous_tokens_without_guessing(monkeypatch):
    """缩写命中多个标的时不得猜测：列出候选与歧义词供澄清。"""
    monkeypatch.setattr(
        tools_stock._stockdata, "match_stock_names",
        _FakeNameSource({
            "candidates": [
                {"code": "600036", "name": "招商银行"},
                {"code": "600999", "name": "招商证券"},
            ],
            "ambiguous_tokens": ["招商"],
        }),
    )
    sink = ExpertSink(domain=BusinessDomain.STOCK_RESEARCH)
    result = json.loads(_run_tool(
        tools_stock.resolve_stock_names, {"user_query": "分析招商"}, sink,
    ))

    assert result["codes"] == [], "歧义时不得静默选定代码"
    assert result["ambiguous_tokens"] == ["招商"]
    assert {item["code"] for item in result["candidates"]} == {"600036", "600999"}


# ── 技术指标：历史不足的诚实降级 ─────────────────────────────────────

def _history_rows(count: int) -> list[dict]:
    return [{"close": 10.0, "high": 10.5, "low": 9.5} for _ in range(count)]


def test_compute_technical_insufficient_history_is_honest(monkeypatch):
    """历史数据不足时登记 limitation，不产出任何技术指标数字。"""
    monkeypatch.setattr(
        tools_stock._stockdata, "fetch_stock_data",
        lambda codes: {codes[0]: {"history": {"data": _history_rows(5)}}},
    )
    sink = ExpertSink(domain=BusinessDomain.STOCK_RESEARCH)
    raw = _run_tool(tools_stock.compute_technical, {"stock_code": "600519"}, sink)

    assert "insufficient_history:600519" in sink.limitations
    assert "600519" in raw
    assert "indicators" not in raw, "不得伪造技术指标"
    assert "technical_analysis" not in sink.structured


# ── 量化网关卸载语义：pending → awaiting_quant + pending_jobs ─────────

class _PendingGateway:
    """submit 后任务始终处于 running：验证卸载为异步处理。"""

    def __init__(self, job_id: str = "job-1"):
        self._job_id = job_id

    def submit(self, *args, **kwargs):
        return AsyncJobRef(job_id=self._job_id, kind="technical_indicators",
                           status="queued", task_id="t-1")

    def status(self, job_id):
        return "running"

    def result(self, job_id):
        return {}


def test_compute_technical_offloads_to_quant_gateway(monkeypatch):
    monkeypatch.setattr(
        tools_stock._stockdata, "fetch_stock_data",
        lambda codes: {codes[0]: {"history": {"data": _history_rows(70)}}},
    )
    monkeypatch.setattr(tools_stock, "_gateway", lambda: _PendingGateway())
    sink = ExpertSink(domain=BusinessDomain.STOCK_RESEARCH, customer_id="CUST1")
    raw = json.loads(_run_tool(
        tools_stock.compute_technical, {"stock_code": "600519"}, sink,
    ))

    assert raw["status"] == "processing"
    assert raw["job_id"] == "job-1"
    assert "awaiting_quant" in sink.limitations
    pending = sink.extras.get("pending_jobs") or []
    assert [job.job_id for job in pending] == ["job-1"]
    assert sink.extras.get("pending_job_codes", {}).get("job-1") == "600519"


def test_stock_expert_pending_job_surfaces_awaiting_quant(monkeypatch):
    """端到端：量化任务排队时专家结论记 limitation 并携带 pending_jobs。"""
    monkeypatch.setattr(
        tools_stock._stockdata, "fetch_stock_data",
        lambda codes: {codes[0]: {"history": {"data": _history_rows(70)}}},
    )
    monkeypatch.setattr(tools_stock, "_gateway", lambda: _PendingGateway("job-9"))
    model = make_fake_tool_model([
        tool_call("compute_technical", {"stock_code": "600519"}),
        final_message("技术指标计算已提交。"),
    ])
    graph = build_expert(BusinessDomain.STOCK_RESEARCH, model=model)
    outcome = graph.invoke({"context": _context(goal="分析600519的技术面")})["domain_outcome"]

    assert outcome.status == "partial"
    assert "awaiting_quant" in outcome.limitations
    assert [job.job_id for job in outcome.pending_jobs] == ["job-9"]


# ── 确定性研究评估工具：填公开契约、可审计 ───────────────────────────

_FETCHED_AT = "2026-08-28T08:00:00+00:00"


def _complete_security(code: str) -> dict:
    """生产取数层真实可得的原始字段（前复权 K 线 + 财务/估值指标）。"""
    closes = [round(10.0 * 1.004 ** index, 4) for index in range(60)]
    return {
        "basic_info": {"code": code, "name": f"测试{code}"},
        "quote": {"code": code, "price": closes[-1], "date": "2026-08-28",
                  "adjustment": "raw", "source": "fixture", "fetched_at": _FETCHED_AT},
        "history": {"adjustment": "forward", "source": "fixture", "fetched_at": _FETCHED_AT,
                    "data": [{"date": "2026-08-28", "close": close} for close in closes]},
        "indicators": {"roe": 18.0, "revenue_yoy": 20.0, "netprofit_yoy": 20.0,
                       "pe_ttm": 18.0, "pb": 2.0, "end_date": "2026-06-30",
                       "ann_date": "2026-08-25", "source": "fixture", "fetched_at": _FETCHED_AT},
    }


def test_evaluate_research_tool_fills_public_contract_keys(monkeypatch):
    """评估工具必须写入 analysis_results/stock_analysis/research_request/facts。

    这四键正是审计持久化（``run_persistence``）与前端卡片消费的契约；缺失任一
    会让 ``AnalysisResult.model_validate`` 或请求归组失败，契约重新变空。
    """
    monkeypatch.setattr(
        tools_stock._stockdata, "fetch_stock_data",
        lambda codes: {code: _complete_security(code) for code in codes},
    )
    sink = ExpertSink(domain=BusinessDomain.STOCK_RESEARCH, customer_id="CUST1")
    raw = json.loads(_run_tool(
        tools_stock.evaluate_research, {"stock_codes": ["600519"]}, sink,
    ))

    assert raw["conclusions"][0]["rating"] == "关注"
    results = sink.structured["analysis_results"]
    assert len(results) == 1
    # 必须能被审计层校验通过，且带规则版本与证据 ID。
    from finance_agent.domains.research.contracts import AnalysisResult

    parsed = AnalysisResult.model_validate(results[0])
    assert parsed.rule_version == "research_rules/v1.2"
    assert parsed.evidence_ids, "结论必须引用证据事实"
    assert sink.structured["stock_analysis"]["600519"]["rating"] == "关注"
    assert sink.structured["research_request"]["stock_codes"] == ["600519"]
    assert sink.structured["facts"], "事实清单必须随结论一并下发（供审计重放）"
    # 未取到评分/结论以外的数字不得凭空编造：结论数字来自工具。
    assert "evaluate_research" in sink.tool_trace


def test_evaluate_research_fails_honestly_without_sink_or_data(monkeypatch):
    """非法输入显式报错；取数失败则如实降级为“数据不足”，不编造结论。"""
    sink = ExpertSink(domain=BusinessDomain.STOCK_RESEARCH)
    empty = json.loads(_run_tool(tools_stock.evaluate_research, {"stock_codes": []}, sink))
    assert empty.get("error")
    assert "analysis_results" not in sink.structured

    def _boom(codes):
        raise RuntimeError("provider down")

    monkeypatch.setattr(tools_stock._stockdata, "fetch_stock_data", _boom)
    failed = json.loads(_run_tool(
        tools_stock.evaluate_research, {"stock_codes": ["600519"]}, sink,
    ))
    # 取数网关异常由快照层转为关键缺失 → 结论是“数据不足”，而非伪造评分。
    assert failed["conclusions"][0]["rating"] == "数据不足"
    assert failed["conclusions"][0]["data_quality"] == "critical_missing"


# ── 步数上限的诚实降级 ───────────────────────────────────────────────

def test_stock_expert_step_limit_degrades_to_partial():
    """模型只发工具调用、不给最终文本并耗尽步数预算：partial + react_step_limit。"""
    from finance_agent.orchestration.experts.registry import step_budget

    budget = step_budget(BusinessDomain.STOCK_RESEARCH)
    # analysis_type="fundamental" 让 compute_technical 直接返回、不触网，只关心步数截断。
    calls = [
        tool_call(
            "compute_technical",
            {"stock_code": "600519", "analysis_type": "fundamental"},
            call_id=f"c{i}",
        )
        for i in range(budget)
    ]
    graph = build_expert(BusinessDomain.STOCK_RESEARCH, model=make_fake_tool_model(calls))
    outcome = graph.invoke({"context": _context()})["domain_outcome"]

    assert outcome.status == "partial"
    assert "react_step_limit" in outcome.limitations


# ── 模型故障的固定降级文案 ───────────────────────────────────────────

def test_stock_expert_model_failure_is_safe():
    class _BoomModel:
        def bind_tools(self, tools, **kwargs):
            return self

        def invoke(self, *args, **kwargs):
            raise RuntimeError("upstream 500: internal host 10.1.2.3")

    graph = build_expert(BusinessDomain.STOCK_RESEARCH, model=_BoomModel())
    outcome = graph.invoke({"context": _context()})["domain_outcome"]

    assert outcome.status == "failed"
    assert outcome.limitations == ["expert_unavailable"]
    assert outcome.summary == "股票数据暂时无法生成，请稍后重试。"
    assert "10.1.2.3" not in outcome.summary
