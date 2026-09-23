"""画像与参数注入：修复"画像从未进入分析链路"的断链。

验证三件事：``DomainTaskContext`` 的 params/user_profile 被领域 handler 正确消费、
``profile_complete`` / ``personalization_status`` 能真正变为个性化、弹窗补填的偏好
会写入长期画像。
"""

from __future__ import annotations

from finance_agent.orchestrator.contracts import BusinessDomain, DomainTaskContext, PlanTask
from finance_agent.orchestrator.domains.product import build_product_domain_graph, ProductDomainDeps
from finance_agent.orchestrator.domains.stock import StockDeps, build_stock_domain_graph
from finance_agent.product_research.contracts import ProductResearchResult
from finance_agent.research.contracts import Action, AnalysisKind, AnalysisRequest, AnalysisResult


def _context(goal: str, *, params=None, user_profile=None, domain=BusinessDomain.STOCK_RESEARCH):
    return DomainTaskContext(
        task=PlanTask(
            task_id=f"single:run-1:{domain.value}",
            domain=domain,
            goal=goal,
            instruction=goal,
            expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message=goal,
        params=params or {},
        user_profile=user_profile or {},
    )


class _RecordingPipeline:
    """记录 pipeline 收到的请求与画像，用于断言注入是否生效。"""

    def __init__(self) -> None:
        self.requests: list[AnalysisRequest] = []
        self.profiles: list[dict] = []

    def analyze_per_security(self, request: AnalysisRequest, *, user_profile):
        self.requests.append(request)
        self.profiles.append(dict(user_profile))
        return [
            AnalysisResult(
                request=AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=[code]),
                action=Action.WATCH,
                data_quality="complete",
                rule_version="research_rules/v1",
                narrative=f"{code} 结论。",
            )
            for code in request.stock_codes
        ], []


def test_profile_reaches_stock_pipeline_and_marks_complete():
    pipeline = _RecordingPipeline()
    graph = build_stock_domain_graph(StockDeps(pipeline=pipeline, injected_pipeline=True))

    graph.invoke({"context": _context(
        "分析600519",
        user_profile={"risk_preference": "稳健", "holding_period": "长期"},
    )})

    assert pipeline.profiles[0]["risk_preference"] == "稳健"
    assert pipeline.requests[0].profile_complete is True, (
        "画像注入后 profile_complete 必须为真（此前恒假）"
    )


def test_missing_profile_keeps_complete_false():
    pipeline = _RecordingPipeline()
    graph = build_stock_domain_graph(StockDeps(pipeline=pipeline, injected_pipeline=True))

    graph.invoke({"context": _context("分析600519")})

    assert pipeline.requests[0].profile_complete is False


def test_params_analysis_type_reaches_stock_request():
    """弹窗补填的分析维度写入 intent_slots，影响 AnalysisRequest.analysis_type。"""
    pipeline = _RecordingPipeline()
    graph = build_stock_domain_graph(StockDeps(pipeline=pipeline, injected_pipeline=True))

    graph.invoke({"context": _context(
        "分析600519", params={"stock_codes": ["600519"], "analysis_type": "技术面"},
    )})

    assert pipeline.requests[0].analysis_type == "technical"


class _ProductPipeline:
    def __init__(self) -> None:
        self.requests = []

    def analyze(self, request):
        self.requests.append(request)
        return ProductResearchResult(
            kind=request.kind,
            product_codes=list(request.product_codes),
            assessments=[],
            report="产品报告",
            data_quality="critical_missing",
            personalization_status="research_candidate",
            evidence_ids=[],
            ambiguities=[],
        )


def _product_outcome(pipeline, params):
    graph = build_product_domain_graph(deps=ProductDomainDeps(pipeline=pipeline))
    return graph.invoke({"context": _context(
        "分析该产品", domain=BusinessDomain.PRODUCT_RESEARCH, params=params,
    )})["domain_outcome"]


def test_params_product_codes_reach_product_request():
    """弹窗/抽取到的产品代码写入 intent_slots，被产品请求读取。"""
    pipeline = _ProductPipeline()

    outcome = _product_outcome(pipeline, {"product_codes": ["110011"]})

    assert outcome.status in {"success", "partial"}
    assert pipeline.requests[0].product_codes == ["110011"]


def test_params_product_names_reach_product_request():
    pipeline = _ProductPipeline()

    _product_outcome(pipeline, {"product_names": ["华夏成长基金"]})

    assert pipeline.requests[0].product_names == ["华夏成长基金"]


def test_context_defaults_params_and_profile_to_empty():
    """默认空值保持旧调用方兼容（不传 params/user_profile 不报错）。"""
    context = DomainTaskContext(
        task=PlanTask(
            task_id="t", domain=BusinessDomain.MARKET_INSIGHT, goal="大盘", instruction="大盘",
            expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message="大盘",
    )

    assert context.params == {}
    assert context.user_profile == {}
