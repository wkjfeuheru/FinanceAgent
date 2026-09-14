"""产品领域子图（设计 §6.4）。

产品节点调用既有 ``ProductResearchPipeline`` 与产品库工具，统一投影为
``DomainOutcome``；失败返回安全 limitations，不伪造产品结论。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from finance_agent.orchestrator.contracts import BusinessDomain, DomainTaskContext
from finance_agent.orchestrator.domains.base import (
    DomainOperation,
    OperationResult,
    build_domain_graph,
    context_text,
)

_PRODUCT_CODE = re.compile(r"[A-Z]{0,2}\d{4,6}")


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


def _product_lookup(context: DomainTaskContext, pipeline: Any) -> OperationResult:
    from finance_agent.product_research.contracts import ProductResearchRequest

    text = f"{context.task.goal} {context.task.instruction}"
    codes = _codes(text)
    request = ProductResearchRequest(kind="question", product_codes=codes)
    result = pipeline.analyze(request)
    payload = _payload(result)
    summary = str(result.report or "").strip() or "已完成产品解读。"
    limitations = list(getattr(result, "ambiguities", []) or [])
    status = "success" if payload.get("assessments") else "partial"
    return OperationResult(
        structured_data={"product_analysis": payload},
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


__all__ = ["ProductDomainDeps", "build_product_domain_graph", "default_product_operations"]
