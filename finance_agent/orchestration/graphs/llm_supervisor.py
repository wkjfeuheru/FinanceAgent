"""LLM Supervisor：以 ``create_agent`` 作路由决策引擎，转交到各业务领域。

本模块承载"**选哪些领域**"这一决策，取代了旧的确定性 ``scope_tasks`` 节点：
参考 ``langgraph_supervisor`` 的 handoff 形式（每个 agent 一个 ``transfer_to_*``
工具），但**不在工具里直接返回跨图 ``Command``**。

为什么不在工具里跳转：本仓库的图把领域任务表达为根图 ``Send`` 并行扇出，而
LangGraph 1.2 在"同一轮多个 handoff 工具各返回 ``Command(graph=PARENT,
goto=[Send(...)])``"时只会保留最后一个分支——并行扇出会被静默丢成一个领域。
因此改为：工具只作为**决策探针**（记录 LLM 选择并做候选集校验），由外层
``make_supervisor_node`` 统一解析选择结果、一次性构造全部 ``Send``。这样
"LLM 决定 + 根图并行扇出"两者都成立，且节点返回的 ``Command`` 必然产生分支，
不存在"无工具调用时静默结束"的悬空路径。

候选集约束（"混合权威"）：``classify`` 的意图推导给出**候选领域**作为硬上界，
LLM 只能在候选内取舍（可少选、不可新增）；若 LLM 未选出任何有效领域，则回退
为候选全集，保证绝不静默不执行。
"""

from __future__ import annotations

from typing import Annotated, Any, Callable, Sequence

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command, Send
from typing_extensions import TypedDict

from finance_agent.domains.contracts import BusinessDomain

#: handoff 工具名前缀：``transfer_to_<domain.value>``。与参考文件同形。
TRANSFER_PREFIX = "transfer_to_"


class SupervisorAgentState(TypedDict, total=False):
    """Supervisor 决策子图的状态：对话消息 + handoff 工具需要读取的轮次字段。

    这些轮次字段**必须**在此声明，``create_agent`` 子图才能从父图状态读到它们
    （``InjectedState`` 只能看到子图 schema 覆盖的键）。
    """

    messages: Annotated[list[Any], lambda left, right: (left or []) + (right or [])]
    #: 本轮允许选择的候选领域（``BusinessDomain.value``），由 classify 给出。
    candidate_domains: list[str]
    user_message: str


def create_domain_handoff_tool(
    *,
    domain: BusinessDomain,
    candidate_domains: Sequence[str],
    label: str,
    description: str | None = None,
):
    """构造单个领域的 handoff 探针工具。

    工具**只做决策记录**：校验候选集后返回一句确认/拒绝文本（不返回 ``Command``，
    真正的 ``Send`` 由 :func:`make_supervisor_node` 统一构造）。候选集外的领域被
    拒绝，因此 LLM 无法越界选择分类器没识别出的领域。
    """
    name = f"{TRANSFER_PREFIX}{domain.value}"
    description = description or f"把任务转交给{label}领域专家处理。"

    @tool(name, description=description)
    def handoff(
        task_description: Annotated[
            str,
            "交给该领域专家的自包含任务描述：补全指代（结合上下文还原标的/主题）、"
            "保留用户全部限定条件，不要回答问题。",
        ],
        state: Annotated[dict, InjectedState],
    ) -> str:
        allowed = state.get("candidate_domains") or list(candidate_domains)
        if domain.value not in allowed:
            return (
                f"拒绝：{domain.value} 不在本轮的候选领域 {list(allowed)} 内，"
                "请只在候选领域中选择。"
            )
        return f"已安排{label}领域任务：{task_description}"

    return handoff


def _transfer_tool_names(domains: Sequence[BusinessDomain]) -> dict[str, BusinessDomain]:
    return {f"{TRANSFER_PREFIX}{domain.value}": domain for domain in domains}


def _decision_messages(result: dict[str, Any]) -> list[Any]:
    messages = result.get("messages")
    return list(messages) if isinstance(messages, list) else []


def _selected_domains(
    messages: list[Any],
    domains: Sequence[BusinessDomain],
    *,
    accepted_only: bool,
) -> list[BusinessDomain]:
    """按 LLM 的 handoff 工具调用顺序还原所选领域（去重、保持稳定顺序）。

    ``accepted_only`` 为真时只保留工具确认接受的领域（候选集外被拒绝的调用不生效）。
    """
    names = _transfer_tool_names(domains)
    # 被拒绝的调用 id：工具返回以"拒绝"开头的 ToolMessage。
    rejected_ids = {
        str(getattr(message, "tool_call_id", ""))
        for message in messages
        if str(getattr(message, "content", "") or "").startswith("拒绝")
    }
    chosen: list[BusinessDomain] = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            domain = names.get(str(call.get("name", "")))
            if domain is None or domain in chosen:
                continue
            if accepted_only and str(call.get("id", "")) in rejected_ids:
                continue
            chosen.append(domain)
    return chosen


def _handoff_task_descriptions(
    messages: list[Any],
    domains: Sequence[BusinessDomain],
) -> dict[str, str]:
    """抽取 LLM 在 handoff 工具里给出的任务描述（``domain.value -> description``）。"""
    names = _transfer_tool_names(domains)
    descriptions: dict[str, str] = {}
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            domain = names.get(str(call.get("name", "")))
            if domain is None or domain.value in descriptions:
                continue
            args = call.get("args") or {}
            text = str(args.get("task_description") or "").strip()
            if text:
                descriptions[domain.value] = text
    return descriptions


def make_supervisor_node(
    model: BaseChatModel | None,
    *,
    domains: Sequence[BusinessDomain],
    domain_labels: dict[BusinessDomain, str],
    candidate_domains_of: Callable[[dict[str, Any]], list[BusinessDomain]],
    describe_tasks: Callable[[dict[str, Any], list[BusinessDomain]], tuple[dict[str, str], list[str]]],
    build_payload: Callable[[dict[str, Any], dict[str, Any], BusinessDomain], tuple[dict[str, Any], dict[str, Any]]],
    max_domains: int,
    should_dispatch: Callable[[dict[str, Any]], bool] | None = None,
    progress: Callable[[str, str], None] | None = None,
) -> Callable[[dict[str, Any]], Command]:
    """构造 Supervisor 节点工厂。

    节点流程：读取候选领域 → 让 ``create_agent`` 决策（handoff 工具）→ 解析选择 →
    为每个领域构造自包含任务描述与 ``Send`` 载荷 → 返回 ``Command(goto=[Send(...)])``。

    ``should_dispatch`` 为停止/截止的统一检查点：返回 False 时不再下发任何领域任务，
    直接转 ``converge``（由汇合节点登记降级原因并保留已完成结论），从而保持"评估
    Dispatch 前先看停止标记"的既有语义。

    依赖注入点（``candidate_domains_of`` / ``describe_tasks`` / ``build_payload``）
    把"图状态的具体形状"留在 supervisor.py，本模块只负责"LLM 决策 → 交转"机制。
    """
    from finance_agent.infrastructure.llm.factory import get_supervisor_model

    tools = [
        create_domain_handoff_tool(
            domain=domain,
            candidate_domains=[d.value for d in domains],
            label=domain_labels.get(domain, domain.value),
        )
        for domain in domains
    ]

    def _resolve_model() -> BaseChatModel:
        return model if model is not None else get_supervisor_model()

    _agent_cache: dict[str, Any] = {}

    def _agent() -> Any:
        # 惰性构造：``legacy`` 模式下本节点不可达，不应为它构建（并校验）模型。
        if "agent" not in _agent_cache:
            _agent_cache["agent"] = create_agent(
                _resolve_model(),
                tools=list(tools),
                system_prompt=(
                    "你是投顾系统的调度器，只负责把一个用户请求分派给最合适的业务领域专家，"
                    "不回答问题、不生成结论。\n"
                    "规则：\n"
                    "1. 只能从提示给出的**候选领域**中选择，不得选择候选之外的领域；\n"
                    "2. 一个请求可能同时涉及多个领域，此时在同一次回复里并行调用多个 transfer 工具；\n"
                    "3. 每个 transfer 工具都要给出该领域的自包含任务描述（补全指代、保留全部限定条件）；\n"
                    "4. 候选领域里只要有与请求相关的，就必须至少选择一个。"
                ),
                state_schema=SupervisorAgentState,
                name="supervisor",
            )
        return _agent_cache["agent"]

    def supervisor_node(state: dict[str, Any]) -> Command:
        candidate = list(candidate_domains_of(state))[: max(1, int(max_domains))]
        if not candidate:
            # 无候选（不应发生：route 只在本模式进本节点）：直接汇合，显式收尾。
            return Command(goto="converge")

        if progress is not None:
            try:
                # 沿用前端 SSE 契约里的 "scope" 阶段名（拆解为各领域任务）。
                progress("scope", "正在判定业务领域")
            except Exception:  # noqa: BLE001 - 进度只影响观感
                pass

        if should_dispatch is not None:
            try:
                dispatch = bool(should_dispatch(state))
            except Exception:  # noqa: BLE001 - 停止查询失败不得影响本轮
                dispatch = True
            if not dispatch:
                # 已请求停止/超出整轮截止：不启动任何领域执行，交汇合节点登记降级。
                return Command(goto="converge")

        message = str(state.get("user_message", "") or "")
        prompt = (
            f"用户请求：{message}\n"
            f"候选领域（只能在这里面选）：{', '.join(d.value for d in candidate)}\n"
            "请调用相应领域的一个或多个 transfer 工具。"
        )
        result = _agent().invoke(
            {
                "messages": [HumanMessage(content=prompt)],
                "candidate_domains": [d.value for d in candidate],
                "user_message": message,
            }
        )
        # 停止/截止的**下发前**再检查一次：LLM 决策本身要花数秒，期间用户可能按下
        # 停止。若不再检查，任务会在停止后仍被下发，专家产出的 partial 摘要会覆盖
        # 「已停止本次生成」兜底文案（run_status 仍为 cancelled，但正文不对）。
        if should_dispatch is not None:
            try:
                dispatch = bool(should_dispatch(state))
            except Exception:  # noqa: BLE001 - 停止查询失败不得影响本轮
                dispatch = True
            if not dispatch:
                return Command(goto="converge")

        messages = _decision_messages(result)
        chosen = _selected_domains(messages, candidate, accepted_only=True)
        if not chosen:
            # LLM 未选出任何有效领域：回退候选全集，绝不静默不执行。
            chosen = list(candidate)

        llm_descriptions = _handoff_task_descriptions(messages, chosen)
        descriptions, _notes = describe_tasks(state, chosen)
        # 确定性改写（task_rewrite + 实体保真校验）**权威**：LLM 的职责是选域，不是
        # 改写任务描述。仅当确定性改写退化为原句（无改写器且无子请求）时，才采用
        # LLM handoff 里更具体的描述作为补充。
        raw_message = str(state.get("user_message", "") or "").strip()
        merged: dict[str, str] = {}
        for domain in chosen:
            described = str(descriptions.get(domain.value, "") or "").strip()
            if described and described != raw_message:
                merged[domain.value] = described
            else:
                merged[domain.value] = str(llm_descriptions.get(domain.value, "") or "").strip() or described

        sends: list[Send] = []
        expert_tasks: dict[str, dict[str, Any]] = {}
        for domain in chosen:
            description = str(merged.get(domain.value, "") or "")
            task_payload, worker_payload = build_payload(state, {"goal": description}, domain)
            expert_tasks[str(task_payload["task_id"])] = task_payload
            if progress is not None:
                try:
                    progress(f"domain:{domain.value}", f"正在分析{domain_labels.get(domain, domain.value)}")
                except Exception:  # noqa: BLE001
                    pass
            sends.append(Send("domain_worker", worker_payload))

        return Command(goto=sends, update={"run": {"expert_tasks": expert_tasks}})

    return supervisor_node


__all__ = [
    "TRANSFER_PREFIX",
    "SupervisorAgentState",
    "create_domain_handoff_tool",
    "make_supervisor_node",
]
