"""无状态确定性产品研究流水线。"""

from __future__ import annotations

from typing import Any

from .contracts import (
    ProductAssessment,
    ProductFieldEvidence,
    ProductResearchRequest,
    ProductResearchResult,
    ProductSnapshot,
)
from .resolver import ProductLookup, ProductReferenceResolver
from .rules import evaluate_suitability, normalize_horizon, normalize_profile_risk, normalize_risk


def _section_value(product: dict[str, Any], key: str) -> dict[str, Any]:
    value = product.get(key, {})
    return dict(value) if isinstance(value, dict) else {}


def _evidence(code: str, field: str, section: dict[str, Any], value: Any) -> ProductFieldEvidence:
    freshness = section.get("freshness", "unknown")
    if freshness not in {"fresh", "stale", "unknown"}:
        freshness = "unknown"
    return ProductFieldEvidence(
        field=field,
        value=value,
        source=str(section.get("source", "postgresql") or "postgresql"),
        as_of=str(section.get("as_of", "") or ""),
        freshness=freshness,
        fact_id=f"product:{code}:{field}",
    )


def _build_snapshot(product: dict[str, Any]) -> ProductSnapshot:
    basic = _section_value(product, "basic_info")
    fee = _section_value(product, "fee")
    holdings = _section_value(product, "holdings")
    performance = _section_value(product, "performance")
    code = str(basic.get("code", "") or "").strip()
    name = str(basic.get("name", "") or "").strip()
    evidences = {
        "basic_info": _evidence(code, "basic_info", basic, basic),
        "risk_level": _evidence(code, "risk_level", basic, basic.get("risk_level")),
        "recommended_holding_period": _evidence(
            code, "recommended_holding_period", basic, basic.get("recommended_holding_period"),
        ),
        "fee": _evidence(code, "fee", fee, fee),
        "holdings": _evidence(code, "holdings", holdings, holdings.get("top10", [])),
        "performance": _evidence(code, "performance", performance, performance),
    }
    missing: list[str] = []
    if not normalize_risk(basic.get("risk_level")):
        missing.append("risk_level")
    if not performance or performance.get("return_1y") is None:
        missing.append("performance.return_1y")
    if not str(basic.get("recommended_holding_period", "") or "").strip():
        missing.append("recommended_holding_period")
    restrictions: list[str] = []
    for field in ("holdings", "performance"):
        if evidences[field].freshness == "stale":
            as_of = f"（截至 {evidences[field].as_of}）" if evidences[field].as_of else ""
            restrictions.append(f"{field} 数据陈旧{as_of}，不得据此生成结论")
    return ProductSnapshot(
        code=code,
        name=name,
        basic_info=basic,
        fee=fee,
        holdings=holdings,
        performance=performance,
        evidences=evidences,
        missing_fields=missing,
        restrictions=restrictions,
    )


class ProductResearchPipeline:
    """把产品事实转换为不含交易指令的结构化研究结果。"""

    def __init__(self, lookup: ProductLookup, resolver: ProductReferenceResolver | None = None):
        self._lookup = lookup
        self._resolver = resolver or ProductReferenceResolver(lookup)

    def analyze(self, request: ProductResearchRequest) -> ProductResearchResult:
        references, ambiguities = self._resolver.resolve(request.product_codes, request.product_names)
        codes = [reference.code for reference in references]
        products = self._lookup.query_by_codes(codes) if codes else []
        snapshots: list[ProductSnapshot] = []
        for item in products:
            snapshot = _build_snapshot(item)
            if snapshot.code:
                snapshots.append(snapshot)

        assessments: list[ProductAssessment] = []
        for snapshot in snapshots:
            risk_level = normalize_risk(snapshot.basic_info.get("risk_level"))
            suitability_status, suitability_reasons = evaluate_suitability(
                risk_level=risk_level,
                recommended_holding_period=snapshot.basic_info.get("recommended_holding_period"),
                profile=request.profile,
            )
            performance = snapshot.evidences["performance"]
            usable = (
                performance.freshness == "fresh"
                and snapshot.performance.get("return_1y") is not None
            )
            assessments.append(ProductAssessment(
                code=snapshot.code,
                name=snapshot.name,
                evidences=snapshot.evidences,
                risk_level=risk_level,
                risk_source="产品库" if risk_level else "",
                suitability_status=suitability_status,
                suitability_reasons=suitability_reasons,
                usable_for_comparison=usable,
                missing_fields=list(snapshot.missing_fields),
                restrictions=list(snapshot.restrictions),
            ))

        personalization = (
            "personalized"
            if normalize_profile_risk(request.profile.get("risk_preference"))
            and normalize_horizon(request.profile.get("holding_period"))
            else "research_candidate"
        )
        has_warning = bool(ambiguities or any(
            item.missing_fields
            or item.restrictions
            or item.risk_level is None
            or item.suitability_status == "unavailable"
            for item in assessments
        ))
        quality = "critical_missing" if not assessments else "warning" if has_warning else "complete"
        evidence_ids = list(dict.fromkeys(
            evidence.fact_id
            for assessment in assessments
            for evidence in assessment.evidences.values()
        ))
        report = self._render(request, assessments, ambiguities, quality)
        return ProductResearchResult(
            kind=request.kind,
            product_codes=[item.code for item in assessments],
            assessments=assessments,
            report=report,
            data_quality=quality,
            personalization_status=personalization,
            evidence_ids=evidence_ids,
            ambiguities=ambiguities,
        )

    @staticmethod
    def _render(
        request: ProductResearchRequest,
        assessments: list[ProductAssessment],
        ambiguities: list[str],
        quality: str,
    ) -> str:
        if not assessments:
            if ambiguities:
                return f"无法唯一确定产品：{'、'.join(ambiguities)}，请提供产品代码。"
            return "产品库暂无该产品数据。"
        lines: list[str] = []
        if ambiguities:
            lines.append(f"以下产品名称存在多个候选，未纳入分析：{'、'.join(ambiguities)}。")
        for assessment in assessments:
            lines.append(f"{assessment.name or '未命名产品'}（{assessment.code}）")
            lines.append(f"风险等级：{assessment.risk_level or '数据不足'}。")
            performance = assessment.evidences["performance"]
            if performance.freshness == "stale":
                as_of = f"（截至 {performance.as_of}）" if performance.as_of else ""
                lines.append(f"业绩数据已陈旧{as_of}，不据此形成收益或比较结论。")
            elif assessment.usable_for_comparison:
                value = performance.value.get("return_1y")
                lines.append(f"近一年收益：{value}。")
            else:
                lines.append("近一年收益：数据不足。")
            if assessment.suitability_status == "matched":
                lines.append("个人适配：匹配。")
            elif assessment.suitability_status == "unmatched":
                lines.append("个人适配：不匹配。")
            elif assessment.suitability_status == "unavailable":
                lines.append("个人适配：数据不足，无法判断。")
            else:
                lines.append("当前仅提供非个性化研究候选，不进行个人适配判断。")
            if assessment.restrictions:
                lines.append("限制：" + "；".join(assessment.restrictions) + "。")
            if assessment.missing_fields:
                lines.append("缺失字段：" + "、".join(assessment.missing_fields) + "。")
        if request.kind == "comparison" and len(assessments) > 1:
            if all(item.usable_for_comparison for item in assessments):
                lines.append("横向比较：各产品近一年收益数据均为新鲜数据，可进行事实比较。")
            else:
                lines.append("横向比较：存在数据陈旧或缺失项，不形成完整收益比较结论。")
        if quality == "warning":
            lines.append("提示：部分字段存在缺失或新鲜度限制，请以产品库来源和数据日期为准。")
        return "\n".join(lines)
