"""编排层 HITL：handle_message 的 awaiting_input / resume / 取消 / 画像落库。

架构变更后：参数提取下沉到领域专家 ReAct 循环，supervisor 不再有
``param_extractor`` 依赖与 ``ExtractedParams``。缺参由领域结论
``DomainOutcome.status="needs_input"`` 表达；根图的 ``converge`` 节点做缺参判定
与确定性计数，``ask`` 节点是 ``interrupt`` 的唯一宿主，拿到答案后按域 ``Send``
重跑并注入 ``clarification_answers``。本文件在 ``AdvisorSystem`` 层面验证
端到端 HITL 行为（用假分类器 + 假领域运行器，不进行重量级打桩）：

- 挂起 → ``awaiting_input``（下发 interrupt_id / pending_input / 文案）；
- ``resume=True`` + answers → 续跑并执行领域；
- 挂起期间自由文本新消息 → 放弃挂起 run、开启新轮（不被当成回答）；
- 弹窗补填的画像字段落长期画像，非法取值不落库；
- SSE 的 final response 事件同样携带追问载荷；
- 入口拒绝交易请求（不进图）。

``project_interrupt_state`` 的形状由 ``test_check_outcomes_graph.py`` 直接覆盖。
"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from finance_agent.orchestration.contracts import DomainOutcome
from tests.conftest import make_fake_supervisor_model
from finance_agent.orchestration.memory import UserProfileCard
from finance_agent.orchestration.needs_input import build_form
from finance_agent.application.advisor import AdvisorSystem
from finance_agent.orchestration.graphs.supervisor import SupervisorDependencies, build_supervisor_graph


class _FakeClassifier:
    def classify_intents(self, message: str, context_summary: str = "") -> dict:
        return {
            "intents": [{"intent": "stock_analysis", "query": message, "confidence": 0.99}],
            "uncertain_intents": [],
            "finance_related": True,
            "intent_source": "deepseek",
            "classification_error": {},
        }


class _NeedsInputRunner:
    """股票首次缺参（needs_input）、补答后成功；记录所有上下文。"""

    def __init__(self) -> None:
        self.contexts = []

    def __call__(self, context) -> DomainOutcome:
        self.contexts.append(context)
        answers = dict(context.clarification_answers or {})
        if not answers:
            return DomainOutcome(
                task_id=context.task.task_id,
                domain=context.task.domain,
                status="needs_input",
                summary="请补充股票标的。",
                structured_data={
                    "pending_input": build_form([(context.task.domain, ("stock_target",))]),
                },
            )
        return DomainOutcome(
            task_id=context.task.task_id, domain=context.task.domain,
            status="success", summary="分析完成。",
        )


class _FakeMemory:
    """最小记忆层：上下文读取 + 画像读写（记录写入以供断言）。"""

    def __init__(self) -> None:
        self.window_size = 10
        self.saved: list[dict] = []

    def load_context(self, customer_id, conversation_id, fallback):
        return {"profile": {}, "context_text": "", "sliding_window": []}

    def append_window_message(self, *args, **kwargs):
        return None

    def update_profile_from_result(self, *args, **kwargs):
        return None

    def get_profile(self, customer_id):
        return UserProfileCard(customer_id=customer_id.upper())

    def save_profile(self, profile):
        from dataclasses import asdict

        self.saved.append(asdict(profile))
        return True


def _supervisor(*, runner=None, classifier=None, conversation_runner=None):
    return build_supervisor_graph(
        SupervisorDependencies(
            supervisor_model=make_fake_supervisor_model(),
            classifier=classifier or _FakeClassifier(),
            domain_runner=runner or _NeedsInputRunner(),
            conversation_runner=conversation_runner,
            # 空改写器：避免默认改写器（惰性构造 INTENT_MODEL）引入外部依赖。
            rewriter=lambda state, domains: {},
        ),
        checkpointer=InMemorySaver(),
    )


def _system(monkeypatch, *, runner=None, classifier=None, conversation_runner=None) -> AdvisorSystem:
    system = object.__new__(AdvisorSystem)
    system._ensure_runtime_state()
    system.budgets = type("B", (), {
        "graph_steps": 32, "react_steps": 4, "max_domains": 4,
        "clarify_rounds": 2, "compliance_rewrites": 1, "turn_deadline": 120.0,
    })()
    system.memory = _FakeMemory()
    system.audit = type("A", (), {
        "create_run": lambda *a, **k: None,
        "complete_run": lambda *a, **k: None,
        "is_available": lambda self: False,
    })()
    system.get_checkpoint_conversation_messages = lambda *a, **k: []
    system._emit_progress = lambda *a, **k: None
    system._trace_agent = lambda *a, **k: None
    system.supervisor = _supervisor(
        runner=runner, classifier=classifier, conversation_runner=conversation_runner,
    )
    monkeypatch.setattr(
        "finance_agent.application.advisor.get_database",
        lambda: type("DB", (), {
            "append_conversation_message": lambda *a, **k: None,
            "rename_conversation_from_message": lambda *a, **k: None,
        })(),
    )
    return system


def test_missing_target_returns_awaiting_input(monkeypatch):
    system = _system(monkeypatch)

    result = system.handle_message("分析贵州茅台", customer_id="CUST1", conversation_id="conv-1")

    assert result["run_status"] == "awaiting_input"
    assert result["interrupt_id"], "必须下发 interrupt_id 供前端显式回传"
    assert result["pending_input"]["fields"][0]["name"] == "stock_target"
    assert "股票标的" in result["response"]
    assert result["conversation_id"] == "conv-1"


def test_resume_with_answers_completes_and_reruns_domain(monkeypatch):
    runner = _NeedsInputRunner()
    system = _system(monkeypatch, runner=runner)

    system.handle_message("分析贵州茅台", customer_id="CUST1", conversation_id="conv-1")
    result = system.handle_message(
        "股票标的：600519", customer_id="CUST1", conversation_id="conv-1",
        resume=True, answers={"stock_target": "600519"},
    )

    assert result["run_status"] == "completed"
    assert not result.get("pending_input")
    reruns = [c for c in runner.contexts if c.clarification_answers]
    assert reruns, "补齐参数后必须重跑领域"
    assert reruns[0].clarification_answers["stock_target"] == "600519"


def test_free_text_new_message_cancels_pending_and_starts_fresh(monkeypatch):
    """挂起期间用户直接发新问题：放弃挂起 run 并开新轮，不得被当成回答。"""
    runner = _NeedsInputRunner()
    system = _system(monkeypatch, runner=runner)

    system.handle_message("分析贵州茅台", customer_id="CUST1", conversation_id="conv-1")
    # 不带 resume/answers 的自由文本：应关掉挂起 run 并重新开始（仍是 awaiting_input）。
    result = system.handle_message(
        "算了，今天大盘怎么样", customer_id="CUST1", conversation_id="conv-1",
    )

    assert result["run_status"] == "awaiting_input", "新问题同样缺少必填标的"
    assert not any(c.clarification_answers for c in runner.contexts), "被放弃的挂起 run 不得执行领域"


def test_answers_profile_fields_are_persisted(monkeypatch):
    system = _system(monkeypatch)

    system.handle_message("分析贵州茅台", customer_id="CUST1", conversation_id="conv-1")
    system.handle_message(
        "600519，偏稳健长期", customer_id="CUST1", conversation_id="conv-1",
        resume=True,
        answers={"stock_target": "600519", "risk_preference": "稳健", "holding_period": "长期"},
    )

    assert system.memory.saved, "弹窗填写的偏好必须写入长期画像"
    saved = system.memory.saved[-1]
    assert saved["risk_preference"] == "稳健"
    assert saved["holding_period"] == "长期"


def test_invalid_profile_answer_is_not_persisted(monkeypatch):
    system = _system(monkeypatch)

    system.handle_message("分析贵州茅台", customer_id="CUST1", conversation_id="conv-1")
    system.handle_message(
        "600519", customer_id="CUST1", conversation_id="conv-1",
        resume=True, answers={"stock_target": "600519", "risk_preference": "随便说说"},
    )

    assert system.memory.saved == [], "非法偏好取值不得写入画像"


def test_stream_yields_final_response_event_for_awaiting_input(monkeypatch):
    """SSE 追问随最终 response 事件下发，前端零新增事件类型即可消费。"""
    import asyncio

    system = _system(monkeypatch)

    async def drain():
        return [
            event async for event in system.handle_message_stream(
                "分析贵州茅台", customer_id="CUST1", conversation_id="conv-1",
            )
        ]

    events = asyncio.run(drain())
    final = events[-1]

    assert final["type"] == "response"
    assert final["data"]["run_status"] == "awaiting_input"
    assert final["data"]["pending_input"]["fields"][0]["name"] == "stock_target"


# ── 交易/下单请求：入口统一拒绝，不进图 ─────────────────────────────────────

def test_trade_request_is_rejected_at_entry_without_running_graph(monkeypatch):
    """代客交易请求在 handle_message 入口即被拒绝：不进图、不调分类模型。"""
    system = _system(monkeypatch)

    result = system.handle_message(
        "帮我买1000块110011", customer_id="CUST1", conversation_id="conv-1",
    )

    assert result["run_status"] == "completed"
    assert result["blocked"] is True
    assert "不代客下单" in result["response"]
    assert result["warnings"] == ["trade_request_rejected"]
    assert result["task_plan"] == []


def test_trade_rule_question_still_enters_graph(monkeypatch):
    """交易规则咨询不得被误拒：仍走正常编排（示例为闲聊/FAQ 通道）。"""

    class _ChatClassifier:
        def classify_intents(self, message, context_summary=""):
            return {
                "intents": [{
                    "intent": "casual_chat", "query": message, "confidence": 0.99,
                }],
                "uncertain_intents": [], "finance_related": False,
                "intent_source": "deepseek", "classification_error": {},
            }

    system = _system(
        monkeypatch,
        classifier=_ChatClassifier(),
        conversation_runner=lambda state: {
            "final_response": "申购费率说明……", "status": "success",
        },
    )

    result = system.handle_message(
        "申购费率是多少", customer_id="CUST1", conversation_id="conv-1",
    )

    assert result.get("blocked") is None or result.get("blocked") is False
    assert "费率" in result["response"]
