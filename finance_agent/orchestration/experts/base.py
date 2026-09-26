"""领域 ReAct 专家的共享外壳：``validate → react_agent → assemble``。

设计要点：

- **专家是外包图**，中间节点调用 LangGraph 原生 ``create_agent`` 编译出的工具
  循环。之所以不把 ``create_agent`` 直接当子图嵌入，是避免把它的
  ``AgentState``（``messages`` 等）与领域图状态做 schema 对齐——仓库既有做法
  （如会话路径）同样是"节点函数内部调用一个编译好的 ReAct 循环"。
- **工具把结构化产物写进 per-run 的 ``ExpertSink``**：工具经 ``RunnableConfig``
  拿到本次运行的 sink，直接把**冻结的 structured_data 键位**写进去。这样
  ``assemble`` 不需要解析自然语言，键位保真由工具保证。
- **缺参靠专用工具**：``request_user_input`` 把表单写进 sink 并置位；无论模型
  之后还说了什么，``assemble`` 一律以 sink 的表单为准产出 ``needs_input`` 结论，
  由 supervisor 统一弹窗。
- **答案是模型分析**：模型的 ``final_text`` 是基于已取到数据写出的分析
  （回答"怎么样"），作为用户可见正文；工具写入冻结的 structured_data 键位
  供前端卡片与数字核对。分析里的数字会与工具 JSON 做确定性比对，越界者
  登记为 limitation（只披露、不阻断）。
- **步数预算是硬约束**：``ModelCallLimitMiddleware`` 在达到上限时结束循环；
  若收尾时最后一条消息仍是工具调用（即被上限截断），按 ``partial`` 诚实降级。
- **停止与截止由宿主下发**：``stop_check`` 经 ``RunnableConfig`` 注入，在**每次
  模型调用前**（``CooperativeStopMiddleware.before_model``）检查一次。已触发时
  结束循环并把原因登记进 sink，由 ``assemble`` 降级为 ``partial``——用户已看到的
  部分结论被保留，而不是丢掉整轮。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from finance_agent.orchestration.contracts import (
    BusinessDomain,
    DomainOutcome,
    DomainTaskContext,
)
from finance_agent.orchestration.needs_input import (
    build_form,
    field_spec,
    fields_for,
)

logger = logging.getLogger(__name__)

#: per-run 累积器在 ``RunnableConfig.configurable`` 里的键。
SINK_KEY = "expert_sink"
#: 本轮弹窗补填答案在 config 里的键（专家重跑时读取）。
ANSWERS_KEY = "expert_answers"
#: 停止/截止查询在 config 里的键：一个返回原因码（空串表示继续）的可调用对象。
#: 宿主在图外构造（``AdvisorSystem._domain_runner``），这样"是否该停"的真相
#: 只有一处，且不需要把可调用对象塞进会被 checkpoint 序列化的图状态。
STOP_CHECK_KEY = "stop_check"

#: 历史键名：工具曾把中文模板写入 extras；专家路径不再拼接该附录。
DIGEST_KEY = "data_digest"

#: 领域数据/模型不可用时的兜底文案（各域可覆盖）。
DEFAULT_UNAVAILABLE = "该领域数据暂时无法生成，请稍后重试。"


def sink_of(config: RunnableConfig | dict[str, Any] | None) -> "ExpertSink | None":
    """从工具拿到的 config 里取出本次运行的 sink。"""
    if not isinstance(config, dict):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        return None
    sink = configurable.get(SINK_KEY)
    return sink if isinstance(sink, ExpertSink) else None


def answers_of(config: RunnableConfig | dict[str, Any] | None) -> dict[str, Any]:
    """从 config 里取出本轮弹窗补填的答案（无则空 dict）。"""
    if not isinstance(config, dict):
        return {}
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        return {}
    answers = configurable.get(ANSWERS_KEY)
    return dict(answers) if isinstance(answers, dict) else {}


def stop_check_of(config: RunnableConfig | dict[str, Any] | None) -> Callable[[], str] | None:
    """从 config 里取出停止/截止查询（无则 None）。"""
    if not isinstance(config, dict):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        return None
    check = configurable.get(STOP_CHECK_KEY)
    return check if callable(check) else None


@dataclass
class ExpertSink:
    """一次专家运行的累积器：结构化产物、局限、缺参信号与工具轨迹。

    工具通过 ``RunnableConfig`` 拿到本对象并直接写入**冻结键位**；``assemble``
    只做汇总，不解析自然语言。
    """

    domain: BusinessDomain
    #: 本轮客户标识：由上下文注入，**绝不来自模型**（防越权）。
    customer_id: str = ""
    #: 用户画像卡快照（上下文注入）。
    user_profile: dict[str, Any] = field(default_factory=dict)
    #: 冻结的 structured_data 键位累积（工具写入）。
    structured: dict[str, Any] = field(default_factory=dict)
    #: 工具上报的局限（逐项降级诚实登记）。
    limitations: list[str] = field(default_factory=list)
    #: 工具轨迹（审计与测试断言用）。
    tool_trace: list[str] = field(default_factory=list)
    #: 是否有工具明确失败（决定整体 failed 而非 partial）。
    failed: bool = False
    #: 缺参表单（``request_user_input`` 写入）；非 None 即产出 needs_input 结论。
    pending_input: dict[str, Any] | None = None
    #: 附加结构化字段：evidence / pending_jobs / 权威 summary 等。
    extras: dict[str, Any] = field(default_factory=dict)

    def record(self, tool_name: str, *, payload: dict[str, Any] | None = None) -> None:
        self.tool_trace.append(tool_name)
        for key, value in (payload or {}).items():
            self.structured[key] = value

    def limit(self, code: str) -> None:
        if code not in self.limitations:
            self.limitations.append(code)

    def fail(self, code: str) -> None:
        self.limit(code)
        self.failed = True

    def need_input(self, fields: list[str], question: str = "") -> dict[str, Any]:
        """登记缺参表单；字段名不在登记处的一律忽略（模型无权发明字段）。"""
        valid = [
            name for name in fields
            if field_spec(self.domain, name) is not None
        ]
        if not valid:
            return {"error": "no_valid_fields"}
        form = build_form([(self.domain, tuple(valid))]) or {}
        if question.strip():
            form["question"] = question.strip()
        self.pending_input = form
        return {"accepted": valid}


@dataclass
class ExpertAssembly:
    """``assemble`` 的产出：直接映射到 ``DomainOutcome``。"""

    structured_data: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    status: str = "success"
    limitations: list[str] = field(default_factory=list)
    evidence: list[Any] = field(default_factory=list)
    pending_jobs: list[Any] = field(default_factory=list)


class ExpertState(TypedDict, total=False):
    context: DomainTaskContext
    domain_outcome: DomainOutcome


def make_request_user_input_tool(domain: BusinessDomain):
    """构造 ``request_user_input`` 工具（按领域绑定字段登记处）。

    模型只能引用**已登记**的字段名；未登记字段会被拒绝并把可用字段回灌给模型，
    从而不会出现"模型自造控件"。调用后 ``sink.pending_input`` 置位，``assemble``
    据此产出 ``needs_input`` 结论。
    """
    from langchain_core.tools import tool

    available = ", ".join(spec.name for spec in fields_for(domain))
    labels = "、".join(
        f"{spec.name}（{spec.label}）" for spec in fields_for(domain)
    )

    @tool
    def request_user_input(fields: list[str], config: RunnableConfig, question: str = "") -> str:
        """当缺少**关键参数**导致无法继续分析时，向用户追问。

        只有在无法自行推断、且缺了它就无法给出有意义结论时才调用；能通过搜索
        或名称解析补齐的标的不要追问。调用后请立即结束回答，不要再调用其它工具。

        Args:
            fields: 需要用户补充的字段名列表。可选值：{labels}
            question: 可选的追问文案（留空则用服务端模板）。
        """
        sink = sink_of(config)
        if sink is None:
            return json.dumps({"error": "no_sink"}, ensure_ascii=False)
        sink.tool_trace.append("request_user_input")
        result = sink.need_input(list(fields or []), question)
        if "error" in result:
            return json.dumps(
                {"error": "unknown_field", "allowed": available}, ensure_ascii=False
            )
        return json.dumps(
            {"accepted": result["accepted"], "note": "已登记追问，请立即结束回答。"},
            ensure_ascii=False,
        )

    return request_user_input


def _task_prompt(context: DomainTaskContext) -> str:
    """把领域任务上下文渲染为专家可读的一段任务描述。"""
    parts: list[str] = []
    goal = str(context.task.goal or "").strip()
    instruction = str(context.task.instruction or "").strip()
    if goal:
        parts.append(goal)
    if instruction and instruction != goal:
        parts.append(instruction)
    upstream = context.upstream_results or {}
    if upstream:
        lines = [
            f"- {getattr(outcome, 'domain', '')}: {str(getattr(outcome, 'summary', '') or '').strip()}"
            for outcome in upstream.values()
            if str(getattr(outcome, "summary", "") or "").strip()
        ]
        if lines:
            parts.append("其它领域的已有结论（可参考，不要重复计算）：\n" + "\n".join(lines))
    if context.clarification_answers:
        filled = "；".join(
            f"{key}={value}" for key, value in context.clarification_answers.items()
        )
        parts.append(f"用户补充的参数：{filled}")
    profile = context.user_profile or {}
    if profile.get("risk_preference") or profile.get("holding_period"):
        parts.append(
            "用户画像：风险偏好 "
            f"{profile.get('risk_preference') or '未设置'}，投资期限 "
            f"{profile.get('holding_period') or '未设置'}。"
        )
    return "\n\n".join(parts) if parts else str(context.user_message or "")


#: ``ModelCallLimitMiddleware`` 触顶时写入的占位消息前缀（框架常量文本）。
#: 仅作二次校验，主判据是工具调用轮次计数（见 ``_final_text``）。
_LIMIT_MARKER = "Model call limits exceeded"


def build_stop_middleware() -> Any:
    """构造"协作式停止/截止"中间件：每次模型调用前检查一次宿主标记。

    为什么放在中间件而不是工具边界：工具只在模型决定调用工具时才执行，一个
    "只调用一次工具、然后长时间生成"的循环根本不会回到工具边界；``before_model``
    是每轮推理的必经点，语义上等价于"下一个轮次边界退出"，与产品承诺一致。

    触发时 ``jump_to="end"`` 结束 ReAct 循环，并注入一条**空内容**的 AI 消息
    （``_final_text`` 会跳过空文本，因此模型此前写出的分析仍会作为正文保留）。
    原因码写进 sink 的 limitations，由 ``assemble`` 降级为 ``partial``。
    """
    from langchain.agents.middleware import AgentMiddleware, hook_config
    from langchain_core.messages import AIMessage
    from langgraph.config import get_config

    class CooperativeStopMiddleware(AgentMiddleware):
        """宿主下发停止/截止标记时结束当前领域执行。"""

        @hook_config(can_jump_to=["end"])
        def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
            check = stop_check_of(get_config())
            if check is None:
                return None
            try:
                reason = str(check() or "")
            except Exception:  # noqa: BLE001 - 停止查询失败按"继续"处理
                logger.warning("stop_check_failed", exc_info=True)
                return None
            if not reason:
                return None
            sink = sink_of(get_config())
            if sink is not None:
                sink.limit(reason)
            logger.info("expert_cooperative_stop reason=%s", reason)
            return {"jump_to": "end", "messages": [AIMessage(content="")]}

    return CooperativeStopMiddleware()


def _final_text(messages: list[Any], max_steps: int) -> tuple[str, bool]:
    """从消息序列取最终答复文本；返回 ``(文本, 是否被步数上限截断)``。

    截断判据是**工具调用轮次计数**而非框架的英文占位文案：AI 消息里携带
    ``tool_calls`` 的条数达到 ``max_steps``，说明循环是被
    ``ModelCallLimitMiddleware`` 截断的（正常收尾时最后一轮是无工具调用的
    答复，轮次必然少一次）。截断时回退到最近一条真实文本，由 ``assemble``
    诚实降级为 partial。
    """
    from langchain_core.messages import AIMessage

    rounds = sum(
        1 for message in messages
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None)
    )
    truncated = rounds >= max_steps

    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        content = getattr(message, "content", "")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        text = str(content or "").strip()
        if not text:
            continue
        # 框架触顶占位消息不是答复，不得当作最终文本。
        if truncated and text.startswith(_LIMIT_MARKER):
            continue
        return text, truncated
    return "", truncated


def build_expert_graph(
    domain: BusinessDomain,
    *,
    tools: list[Any],
    system_prompt: str,
    max_steps: int,
    model: Any = None,
    assemble: Callable[[ExpertSink, str], ExpertAssembly] | None = None,
    unavailable_text: str = DEFAULT_UNAVAILABLE,
    name: str | None = None,
):
    """编译一个领域专家子图（``validate → react_agent → assemble``）。

    ``model`` 可注入（测试用假 tool-calling 模型）；默认取 ``get_expert_model()``。
    ``assemble`` 为 None 时用默认实现（直接透传 sink 产物 + 最终文本）。
    """
    assemble_fn = assemble or default_assemble

    def _resolve_model() -> Any:
        if model is not None:
            return model
        from finance_agent.infrastructure.llm.factory import get_expert_model

        return get_expert_model()

    def _build_agent() -> Any:
        from langchain.agents import create_agent
        from langchain.agents.middleware import ModelCallLimitMiddleware

        return create_agent(
            _resolve_model(),
            tools=[*tools, make_request_user_input_tool(domain)],
            system_prompt=system_prompt,
            middleware=[
                ModelCallLimitMiddleware(run_limit=max_steps, exit_behavior="end"),
                build_stop_middleware(),
            ],
            name=name or f"{domain.value}_expert",
        )

    # 编译一次、复用于所有轮次（工具经 RunnableConfig 取 per-run sink，天然无状态）。
    agent = _build_agent()

    def validate_node(state: ExpertState) -> dict[str, Any]:
        context = state["context"]
        if context.task.domain is not domain:
            return {
                "domain_outcome": DomainOutcome(
                    task_id=context.task.task_id,
                    domain=domain,
                    status="failed",
                    summary="",
                    limitations=["domain_mismatch"],
                )
            }
        # 主题/板块筛选不再在这里被短路：过去用正则判定"推荐/筛选 + 主题/板块"就
        # 直接返回固定拒绝文案（模型都不会被调用），代价是"帮我推荐几个AI行业
        # 值得关注的股票"永远拿不到答案。现在改由专家的 ``list_boards`` /
        # ``screen_board_candidates`` 取真实板块数据 + 确定性评分，匹配不到时
        # 由工具返回引导文案，不在这里猜。
        return {}

    def run_agent_node(state: ExpertState, config: RunnableConfig) -> dict[str, Any]:
        context = state["context"]
        sink = ExpertSink(
            domain=domain,
            customer_id=str(context.customer_id or ""),
            user_profile=dict(context.user_profile or {}),
        )
        try:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": _task_prompt(context)}]},
                config={
                    "configurable": {
                        SINK_KEY: sink,
                        ANSWERS_KEY: dict(context.clarification_answers or {}),
                        # 宿主下发的停止/截止查询经外层图 config 透传到内层
                        # ReAct 循环：中间件在每次模型调用前读取它。
                        STOP_CHECK_KEY: stop_check_of(config),
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001 - 模型/图故障只降级，不崩溃整轮
            logger.exception(
                "expert_agent_failed domain=%s task=%s", domain.value, context.task.task_id,
            )
            sink.fail("expert_unavailable")
            return {
                "domain_outcome": DomainOutcome(
                    task_id=context.task.task_id,
                    domain=domain,
                    status="failed",
                    summary=unavailable_text,
                    limitations=["expert_unavailable"],
                )
            }

        messages = list((result or {}).get("messages") or [])
        final_text, truncated = _final_text(messages, max_steps)
        if truncated:
            sink.limit("react_step_limit")
        assembly = assemble_fn(sink, final_text)
        return {
            "domain_outcome": DomainOutcome(
                task_id=context.task.task_id,
                domain=domain,
                status=assembly.status,
                summary=assembly.summary,
                structured_data=assembly.structured_data,
                evidence=assembly.evidence,
                limitations=assembly.limitations,
                pending_jobs=assembly.pending_jobs,
            )
        }

    def assemble_node(state: ExpertState) -> dict[str, Any]:
        outcome = state.get("domain_outcome")
        return {"domain_outcome": outcome} if outcome is not None else {}

    def _after_validate(state: ExpertState) -> str:
        return "assemble" if state.get("domain_outcome") is not None else "agent"

    graph = StateGraph(ExpertState)
    graph.add_node("validate", validate_node)
    graph.add_node("agent", run_agent_node)
    graph.add_node("assemble", assemble_node)
    graph.add_edge(START, "validate")
    graph.add_conditional_edges(
        "validate", _after_validate, {"agent": "agent", "assemble": "assemble"},
    )
    graph.add_edge("agent", "assemble")
    graph.add_edge("assemble", END)
    return graph.compile()


def default_assemble(sink: ExpertSink, final_text: str) -> ExpertAssembly:
    """默认汇总：用户可见正文 = 模型分析；结构化键位给前端卡片。

    工具只负责取数/算数。``final_text`` 是模型基于工具 JSON 写出的分析。
    不再把中文 ``data_digest`` 接到正文后。

    状态判定（诚实优先）：
    1. 有缺参信号 → ``needs_input``（结论交给 supervisor 弹窗，不当作成功）；
    2. 有工具明确失败 → ``failed``；
    3. 有局限或未产出任何结构化数据 → ``partial``；
    4. 其余 → ``success``。
    """
    if sink.pending_input is not None:
        structured = dict(sink.structured)
        structured["pending_input"] = sink.pending_input
        return ExpertAssembly(
            structured_data=structured,
            summary=str(sink.pending_input.get("question") or ""),
            status="needs_input",
            limitations=list(sink.limitations),
            evidence=list(sink.extras.get("evidence") or []),
            pending_jobs=list(sink.extras.get("pending_jobs") or []),
        )

    structured = dict(sink.structured)
    for key, value in (sink.extras or {}).items():
        if key == DIGEST_KEY:
            continue
        structured.setdefault(key, value)

    if sink.failed:
        status = "failed"
    elif sink.limitations or not structured:
        status = "partial"
    else:
        status = "success"

    analysis = final_text.strip()
    limitations = list(sink.limitations)

    grounding = _ungrounded_numbers(analysis, structured, "") if analysis else []
    if grounding:
        structured["analysis_grounding"] = {"ungrounded": grounding}
        for number in grounding:
            limitations.append(f"analysis_number_not_grounded:{number}")

    summary = analysis or _fallback_summary(sink, structured)

    return ExpertAssembly(
        structured_data=structured,
        summary=summary,
        status=status,
        limitations=limitations,
        evidence=list(sink.extras.get("evidence") or []),
        pending_jobs=list(sink.extras.get("pending_jobs") or []),
    )


def _ungrounded_numbers(analysis: str, structured: dict[str, Any], digest: str) -> list[str]:
    """找出分析里出现、但工具输出中不存在的数字（去重、保序）。

    设计取舍：**只登记不阻断**。金融场景下数字准确性权重高，但分析是模型写的，
    宁可如实披露"这个数字没有依据"（进入 limitations 与
    ``structured_data.analysis_grounding`` 供前端/审计读取），也不要静默改写
    或直接拒答——后者会把一次可用的分析整体丢掉。

    允许集来自工具的结构化产出（``structured`` 的 JSON）与确定性明细文本；相对
    容差吸收四舍五入（``2.68%`` 与 ``2.679%`` 视为同一数字）。候选数字只取"看起来
    像金融数值"的形态（带单位/小数/千分位整数），避免把"2026""3 只"这类
    年份、序号、计数误报为越界数字。
    """
    allowed = _numbers_in(_json_text(structured)) | _numbers_in(digest)
    if not allowed:
        # 工具没有任何数字产出（未取数/工具失败）：无法判定依据，不做误报。
        return []
    # 符号不敏感：原始值可能是 -1.18（跌幅），分析常写成"跌 1.18%"（正的数量）。
    # 把绝对值一并纳入允许集，避免把同一数字的两种写法误报为越界。
    allowed |= {abs(value) for value in allowed}

    ungrounded: list[str] = []
    for raw, value in _candidate_numbers(analysis):
        if raw in ungrounded:
            continue
        if any(_close(value, known) for known in allowed):
            continue
        if any(_close(abs(value), known) for known in allowed):
            continue
        ungrounded.append(raw)
    return ungrounded


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def _numbers_in(text: str) -> set[float]:
    """提取文本中的全部数字（去千分位）。"""
    out: set[float] = set()
    for token in re.findall(r"-?\d[\d,]*(?:\.\d+)?", str(text or "")):
        try:
            out.add(float(token.replace(",", "")))
        except ValueError:
            continue
    return out


#: 看起来像金融数值的形态：带单位、带小数、或 ≥1000 的整数（千分位）。
#: 单独出现的小整数（年份片段、序号、只数）不算——它们常是叙述而非数据引用。
_UNIT_RE = r"(?:%|％|亿元|万元|亿|万|元|家|只|倍|点|个|天|年|月|日)"
_CANDIDATE_RE = re.compile(rf"-?\d[\d,]*(?:\.\d+)?\s*{_UNIT_RE}|-?\d[\d,]*\.\d+|-?\d{{1,3}}(?:,\d{{3}})+")


def _candidate_numbers(text: str) -> list[tuple[str, float]]:
    """从分析文本里挑出"像数据引用"的数字，返回 ``(原文片段, 归一化数值)``。"""
    out: list[tuple[str, float]] = []
    for match in _CANDIDATE_RE.findall(str(text or "")):
        raw = match.strip()
        digits = re.match(r"-?\d[\d,]*(?:\.\d+)?", raw)
        if digits is None:
            continue
        try:
            value = float(digits.group(0).replace(",", ""))
        except ValueError:
            continue
        out.append((raw, value))
    return out


def _close(a: float, b: float, *, rel: float = 0.001, floor: float = 0.005) -> bool:
    """相对容差比较：吸收模型转述时的四舍五入。"""
    return abs(a - b) <= max(floor, rel * abs(b))


def _fallback_summary(sink: ExpertSink, structured: dict[str, Any]) -> str:
    """模型没给最终文本时的兜底：用工具轨迹拼一句诚实说明。"""
    if not sink.tool_trace:
        return "本次未能获取到可用数据，请稍后重试或补充更具体的需求。"
    return "已获取相关数据，但未能生成完整解读，请稍后重试。"


__all__ = [
    "ANSWERS_KEY",
    "DEFAULT_UNAVAILABLE",
    "DIGEST_KEY",
    "ExpertAssembly",
    "ExpertSink",
    "ExpertState",
    "SINK_KEY",
    "answers_of",
    "build_expert_graph",
    "default_assemble",
    "make_request_user_input_tool",
    "sink_of",
]
