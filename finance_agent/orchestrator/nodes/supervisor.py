"""Supervisor Graph 的节点函数（分类、路由、领域/计划执行、合规出口）。

节点实现从 ``supervisor_graph.build_supervisor_graph`` 的闭包迁出：依赖经工厂参数显式
注入，宿主模块负责装配节点与边。节点读写 ``SupervisorState``（定义仍在
``supervisor_graph``，避免模块级循环导入）；需要宿主纯辅助函数
（``classify_domains``、``reduce_run_status`` 等）时在函数体内惰性导入。
"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.errors import NodeError
from langgraph.graph import END
from langgraph.types import Command, interrupt

from finance_agent.orchestrator.contracts import BusinessDomain, DomainTaskContext

#: 合法的领域枚举值集合；用于把路由结果里的字符串安全还原为枚举（未知值丢弃）。
_DOMAIN_VALUES = frozenset(item.value for item in BusinessDomain)


def _domain_params(state: dict[str, Any], domain: BusinessDomain) -> dict[str, Any]:
    """从根图状态取出**该领域**的参数（``extracted_params.values[domain]``）。"""
    extracted = state.get("extracted_params", {}) or {}
    values = extracted.get("values") if isinstance(extracted, dict) else {}
    scoped = (values or {}).get(domain.value) if isinstance(values, dict) else {}
    return dict(scoped) if isinstance(scoped, dict) else {}


def make_classify_node(classifier: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """分类节点工厂：``classifier`` 由 SupervisorDependencies 注入。"""

    def classify_node(state: dict[str, Any]) -> dict[str, Any]:
        from finance_agent.orchestrator.supervisor_graph import classify_domains

        routing = classify_domains(
            str(state.get("user_message", "")),
            str(state.get("history", "") or ""),
            classifier=classifier,
        )
        # 接入 checkpointer 后状态会跨轮次保留，而各分支只写自己那部分键。
        # 若不在入口复位，上一轮的值会泄漏到本轮：最危险的是 trusted_content
        # （上一轮 FAQ 命中后置真，会让本轮股票分析走"只审计不改写"的合规路径，
        # 风险表述被直接放行）；warnings 同理（澄清分支不写该键时会残留）。
        # classify 每轮都是 START 后的第一个节点，在这里统一清空本轮派生键，
        # 保证"每轮从干净状态开始"这一不变量不依赖调用方记忆。
        return {
            "routing": routing.model_dump(mode="json"),
            "final_response": "",
            "run_status": "",
            "warnings": [],
            "task_results": {},
            "domain_outcomes": {},
            "compliance": {},
            "single_task_id": "",
            "trusted_content": False,
            # 每轮的参数抽取结果与校验结论：不清空会让上一轮的缺参状态泄漏到本轮
            # （param_blocked 残留会把本轮直接短路到合规出口）。
            "extracted_params": {},
            "param_blocked": False,
            "param_missing": {},
        }

    return classify_node


def make_extract_node(
    extract_fn: Callable[..., Any],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """参数抽取节点工厂：只读消息与路由，写入 ``extracted_params``。

    与 ``validate`` 分成两个节点是**硬要求**：``interrupt`` 恢复时会从节点开头
    重跑，若把（可能含模型调用的）抽取与 ``interrupt`` 放在同一节点，每次恢复都
    会重复付费调用模型。拆开后抽取产物已随 checkpoint 落库，恢复只重跑确定性校验。

    会话/澄清分支不需要参数，直接短路，避免闲聊也触发一次抽取。
    """

    def extract_node(state: dict[str, Any]) -> dict[str, Any]:
        routing = state.get("routing", {}) or {}
        if routing.get("error_code") or routing.get("execution_mode") in ("conversation", "clarify"):
            return {}
        domains = [
            BusinessDomain(value)
            for value in routing.get("domains", []) or []
            if value in _DOMAIN_VALUES
        ]
        params = extract_fn(
            str(state.get("user_message", "")),
            str(state.get("history", "") or ""),
            domains=domains,
        )
        return {"extracted_params": params.model_dump(mode="json")}

    return extract_node


def make_validate_node(
    *,
    allow_interrupt: bool,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """入参校验节点工厂：缺必填项时用 LangGraph ``interrupt`` 追问。

    ``allow_interrupt`` 由图是否挂了 checkpointer 决定：没有 checkpointer 无法
    suspend/resume，此时退化为"澄清式收尾"（把问题作为回复返回），与本仓库
    interrupt 之前的既有行为一致，测试与单次调用不受影响。
    """

    def validate_node(state: dict[str, Any]) -> dict[str, Any]:
        from finance_agent.orchestrator.params import (
            ExtractedParams,
            apply_answers,
            build_form,
            find_missing,
            is_cancel,
            merge_target_queries,
        )
        from finance_agent.orchestrator.supervisor_graph import PARAM_CANCELLED_RESPONSE

        routing = state.get("routing", {}) or {}
        if routing.get("error_code") or routing.get("execution_mode") in ("conversation", "clarify"):
            return {}
        domains = [
            BusinessDomain(value)
            for value in routing.get("domains", []) or []
            if value in _DOMAIN_VALUES
        ]
        params = ExtractedParams.model_validate(state.get("extracted_params") or {})
        missing = find_missing(domains, params)
        if not missing or not params.extraction_available:
            # 抽取不可用（模型未配置/失败）时不得把"没抽到"当成"用户没说"：
            # 否则只能给名称的请求会被误拦，放行让领域自行解析/降级。
            return {}
        if not allow_interrupt:
            form = build_form(domains, missing)
            return {
                "final_response": form["question"],
                "run_status": "partial",
                "param_blocked": True,
                "param_missing": form,
                "warnings": [f"param_missing:{name}" for name in form["missing"]],
            }

        # 追问必须是服务端确定性模板：只含登记字段与提示，不含分析结论。
        # 注意：interrupt 不得包在 try/except 里（重跑语义要求异常不被吞掉）。
        form = build_form(domains, missing)
        answer = interrupt(form)
        if is_cancel(answer):
            return {
                "final_response": PARAM_CANCELLED_RESPONSE,
                "run_status": "completed",
                "param_blocked": True,
                "param_missing": {},
                "warnings": ["param_cancelled_by_user"],
            }
        params = apply_answers(params, answer, domains)
        remaining = find_missing(domains, params)
        if remaining:
            # 单次询问不重问：仍缺则显式收尾（携带已填部分继续执行风险更高）。
            form = build_form(domains, remaining)
            return {
                "final_response": form["question"],
                "run_status": "partial",
                "param_blocked": True,
                "param_missing": form,
                "warnings": [f"param_missing:{name}" for name in form["missing"]],
            }
        return {
            "extracted_params": params.model_dump(mode="json"),
            "param_missing": {},
            # 缺参补齐后把标的并入该领域子请求，保持分类器子请求的上下文。
            "routing": merge_target_queries(routing, params, domains),
        }

    return validate_node


def make_conversation_node(
    conversation_runner: Callable[[dict[str, Any]], dict[str, Any]] | None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """会话节点工厂：casual chat / FAQ 的受限 ReAct 执行器。"""

    def conversation_node(state: dict[str, Any]) -> dict[str, Any]:
        if conversation_runner is None:
            return {
                "final_response": "会话能力暂不可用，请稍后重试。",
                "run_status": "failed",
                "warnings": ["conversation_runner_unavailable"],
            }
        result = conversation_runner(dict(state))
        return {
            "final_response": result.get("final_response", ""),
            "run_status": "completed" if result.get("status") == "success" else "partial",
            "warnings": list(result.get("warnings", []) or []),
            # 引用了 FAQ 知识库原文时，内容属于受信语料，合规出口只审计不改写。
            "trusted_content": bool(result.get("cited_faq", False)),
        }

    return conversation_node


def clarify_node(state: dict[str, Any]) -> dict[str, Any]:
    """澄清分支：显式转述澄清问题，分类协议错误显式失败。"""
    from finance_agent.orchestrator.supervisor_graph import (
        CLASSIFICATION_FAILED_RESPONSE,
        CLARIFICATION_FALLBACK,
    )

    routing = state.get("routing", {}) or {}
    if routing.get("error_code"):
        return {
            "final_response": str(routing.get("clarification") or CLASSIFICATION_FAILED_RESPONSE),
            "run_status": "failed",
            "warnings": [f"classification_error:{routing['error_code']}"],
        }
    return {
        "final_response": str(routing.get("clarification") or CLARIFICATION_FALLBACK),
        "run_status": "completed",
    }


def make_single_domain_node(
    domain_runner: Callable[[DomainTaskContext], Any] | None,
    should_stop: Callable[[], bool] | None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """单领域节点工厂：以该领域的子请求直达领域执行器。"""

    def single_domain_node(state: dict[str, Any]) -> dict[str, Any]:
        from finance_agent.orchestrator.supervisor_graph import (
            CANCELLED_RESPONSE,
            _single_task,
            _single_task_id,
            _status_from_outcome,
        )

        routing = state.get("routing", {}) or {}
        domain = BusinessDomain(routing["domains"][0])
        run_id = str(state.get("run_id", ""))
        task_id = _single_task_id(run_id, domain)
        updates: dict[str, Any] = {"single_task_id": task_id}
        if domain_runner is None:
            updates.update(
                {
                    "final_response": "该业务领域能力暂不可用，请稍后重试。",
                    "run_status": "failed",
                    "warnings": [f"domain_runner_unavailable:{domain.value}"],
                }
            )
            return updates

        # 协作式停止：用户已请求停止时不再启动领域执行（与计划分支同一语义）。
        if should_stop is not None and should_stop():
            updates.update(
                {
                    "final_response": CANCELLED_RESPONSE,
                    "run_status": "cancelled",
                    "warnings": ["cancelled_by_user"],
                }
            )
            return updates

        # 单领域直达也使用该领域的子请求：多意图里只要有一个领域时，query 已
        # 是该领域的精确子请求，避免整句干扰解析。
        scoped = str((routing.get("domain_queries") or {}).get(domain.value) or "").strip() \
            or str(state.get("user_message", ""))
        outcome = domain_runner(
            DomainTaskContext(
                task=_single_task(
                    goal=scoped,
                    instruction=scoped,
                    domain=domain,
                    task_id=task_id,
                ),
                thread_id=str(state.get("thread_id", "")),
                customer_id=str(state.get("customer_id", "")),
                conversation_id=str(state.get("conversation_id", "")),
                user_message=str(state.get("user_message", "")),
                run_id=run_id,
                params=_domain_params(state, domain),
                user_profile=dict(state.get("user_profile", {}) or {}),
            )
        )
        return {
            **updates,
            "final_response": outcome.summary,
            "run_status": _status_from_outcome(outcome),
            "domain_outcomes": {task_id: outcome.model_dump(mode="json")},
            "task_results": {task_id: outcome.model_dump(mode="json")},
            "warnings": list(outcome.limitations),
        }

    return single_domain_node


def make_plan_node(
    plan_runner: Callable[[dict[str, Any], list[BusinessDomain]], Any] | None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """计划节点工厂：跨领域 Plan-and-Execute 分支。"""

    def plan_node(state: dict[str, Any]) -> dict[str, Any]:
        from finance_agent.orchestrator.supervisor_graph import PlanRunResult, reduce_run_status

        routing = state.get("routing", {}) or {}
        domains = [BusinessDomain(value) for value in routing.get("domains", [])]
        if plan_runner is None:
            return {
                "final_response": "跨领域规划能力暂不可用，请拆分为单个领域分别提问。",
                "run_status": "failed",
                "warnings": ["plan_runner_unavailable"],
            }
        raw = plan_runner(dict(state), domains)
        # 兼容两种返回：携带降级信息的结果对象，或旧式的结论列表。
        if isinstance(raw, PlanRunResult):
            outcomes, extra_warnings, reported_status = raw.outcomes, raw.warnings, raw.run_status
        else:
            outcomes, extra_warnings, reported_status = list(raw), [], ""
        responses = [outcome.summary for outcome in outcomes if outcome.summary]
        # 状态归约的优先级链集中在 reduce_run_status 内（含 cancelled 与降级语义）。
        run_status = reduce_run_status(outcomes, extra_warnings, reported_status)
        return {
            "final_response": "\n\n".join(responses),
            "run_status": run_status,
            "task_results": {outcome.task_id: outcome.model_dump(mode="json") for outcome in outcomes},
            "domain_outcomes": {outcome.task_id: outcome.model_dump(mode="json") for outcome in outcomes},
            "warnings": extra_warnings + [
                limitation for outcome in outcomes for limitation in outcome.limitations
            ],
        }

    return plan_node


def route(state: dict[str, Any]) -> str:
    """classify/validate 之后的条件路由：按执行模式选择分支。"""
    routing = state.get("routing", {}) or {}
    # 校验已收尾（缺参追问挂起、用户取消、或补齐失败）：直接去合规出口，
    # 不得再进入领域执行——此时 final_response 已经是给用户的追问/取消文案。
    if state.get("param_blocked"):
        return "validate_stop"
    mode = routing.get("execution_mode", "conversation")
    if routing.get("error_code"):
        return "clarify"
    if mode == "clarify":
        return "clarify"
    if mode == "domain_react":
        return "single_domain"
    if mode == "plan_execute":
        return "plan"
    return "conversation"


def compliance_node(state: dict[str, Any]) -> dict[str, Any]:
    """所有执行模式的成功/部分/降级输出都必须经过合规出口。"""
    from finance_agent.orchestrator.compliance import run_compliance

    outcome_refs: list[dict[str, Any]] = []
    for value in (state.get("task_results", {}) or {}).values():
        if isinstance(value, dict):
            for ref in value.get("evidence", []) or []:
                if isinstance(ref, dict):
                    outcome_refs.append(
                        {"fact_id": str(ref.get("uri", "")), "value": ref.get("content_hash", "")}
                    )
    # 未执行的澄清提示必须出现在回复里（而非只进 warnings），否则用户会以为
    # 整条请求都处理完了。先并入草稿再走合规，保证提示本身也受合规校验。
    draft = str(state.get("final_response", ""))
    notes = [str(n) for n in ((state.get("routing") or {}).get("warnings") or []) if str(n).strip()]
    if notes:
        hint = "补充说明：" + "；".join(notes)
        draft = f"{draft}\n\n{hint}".strip() if draft.strip() else hint
    result = run_compliance(
        draft=draft,
        evidence=outcome_refs,
        # FAQ 原文等受信内容：检查并记录审计，但不改写、不拦截。
        audit_only=bool(state.get("trusted_content", False)),
    )
    updates: dict[str, Any] = {
        "compliance": result.model_dump(mode="json"),
        "final_response": result.response,
    }
    if notes:
        updates["warnings"] = list(state.get("warnings", []) or []) + [
            f"clarification_needed:{note}" for note in notes
        ]
    if result.action == "blocked":
        updates["run_status"] = "failed"
        updates["warnings"] = list(updates.get("warnings") or state.get("warnings", []) or []) + [
            "compliance_blocked"
        ]
    return updates


def degradation_error_handler(state: dict[str, Any], error: NodeError) -> Command:
    """执行类节点耗尽重试后的统一降级：给出安全文案并路由到合规出口。

    没有 handler 时异常会冒泡到 ``AdvisorSystem.handle_message``，被统一吞成
    笼统的"处理请求时发生内部错误"（且 warnings 里不留任何诊断线索）。
    需要 ``Command(goto=...)``：error_handler 不是普通节点，返回 dict 不会
    沿该节点的静态边继续，只有显式 goto 才能继续到 compliance，让降级文案
    同样经过合规校验；早前节点已写入的状态（如分类结果）也随之保留。
    只暴露节点名与异常类型，不泄露内部细节。
    """
    node = str(getattr(error, "node", "") or "unknown")
    detail = type(getattr(error, "error", None)).__name__
    return Command(
        update={
            "final_response": "该部分内容暂时无法生成，请稍后重试。",
            "run_status": "failed",
            "warnings": [f"node_failed:{node}:{detail}"],
        },
        goto="compliance",
    )


def classification_error_handler(state: dict[str, Any], error: NodeError) -> Command:
    """分类节点失败：显式报告无法识别领域，绝不静默猜测业务领域。"""
    from finance_agent.orchestrator.supervisor_graph import CLASSIFICATION_FAILED_RESPONSE

    return Command(
        update={
            "final_response": CLASSIFICATION_FAILED_RESPONSE,
            "run_status": "failed",
            "warnings": ["classification_failed_node"],
        },
        goto="compliance",
    )


def compliance_error_handler(state: dict[str, Any], error: NodeError) -> Command:
    """合规出口自身失败必须 fail-closed：拦截未经校验的草稿。

    合规不可用时"放行原文"是错误选择——那正是合规存在的意义所在。
    合规节点已是终点前的最后一站，因此 goto=END。
    """
    from finance_agent.orchestrator.compliance import BLOCKED_RESPONSE

    return Command(
        update={
            "final_response": BLOCKED_RESPONSE,
            "run_status": "failed",
            "compliance": {
                "action": "blocked",
                "reason_codes": ["compliance_unavailable"],
                "response": BLOCKED_RESPONSE,
                "rewrite_count": 0,
            },
            "warnings": ["compliance_unavailable"],
        },
        goto=END,
    )


__all__ = [
    "classification_error_handler",
    "clarify_node",
    "compliance_error_handler",
    "compliance_node",
    "degradation_error_handler",
    "make_classify_node",
    "make_conversation_node",
    "make_extract_node",
    "make_plan_node",
    "make_single_domain_node",
    "make_validate_node",
    "route",
]
