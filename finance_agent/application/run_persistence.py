"""会话、画像与研究审计的持久化协作器。"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from typing import Any, Callable, Dict, List, Protocol

from finance_agent.shared.contracts import FactSnapshot
from finance_agent.orchestration.needs_input import profile_updates
from finance_agent.orchestration.runtime.thread_key import build_thread_id
from finance_agent.domains.research.contracts import AnalysisRequest, AnalysisResult

logger = logging.getLogger(__name__)


class _Host(Protocol):
    audit: Any
    memory: Any

    def _best_effort(self, category: str, action: Callable[[], Any]) -> None: ...
    def _bump_degradation(self, category: str) -> None: ...
    def _audit_research_results(self, state: Dict[str, Any]) -> None: ...
    def _save_research_run(self, save_run: Any, **kwargs: Any) -> None: ...


class PersistenceCoordinator:
    """实现可重放研究审计与会话/画像写入，依赖通过 AdvisorSystem 宿主接入。"""

    def __init__(self, host: _Host, database_getter: Callable[[], Any]) -> None:
        self._host = host
        self._database_getter = database_getter

    def audit_research_results(self, state: Dict[str, Any]) -> None:
        """将确定性研究结果及其引用的原始快照写入可重放审计表。"""
        save = getattr(self._host.audit, "save_research_result", None)
        save_run = getattr(self._host.audit, "save_research_run", None)
        evidence_facts = {
            fact.fact_id: fact.model_dump(mode="json")
            for fact in state.get("facts", []) or []
            if isinstance(fact, FactSnapshot)
        }
        results = []
        for raw_result in state.get("analysis_results", []) or []:
            try:
                results.append(AnalysisResult.model_validate(raw_result))
            except (TypeError, ValueError):
                continue

        run_request = self._run_level_request(state, results)
        if len(results) > 1 and callable(save_run) and run_request is not None:
            # 走宿主同名扩展点，保留现有 monkeypatch/子类注入语义。
            self._host._save_research_run(
                save_run, request=run_request, results=results, evidence_facts=evidence_facts,
                state=state, status="completed",
            )
            return

        if not callable(save):
            # 能力缺失不算 best_effort 写入失败，单独计数并留日志。
            logger.warning(
                "audit_capability_missing method=save_research_result",
            )
            self._host._bump_degradation("audit_capability_missing")
            return
        for result in results:
            save(
                result,
                snapshot_manifest=[
                    evidence_facts[fact_id]
                    for fact_id in result.evidence_ids
                    if fact_id in evidence_facts
                ],
                run_id=str(state.get("run_id", "")),
                customer_id=str(state.get("customer_id", "")),
                conversation_id=str(state.get("thread_id", "")),
            )

    def save_research_run(
        self,
        save_run: Any,
        *,
        request: AnalysisRequest,
        results: List[AnalysisResult],
        evidence_facts: Dict[str, Any],
        state: Dict[str, Any],
        status: str,
    ) -> None:
        if not callable(save_run):
            logger.warning("audit_capability_missing method=save_research_run")
            self._host._bump_degradation("audit_capability_missing")
            return
        fact_ids = {fact_id for result in results for fact_id in result.evidence_ids}
        save_run(
            request=request,
            results=results,
            snapshot_manifest=[
                evidence_facts[fact_id] for fact_id in fact_ids if fact_id in evidence_facts
            ],
            run_id=str(state.get("run_id", "")),
            customer_id=str(state.get("customer_id", "")),
            conversation_id=str(state.get("thread_id", "")),
            status=status,
        )

    @staticmethod
    def _run_level_request(
        state: Dict[str, Any], results: List[AnalysisResult],
    ) -> AnalysisRequest | None:
        """优先取专家留档的原始请求，否则回退首条结论中的请求。"""
        raw_request = state.get("research_request")
        if isinstance(raw_request, dict):
            try:
                return AnalysisRequest.model_validate(raw_request)
            except (TypeError, ValueError):
                pass
        for result in results:
            if result.request is not None:
                return result.request
        return None

    def persist(
        self, customer_id: str, conversation_id: str, message: str,
        output: Dict[str, Any], run_id: str,
    ) -> None:
        self._host._best_effort(
            "audit_complete_run",
            lambda: self._host.audit.complete_run(
                run_id, conversation_id, output.get("response", ""),
                message_id=str(uuid.uuid4()),
                status=output.get("run_status", "completed"),
                metadata={"task_plan": output.get("task_plan", [])},
            ),
        )
        self._host._best_effort(
            "audit_research_results",
            lambda: self._host._audit_research_results({
                "run_id": run_id,
                "customer_id": customer_id,
                "thread_id": build_thread_id(customer_id, conversation_id),
                "analysis_results": output.get("analysis_results", []) or [],
                "research_request": output.get("research_request"),
                "facts": [
                    FactSnapshot.model_validate(fact)
                    for fact in output.get("facts", []) or []
                    if isinstance(fact, dict)
                ],
            }),
        )

        def persist_conversation() -> None:
            database = self._database_getter()
            database.append_conversation_message(conversation_id, "user", message)
            database.append_conversation_message(
                conversation_id, "assistant", output.get("response", ""),
                {"task_plan": output.get("task_plan", [])},
            )
            database.rename_conversation_from_message(conversation_id, message)

        self._host._best_effort("persist_conversation", persist_conversation)

        def persist_memory() -> None:
            # None 来自旧式测试替身时不代表失败，真实 False 才计入降级。
            persisted = (
                self._host.memory.append_window_message(customer_id, conversation_id, "user", message)
                and self._host.memory.append_window_message(
                    customer_id, conversation_id, "assistant", output.get("response", ""),
                    {"task_plan": output.get("task_plan", [])},
                )
                and self._host.memory.update_profile_from_result(customer_id, message, output)
            )
            if persisted is False:
                self._host._bump_degradation("memory_persist_failed")

        self._host._best_effort("persist_memory", persist_memory)

    def persist_param_profile(
        self, customer_id: str, answers: Dict[str, Any] | None,
        profile_payload: Dict[str, Any],
    ) -> None:
        """合并用户在补参弹窗提交的偏好，并更新本轮画像载荷。"""
        updates = profile_updates(answers)
        if not updates:
            return
        from finance_agent.orchestration.memory import UserProfileCard

        def save() -> None:
            existing = self._host.memory.get_profile(customer_id)
            card = UserProfileCard.from_dict(asdict(existing)) if existing is not None \
                else UserProfileCard(customer_id=customer_id.upper())
            for key, value in updates.items():
                setattr(card, key, value)
            if self._host.memory.save_profile(card):
                profile_payload.update(asdict(card))

        self._host._best_effort("persist_param_profile", save)
