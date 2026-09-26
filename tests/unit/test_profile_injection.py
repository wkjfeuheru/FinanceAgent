"""画像注入：用户画像必须到达专家任务上下文（模型可见）与账户测算（工具可读）。

专家路径不再经研究/产品管线消费画像；股票/产品工具只取数。画像经
``DomainTaskContext.user_profile`` → 任务描述，以及 ``ExpertSink.user_profile``
到达会读画像的测算工具。
"""

from __future__ import annotations

from finance_agent.orchestration.contracts import BusinessDomain, DomainTaskContext, PlanTask
from finance_agent.orchestration.experts.base import _task_prompt


def _context(
    goal: str,
    *,
    user_profile=None,
    domain=BusinessDomain.STOCK_RESEARCH,
) -> DomainTaskContext:
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
        user_profile=user_profile or {},
    )


def test_task_prompt_includes_injected_profile():
    text = _task_prompt(_context(
        "分析600519",
        user_profile={"risk_preference": "稳健", "holding_period": "长期"},
    ))
    assert "稳健" in text
    assert "长期" in text


def test_missing_profile_omits_portrait_line():
    text = _task_prompt(_context("分析600519"))
    assert "用户画像" not in text


def test_product_task_prompt_carries_profile():
    text = _task_prompt(_context(
        "分析该产品",
        domain=BusinessDomain.PRODUCT_RESEARCH,
        user_profile={"risk_preference": "稳健", "holding_period": "长期"},
    ))
    assert "稳健" in text
    assert "长期" in text


def test_context_defaults_params_and_profile_to_empty():
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
