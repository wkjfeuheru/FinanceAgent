"""端到端冒烟：用户消息经 Supervisor 路由到正确领域并产出响应。

架构重构后，旧的 ``orchestrator.domains.{stock,market,product}`` 领域图已删除；
领域执行改由 ``build_expert`` 编译的 ReAct 专家子图承担。本文件保留 E2E 精神：

- **默认运行**（离线）：用假分类器 + 假领域执行器驱动 Supervisor 根图，断言
  单/跨领域路由与响应生成（确定性，不依赖外部模型与第三方接口）。
- **网络门禁**（``RUN_NETWORK_TESTS=1``）：股票报价工具对真实数据源跑通取数。
"""

from __future__ import annotations

import json
import os

import pytest

from finance_agent.orchestration.contracts import BusinessDomain, DomainOutcome
from finance_agent.orchestration.graphs.supervisor import (
    SupervisorDependencies,
    build_supervisor_graph,
    project_supervisor_state,
    routing_of,
    run_of,
)


class _FakeClassifier:
    """注入确定性分类结果，隔离分类模型波动。"""

    def __init__(self, intents):
        self._intents = intents

    def classify_intents(self, message: str, context_summary: str = "") -> dict:
        return {
            "intents": [
                {"intent": intent, "query": message, "confidence": 0.99,
                 "evidence": message, "clarification_question": ""}
                for intent in self._intents
            ],
            "uncertain_intents": [],
            "finance_related": True,
            "intent_source": "fake",
            "classification_error": {},
        }


def _echo_runner(context):
    return DomainOutcome(
        task_id=context.task.task_id,
        domain=context.task.domain,
        status="success",
        summary=f"{context.task.domain.value} 结论：{context.task.instruction}",
        structured_data={},
    )


def _run(intents, message: str) -> dict:
    graph = build_supervisor_graph(
        SupervisorDependencies(
            classifier=_FakeClassifier(intents), domain_runner=_echo_runner,
        )
    )
    return graph.invoke({"user_message": message, "run_id": "e2e-run"})


@pytest.mark.parametrize("intent,domain", [
    ("stock_analysis", "stock_research"),
    ("market_insight", "market_insight"),
    ("product_analysis", "product_research"),
    ("portfolio_analysis", "account_portfolio"),
])
def test_message_routes_to_single_domain_and_produces_response(intent, domain):
    """单领域消息路由到正确领域，产出该领域的结论文本。"""
    result = _run([intent], "请分析一下")

    routing = routing_of(result)
    assert routing["domains"] == [domain]
    assert routing["execution_mode"] == "domain_workflow"
    assert run_of(result)["run_status"] == "completed"
    assert domain in run_of(result)["final_response"]


def test_cross_domain_message_routes_to_both_domains():
    """跨领域消息同样扇出到两个领域，两个领域都产出结论。

    （旧断言的 ``plan_execute`` 执行模式与计划层一并删除：单/多领域现在共用
    ``domain_workflow`` 一条路径，区别只是 ``Send`` 扇出数量。）
    """
    result = _run(["stock_analysis", "market_insight"], "分析茅台并看大盘")

    routing = routing_of(result)
    assert set(routing["domains"]) == {"stock_research", "market_insight"}
    assert routing["execution_mode"] == "domain_workflow"
    assert run_of(result)["run_status"] == "completed"
    assert len(result["task_results"]) == 2


def test_projection_carries_legacy_response_shape():
    """投影保留旧响应键（task_plan / response / run_status）。"""
    result = _run(["market_insight"], "今天大盘怎么样")

    projected = project_supervisor_state(result, conversation_id="e2e-conversation")

    assert projected["task_plan"] == ["market_insight"]
    assert projected["response"]
    assert projected["run_status"] == "completed"
    assert projected["conversation_id"] == "e2e-conversation"


# ── 网络门禁：真实数据源的股票专家 E2E ─────────────────────────────────────

pytestmark_network = pytest.mark.skipif(
    os.getenv("RUN_NETWORK_TESTS", "").strip().lower() not in {"1", "true", "yes", "on"},
    reason="端到端冒烟测试默认跳过；设置 RUN_NETWORK_TESTS=1 启用",
)


@pytest.mark.network
@pytestmark_network
def test_live_stock_quote_tool_returns_price():
    """真实数据源：报价工具返回代码与价格，不走研究管线。"""
    from finance_agent.domains.research.expert.stockdata import get_stock_quote

    payload = json.loads(get_stock_quote.invoke({"stock_code": "600519"}))
    assert payload.get("code") == "600519"
    assert payload.get("price") not in (None, "")
    assert "error" not in payload
