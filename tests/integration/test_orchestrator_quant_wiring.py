"""生产编排到领域专家与 QuantGateway 的接线回归测试。

重构后股票领域图（``build_stock_domain_graph`` + ``StockDeps.quant_gateway``）
已删除，接线分为两处：

1. ``AdvisorSystem._domain_runner`` 按领域分发到 ``build_expert`` 编译的专家图；
2. 股票专家的 ``compute_technical`` 经模块级 ``_gateway()`` 取 QuantGateway，
   有网关时**必须卸载**，绝不静默回退到 Web 进程内联计算。
"""

from __future__ import annotations

from finance_agent.shared.contracts import AsyncJobRef
from finance_agent.orchestration.contracts import (
    BusinessDomain,
    DomainOutcome,
    DomainTaskContext,
    PlanTask,
)


def _stock_context() -> DomainTaskContext:
    return DomainTaskContext(
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


def test_domain_runner_dispatches_to_domain_expert(monkeypatch):
    """生产编排把领域任务分发给对应领域的专家子图。"""
    from finance_agent.application.advisor import AdvisorSystem
    import finance_agent.orchestration.experts as experts

    system = object.__new__(AdvisorSystem)
    system._ensure_runtime_state()
    captured: dict = {}

    class _StockGraph:
        # 宿主以 ``graph.invoke(state, config=...)`` 调用：专家子图据此拿到
        # stop_check（模型轮次边界的协作式停止查询），因此必须接受 config。
        def invoke(self, state, config=None):
            context = state["context"]
            captured["config"] = config
            return {
                "domain_outcome": DomainOutcome(
                    task_id=context.task.task_id,
                    domain=context.task.domain,
                    status="success",
                    summary="股票结论。",
                )
            }

    def build_expert(domain, *, model=None):
        captured["domain"] = domain
        return _StockGraph()

    monkeypatch.setattr(experts, "build_expert", build_expert)

    outcome = system._domain_runner(_stock_context())

    assert captured["domain"] is BusinessDomain.STOCK_RESEARCH
    assert outcome.summary == "股票结论。"
    # 停止查询必须经 config 下发（否则专家无法在模型轮次边界自行退出）。
    from finance_agent.orchestration.experts.base import STOP_CHECK_KEY

    assert callable(captured["config"]["configurable"][STOP_CHECK_KEY])
    # 同领域再次调用复用已编译的专家图，不重复编译。
    system._domain_runner(_stock_context())
    assert system._expert_graphs[BusinessDomain.STOCK_RESEARCH] is not None


def test_technical_tool_offloads_to_quant_gateway(monkeypatch):
    """存在 QuantGateway 时技术指标必须卸载，不得静默内联计算。"""
    import finance_agent.domains.research.expert.tools as tools_stock
    from finance_agent.orchestration.experts.base import ExpertSink
    from finance_agent.domains.research.expert.tools import compute_technical

    submitted: list[str] = []

    class _RecordingGateway:
        def submit(self, kind, payload, idempotency_key, *, customer_id=""):
            submitted.append(kind)
            return AsyncJobRef(job_id="job-1", kind=kind, status="queued", task_id="job-1")

        def status(self, job_id):
            return "queued"

        def result(self, job_id):
            return None

    monkeypatch.setattr(tools_stock, "_gateway", lambda: _RecordingGateway())
    monkeypatch.setattr(
        tools_stock._stockdata, "fetch_stock_data",
        lambda codes: {"600519": {"history": {"data": [
            {"close": 10.0 + i, "high": 11.0 + i, "low": 9.0 + i} for i in range(80)
        ]}}},
    )
    sink = ExpertSink(domain=BusinessDomain.STOCK_RESEARCH, customer_id="CUST1")

    compute_technical.invoke(
        {"stock_code": "600519"},
        config={"configurable": {"expert_sink": sink}},
    )

    assert submitted == ["technical_indicators"]
    assert "awaiting_quant" in sink.limitations
