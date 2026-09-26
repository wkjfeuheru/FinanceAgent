"""产品研究专家（LangChain ReAct）测试：目录查询写入结构化字段。"""

from __future__ import annotations

import json

from finance_agent.orchestration.contracts import (
    BusinessDomain,
    DomainTaskContext,
    PlanTask,
)
from finance_agent.orchestration.experts import build_expert
from finance_agent.domains.products.expert import product_tools
from finance_agent.domains.products.expert import catalog as tools_product
from finance_agent.orchestration.experts.base import ExpertSink, SINK_KEY

from tests.conftest import final_message, make_fake_tool_model, tool_call


def _context(goal: str = "分析基金110011", profile: dict | None = None,
             domain: BusinessDomain = BusinessDomain.PRODUCT_RESEARCH):
    return DomainTaskContext(
        task=PlanTask(
            task_id="t-1", domain=domain,
            goal=goal, instruction=goal, expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message=goal,
        user_profile=profile or {},
    )


def _run_tool(tool, args, sink):
    return tool.invoke(args, config={"configurable": {SINK_KEY: sink}})


class _Library:
    def __init__(self, by_code=None, by_name=None, listing=None, error=None):
        self.by_code = by_code or {}
        self.by_name = by_name or {}
        self.listing = listing or []
        self.error = error

    def query_by_code(self, code):
        if self.error:
            raise self.error
        return self.by_code.get(code)

    def query_by_name(self, name):
        if self.error:
            raise self.error
        return self.by_name.get(name)

    def list_products(self, product_type):
        if self.error:
            raise self.error
        return list(self.listing)


def _patch_library(monkeypatch, library: _Library) -> None:
    monkeypatch.setattr(tools_product, "get_product_library", lambda: library)


SAMPLE = {
    "product_code": "P001",
    "name": "示例基金",
    "risk_level": "R2",
    "nav": 1.23,
}


def test_product_expert_tool_whitelist():
    names = [tool.name for tool in product_tools()]
    assert names == ["query_product", "list_products"]
    assert "analyze_products" not in names


def test_product_expert_returns_catalog_fields(monkeypatch):
    _patch_library(monkeypatch, _Library(by_code={"110011": SAMPLE}))
    model = make_fake_tool_model([
        tool_call("query_product", {"product_code": "110011"}),
        final_message("示例基金风险等级为 R2。"),
    ])
    graph = build_expert(BusinessDomain.PRODUCT_RESEARCH, model=model)
    outcome = graph.invoke({"context": _context()})["domain_outcome"]

    assert outcome.domain == BusinessDomain.PRODUCT_RESEARCH
    assert outcome.status == "success"
    assert outcome.structured_data["product"]["risk_level"] == "R2"
    assert outcome.summary == "示例基金风险等级为 R2。"


def test_product_catalog_failure_maps_to_failed_status(monkeypatch):
    _patch_library(monkeypatch, _Library(error=RuntimeError("DB_PASSWORD=secret-connection-detail")))
    model = make_fake_tool_model([
        tool_call("query_product", {"product_code": "110011"}),
        final_message("产品研究暂不可用，请稍后重试。"),
    ])
    graph = build_expert(BusinessDomain.PRODUCT_RESEARCH, model=model)
    outcome = graph.invoke({"context": _context()})["domain_outcome"]

    assert outcome.status == "failed"
    assert outcome.limitations == ["product_catalog_failed"]
    assert "secret-connection-detail" not in outcome.summary
    assert "DB_PASSWORD" not in outcome.summary


def test_query_product_reports_fixed_text_on_library_failure(monkeypatch):
    _patch_library(monkeypatch, _Library(error=RuntimeError("DB_PASSWORD=secret-connection-detail")))
    sink = ExpertSink(domain=BusinessDomain.PRODUCT_RESEARCH)
    raw = _run_tool(tools_product.query_product, {"product_code": "110011"}, sink)

    assert tools_product.PRODUCT_UNAVAILABLE in raw
    assert "secret-connection-detail" not in raw
    assert sink.failed is True
    assert "product_catalog_failed" in sink.limitations


def test_query_product_writes_product_json(monkeypatch):
    _patch_library(monkeypatch, _Library(by_code={"P001": SAMPLE}))
    sink = ExpertSink(domain=BusinessDomain.PRODUCT_RESEARCH)
    raw = _run_tool(tools_product.query_product, {"product_code": "P001"}, sink)

    assert json.loads(raw)["name"] == "示例基金"
    assert sink.structured["product"]["product_code"] == "P001"
    assert sink.structured["products"][0]["risk_level"] == "R2"


def test_query_product_missing_does_not_fabricate(monkeypatch):
    _patch_library(monkeypatch, _Library(by_code={}))
    sink = ExpertSink(domain=BusinessDomain.PRODUCT_RESEARCH)
    raw = _run_tool(tools_product.query_product, {"product_code": "110011"}, sink)

    assert json.loads(raw)["error"]
    assert "product_not_found" in sink.limitations
    assert "product" not in sink.structured


def test_product_expert_refuses_foreign_task():
    graph = build_expert(BusinessDomain.PRODUCT_RESEARCH, model=make_fake_tool_model([]))
    outcome = graph.invoke(
        {"context": _context(goal="分析600519", domain=BusinessDomain.STOCK_RESEARCH)}
    )["domain_outcome"]

    assert outcome.status == "failed"
    assert outcome.limitations == ["domain_mismatch"]


def test_product_expert_needs_input_for_missing_reference():
    model = make_fake_tool_model([
        tool_call("request_user_input", {"fields": ["product_reference"]}),
        final_message("请补充产品名称或代码。"),
    ])
    graph = build_expert(BusinessDomain.PRODUCT_RESEARCH, model=model)
    outcome = graph.invoke({"context": _context(goal="帮我看看这只基金")})["domain_outcome"]

    assert outcome.status == "needs_input"
    assert outcome.structured_data["pending_input"]["missing"] == [
        "product_research:product_reference"
    ]


def test_horizon_normalization_covers_common_phrasings():
    from finance_agent.domains.products.rules import normalize_profile_risk, normalize_risk

    assert normalize_risk("R2 中低风险") == "R2"
    assert normalize_profile_risk("稳健") == "R2"
    assert normalize_profile_risk("未知偏好") is None
