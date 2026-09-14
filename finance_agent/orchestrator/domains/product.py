"""产品领域子图（设计 §6.4）。

产品节点调用既有 ``ProductResearchPipeline`` 与产品库工具，统一投影为
``DomainOutcome``；失败返回安全 limitations，不伪造产品结论。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from finance_agent.contracts import FactSnapshot
from finance_agent.orchestrator.contracts import BusinessDomain, DomainTaskContext
from finance_agent.orchestrator.domains.base import (
    DomainOperation,
    OperationResult,
    build_domain_graph,
    context_text,
)

_PRODUCT_CODE = re.compile(r"[A-Z]{0,2}\d{4,6}")
_MESSAGE_CODE = re.compile(r"(?<!\d)\d{6}(?!\d)")

# 产品名抽取的噪声前缀：中文无分词，请求短语会被贪婪正则一起吃进产品名。
_PRODUCT_NAME_NOISE = (
    "帮我看看", "帮我推荐", "帮我查查", "帮我", "给我推荐", "给我看看", "给我",
    "我想了解", "我想知道", "我想", "请问", "请帮我", "请分析", "请对比", "请",
    "看看", "了解", "分析一下", "对比一下", "比较一下", "分析", "对比", "比较",
    "推荐几只", "推荐几个", "推荐", "了解一下",
    "哪些", "什么", "几只", "几个", "一些", "一只", "一支", "一下", "怎么样", "如何",
)
_PRODUCT_SUFFIXES = ("基金", "ETF", "etf", "债基", "指数", "产品")


@dataclass
class ProductDomainDeps:
    """产品领域确定性依赖；lookup/pipeline 可注入以便测试。"""

    pipeline: Any = None
    lookup: Any = None
    resolver: Any = None

    def build_pipeline(self) -> Any:
        if self.pipeline is not None:
            return self.pipeline
        from finance_agent.product_research.pipeline import ProductResearchPipeline

        return ProductResearchPipeline(self.lookup or _lazy_product_lookup())


class _LazyProductLookup:
    def __init__(self) -> None:
        self._library = None

    def _get(self):
        if self._library is None:
            from finance_agent.data.product_library import get_product_library

            self._library = get_product_library()
        return self._library

    def query_by_codes(self, codes):
        return self._get().query_by_codes(codes)

    def search_by_name(self, name):
        return self._get().search_by_name(name)


def _lazy_product_lookup() -> _LazyProductLookup:
    return _LazyProductLookup()


def _codes(text: str) -> list[str]:
    return list(dict.fromkeys(_PRODUCT_CODE.findall(text.upper())))


def _kind(message: str) -> str:
    if any(word in message for word in ("对比", "比较", "哪个好", "区别")):
        return "comparison"
    if any(word in message for word in ("深度", "全面", "透视", "分析")):
        return "deep_dive"
    return "question"


def _codes_from_message(message: str) -> list[str]:
    return list(dict.fromkeys(_MESSAGE_CODE.findall(message)))


def _strip_product_noise(token: str) -> str:
    """反复剥离请求噪声前缀与连词，返回候选产品名。"""
    text = token.strip()
    changed = True
    while changed and text:
        changed = False
        for noise in sorted(_PRODUCT_NAME_NOISE, key=len, reverse=True):
            if text.startswith(noise):
                text = text[len(noise):].strip()
                changed = True
                break
        else:
            for sep in ("和", "与", "及", "、"):
                if text.startswith(sep):
                    text = text[len(sep):].strip()
                    changed = True
                    break
    return text


def candidate_product_names(message: str) -> list[str]:
    """从消息中抽取产品名候选，剥离请求噪声并剔除只剩类型词的空壳。"""
    if not message:
        return []
    parts = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,12}(?:基金|ETF|债基|指数|产品)", message)
    cleaned: list[str] = []
    for raw in parts:
        name = _strip_product_noise(raw)
        suffix = next((s for s in _PRODUCT_SUFFIXES if name.endswith(s)), None)
        if suffix is None or len(name) <= len(suffix):
            continue
        cleaned.append(name)
    return list(dict.fromkeys(cleaned))[:5]


def _slots(state: dict[str, Any]) -> dict[str, Any]:
    context = state.get("task_context", {}) or {}
    context_slots = context.get("slots", {}) if isinstance(context, dict) else {}
    intent_slots = state.get("intent_slots", {}) or {}
    product_slots = intent_slots.get("product_analysis", {}) if isinstance(intent_slots, dict) else {}
    merged = dict(product_slots) if isinstance(product_slots, dict) else {}
    if isinstance(context_slots, dict):
        merged.update(context_slots)
    return merged


def build_product_request(state: dict[str, Any]) -> Any:
    """把状态/消息转换为 ``ProductResearchRequest``。"""
    from finance_agent.product_research.contracts import ProductResearchRequest

    context = state.get("task_context", {}) or {}
    message = str(
        state.get("requirement", "")
        or state.get("user_message", "")
        or (context.get("requirement", "") if isinstance(context, dict) else "")
    )
    slots = _slots(state)
    codes = [str(item).strip() for item in slots.get("product_codes", []) or [] if str(item).strip()]
    if not codes:
        codes = _codes_from_message(message)
    names = [str(item).strip() for item in slots.get("product_names", []) or [] if str(item).strip()]
    if not names and not codes:
        names = candidate_product_names(message)
    context_profile = context.get("user_profile", {}) if isinstance(context, dict) else {}
    profile = dict(context_profile) if isinstance(context_profile, dict) else {}
    state_profile = state.get("user_profile", {}) or {}
    if isinstance(state_profile, dict):
        profile.update(state_profile)
    return ProductResearchRequest(
        kind=_kind(message),
        product_codes=codes,
        product_names=names,
        profile=profile,
    )


def _payload(result: Any) -> dict[str, Any]:
    payload = result.model_dump(mode="json")
    if not payload.get("evidence_ids"):
        payload["evidence_ids"] = list(dict.fromkeys(
            evidence.fact_id
            for assessment in result.assessments
            for evidence in assessment.evidences.values()
        ))
    payload["type"] = result.kind
    payload["products"] = [item.model_dump(mode="json") for item in result.assessments]
    return payload


def _write_facts(state: dict[str, Any], result: Any) -> None:
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


def invoke_product(deps: ProductDomainDeps, state: dict[str, Any]) -> dict[str, Any]:
    """执行一次产品研究并写回旧状态字段；失败给固定安全文案。"""
    pipeline = deps.build_pipeline()
    try:
        result = pipeline.analyze(build_product_request(state))
    except Exception:  # noqa: BLE001 - 失败只给固定文案，细节进日志
        import logging

        logging.getLogger(__name__).exception(
            "产品研究失败 requirement=%s",
            state.get("requirement") or state.get("user_message"),
        )
        state["product_analysis"] = {
            "schema_version": "product_research.v1",
            "type": _kind(str(state.get("user_message", ""))),
            "product_codes": [], "products": [], "assessments": [], "evidence_ids": [],
            "data_quality": "critical_missing",
            "personalization_status": "research_candidate",
            "ambiguities": [],
            "report": "产品研究暂不可用，请稍后重试。",
        }
        state["agent_response"] = state["product_analysis"]["report"]
        state.setdefault("intent_results", {})["product_analysis"] = {
            "status": "failed", "content": state["agent_response"],
        }
        return state

    state["product_analysis"] = _payload(result)
    state["agent_response"] = result.report
    _write_facts(state, result)
    state.setdefault("intent_results", {})["product_analysis"] = {
        "status": "success" if result.data_quality == "complete" else "degraded",
        "content": result.report,
    }
    return state


def _product_lookup(context: DomainTaskContext, pipeline: Any) -> OperationResult:
    state = {
        "requirement": context.task.goal,
        "user_message": context.user_message,
        "intent_slots": {},
        "user_profile": {},
        "facts": [],
    }
    result_state = invoke_product(ProductDomainDeps(pipeline=pipeline), state)
    payload = result_state.get("product_analysis", {}) or {}
    summary = str(result_state.get("agent_response", "") or "").strip() or "已完成产品解读。"
    limitations = list(payload.get("ambiguities", []) or [])
    intent_status = (result_state.get("intent_results", {}) or {}).get(
        "product_analysis", {}
    ).get("status")
    status = {"success": "success", "degraded": "partial", "failed": "failed"}.get(
        intent_status, "partial"
    )
    if status == "failed":
        # 失败原因只登记安全标识，绝不回传原始异常文本。
        limitations.append("product_pipeline_failed")
    structured: dict[str, Any] = {"product_analysis": payload}
    facts = result_state.get("facts", []) or []
    if facts:
        structured["facts"] = [
            fact.model_dump(mode="json") if hasattr(fact, "model_dump") else fact
            for fact in facts
        ]
    return OperationResult(
        structured_data=structured,
        summary=summary,
        status=status,
        limitations=limitations,
    )


def default_product_operations(deps: ProductDomainDeps | None = None) -> list[DomainOperation]:
    deps = deps or ProductDomainDeps()
    pipeline = deps.build_pipeline()
    return [
        DomainOperation(
            name="product_lookup",
            modes=frozenset({"product_lookup", "product_evaluation", "question"}),
            handler=lambda context: _product_lookup(context, pipeline),
        )
    ]


def build_product_domain_graph(operations=None, *, deps: ProductDomainDeps | None = None):
    """编译产品领域子图；默认白名单为产品查询/评估。"""
    return build_domain_graph(
        BusinessDomain.PRODUCT_RESEARCH,
        operations or default_product_operations(deps),
        default_mode="product_lookup",
    )


__all__ = [
    "ProductDomainDeps",
    "build_product_domain_graph",
    "build_product_request",
    "candidate_product_names",
    "default_product_operations",
    "invoke_product",
]
