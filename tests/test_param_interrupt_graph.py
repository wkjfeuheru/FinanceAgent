"""根图缺参追问：interrupt / resume / 取消 / 降级 / 无 checkpointer 回退。"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from finance_agent.orchestrator.contracts import BusinessDomain, DomainOutcome
from finance_agent.orchestrator.routing.params import ExtractedParams
from finance_agent.orchestrator.graphs.supervisor_graph import (
    SupervisorDependencies,
    build_supervisor_graph,
    project_interrupt_state,
)


class _FakeClassifier:
    def __init__(self, intents: list[str], *, queries: dict[str, str] | None = None) -> None:
        self._intents = intents
        self._queries = queries or {}

    def classify_intents(self, message: str, context_summary: str = "") -> dict:
        return {
            "intents": [
                {
                    "intent": intent,
                    "query": self._queries.get(intent, intent),
                    "confidence": 0.99,
                }
                for intent in self._intents
            ],
            "uncertain_intents": [],
            "finance_related": True,
            "intent_source": "deepseek",
            "classification_error": {},
        }


class _FakeExtractor:
    """确定性假抽取器：按预设返回，并记录调用次数（验证恢复不重复抽取）。"""

    def __init__(self, *, available: bool = True) -> None:
        self.calls = 0
        self._available = available

    def __call__(self, message, history="", *, domains):
        self.calls += 1
        return ExtractedParams(values={}, warnings=[], extraction_available=self._available)


class _RecordingDomainRunner:
    def __init__(self) -> None:
        self.contexts = []

    def __call__(self, context) -> DomainOutcome:
        self.contexts.append(context)
        return DomainOutcome(
            task_id=context.task.task_id,
            domain=context.task.domain,
            status="success",
            summary="已完成分析。",
        )


def _graph(intents, *, extractor=None, runner=None, checkpointer=None, queries=None):
    return build_supervisor_graph(
        SupervisorDependencies(
            classifier=_FakeClassifier(intents, queries=queries),
            domain_runner=runner or _RecordingDomainRunner(),
            conversation_runner=lambda state: {"final_response": "你好", "status": "success"},
            param_extractor=extractor or _FakeExtractor(),
        ),
        checkpointer=checkpointer,
    )


def _inputs(thread_id: str = "t1") -> dict:
    return {
        "user_message": "分析贵州茅台",
        "run_id": "run-1",
        "customer_id": "CUST1",
        "conversation_id": "conv-1",
        "thread_id": thread_id,
    }


def _config(thread_id: str = "t1") -> dict:
    return {"configurable": {"thread_id": thread_id}}


def test_stock_request_without_target_interrupts_with_form():
    graph = _graph(["stock_analysis"], checkpointer=InMemorySaver())

    result = graph.invoke(_inputs(), _config())

    interrupts = result.get("__interrupt__") or ()
    assert interrupts, "缺标的的股票请求必须挂起等待用户补充"
    form = interrupts[0].value
    assert "股票标的" in form["question"]
    assert [field["name"] for field in form["fields"]][0] == "stock_target"
    assert any(field["required"] for field in form["fields"])


def test_resume_with_target_completes_and_passes_params_to_domain():
    extractor = _FakeExtractor()
    runner = _RecordingDomainRunner()
    graph = _graph(["stock_analysis"], extractor=extractor, runner=runner, checkpointer=InMemorySaver())
    config = _config()

    graph.invoke(_inputs(), config)
    result = graph.invoke(Command(resume={"stock_target": "600519"}), config)

    assert not result.get("__interrupt__")
    assert result["run_status"] == "completed"
    assert runner.contexts, "补齐参数后必须真正执行领域"
    assert runner.contexts[0].params["stock_target"] == "600519"
    # extract 节点只在恢复前跑过一次：interrupt 重跑的是确定性 validate 节点。
    assert extractor.calls == 1


def test_resume_target_is_merged_into_domain_query():
    runner = _RecordingDomainRunner()
    graph = _graph(
        ["stock_analysis"], runner=runner, checkpointer=InMemorySaver(),
        queries={"stock_analysis": "分析贵州茅台"},
    )
    config = _config()

    graph.invoke(_inputs(), config)
    graph.invoke(Command(resume={"stock_target": "600519"}), config)

    assert "600519" in runner.contexts[0].task.goal


def test_cancel_resume_finishes_without_executing_domain():
    runner = _RecordingDomainRunner()
    graph = _graph(["stock_analysis"], runner=runner, checkpointer=InMemorySaver())
    config = _config()

    graph.invoke(_inputs(), config)
    result = graph.invoke(Command(resume={"__cancel__": True}), config)

    assert not result.get("__interrupt__")
    assert result["run_status"] == "completed"
    assert "已取消" in result["final_response"]
    assert runner.contexts == [], "用户取消后不得执行领域"


def test_market_and_account_never_interrupt():
    """市场/账户无必填项，不得因缺参挂起。"""
    for intent, domain in (("market_insight", "market_insight"), ("account_query", "account_portfolio")):
        graph = _graph([intent], checkpointer=InMemorySaver())
        result = graph.invoke(_inputs(thread_id=f"t-{domain}"), _config(f"t-{domain}"))
        assert not result.get("__interrupt__"), f"{domain} 不应触发追问"
        assert result["run_status"] == "completed"


def test_partial_answer_degrades_to_partial_without_requestion():
    """单次询问：恢复值仍缺必填时显式收尾为 partial，不再次挂起。

    注：LangGraph 把空字典 resume 视作"未提供恢复值"并会重新挂起；生产路径下
    编排层只在 ``answers`` 非空时才 resume（空则走取消+重开），因此这里用"只填了
    可选字段"的真实场景验证收尾逻辑。
    """
    graph = _graph(["stock_analysis"], checkpointer=InMemorySaver())
    config = _config()

    graph.invoke(_inputs(), config)
    result = graph.invoke(Command(resume={"analysis_type": "综合"}), config)

    assert not result.get("__interrupt__"), "不得重复追问"
    assert result["run_status"] == "partial"
    assert "股票标的" in result["final_response"]


def test_extraction_unavailable_does_not_interrupt():
    """抽取不可用（模型未配置/失败）时不得把"没抽到"当"用户没说"，直接放行。"""
    runner = _RecordingDomainRunner()
    graph = _graph(
        ["stock_analysis"], extractor=_FakeExtractor(available=False),
        runner=runner, checkpointer=InMemorySaver(),
    )

    result = graph.invoke(_inputs(), _config())

    assert not result.get("__interrupt__")
    assert runner.contexts, "放行后领域自行解析/降级"


def test_without_checkpointer_degrades_to_clarify_not_interrupt():
    """无 checkpointer 无法 suspend/resume：退化为澄清式收尾。"""
    graph = _graph(["stock_analysis"], checkpointer=None)

    result = graph.invoke(_inputs())

    assert not result.get("__interrupt__")
    assert result["run_status"] == "partial"
    assert "股票标的" in result["final_response"]


def test_conversation_mode_skips_extraction_entirely():
    extractor = _FakeExtractor()
    graph = _graph(["casual_chat"], extractor=extractor, checkpointer=InMemorySaver())

    result = graph.invoke(
        {**_inputs("t-chat"), "user_message": "你好"}, _config("t-chat"),
    )

    assert result["final_response"] == "你好"
    assert extractor.calls == 0, "闲聊分支不应触发参数抽取"


def test_plan_execute_domain_receives_params_and_profile():
    """复合请求的每领域任务同样拿到参数与画像。"""
    runner = _RecordingDomainRunner()
    graph = _graph(["stock_analysis", "product_analysis"], runner=runner, checkpointer=InMemorySaver())
    config = _config("t-plan")

    graph.invoke(
        {
            **_inputs("t-plan"),
            "user_message": "分析贵州茅台并比较合适的基金产品",
            "user_profile": {"risk_preference": "稳健", "holding_period": "长期"},
        },
        config,
    )
    graph.invoke(
        Command(resume={"stock_target": "600519", "product_reference": "华夏成长基金"}), config,
    )

    stock_contexts = [c for c in runner.contexts if c.task.domain == BusinessDomain.STOCK_RESEARCH]
    assert stock_contexts, "股票领域必须被执行"
    assert stock_contexts[0].params["stock_target"] == "600519"
    assert stock_contexts[0].user_profile["risk_preference"] == "稳健"


def test_project_interrupt_state_reports_awaiting_input():
    class _Interrupt:
        id = "abc123"
        value = {"question": "请补充股票标的。", "missing": ["stock_research:stock_target"], "fields": []}

    output = project_interrupt_state({"__interrupt__": (_Interrupt(),)}, conversation_id="conv-1")

    assert output["run_status"] == "awaiting_input"
    assert output["response"] == "请补充股票标的。"
    assert output["interrupt_id"] == "abc123"
    assert output["pending_input"]["missing"] == ["stock_research:stock_target"]
    assert output["warnings"] == ["awaiting_user_input"]
    assert output["pending_task_ids"] == []


def test_project_interrupt_state_handles_empty_interrupts():
    output = project_interrupt_state({"param_missing": {}}, conversation_id="c")

    assert output["run_status"] == "awaiting_input"
    assert output["pending_input"] is None
