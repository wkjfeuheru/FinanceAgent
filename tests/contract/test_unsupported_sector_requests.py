"""主题筛选能力下线后的公开契约。"""

from finance_agent.api.app import app
from finance_agent.api.schemas.chat import ChatResponse
from finance_agent.orchestration.contracts import (
    BusinessDomain,
    DomainTaskContext,
    PlanTask,
)
from finance_agent.orchestration.experts import build_expert
from finance_agent.domains.research.expert import stock_tools
from finance_agent.domains.research.contracts import AnalysisKind, AnalysisRequest
from tests.conftest import final_message, make_fake_tool_model


UNSUPPORTED_THEME_MESSAGE = "当前不支持按主题或板块自动筛选股票，请提供具体股票名称或代码进行分析。"


def _run_stock_request(text: str, model):
    expert = build_expert(BusinessDomain.STOCK_RESEARCH, model=model)
    context = DomainTaskContext(
        task=PlanTask(
            task_id="screening-request",
            domain=BusinessDomain.STOCK_RESEARCH,
            goal=text,
            instruction=text,
            expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message=text,
    )
    return expert.invoke({"context": context})["domain_outcome"]


def test_research_contract_has_no_theme_screening_kind_or_theme_id():
    assert "theme_screening" not in {kind.value for kind in AnalysisKind}
    assert "theme_id" not in AnalysisRequest.model_fields


def test_chat_response_and_stock_tools_have_no_theme_capability_fields():
    response_fields = set(ChatResponse.model_fields)
    assert response_fields.isdisjoint({
        "theme_screening", "theme_screening_status", "theme_candidates", "pending_leads",
    })
    assert "screen_theme" not in {tool.name for tool in stock_tools()}


def test_theme_admin_routes_are_absent():
    paths = set(app.openapi()["paths"])
    assert not any("/themes" in path or "theme-leads" in path for path in paths)


def test_theme_and_sector_screening_requests_get_fixed_unsupported_message():
    for text in ("推荐人工智能主题股票", "筛选半导体板块龙头"):
        outcome = _run_stock_request(text, make_fake_tool_model([]))
        assert outcome.summary == UNSUPPORTED_THEME_MESSAGE


def test_unlabeled_sector_candidate_requests_get_fixed_message_before_model_call():
    for text in ("推荐几只新能源股", "找一些半导体股票"):
        outcome = _run_stock_request(text, make_fake_tool_model([]))
        assert outcome.summary == UNSUPPORTED_THEME_MESSAGE


def test_explicit_stock_analysis_is_not_treated_as_sector_screening():
    for text in ("分析贵州茅台", "分析600519"):
        outcome = _run_stock_request(text, make_fake_tool_model([
            final_message("个股分析正常。"),
        ]))
        assert outcome.summary != UNSUPPORTED_THEME_MESSAGE
