"""确定性研究评估（``evaluation.evaluate``）的不变量测试。

架构重构后 ``ResearchPipeline`` 已删除，改为可被 ReAct 工具调用的确定性函数
``evaluate``。本文件保留纯研究层的核心不变量：逐标的隔离、行动结论与叙述分离、
事实可重放、证据 ID 与结论一致。
"""

from concurrent.futures import ThreadPoolExecutor

from finance_agent.domains.research.contracts import AnalysisKind, AnalysisRequest
from finance_agent.domains.research.evaluation import evaluate, project_analysis_results


def _closes(rate: float) -> list[float]:
    """生成 60 根等比收盘价，供确定性的技术面/风险面评分使用。"""
    return [round(10.0 * (1 + rate) ** index, 4) for index in range(60)]


# 夹具使用固定的数据日期与抓取时刻：新鲜度门禁是时间敏感的，用 now() 会让
# 测试结果随系统时钟漂移。
FIXTURE_DAY = "2026-08-28"
FIXTURE_FETCHED_AT = "2026-08-28T08:00:00+00:00"


class CompleteGateway:
    """为逐标的隔离测试提供两只股票的独立快照。

    只提供生产取数层真实可得的原始字段（财务指标 + 前复权 K 线），
    评分必须由 ``research.scoring`` 从这些原始字段推导。
    """

    def get_security_data(self, stock_code: str) -> dict:
        return {
            "basic_info": {"code": stock_code, "name": f"测试{stock_code}"},
            "quote": {
                "code": stock_code,
                "price": 12.6558,
                "date": FIXTURE_DAY,
                "adjustment": "raw",
                "source": "fixture",
                "fetched_at": FIXTURE_FETCHED_AT,
            },
            "history": {
                "adjustment": "forward",
                "as_of": FIXTURE_DAY,
                "source": "fixture",
                "fetched_at": FIXTURE_FETCHED_AT,
                "data": [
                    {"date": FIXTURE_DAY, "close": close, "high": close * 1.01, "low": close * 0.99}
                    for close in _closes(0.004)
                ],
            },
            "indicators": {
                "roe": 18.0 if stock_code == "600519" else 12.0,
                "revenue_yoy": 20.0,
                "netprofit_yoy": 20.0,
                "pe_ttm": 18.0,
                "pb": 2.0,
                "end_date": "2026-06-30",
                "ann_date": "2026-08-25",
                "source": "fixture",
                "fetched_at": FIXTURE_FETCHED_AT,
                "suitability_score": 80.0,
            },
        }


def _evaluate(request: AnalysisRequest, gateway=None, *, user_profile=None):
    return evaluate(
        request,
        user_profile=user_profile or {},
        gateway=gateway or CompleteGateway(),
    )


def _analyze(request: AnalysisRequest, gateway=None, *, user_profile=None):
    """单标的便捷入口：返回唯一结论（与旧 ``pipeline.analyze`` 等价）。"""
    results, _ = _evaluate(request, gateway, user_profile=user_profile)
    return results[0]


def test_parallel_evaluations_do_not_share_stock_data():
    """同一网关并行处理不同股票时不得串数据。"""
    requests = [
        AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"]),
        AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600036"]),
    ]

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(lambda request: _analyze(request), requests)
        )

    first, second = outcomes
    assert first.request.stock_codes == ["600519"]
    assert second.request.stock_codes == ["600036"]
    assert first.evidence_ids != second.evidence_ids


def test_evaluation_keeps_structured_action_separate_from_narrative():
    """报告文本不得替换确定性行动结论。"""
    request = AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"])

    result = _analyze(request)

    assert result.action.value == "关注"
    assert result.report_mode == "template_fallback"
    assert result.rule_version == "research_rules/v1.2"
    assert result.personalization_status == "research_candidate"
    assert "关注" in result.narrative


def test_stale_quote_is_reported_and_blocks_the_conclusion():
    """超过允许交易日龄的报价必须降级为“数据不足”并给出原因。"""
    class StaleQuoteGateway(CompleteGateway):
        def get_security_data(self, stock_code: str) -> dict:
            data = super().get_security_data(stock_code)
            data["quote"]["date"] = "2026-08-20"
            return data

    request = AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"])

    result = _analyze(request, StaleQuoteGateway())

    assert result.data_quality == "critical_missing"
    assert result.action.value == "数据不足"
    assert "stale_quote" in result.restrictions
    assert "最新报价超过允许的数据新鲜度" in result.narrative


def test_facts_carry_replay_inputs_and_stable_ids():
    """证据必须包含完整重放输入，且同一输入的两次运行得到同一事实 ID。"""
    request = AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"])

    _, first_facts = _evaluate(request)
    _, second_facts = _evaluate(request)

    payload = first_facts[0].payload
    assert payload["inputs"]["history"]["data"]
    assert payload["inputs"]["indicators"]["roe"] == 18.0
    assert payload["request"]["stock_codes"] == ["600519"]
    assert payload["evaluated_at"] == FIXTURE_FETCHED_AT
    assert payload["provenance"]["quote"]["price_basis"] == "raw"
    assert [fact.fact_id for fact in first_facts] == [fact.fact_id for fact in second_facts]


def _critical_result():
    from finance_agent.domains.research.contracts import Action, AnalysisResult

    request = AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"])
    return AnalysisResult(
        request=request,
        action=Action.INSUFFICIENT_DATA,
        data_quality="critical_missing",
        rule_version="research_rules/v1",
        scores={"total": None},
        evidence_ids=["fact-critical"],
        narrative="关键数据缺失，无法完成研究。",
        report_mode="template_fallback",
    )


def test_critical_result_projects_as_insufficient_data():
    """关键数据缺失的结论投影为“数据不足”，规则版本如实保留。"""
    projected = project_analysis_results([_critical_result()])

    assert projected["stock_analysis"]["600519"]["rating"] == "数据不足"
    assert projected["analysis_results"][0]["rule_version"] == "research_rules/v1"


def test_publishes_facts_matching_evidence_ids():
    """发布的事实 ID 必须与其结论引用的证据 ID 一致（供审计重放关联）。"""
    request = AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"])

    results, facts = _evaluate(request)

    assert results[0].evidence_ids
    assert [fact.fact_id for fact in facts] == results[0].evidence_ids
