"""生产编排到 QuantGateway 的依赖注入回归测试。"""

from __future__ import annotations

from finance_agent.orchestrator.contracts import (
    BusinessDomain,
    DomainOutcome,
    DomainTaskContext,
    PlanTask,
)


def test_stock_domain_runner_injects_quant_gateway(monkeypatch):
    """删除网关注入会使 CPU 指标计算悄悄回退到 Web 进程，必须阻止。"""
    from finance_agent.orchestrator.orchestrator import AdvisorSystem
    import finance_agent.orchestrator.domains.stock as stock_domain

    system = object.__new__(AdvisorSystem)
    gateway = object()
    captured: dict = {}

    class _StockGraph:
        def invoke(self, state):
            context = state["context"]
            return {
                "domain_outcome": DomainOutcome(
                    task_id=context.task.task_id,
                    domain=context.task.domain,
                    status="success",
                    summary="股票结论。",
                )
            }

    def build_stock_graph(deps):
        captured["deps"] = deps
        return _StockGraph()

    monkeypatch.setattr(stock_domain, "build_stock_domain_graph", build_stock_graph)
    system._get_quant_gateway = lambda: gateway
    context = DomainTaskContext(
        task=PlanTask(
            task_id="single:run-1:stock_research",
            domain=BusinessDomain.STOCK_RESEARCH,
            goal="分析贵州茅台",
            instruction="分析贵州茅台",
            expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message="分析贵州茅台",
    )

    outcome = system._domain_runner(context)

    assert captured["deps"].quant_gateway is gateway
    assert outcome.summary == "股票结论。"
