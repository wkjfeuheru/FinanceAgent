"""确定性金融产品研究专家。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from finance_agent.agents.base import AgentProtocol
from finance_agent.contracts import FactSnapshot
from finance_agent.product_research.contracts import ProductResearchRequest, ProductResearchResult
from finance_agent.product_research.pipeline import ProductResearchPipeline


class _LazyProductLookup:
    """延迟创建 PostgreSQL 产品库，避免专家初始化阶段强制要求数据库配置。"""

    def __init__(self) -> None:
        self._library = None

    def _get_library(self):
        if self._library is None:
            from finance_agent.data.product_library import get_product_library

            self._library = get_product_library()
        return self._library

    def query_by_codes(self, codes: list[str]) -> list[dict[str, Any]]:
        return self._get_library().query_by_codes(codes)

    def search_by_name(self, name: str) -> list[dict[str, Any]]:
        return self._get_library().search_by_name(name)


class ProductAnalysisAgent(AgentProtocol):
    """把编排状态转换为确定性产品研究结果，并保留旧状态投影。"""

    agent_name = "product_analysis"

    def __init__(self, checkpointer: Any = None, *, pipeline: Any = None):
        # 保留旧编排器的构造签名；确定性专家不持有检查点或会话状态。
        del checkpointer
        self._pipeline = pipeline or ProductResearchPipeline(_LazyProductLookup())

    @staticmethod
    def _kind(message: str) -> str:
        if any(word in message for word in ("对比", "比较", "哪个好", "区别")):
            return "comparison"
        if any(word in message for word in ("深度", "全面", "透视", "分析")):
            return "deep_dive"
        return "question"

    @staticmethod
    def _codes_from_message(message: str) -> list[str]:
        return list(dict.fromkeys(re.findall(r"(?<!\d)\d{6}(?!\d)", message)))

    @staticmethod
    def _slots(state: dict[str, Any]) -> dict[str, Any]:
        context = state.get("task_context", {}) or {}
        context_slots = context.get("slots", {}) if isinstance(context, dict) else {}
        intent_slots = state.get("intent_slots", {}) or {}
        product_slots = intent_slots.get("product_analysis", {}) if isinstance(intent_slots, dict) else {}
        merged = dict(product_slots) if isinstance(product_slots, dict) else {}
        if isinstance(context_slots, dict):
            merged.update(context_slots)
        return merged

    def _request(self, state: dict[str, Any]) -> ProductResearchRequest:
        context = state.get("task_context", {}) or {}
        message = str(
            state.get("requirement", "")
            or state.get("user_message", "")
            or (context.get("requirement", "") if isinstance(context, dict) else "")
        )
        slots = self._slots(state)
        codes = [str(item).strip() for item in slots.get("product_codes", []) or [] if str(item).strip()]
        if not codes:
            codes = self._codes_from_message(message)
        names = [str(item).strip() for item in slots.get("product_names", []) or [] if str(item).strip()]
        context_profile = context.get("user_profile", {}) if isinstance(context, dict) else {}
        profile = dict(context_profile) if isinstance(context_profile, dict) else {}
        state_profile = state.get("user_profile", {}) or {}
        if isinstance(state_profile, dict):
            profile.update(state_profile)
        return ProductResearchRequest(
            kind=self._kind(message),
            product_codes=codes,
            product_names=names,
            profile=profile,
        )

    @staticmethod
    def _payload(result: ProductResearchResult) -> dict[str, Any]:
        payload = result.model_dump(mode="json")
        if not payload["evidence_ids"]:
            payload["evidence_ids"] = list(dict.fromkeys(
                evidence.fact_id
                for assessment in result.assessments
                for evidence in assessment.evidences.values()
            ))
        payload["type"] = result.kind
        payload["products"] = [item.model_dump(mode="json") for item in result.assessments]
        return payload

    @staticmethod
    def _write_facts(state: dict[str, Any], result: ProductResearchResult) -> None:
        existing = list(state.get("facts", []) or [])
        existing_ids = {
            item.fact_id if isinstance(item, FactSnapshot) else item.get("fact_id")
            for item in existing
            if isinstance(item, FactSnapshot) or isinstance(item, dict)
        }
        for assessment in result.assessments:
            for evidence in assessment.evidences.values():
                if evidence.fact_id in existing_ids:
                    continue
                existing.append(FactSnapshot(
                    fact_id=evidence.fact_id,
                    domain="product",
                    source=evidence.source,
                    fetched_at=datetime.now(timezone.utc),
                    payload={
                        "product_code": assessment.code,
                        "product_name": assessment.name,
                        "field": evidence.field,
                        "value": evidence.value,
                        "as_of": evidence.as_of,
                        "freshness": evidence.freshness,
                    },
                ))
                existing_ids.add(evidence.fact_id)
        state["facts"] = existing

    def _build_result(self, state: dict[str, Any]) -> dict[str, Any]:
        """返回已有产品结果或构造无事实的兼容空结果。"""
        current = state.get("product_analysis")
        if isinstance(current, dict) and current:
            return dict(current)
        message = str(state.get("user_message", ""))
        return {
            "schema_version": "product_research.v1",
            "type": self._kind(message),
            "product_codes": [],
            "products": [],
            "assessments": [],
            "evidence_ids": [],
            "data_quality": "critical_missing",
            "personalization_status": "research_candidate",
            "ambiguities": [],
            "report": str(state.get("agent_response", "")),
        }

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        """执行一次产品研究，不读取或写入 ReAct 会话状态。"""
        try:
            result = self._pipeline.analyze(self._request(state))
        except Exception as exc:  # noqa: BLE001
            state["product_analysis"] = {
                "schema_version": "product_research.v1",
                "type": self._kind(str(state.get("user_message", ""))),
                "product_codes": [],
                "products": [],
                "assessments": [],
                "evidence_ids": [],
                "data_quality": "critical_missing",
                "personalization_status": "research_candidate",
                "ambiguities": [],
                "report": f"产品研究暂不可用：{exc}",
            }
            state["agent_response"] = state["product_analysis"]["report"]
            state.setdefault("intent_results", {})["product_analysis"] = {
                "status": "failed",
                "content": state["agent_response"],
            }
            return state

        state["product_analysis"] = self._payload(result)
        state["agent_response"] = result.report
        self._write_facts(state, result)
        state.setdefault("intent_results", {})["product_analysis"] = {
            "status": "success" if result.data_quality == "complete" else "degraded",
            "content": result.report,
        }
        return state


__all__ = ["ProductAnalysisAgent"]
