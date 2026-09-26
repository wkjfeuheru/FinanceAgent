"""Supervisor 工作流：领域分类、跨领域扇出、缺参追问与响应投影。

本模块是该工作流的**唯一宿主**：状态定义、节点工厂、边装配与响应投影同源。

拓扑（``plan`` 节点内嵌子图与 ``single_domain`` 分支均已删除）：

```text
START → classify ─┬─ conversation ─┐
                  ├─ clarify ──────┤
                  └─ scope_tasks ──┴─→ [Send(domain_worker × N)] → converge
                                                                   ├─ ask → [Send(domain_worker × M)] → converge ⟲
                                                                   ├─ synthesize → compliance
                                                                   └─ compliance → END
```

设计要点：

- **单领域与多领域是同一条路径**：``scope_tasks`` 为每个业务领域构造一条自包含任务
  描述，再由 ``Send`` 并行扇出。单领域只是扇出数为 1，因此截止时间、停止语义、
  崩溃恢复三者对两种场景完全一致。
- **扇出即检查点**：``Send`` 的每个领域任务都是根图的独立 superstep，随根
  checkpointer 持久化。进程在第二个领域处崩溃时，resume 只重跑未完成的领域
  （旧做法是在节点函数里 ``invoke`` 一个未挂 checkpointer 的子图，任何异常都要
  整轮重跑）。
- **每轮派生状态收在单个 ``run`` 键下**，由 ``classify`` 用 ``Overwrite`` 整键重置。
  跨轮残留从"新增键必须记得登记"变成结构上不可能（历史上 ``trusted_content`` 与
  ``param_blocked`` 都曾静默泄漏到下一轮）。
- **告警分两级**：``warnings`` 只披露（提示类），``degradations`` 会把
  ``run_status`` 从 completed 翻成 partial/failed/cancelled。
- Supervisor 不承载任何工具实现；取数与计算由各领域 ReAct 专家子图完成。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Annotated, Any, Callable

from langgraph.errors import NodeError
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Overwrite, RetryPolicy, Send, interrupt
from typing_extensions import TypedDict

from finance_agent.shared.contracts import RunStatus
from finance_agent.domains.contracts import DOMAIN_ORDER
from finance_agent.orchestration.budgets import RunBudgets
from finance_agent.orchestration.contracts import (
    DOMAIN_STATUS_TO_RUN_STATUS,
    RUN_CANCELLED_WARNING,
    TURN_DEADLINE_WARNING,
    BusinessDomain,
    DomainOutcome,
    DomainTaskContext,
    PlanTask,
    RoutingDecision,
)
# 意图 → 业务领域沿用分类器的注册表（唯一事实源），此处不再硬编码一份：
# 两份映射曾发生漂移（portfolio_analysis 只在分类器登记、路由表却缺席）。
from finance_agent.orchestration.routing.intent import _INTENT_TO_DOMAIN
from finance_agent.orchestration.needs_input import (
    apply_answers,
    build_form,
    domain_label,
    is_cancel,
    known_field_names,
    merge_forms,
)
from finance_agent.orchestration.routing.task_rewrite import task_to_payload
from finance_agent.orchestration.runtime.state import (
    merge_dict,
    replace_keys,
    routing_of,
    run_of,
    task_results_of,
)

logger = logging.getLogger(__name__)

# casual_chat 在注册表中映射为 None，不属于任何业务领域。

# 领域稳定排序，保证多领域路由结果确定。顺序的唯一定义在
# ``domains/contracts.py::DOMAIN_ORDER``（与领域注册表同源），此处直接复用，
# 避免新增领域时漏改本文件导致 ``.index`` 抛 ValueError。
_DOMAIN_ORDER = DOMAIN_ORDER

CLASSIFICATION_FAILED_RESPONSE = "暂时无法理解您的请求，请转接人工或尝试换一种说法。"
CLARIFICATION_FALLBACK = "请补充更具体的信息，例如要分析的标的、市场范围或产品类型。"
CANCELLED_RESPONSE = "已停止本次生成。"
#: 用户在缺参追问弹窗上选择"取消"时的收尾文案（与停止生成区分）。
PARAM_CANCELLED_RESPONSE = "已取消本次请求。您可以随时重新提问。"
#: 整轮截止时仍有领域未完成/未开始的兜底正文（已完成领域的结论仍会拼接在下发）。
DEADLINE_FALLBACK_RESPONSE = "本次请求处理超时，以下是已完成部分的分析。"


class RunState(TypedDict, total=False):
    """单轮（run-scoped）派生状态：整键覆盖，跨轮不残留。

    由 ``classify`` 用 ``Overwrite`` 写入一份全新快照，其余节点只写自己负责的
    少数键（``replace_keys`` 做顶层浅覆盖）。新增字段因此**不可能**泄漏到下一轮。
    """

    routing: dict[str, Any]
    #: 提示类告警：只披露，不改变 run_status。
    warnings: list[str]
    #: 降级类告警：会把 run_status 从 completed 翻成 partial/failed/cancelled。
    degradations: list[str]
    final_response: str
    run_status: str
    compliance: dict[str, Any]
    #: 下发给各专家的任务描述（task_id → 载荷），缺参重跑时据此重建上下文。
    expert_tasks: dict[str, dict[str, Any]]
    #: 挂起追问的表单载荷；非空且未 blocked 表示"待用户补充"。
    param_missing: dict[str, Any]
    param_blocked: bool
    param_cancelled: bool
    #: 已弹窗次数（确定性计数，达上限后不再追问）。
    clarify_rounds: int
    #: 本轮弹窗补填的答案（重跑任务据此继续）。
    rerun_answers: dict[str, Any]
    #: 本轮命中的受信语料原文（FAQ），合规出口据此做受信判定。
    trusted_sources: list[str]
    #: 该轮回答是否全部来自受信来源；为真时合规只审计、不改写。
    trusted_content: bool
    #: 整轮墙钟截止（``time.monotonic()`` 基准）；缺省表示不限。
    deadline_monotonic: float
    halted: bool


class SupervisorState(TypedDict, total=False):
    """根图状态：轮次输入 + 扇出通道 + 单键承载的每轮派生状态。"""

    # ── 调用方注入的轮次输入（每轮由 base_input 覆盖，无需重置）──
    user_message: str
    history: str
    customer_id: str
    conversation_id: str
    thread_id: str
    run_id: str
    user_profile: dict[str, Any]
    # ── 扇出写入通道：并发领域任务各写自己的 task_id，必须用 reducer 合并 ──
    task_results: Annotated[dict[str, dict[str, Any]], merge_dict]
    # ── 其余每轮派生状态：单键承载，classify 整键覆盖 ──
    run: Annotated[RunState, replace_keys]


def classify_domains(
    message: str,
    context_summary: str = "",
    *,
    classifier: Any,
) -> RoutingDecision:
    """把现有分类器输出映射为业务领域路由决策。"""
    classified = classifier.classify_intents(message, context_summary)

    error = classified.get("classification_error") or {}
    if error:
        return RoutingDecision(
            domains=[],
            execution_mode="clarify",
            clarification=CLASSIFICATION_FAILED_RESPONSE,
            error_code=str(error.get("error_code") or "classification_error"),
        )

    intents = classified.get("intents", []) or []
    domains: list[BusinessDomain] = []
    domain_queries: dict[str, str] = {}
    for item in intents:
        domain = _INTENT_TO_DOMAIN.get(str(item.get("intent", "")))
        if domain is None:
            continue
        if domain not in domains:
            domains.append(domain)
        # 记录该领域的子请求：复合请求下每个领域只处理属于自己的那部分，
        # 避免把整句（含其它领域实体）丢给单一领域而解析失败。
        query = str(item.get("query", "")).strip()
        if query and not domain_queries.get(domain.value):
            domain_queries[domain.value] = query
    domains.sort(key=_DOMAIN_ORDER.index)
    uncertain = classified.get("uncertain_intents", []) or []

    if not domains:
        if uncertain:
            return RoutingDecision(
                domains=[],
                execution_mode="clarify",
                clarification=CLARIFICATION_FALLBACK,
            )
        return RoutingDecision(domains=[], execution_mode="conversation")

    # 低置信度意图不进入执行，但**不得静默丢弃**：把被跳过的子请求与所需澄清
    # 作为提示带回，让用户知道哪一部分没执行、需要补充什么。
    dropped_notes: list[str] = []
    for item in uncertain:
        query = str(item.get("query", "")).strip()
        ask = str(item.get("clarification_question", "")).strip()
        if query:
            note = f"「{query}」未执行：{ask}" if ask else f"「{query}」信息不足，请补充更具体的需求。"
        else:
            note = ask or CLARIFICATION_FALLBACK
        if note not in dropped_notes:
            dropped_notes.append(note)

    # 单领域与多领域走同一条路径：扇出数量不同，执行语义完全相同。
    return RoutingDecision(
        domains=domains,
        execution_mode="domain_workflow",
        domain_queries=domain_queries,
        warnings=dropped_notes,
    )


@dataclass
class SupervisorDependencies:
    """Supervisor Graph 的可注入执行依赖。"""

    classifier: Any
    conversation_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    domain_runner: Callable[[DomainTaskContext], DomainOutcome] | None = None
    #: 协作式停止查询：返回 True 时不再下发新的领域任务，专家也会在模型轮次
    #: 边界自行退出（已完成结果保留）。
    should_stop: Callable[[], bool] | None = None
    #: 任务改写器注入点（签名 ``(state, domains) -> {domain.value: 描述}``）。
    #: None 时使用 ``task_rewrite.build_llm_rewriter(get_intent_model())``。
    rewriter: Any = None
    #: 多领域汇合节点的模型注入点（None 时用 ``get_model_for_agent("synthesis")``）。
    synthesis_model: Any = None
    #: 进度回调注入点（``(stage, message) -> None``）。None 时节点不发进度。
    #: 图内节点必须是纯函数式依赖注入，不能反向引用宿主对象。
    progress: Callable[[str, str], None] | None = None
    #: 受校验运行预算（``RunBudgets``）；None 时取 ``RunBudgets.from_config()``。
    budgets: RunBudgets | None = None
    #: 合规语义校验器（只输出违规码）。None 时只做确定性检查；调用失败必须
    #: fail-closed（由 compliance 节点的错误处理器拦截）。
    semantic_check: Callable[[str], list[str]] | None = None
    #: 句级受信判定用的 embedding 提供者（``embed_query(text)``）。None 时不放行
    #: 任何受信豁免。
    trust_embeddings: Any = None
    #: 受信判定相似度阈值；None 时用合规模块的默认值。
    trust_threshold: float | None = None


# ── 状态访问helpers ───────────────────────────────────────────────────
# 读取口径（``run_of`` / ``routing_of`` / ``task_results_of``）定义在
# ``runtime/state.py``，与 ``routing/task_rewrite`` 共用一份实现。
# 本模块 re-export，保持既有导入点。


def _emit(progress: Callable[[str, str], None] | None, stage: str, message: str) -> None:
    if progress is None:
        return
    try:
        progress(stage, message)
    except Exception:  # noqa: BLE001 - 进度只影响观感，绝不影响业务结果
        logger.warning("progress_emit_failed stage=%s", stage, exc_info=True)


def task_id_of(run_id: str, domain: BusinessDomain) -> str:
    """领域任务标识：``{run_id}:{domain}``（单/多领域统一，不再有两套命名）。"""
    return f"{run_id}:{domain.value}"


def _status_from_outcome(outcome: DomainOutcome) -> str:
    return DOMAIN_STATUS_TO_RUN_STATUS.get(outcome.status, RunStatus.PARTIAL.value)


def _needs_input_outcomes(outcomes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        task_id: value
        for task_id, value in (outcomes or {}).items()
        if isinstance(value, dict) and value.get("status") == "needs_input"
    }


def _per_domain_requests(outcomes: dict[str, Any]) -> list[tuple[BusinessDomain, tuple[str, ...]]]:
    """从断点结论里还原 (领域, 缺失字段) 列表，用于重建合并表单。"""
    requests: list[tuple[BusinessDomain, tuple[str, ...]]] = []
    for value in outcomes.values():
        try:
            domain = BusinessDomain(str(value.get("domain")))
        except ValueError:
            continue
        pending = (value.get("structured_data") or {}).get("pending_input") or {}
        names = _missing_names(pending)
        if names:
            requests.append((domain, names))
    return requests


def _missing_names(pending: dict[str, Any]) -> tuple[str, ...]:
    """``["{domain}:{field}", ...]`` → 裸字段名元组。"""
    return tuple(
        str(entry).split(":", 1)[1]
        for entry in (pending.get("missing") or [])
        if isinstance(entry, str) and ":" in entry
    )


def _answers_for_domain(answers: dict[str, Any], domain: BusinessDomain) -> dict[str, Any]:
    """只保留该领域登记的字段（防止跨域答案串入）。"""
    known = set(known_field_names(domain))
    return {key: value for key, value in answers.items() if key in known}


def _outcome_summaries(outcomes: dict[str, Any]) -> list[str]:
    return [
        str((value or {}).get("summary") or "").strip()
        for value in (outcomes or {}).values()
        if isinstance(value, dict) and str((value or {}).get("summary") or "").strip()
    ]


#: 由**运行级**原因码构成的领域 limitation：它们描述的是整轮被停止/截断，
#: 因此必须升级为 degradation（会把 run_status 从 completed 翻成 cancelled/partial）。
#: 其余 limitation（步数触顶、数字未落地、单域降级）只做披露：它们已经通过
#: 该领域的结论状态让整轮变成 partial，不需要再用告警二次降级。
_RUN_LEVEL_REASONS = frozenset({RUN_CANCELLED_WARNING, TURN_DEADLINE_WARNING})


def _parse_outcomes(outcomes: dict[str, Any]) -> list[DomainOutcome]:
    parsed: list[DomainOutcome] = []
    for value in (outcomes or {}).values():
        if not isinstance(value, dict):
            continue
        try:
            parsed.append(DomainOutcome.model_validate(value))
        except Exception:  # noqa: BLE001 - 非法结论不参与状态归约
            continue
    return parsed


def collect_outcome_notes(outcomes: dict[str, Any]) -> tuple[list[str], list[str]]:
    """把各领域结论的 limitations 拆成 ``(提示级, 降级级)`` 两份（去重保序）。"""
    warnings: list[str] = []
    degradations: list[str] = []
    for value in (outcomes or {}).values():
        if not isinstance(value, dict):
            continue
        for item in value.get("limitations") or []:
            code = str(item)
            if not code:
                continue
            target = degradations if code in _RUN_LEVEL_REASONS else warnings
            _append(target, code)
    return warnings, degradations


def halt_fallback_response(reason: str) -> str:
    """停止/截止时的兜底正文（按原因码区分，避免"停止"被说成"超时"）。"""
    if reason == RUN_CANCELLED_WARNING:
        return CANCELLED_RESPONSE
    return DEADLINE_FALLBACK_RESPONSE


def reduce_run_status(
    outcomes: list[DomainOutcome],
    degradations: list[str],
) -> str:
    """由领域结论集合与降级告警归约为本轮运行状态（纯函数）。

    优先级链（高 → 低，修改任一层都会影响前端"停止"与"出错"的区分）：

    1. **结论集合**：存在 processing → processing；全部 completed → completed；
       全部 failed → failed；其余（含空集合、混合）→ partial；
    2. **用户主动停止**：``RUN_CANCELLED_WARNING`` 出现即覆盖为 cancelled ——
       必须高于结论集合，否则前端无法区分"停止"与"出错"；
    3. **降级告警**：存在任何**降级级**告警时，completed 降级为 partial。
       提示级告警（``warnings``）不在此列：``task_rewrite_dropped_entities``
       这类提示过去会把正常回答翻成"部分完成"，属于误伤。
    """
    statuses = {_status_from_outcome(outcome) for outcome in outcomes}
    if "processing" in statuses:
        run_status = "processing"
    elif statuses == {RunStatus.COMPLETED.value}:
        run_status = RunStatus.COMPLETED.value
    elif statuses == {RunStatus.FAILED.value}:
        run_status = RunStatus.FAILED.value
    else:
        run_status = RunStatus.PARTIAL.value

    if RUN_CANCELLED_WARNING in degradations:
        run_status = RunStatus.CANCELLED.value
    elif degradations and run_status == RunStatus.COMPLETED.value:
        run_status = RunStatus.PARTIAL.value
    return run_status


# ── 节点工厂 ──────────────────────────────────────────────────────────


def make_classify_node(
    classifier: Any,
    *,
    turn_deadline: float = 0.0,
    progress: Callable[[str, str], None] | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """分类节点工厂：分类 + 本轮派生状态的**整键重置**。

    ``run`` 用 ``Overwrite`` 写入一份全新快照，``task_results`` 同样被重置（它是
    带 reducer 的扇出通道，写 ``{}`` 会被当成"无更新"，必须用 ``Overwrite``）。
    这样"每轮从干净状态开始"不再依赖调用方或后来者记得登记新键。
    """

    def classify_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(progress, "routing", "正在识别业务领域")
        routing = classify_domains(
            str(state.get("user_message", "")),
            str(state.get("history", "") or ""),
            classifier=classifier,
        )
        fresh: RunState = {
            "routing": routing.model_dump(mode="json"),
            "warnings": list(routing.warnings or []),
            "degradations": [],
            "final_response": "",
            "run_status": "",
            "compliance": {},
            "expert_tasks": {},
            "param_missing": {},
            "param_blocked": False,
            "param_cancelled": False,
            "clarify_rounds": 0,
            "rerun_answers": {},
            "trusted_sources": [],
            "trusted_content": False,
            "halted": False,
        }
        if turn_deadline > 0:
            fresh["deadline_monotonic"] = time.monotonic() + float(turn_deadline)
        return {"run": Overwrite(fresh), "task_results": Overwrite({})}

    return classify_node


def make_conversation_node(
    conversation_runner: Callable[[dict[str, Any]], dict[str, Any]] | None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """会话节点工厂：casual chat / FAQ 的受限 ReAct 执行器。"""

    def conversation_node(state: dict[str, Any]) -> dict[str, Any]:
        if conversation_runner is None:
            return {
                "run": {
                    "final_response": "会话能力暂不可用，请稍后重试。",
                    "run_status": "failed",
                    "degradations": ["conversation_runner_unavailable"],
                }
            }
        result = conversation_runner(dict(state))
        return {
            "run": {
                "final_response": result.get("final_response", ""),
                "run_status": "completed" if result.get("status") == "success" else "partial",
                "warnings": list(result.get("warnings", []) or []),
                # 引用了 FAQ 知识库原文时，内容属于受信语料；合规出口据此做
                # 逐句受信判定（只对确实有原文支撑的句子审计豁免）。
                "trusted_content": bool(result.get("cited_faq", False)),
                "trusted_sources": list(result.get("cited_sources", []) or []),
            }
        }

    return conversation_node


def clarify_node(state: dict[str, Any]) -> dict[str, Any]:
    """澄清分支：显式转述澄清问题，分类协议错误显式失败。"""
    routing = routing_of(state)
    if routing.get("error_code"):
        return {
            "run": {
                "final_response": str(
                    routing.get("clarification") or CLASSIFICATION_FAILED_RESPONSE
                ),
                "run_status": "failed",
                "degradations": [f"classification_error:{routing['error_code']}"],
            }
        }
    return {
        "run": {
            "final_response": str(routing.get("clarification") or CLARIFICATION_FALLBACK),
            "run_status": "completed",
        }
    }


def _task_descriptions(
    state: dict[str, Any],
    domains: list[BusinessDomain],
    rewriter: Callable[[dict[str, Any], list[BusinessDomain]], dict[str, str]] | None,
) -> tuple[dict[str, str], list[str]]:
    """各领域任务的自包含描述 + 改写告警。

    优先级：改写器输出 → 分类器子请求原文 → 整句原话。实体丢失时
    ``resolve_description`` 会回退到子请求原文并给出告警。
    """
    from finance_agent.orchestration.routing.task_rewrite import (
        resolve_description,
        scoped_queries,
    )

    rewritten: dict[str, str] = {}
    if rewriter is not None:
        try:
            rewritten = dict(rewriter(dict(state), domains) or {})
        except Exception:  # noqa: BLE001 - 改写失败回退子请求原文
            rewritten = {}
    queries = scoped_queries(state, domains)
    message = str(state.get("user_message", "") or "")
    out: dict[str, str] = {}
    notes: list[str] = []
    for domain in domains:
        description, missing = resolve_description(
            domain=domain,
            message=message,
            rewritten=rewritten.get(domain.value, ""),
            fallback=queries.get(domain.value, ""),
        )
        out[domain.value] = description
        notes.extend(missing)
    return out, notes


def make_scope_tasks_node(
    rewriter: Callable[[dict[str, Any], list[BusinessDomain]], dict[str, str]] | None,
    *,
    max_domains: int,
    progress: Callable[[str, str], None] | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """任务铺开节点：为每个业务领域构造一条自包含任务描述。

    这里取代了旧的 LLM Planner：Planner 的唯一产出（每域一条自包含描述）与
    ``task_rewrite`` 的改写器完全重叠，而后者不做计划、不引入一次额外的模型调用
    与一层"规范化"（旧 ``_normalize_plan`` 会把依赖抹平，使 replan 永不可达）。
    """

    def scope_tasks_node(state: dict[str, Any]) -> dict[str, Any]:
        _emit(progress, "scope", "正在拆解为各领域任务")
        routing = routing_of(state)
        domains = [BusinessDomain(value) for value in routing.get("domains", [])]
        degradations: list[str] = []
        if len(domains) > max_domains:
            degradations.append(f"domains_truncated:{len(domains)}>{max_domains}")
            domains = domains[:max_domains]

        descriptions, notes = _task_descriptions(state, domains, rewriter)
        run_id = str(state.get("run_id", ""))
        expert_tasks: dict[str, dict[str, Any]] = {}
        for domain in domains:
            description = descriptions.get(domain.value, "")
            task = PlanTask(
                task_id=task_id_of(run_id, domain),
                domain=domain,
                goal=description,
                instruction=description,
                expected_output="domain_outcome",
            )
            expert_tasks[task.task_id] = task_to_payload(task)
            _emit(progress, f"domain:{domain.value}", f"正在分析{_domain_label(domain)}")

        updates: dict[str, Any] = {"expert_tasks": expert_tasks}
        if notes:
            updates["warnings"] = notes
        if degradations:
            updates["degradations"] = degradations
        return {"run": updates}

    return scope_tasks_node


def _domain_label(domain: BusinessDomain) -> str:
    return domain_label(domain)


def make_domain_worker(
    domain_runner: Callable[[DomainTaskContext], DomainOutcome] | None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """``Send`` 目标节点工厂：接收任务载荷（非图状态），执行单个领域任务。

    同一个节点承载首轮执行与缺参重跑：载荷里的 ``answers`` 为空就是首轮。
    每个任务是独立 superstep，完成即随根 checkpoint 持久化——这正是"第 2 个领域
    崩溃后只重跑未完成领域"的实现基础。
    """

    def domain_worker(payload: dict[str, Any]) -> dict[str, Any]:
        domain = BusinessDomain(payload["domain"])
        task = PlanTask(
            task_id=payload["task_id"],
            domain=domain,
            goal=payload["goal"],
            instruction=payload["instruction"],
            expected_output=payload["expected_output"],
        )
        if domain_runner is None:
            outcome = DomainOutcome(
                task_id=task.task_id,
                domain=domain,
                status="failed",
                summary="",
                limitations=[f"domain_runner_unavailable:{domain.value}"],
            )
            return {"task_results": {outcome.task_id: outcome.model_dump(mode="json")}}

        context = DomainTaskContext(
            task=task,
            thread_id=payload["thread_id"],
            customer_id=payload["customer_id"],
            conversation_id=payload["conversation_id"],
            user_message=payload["user_message"],
            run_id=str(payload.get("run_id", "")),
            user_profile=dict(payload.get("user_profile", {}) or {}),
            turn_deadline_monotonic=float(payload.get("turn_deadline_monotonic") or 0.0),
            clarification_answers=dict(payload.get("answers", {}) or {}),
        )
        try:
            outcome = domain_runner(context)
        except Exception:  # noqa: BLE001 - 单任务失败不阻断整轮
            logger.exception("domain_worker_failed domain=%s", domain.value)
            outcome = DomainOutcome(
                task_id=task.task_id,
                domain=domain,
                status="failed",
                summary="",
                limitations=[f"domain_runner_failed:{domain.value}"],
            )
        return {"task_results": {outcome.task_id: outcome.model_dump(mode="json")}}

    return domain_worker


def _worker_payload(
    state: dict[str, Any],
    task_payload: dict[str, Any],
    domain: BusinessDomain,
    *,
    answers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "task_id": str(task_payload.get("task_id") or task_id_of(str(state.get("run_id", "")), domain)),
        "domain": domain.value,
        "goal": str(task_payload.get("goal") or ""),
        "instruction": str(task_payload.get("instruction") or ""),
        "expected_output": str(task_payload.get("expected_output") or "domain_outcome"),
        "thread_id": str(state.get("thread_id", "")),
        "run_id": str(state.get("run_id", "")),
        "customer_id": str(state.get("customer_id", "")),
        "conversation_id": str(state.get("conversation_id", "")),
        "user_message": str(state.get("user_message", "")),
        "user_profile": dict(state.get("user_profile", {}) or {}),
        "answers": dict(answers or {}),
        # 整轮截止随任务下发：宿主据此在专家内部构造停止/截止查询。
        "turn_deadline_monotonic": float(run_of(state).get("deadline_monotonic") or 0.0),
    }


def _halt_reason(state: dict[str, Any], run: RunState, should_stop: Callable[[], bool] | None) -> str:
    """本轮是否已被停止或超出墙钟上限；返回降级原因码（空串表示未触发）。"""
    if should_stop is not None:
        try:
            if should_stop():
                return RUN_CANCELLED_WARNING
        except Exception:  # noqa: BLE001 - 停止查询失败不得影响本轮
            logger.warning("should_stop_check_failed", exc_info=True)
    deadline = run.get("deadline_monotonic")
    if deadline and time.monotonic() >= float(deadline):
        return TURN_DEADLINE_WARNING
    return ""


def make_converge_node(
    *,
    allow_interrupt: bool,
    clarify_limit: int,
    should_stop: Callable[[], bool] | None = None,
    progress: Callable[[str, str], None] | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """汇合/追问判定节点。

    这是**唯一**决定"是否再向用户追问"的位置，也是停止与截止的统一检查点：

    - 没有缺参结论 → 清空 ``param_missing``（否则上一轮的挂起表单会残留）并交回路由；
    - 有缺参结论且还有弹窗预算 → 记一次计数并转到 ``ask``（``interrupt`` 宿主）；
    - 到达弹窗上限、或本轮已停止/超时、或无 checkpointer → 不再追问，显式收尾；
    - 计数在**本节点**写入（``ask`` 中断时本节点的更新已提交；``interrupt`` 所在
      节点重跑不会重复计数）。
    """

    def converge_node(state: dict[str, Any]) -> dict[str, Any]:
        run = run_of(state)
        outcomes = task_results_of(state)
        halt = _halt_reason(state, run, should_stop)
        note_warnings, note_degradations = collect_outcome_notes(outcomes)
        converged = [*list(run.get("warnings") or []), *note_warnings]
        degraded = [*list(run.get("degradations") or []), *note_degradations]
        if halt:
            _append(degraded, halt)

        updates: dict[str, Any] = {"warnings": converged, "degradations": degraded}
        if halt:
            updates["halted"] = True

        # 领域结论是"本轮答复正文与运行状态"的事实源：正文由各域 summary 拼接
        # （多领域时随后由 ``synthesize`` 组织表述覆盖），状态由结论集合 + 降级
        # 告警归约。会话/澄清分支没有领域结论，各自写入的状态不被覆盖。
        parsed = _parse_outcomes(outcomes)
        if parsed or halt:
            updates["run_status"] = reduce_run_status(parsed, degraded)
        summaries = _outcome_summaries(outcomes)
        if summaries:
            updates["final_response"] = "\n\n".join(summaries)
        elif halt and not str(run.get("final_response") or "").strip():
            updates["final_response"] = halt_fallback_response(halt)

        pending = _needs_input_outcomes(outcomes)
        if not pending:
            updates["param_missing"] = {}
            updates["param_blocked"] = False
            return {"run": updates}

        requests = _per_domain_requests(pending)
        form = merge_forms([build_form(requests)]) if requests else None
        rounds = int(run.get("clarify_rounds", 0) or 0)
        question = str((form or {}).get("question") or "请补充必要参数。")

        if form is None:
            # 结论标记缺参但表单不可重建（异常态）：如实降级，不静默继续。
            updates.update(
                {
                    "final_response": "缺少必要参数，请补充后重试。",
                    "param_blocked": True,
                    "param_missing": {},
                }
            )
            # 停止/截止优先：不得把 cancelled 覆写成 partial。
            updates.setdefault("run_status", RunStatus.PARTIAL.value)
            _append(updates["degradations"], "needs_input_unresolved")
            return {"run": updates}

        if halt or rounds >= clarify_limit or not allow_interrupt:
            # 不再追问：把问题作为回复返回，保留已完成领域的结论。
            updates.update(
                {
                    "final_response": question,
                    "param_blocked": True,
                    "param_missing": form,
                }
            )
            updates.setdefault("run_status", RunStatus.PARTIAL.value)
            updates["warnings"] = [
                *updates["warnings"],
                *[f"param_missing:{entry}" for entry in (form.get("missing") or [])],
            ]
            _append(updates["degradations"], "needs_input_unresolved")
            return {"run": updates}

        # 记一次弹窗并挂起（计数必须在本节点提交）。
        updates.update({"param_missing": form, "param_blocked": False, "clarify_rounds": rounds + 1})
        updates["warnings"] = [
            *updates["warnings"],
            *[f"param_missing:{entry}" for entry in (form.get("missing") or [])],
        ]
        _emit(progress, "clarify", "需要你补充必要参数")
        return {"run": updates}

    return converge_node


def _append(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def make_ask_node(
    *,
    turn_deadline: float = 0.0,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """追问节点：``interrupt`` 的唯一宿主。

    节点内不得用 ``try/except`` 包住 ``interrupt``（重跑语义要求异常不被吞掉）。
    恢复时本节点从头重跑，``interrupt`` 返回用户提交的答案，随后在此处判定：
    取消 → 收尾；没拿到有效答案 → 单次收尾（不重问）；否则写答案并交给条件边扇出重跑。

    拿到答案后**重置整轮截止**：``deadline_monotonic`` 是从上一轮开始算的墙钟，
    用户在弹窗上停留的时间（可能几分钟）不是计算预算的一部分；不重置的话，任何
    稍慢的补充都会让重跑一开始就"已经超时"。
    """

    def ask_node(state: dict[str, Any]) -> dict[str, Any]:
        run = run_of(state)
        form = dict(run.get("param_missing") or {})
        answer = interrupt(form)
        updates: dict[str, Any] = {}
        if is_cancel(answer):
            updates.update(
                {
                    "final_response": PARAM_CANCELLED_RESPONSE,
                    "run_status": RunStatus.COMPLETED.value,
                    "param_blocked": True,
                    "param_cancelled": True,
                    "param_missing": {},
                }
            )
            updates["warnings"] = [*list(run.get("warnings") or []), "param_cancelled_by_user"]
            return {"run": updates}

        pending = _needs_input_outcomes(task_results_of(state))
        domains: list[BusinessDomain] = []
        for value in pending.values():
            try:
                domain = BusinessDomain(str(value.get("domain")))
            except ValueError:
                continue
            if domain not in domains:
                domains.append(domain)
        filled = apply_answers(answer, domains=domains)
        if not filled:
            # 没拿到有效答案：单次询问不重问，显式收尾（携带原问题）。
            updates.update(
                {
                    "final_response": str(form.get("question") or "请补充必要参数。"),
                    "run_status": RunStatus.PARTIAL.value,
                    "param_blocked": True,
                    "param_missing": form,
                }
            )
            updates["warnings"] = [*list(run.get("warnings") or []), "param_answers_empty"]
            return {"run": updates}

        rerun: dict[str, Any] = {"rerun_answers": filled, "param_missing": {}}
        if turn_deadline > 0:
            rerun["deadline_monotonic"] = time.monotonic() + float(turn_deadline)
            rerun["halted"] = False
        return {"run": rerun}

    return ask_node


# ── 条件路由（含 Send 扇出）────────────────────────────────────────────


def route(state: dict[str, Any]) -> str:
    """classify 之后的条件路由：按执行模式选择分支。"""
    routing = routing_of(state)
    if routing.get("error_code"):
        return "clarify"
    mode = str(routing.get("execution_mode", "conversation"))
    if mode == "clarify":
        return "clarify"
    if mode == "domain_workflow":
        return "domain"
    return "conversation"


def make_scope_router(
    should_stop: Callable[[], bool] | None = None,
):
    """``scope_tasks`` 之后的条件边：扇出全部领域任务，或直接汇合。

    停止/超时在下发前检查：已触发则不再启动新的领域执行，直接走汇合节点
    （那里会登记降级原因并保留已完成结论）。
    """

    def route_after_scope(state: dict[str, Any]):
        run = run_of(state)
        if _halt_reason(state, run, should_stop):
            return "converge"
        routing = routing_of(state)
        domains = [BusinessDomain(value) for value in routing.get("domains", [])]
        expert_tasks = run.get("expert_tasks") or {}
        sends: list[Send] = []
        for domain in domains:
            payload = expert_tasks.get(task_id_of(str(state.get("run_id", "")), domain))
            if not isinstance(payload, dict):
                continue
            sends.append(Send("domain_worker", _worker_payload(state, payload, domain)))
        return sends or "converge"

    return route_after_scope


def route_after_converge(state: dict[str, Any]):
    """汇合后的路由：继续追问 / 汇合表述 / 合规收尾。"""
    run = run_of(state)
    if run.get("param_blocked"):
        return "compliance"
    if run.get("param_missing"):
        return "ask"
    if len(task_results_of(state)) >= 2:
        return "synthesize"
    return "compliance"


def make_rerun_router():
    """``ask`` 之后的条件边：按域扇出缺参重跑。"""

    def route_after_ask(state: dict[str, Any]):
        run = run_of(state)
        if run.get("param_blocked"):
            return "compliance"
        answers = dict(run.get("rerun_answers") or {})
        if not answers:
            return "compliance"
        pending = _needs_input_outcomes(task_results_of(state))
        expert_tasks = run.get("expert_tasks") or {}
        sends: list[Send] = []
        for value in pending.values():
            try:
                domain = BusinessDomain(str(value.get("domain")))
            except ValueError:
                continue
            task_payload = expert_tasks.get(str(value.get("task_id")))
            if not isinstance(task_payload, dict):
                # 无法重建任务：不再重跑，交由汇合节点如实收尾。
                continue
            sends.append(
                Send(
                    "domain_worker",
                    _worker_payload(
                        state,
                        task_payload,
                        domain,
                        answers=_answers_for_domain(answers, domain),
                    ),
                )
            )
        return sends or "converge"

    return route_after_ask


# ── 多领域汇合节点 ────────────────────────────────────────────────────

_SYNTHESIS_PROMPT = """你是投顾助手。下面是各领域专家给出的结论，请把它们组织成一段连贯、
对用户友好的回复。

## 硬约束
1. **不得新增或改动任何数字**（收益、比例、点位、金额、评分等），只能引用专家结论里
   已有的数字。若某结论没有数字，就不要补充。
2. **不得新增事实或预测**，不得推荐个股，不得给出买卖/仓位指令。
3. 保留每个领域结论的核心信息；可以补充过渡语句、加小标题让结构清晰。
4. 某领域结论为空或表示不可用时，如实带过，不要编造。
5. 用简体中文，直接输出回复正文，不要输出"以下是"之类的元话语。

## 各领域结论
{sections}

## 用户原始问题
{message}"""


def make_synthesize_node(
    model: Any = None,
    *,
    progress: Callable[[str, str], None] | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """构造汇合节点工厂；``model`` 可注入（测试用假模型）。"""

    def _resolve_model() -> Any:
        if model is not None:
            return model
        from finance_agent.infrastructure.llm.factory import get_model_for_agent

        return get_model_for_agent("synthesis")

    def synthesize_node(state: dict[str, Any]) -> dict[str, Any]:
        run = run_of(state)
        sections = _outcome_summaries(task_results_of(state))
        if len(sections) < 2:
            # 不足两段无需汇合（单域或全空）：保持既有拼接语义。
            return {}
        _emit(progress, "synthesize", "正在汇总结论")
        message = str(state.get("user_message", "") or "")
        prompt = _SYNTHESIS_PROMPT.format(
            sections="\n\n---\n\n".join(sections), message=message,
        )
        try:
            from langchain_core.messages import HumanMessage

            response = _resolve_model().invoke([HumanMessage(content=prompt)])
            text = getattr(response, "content", response)
            if isinstance(text, list):
                text = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in text
                )
            text = str(text or "").strip()
        except Exception:  # noqa: BLE001 - 汇合失败回退原样拼接，绝不丢结果
            logger.warning("synthesis_failed", exc_info=True)
            return {"run": {"warnings": [*list(run.get("warnings") or []), "synthesis_unavailable"]}}

        if not text:
            return {"run": {"warnings": [*list(run.get("warnings") or []), "synthesis_empty"]}}
        return {"run": {"final_response": text}}

    return synthesize_node


def make_compliance_node(
    progress: Callable[[str, str], None] | None = None,
    *,
    semantic_check: Callable[[str], list[str]] | None = None,
    trust_embeddings: Any = None,
    trust_threshold: float | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """合规出口节点：所有执行模式的输出都必须经过它。

    ``trust_embeddings`` 是句级受信判定用的 embedding 提供者（实现
    ``embed_query(text)``）；未注入时不放行任何受信豁免。``semantic_check`` 只输出
    违规码、不改写文本；它不可用时抛错，由 ``compliance_error_handler`` 按
    fail-closed 拦截。
    """

    def compliance_node(state: dict[str, Any]) -> dict[str, Any]:
        from finance_agent.orchestration.graphs.compliance import (
            TRUST_SIMILARITY_THRESHOLD,
            run_compliance,
        )

        _emit(progress, "compliance", "正在合规校验")
        run = run_of(state)
        outcome_refs: list[dict[str, Any]] = []
        for value in task_results_of(state).values():
            if isinstance(value, dict):
                for ref in value.get("evidence", []) or []:
                    if isinstance(ref, dict):
                        outcome_refs.append(
                            {"fact_id": str(ref.get("uri", "")), "value": ref.get("content_hash", "")}
                        )
        # 未执行的澄清提示必须出现在回复里（而非只进 warnings），否则用户会以为
        # 整条请求都处理完了。先并入草稿再走合规，保证提示本身也受合规校验。
        draft = str(run.get("final_response", "") or "")
        notes = [str(n) for n in (routing_of(state).get("warnings") or []) if str(n).strip()]
        if notes:
            hint = "补充说明：" + "；".join(notes)
            draft = f"{draft}\n\n{hint}".strip() if draft.strip() else hint
        result = run_compliance(
            draft=draft,
            evidence=outcome_refs,
            # FAQ 原文等受信内容：**逐句**判定后只审计、不改写（模型在原文之外
            # 自由发挥的句子照常走确定性检查与改写）。
            trusted_sources=list(run.get("trusted_sources") or []),
            embed=trust_embeddings,
            trust_threshold=(
                TRUST_SIMILARITY_THRESHOLD if trust_threshold is None else trust_threshold
            ),
            semantic_check=semantic_check,
            # 无原文可比对时的旧口径：整段受信，只审计。
            audit_only=bool(run.get("trusted_content", False)),
        )
        updates: dict[str, Any] = {
            "compliance": result.model_dump(mode="json"),
            "final_response": result.response,
            "warnings": list(run.get("warnings") or []),
            "degradations": list(run.get("degradations") or []),
        }
        if notes:
            updates["warnings"] = [
                *updates["warnings"],
                *[f"clarification_needed:{note}" for note in notes],
            ]
        if result.action == "blocked":
            updates["run_status"] = RunStatus.FAILED.value
            _append(updates["degradations"], "compliance_blocked")
        return {"run": updates}

    return compliance_node


# ── 错误处理器 ────────────────────────────────────────────────────────


def degradation_error_handler(state: dict[str, Any], error: NodeError) -> Command:
    """执行类节点耗尽重试后的统一降级：给出安全文案并路由到合规出口。

    需要 ``Command(goto=...)``：error_handler 不是普通节点，返回 dict 不会沿该
    节点的静态边继续，只有显式 goto 才能继续到 compliance，让降级文案同样经过
    合规校验。只暴露节点名与异常类型，不泄露内部细节。
    """
    node = str(getattr(error, "node", "") or "unknown")
    detail = type(getattr(error, "error", None)).__name__
    return Command(
        update={
            "run": {
                "final_response": "该部分内容暂时无法生成，请稍后重试。",
                "run_status": RunStatus.FAILED.value,
                "degradations": [f"node_failed:{node}:{detail}"],
            }
        },
        goto="compliance",
    )


def classification_error_handler(state: dict[str, Any], error: NodeError) -> Command:
    """分类节点失败：显式报告无法识别领域，绝不静默猜测业务领域。"""
    return Command(
        update={
            "run": {
                "final_response": CLASSIFICATION_FAILED_RESPONSE,
                "run_status": RunStatus.FAILED.value,
                "degradations": ["classification_failed_node"],
            }
        },
        goto="compliance",
    )


def compliance_error_handler(state: dict[str, Any], error: NodeError) -> Command:
    """合规出口自身失败必须 fail-closed：拦截未经校验的草稿。

    合规不可用时"放行原文"是错误选择——那正是合规存在的意义所在。
    合规节点已是终点前的最后一站，因此 goto=END。
    """
    from finance_agent.orchestration.graphs.compliance import BLOCKED_RESPONSE

    return Command(
        update={
            "run": {
                "final_response": BLOCKED_RESPONSE,
                "run_status": RunStatus.FAILED.value,
                "compliance": {
                    "action": "blocked",
                    "reason_codes": ["compliance_unavailable"],
                    "response": BLOCKED_RESPONSE,
                    "rewrite_count": 0,
                },
                "degradations": ["compliance_unavailable"],
            }
        },
        goto=END,
    )


# ── 图装配 ────────────────────────────────────────────────────────────


def build_supervisor_graph(dependencies: SupervisorDependencies, *, checkpointer: Any = None):
    """编译 Supervisor Graph；节点只做分类、铺开任务、扇出与汇合。

    ``checkpointer`` 为 ``None`` 时不持久化（单次调用与测试场景）；生产由
    ``AdvisorSystem`` 注入 PostgresSaver。领域任务是根图的独立 superstep，因此
    崩溃/重启后可从最近一个已完成的领域任务之后继续，而不是整轮重跑。
    """
    budgets = dependencies.budgets or RunBudgets.from_config()
    progress = dependencies.progress
    rewriter = dependencies.rewriter if dependencies.rewriter is not None else _default_rewriter()

    classify_node = make_classify_node(
        dependencies.classifier,
        turn_deadline=budgets.turn_deadline,
        progress=progress,
    )
    conversation_node = make_conversation_node(dependencies.conversation_runner)
    scope_tasks_node = make_scope_tasks_node(
        rewriter, max_domains=budgets.max_domains, progress=progress,
    )
    domain_worker = make_domain_worker(dependencies.domain_runner)
    converge_node = make_converge_node(
        allow_interrupt=checkpointer is not None,
        clarify_limit=budgets.clarify_rounds,
        should_stop=dependencies.should_stop,
        progress=progress,
    )
    ask_node = make_ask_node(turn_deadline=budgets.turn_deadline)
    synthesize_node = make_synthesize_node(dependencies.synthesis_model, progress=progress)
    compliance_node = make_compliance_node(
        progress,
        semantic_check=dependencies.semantic_check,
        trust_embeddings=dependencies.trust_embeddings,
        trust_threshold=dependencies.trust_threshold,
    )

    graph = StateGraph(SupervisorState)
    # 图级默认重试：瞬时的模型/网络故障应当自动重试一次，而不是立刻降级。
    # 重试的粒度是**单个领域任务**（Send 的目标节点），不会重跑整轮扇出；
    # 领域任务可能提交量化任务，但 QuantGateway 的 submit 以 idempotency_key
    # 保证幂等，因此重试不会重复下单。
    graph.set_node_defaults(retry_policy=RetryPolicy(max_attempts=2, initial_interval=0.5))
    graph.add_node("classify", classify_node, error_handler=classification_error_handler)
    graph.add_node("conversation", conversation_node, error_handler=degradation_error_handler)
    graph.add_node("clarify", clarify_node)
    graph.add_node("scope_tasks", scope_tasks_node, error_handler=degradation_error_handler)
    graph.add_node("domain_worker", domain_worker, error_handler=degradation_error_handler)
    # converge 不设 error_handler：其本身不做模型调用与 I/O。
    graph.add_node("converge", converge_node)
    # ask 是 interrupt 宿主：节点重跑语义要求异常不被吞掉，因此不挂 error_handler
    # （``interrupt`` 抛出的控制流异常必须原样冒泡）。
    graph.add_node("ask", ask_node)
    graph.add_node("synthesize", synthesize_node, error_handler=degradation_error_handler)
    # 合规出口失败必须 fail-closed：绝不把未经校验的草稿当作结果返回。
    graph.add_node("compliance", compliance_node, error_handler=compliance_error_handler)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        route,
        {
            "conversation": "conversation",
            "clarify": "clarify",
            "domain": "scope_tasks",
        },
    )
    for node in ("conversation", "clarify"):
        graph.add_edge(node, "converge")
    graph.add_conditional_edges(
        "scope_tasks", make_scope_router(dependencies.should_stop), ["domain_worker", "converge"],
    )
    graph.add_edge("domain_worker", "converge")
    graph.add_conditional_edges(
        "converge",
        route_after_converge,
        {"ask": "ask", "synthesize": "synthesize", "compliance": "compliance"},
    )
    # 缺参重跑复用同一个 domain_worker：载荷里的 answers 非空即为重跑。
    graph.add_conditional_edges(
        "ask", make_rerun_router(), ["domain_worker", "converge", "compliance"],
    )
    graph.add_edge("synthesize", "compliance")
    graph.add_edge("compliance", END)
    return graph.compile(checkpointer=checkpointer)


def _default_rewriter() -> Callable[..., Any] | None:
    """惰性构造默认改写器（按域产出自包含描述）。"""
    from finance_agent.orchestration.routing.task_rewrite import build_llm_rewriter
    from finance_agent.infrastructure.llm.factory import get_intent_model

    model = get_intent_model()
    return build_llm_rewriter(model) if model is not None else None


def _pending_job_ids(outcomes: dict[str, Any]) -> list[str]:
    """收集 processing 结论中的真实 Celery job_id（去重、稳定排序）。

    兼容两种来源：结论显式携带的 ``pending_jobs``，以及
    ``structured_data.pending_jobs``（领域图写回的结构化字段）。两者都缺失时
    不回退到领域 task_id——回退值对状态端点无意义，会让前端拿到查不到的 id。
    """
    job_ids: set[str] = set()
    for value in outcomes.values():
        if not isinstance(value, dict) or value.get("status") != "processing":
            continue
        refs = list(value.get("pending_jobs") or [])
        structured = value.get("structured_data") or {}
        if isinstance(structured, dict):
            refs += list(structured.get("pending_jobs") or [])
        for ref in refs:
            if isinstance(ref, dict) and ref.get("job_id"):
                job_ids.add(str(ref["job_id"]))
    return sorted(job_ids)


# 现有响应键必须保留；V2 只追加 run_status/task_id/pending_task_ids/warnings。
_V2_RESPONSE_KEYS = (
    "response",
    "task_plan",
    "task_dispatch",
    "tasks",
    "task_results",
    "user_profile",
    "stock_data",
    "fundamental_analysis",
    "stock_analysis",
    "technical_analysis",
    "analysis_results",
    "personalization_status",
    "product_analysis",
    "market_insight",
    "compliance_result",
    "conversation_id",
    "run_status",
    "warnings",
    "account",
    # 缺参追问的表单载荷；非追问响应为空。
    "pending_input",
)


def project_supervisor_state(state: dict[str, Any], *, conversation_id: str = "") -> dict[str, Any]:
    """把 Supervisor Graph 终态投影为兼容现有 /api/chat 的响应字典。

    保留全部既有字段（缺省为空），只追加 run_status/task_id/pending_task_ids/warnings。

    ``task_dispatch`` / ``tasks`` / ``task_plan`` 已停止写入（前端不消费，且计划层
    已删除）：键名保留以免破坏响应契约，值恒为空容器。
    """
    run = run_of(state)
    routing = run.get("routing") if isinstance(run.get("routing"), dict) else {}
    domains = list((routing or {}).get("domains", []) or [])
    outcomes = task_results_of(state)
    # 降级级告警排在前面：``warnings`` 是对外契约字段（单一列表），
    # 保序让消费方一眼看到真正影响 run_status 的原因。
    warnings = [*list(run.get("degradations") or []), *list(run.get("warnings") or [])]

    output: dict[str, Any] = {key: None for key in _V2_RESPONSE_KEYS}
    output.update(
        {
            "response": str(run.get("final_response", "") or ""),
            "task_plan": list(domains),
            "task_dispatch": [],
            "tasks": [],
            "task_results": dict(outcomes),
            # 画像卡由调用方随输入注入，此处如实回传（此前硬编码空字典，
            # 导致前端的画像刷新分支永不触发）。
            "user_profile": dict(state.get("user_profile", {}) or {}),
            "stock_data": {},
            "fundamental_analysis": {},
            "stock_analysis": {},
            "technical_analysis": {},
            "analysis_results": [],
            "personalization_status": "",
            "product_analysis": {},
            "market_insight": {},
            "compliance_result": dict(run.get("compliance", {}) or {}),
            "conversation_id": conversation_id,
            "run_status": str(run.get("run_status") or RunStatus.COMPLETED.value),
            "warnings": warnings,
            "account": {},
            # 缺参追问的表单载荷（非追问响应为空 dict）；响应契约里是可选字段。
            "pending_input": dict(run.get("param_missing", {}) or {}) or None,
            # 待处理异步任务的标识必须是**真实 Celery job_id**：状态端点
            # GET /api/runs/{task_id} 按 job_id（即仓储主键）查询。
            "pending_task_ids": _pending_job_ids(outcomes),
        }
    )

    for outcome in outcomes.values():
        if not isinstance(outcome, dict):
            continue
        data = outcome.get("structured_data", {}) or {}
        domain = outcome.get("domain")
        if domain == BusinessDomain.STOCK_RESEARCH.value:
            for key in (
                "stock_data",
                "fundamental_analysis",
                "stock_analysis",
                "technical_analysis",
                "analysis_results",
                "facts",
                "research_request",
            ):
                if key in data:
                    output[key] = data[key]
            for key in ("personalization_status",):
                if key in data:
                    output[key] = data[key]
        elif domain == BusinessDomain.MARKET_INSIGHT.value:
            output["market_insight"] = data.get("market_insight", data)
        elif domain == BusinessDomain.PRODUCT_RESEARCH.value:
            nested = data.get("product_analysis")
            output["product_analysis"] = nested if isinstance(nested, dict) else data
        elif domain == BusinessDomain.ACCOUNT_PORTFOLIO.value:
            # 账户领域投影为 {account, positions}；两者都只读。allocation_review 为
            # 配置诊断与优化参考（测算口径），随账户一起下发供前端渲染。
            output["account"] = {
                "account": data.get("account", {}) or {},
                "positions": data.get("positions", []) or [],
                "mode": data.get("mode", ""),
                "allocation_review": data.get("allocation_review", {}) or {},
            }

    return output


def project_interrupt_state(
    state: dict[str, Any], *, conversation_id: str = "", customer_id: str = "",
) -> dict[str, Any]:
    """把"缺参追问挂起"的图状态投影为兼容 /api/chat 的响应。

    追问以 LangGraph ``interrupt`` 挂起，``invoke`` 返回体里带 ``__interrupt__``；
    ``run_status`` 置为 ``awaiting_input``（非终态），提示调用方这是一次需要用户
    补充参数的交互。
    """
    pending: dict[str, Any] = {}
    interrupt_id = ""
    for item in state.get("__interrupt__") or ():
        value = getattr(item, "value", item)
        if isinstance(value, dict):
            pending = dict(value)
        interrupt_id = str(getattr(item, "id", "") or "")
        break
    if not pending:
        # 兼容快照形状：挂起载荷可能挂在 run.param_missing 上。
        pending = dict(run_of(state).get("param_missing", {}) or {})

    # 与 project_supervisor_state 保持同一套空值默认：dict/list/str 各用其空容器，
    # 而不是统一置 None。否则 /api/chat 的 ChatResponse 校验会因 user_profile、
    # stock_data 等字段收到 None 而整体 500，追问弹窗永远到不了前端。
    output: dict[str, Any] = {
        "response": "",
        "task_plan": [],
        "task_dispatch": [],
        "tasks": [],
        "task_results": {},
        "user_profile": dict(state.get("user_profile", {}) or {}),
        "stock_data": {},
        "fundamental_analysis": {},
        "stock_analysis": {},
        "technical_analysis": {},
        "analysis_results": [],
        "personalization_status": "",
        "product_analysis": {},
        "market_insight": {},
        "compliance_result": {},
        "conversation_id": conversation_id,
        "run_status": "awaiting_input",
        "warnings": ["awaiting_user_input"],
        "account": {},
        "pending_input": None,
        "pending_task_ids": [],
    }
    output.update(
        {
            "response": str(pending.get("question", "") or ""),
            "pending_input": pending or None,
            "interrupt_id": interrupt_id,
        }
    )
    if customer_id:
        output["customer_id"] = customer_id
    return output


__all__ = [
    "CANCELLED_RESPONSE",
    "CLASSIFICATION_FAILED_RESPONSE",
    "CLARIFICATION_FALLBACK",
    "PARAM_CANCELLED_RESPONSE",
    "RunState",
    "SupervisorDependencies",
    "SupervisorState",
    "build_supervisor_graph",
    "classify_domains",
    "classification_error_handler",
    "clarify_node",
    "compliance_error_handler",
    "degradation_error_handler",
    "route",
    "routing_of",
    "run_of",
    "task_id_of",
    "task_results_of",
    "project_interrupt_state",
    "project_supervisor_state",
    "reduce_run_status",
]
