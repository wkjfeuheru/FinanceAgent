"""关键参数抽取与入参校验：human-in-the-loop 弹窗的唯一数据源。

三件事集中在此，避免"哪些字段必填""缺参怎么问"散落到根图与前端两处：

- ``PARAM_SPECS``：每个业务领域的参数登记处（必填/可选、控件类型、可选项）。
  **必填与可选的分野是唯一事实源**：前端弹窗按它渲染，根图按它判定缺参。
- ``extract_params``：从用户消息抽取参数。确定性优先（复用股票六位代码正则、
  主题注册表、产品名抽取），**仅当必填项仍缺失时**才调用一次低温模型兜底。
  抽取失败一律降级为"未抽到"，绝不抛出。
- ``find_missing`` / ``build_form``：入参校验与追问表单/文案。

本模块只做文本解析，不调用工具、不写库：缺参的处置由根图 ``validate`` 节点用
LangGraph ``interrupt`` 完成，参数如何流向领域由 ``intent_slots_for`` 与
``merge_target_queries`` 决定。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Literal

import requests
from pydantic import BaseModel, ConfigDict, Field

from finance_agent.orchestrator.contracts import BusinessDomain

logger = logging.getLogger(__name__)

ParamKind = Literal["text", "code", "choice", "number"]
#: ``turn`` 参数只影响本轮；``profile`` 参数同时可写入长期用户画像。
ParamScope = Literal["turn", "profile"]

#: 取消追问的哨兵：前端"取消"按钮回传,``validate`` 据此收尾而非执行领域。
CANCEL_SENTINEL = "__cancel__"


@dataclass(frozen=True)
class ParamSpec:
    """一个可抽取/可填写的参数规格（前端表单字段与后端校验共用）。"""

    name: str
    label: str
    required: bool = False
    kind: ParamKind = "text"
    options: tuple[str, ...] = ()
    default: str = ""
    scope: ParamScope = "turn"
    placeholder: str = ""

    def to_field(self) -> dict[str, Any]:
        """投影为 JSON 可序列化的表单字段规格（随 SSE 响应下发）。"""
        return {
            "name": self.name,
            "label": self.label,
            "required": self.required,
            "kind": self.kind,
            "options": list(self.options),
            "default": self.default,
            "scope": self.scope,
            "placeholder": self.placeholder,
        }


# 可选项与 ``product_research/rules.py`` 的归一映射保持一致：
# 保守→R1 稳健→R2 平衡→R3 积极→R4 激进→R5；短期/中期/长期→short/medium/long。
_RISK_OPTIONS = ("保守", "稳健", "平衡", "积极", "激进")
_HORIZON_OPTIONS = ("短期", "中期", "长期")
_ANALYSIS_TYPE_OPTIONS = ("基本面", "技术面", "综合")

#: 表单展示值 → ``AnalysisRequest.analysis_type`` 的取值域。
_ANALYSIS_TYPE_TO_SLOT = {
    "基本面": "fundamental", "技术面": "technical", "综合": "both",
    "综合分析": "both", "fundamental": "fundamental",
    "technical": "technical", "both": "both",
}

STOCK_TARGET_SPEC = ParamSpec(
    name="stock_target", label="股票标的", required=True, kind="code",
    placeholder="股票名称或6位代码，如 600519",
)
PRODUCT_REFERENCE_SPEC = ParamSpec(
    name="product_reference", label="产品", required=True, kind="text",
    placeholder="基金/理财产品名称或6位代码",
)
ANALYSIS_TYPE_SPEC = ParamSpec(
    name="analysis_type", label="分析维度", kind="choice",
    options=_ANALYSIS_TYPE_OPTIONS, default="综合",
)
RISK_PREFERENCE_SPEC = ParamSpec(
    name="risk_preference", label="风险偏好", kind="choice", options=_RISK_OPTIONS,
    scope="profile", placeholder="可选，留空按非个性化研究处理",
)
HOLDING_PERIOD_SPEC = ParamSpec(
    name="holding_period", label="投资期限", kind="choice", options=_HORIZON_OPTIONS,
    scope="profile", placeholder="可选",
)

#: 各领域的完整参数登记处（含可选偏好）。空元组表示该领域无参数可缺——市场洞察
#: 的数据采集器零入参（时间窗口读配置），账户问答只需会话里的客户身份，
#: 二者都不消费用户偏好，因此永不触发追问。
PARAM_SPECS: dict[BusinessDomain, tuple[ParamSpec, ...]] = {
    BusinessDomain.STOCK_RESEARCH: (
        STOCK_TARGET_SPEC, ANALYSIS_TYPE_SPEC, RISK_PREFERENCE_SPEC, HOLDING_PERIOD_SPEC,
    ),
    BusinessDomain.PRODUCT_RESEARCH: (
        PRODUCT_REFERENCE_SPEC, RISK_PREFERENCE_SPEC, HOLDING_PERIOD_SPEC,
    ),
    BusinessDomain.MARKET_INSIGHT: (),
    BusinessDomain.ACCOUNT_PORTFOLIO: (),
}

#: 会被写入长期画像的字段（与 ``UserProfileCard`` 同名）。
PROFILE_FIELDS = ("risk_preference", "holding_period")

# A 股 6 位代码：与 ``domains/stock.py`` 同口径（此处不导入领域模块，避免把
# 研究管线/图构建拖进抽取路径）。
_CODE_RE = re.compile(r"(?<!\d)(?:60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)")
_ANY_SIX_DIGITS_RE = re.compile(r"(?<!\d)\d{6}(?!\d)")

_EXTRACT_PROMPT = """你是金融请求的参数抽取器，只从当前用户消息抽取结构化参数，不回答问题。
允许的字段（缺失一律填空字符串，不得猜测、不得编造标的）：
- stock_target：用户要研究的股票标的，填股票名称或 6 位代码
- product_reference：用户要查询的基金/理财产品，填名称或 6 位代码
- analysis_type：分析维度，只能填 基本面 / 技术面 / 综合 之一
- risk_preference：用户**自述的**风险偏好，只能填 保守 / 稳健 / 平衡 / 积极 / 激进 之一
- holding_period：用户**自述的**投资期限，只能填 短期 / 中期 / 长期 之一
只输出 JSON 对象。"""


class ExtractedParams(BaseModel):
    """一次抽取/一次回答后的参数集合：``values[domain] = {字段: 值}``。

    ``extraction_available`` 为假表示"必填缺失"这一判定**不可信**（模型未配置或
    调用失败），调用方必须放行而不弹窗——否则模型不可用会被误当成"用户没说标的"，
    反而把能正常处理的请求（如仅给股票名称、由领域自行做名称→代码解析）拦下来。
    """

    model_config = ConfigDict(extra="forbid")

    values: dict[str, dict[str, Any]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    extraction_available: bool = True

    def for_domain(self, domain: BusinessDomain) -> dict[str, Any]:
        raw = self.values.get(domain.value)
        return dict(raw) if isinstance(raw, dict) else {}

    def profile_updates(self, domains: Iterable[BusinessDomain]) -> dict[str, str]:
        """收集只该写画像的偏好字段；按领域顺序取首个非空值。"""
        out: dict[str, str] = {}
        for domain in domains:
            if not any(spec.scope == "profile" for spec in PARAM_SPECS.get(domain, ())):
                continue
            values = self.for_domain(domain)
            for name in PROFILE_FIELDS:
                value = str(values.get(name, "") or "").strip()
                if value and name not in out:
                    out[name] = value
        return out


def specs_for(domain: BusinessDomain) -> tuple[ParamSpec, ...]:
    return PARAM_SPECS.get(domain, ())


def required_specs(domain: BusinessDomain) -> tuple[ParamSpec, ...]:
    return tuple(spec for spec in specs_for(domain) if spec.required)


def _spec(domain: BusinessDomain, name: str) -> ParamSpec | None:
    for spec in specs_for(domain):
        if spec.name == name:
            return spec
    return None


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _put(values: dict[str, dict[str, Any]], domain: BusinessDomain, name: str, value: Any) -> None:
    if not _present(value):
        return
    values.setdefault(domain.value, {})[name] = value


def _clean_choice(spec: ParamSpec, raw: Any) -> str:
    """把取值归一到 ``spec.options``；不可识别返回空串（不阻塞本轮）。"""
    text = str(raw or "").strip()
    if not text:
        return ""
    for option in spec.options:
        if text == option:
            return option
    return ""


# ── 确定性抽取 ───────────────────────────────────────────────────


def _theme_in_text(message: str, registry: Any) -> str:
    """返回消息中命中的已注册主题名（最长优先），无命中返回空串。"""
    if registry is None or not message:
        return ""
    lowered = message.lower()
    try:
        entries = registry.list_themes()
    except Exception:  # noqa: BLE001 - 注册表不可用不得阻断抽取
        return ""
    for entry in entries:
        for name in sorted(entry.names(), key=len, reverse=True):
            if name and name.lower() in lowered:
                return name
    return ""


def _stock_deterministic(message: str, registry: Any) -> dict[str, Any]:
    codes = list(dict.fromkeys(_CODE_RE.findall(message or "")))
    theme = _theme_in_text(message, registry)
    out: dict[str, Any] = {}
    if codes:
        out["stock_codes"] = codes
        out["stock_target"] = codes[0]
    elif theme:
        # 存**消息中出现的主题名**而非解析后的 theme_id：领域侧
        # ``parse_analysis_request`` 会用主题注册表把它解析成 theme_id，
        # 与用户原话里的说法保持一致。
        out["theme"] = theme
        out["stock_target"] = theme
    return out


def _product_deterministic(message: str) -> dict[str, Any]:
    # 产品名抽取依赖领域模块的正则与噪声表，惰性导入避免拖入研究管线。
    try:
        from finance_agent.orchestrator.domains.product import candidate_product_names
    except Exception:  # noqa: BLE001 - 导入失败退化为仅代码抽取
        candidate_product_names = None  # type: ignore[assignment]

    codes = list(dict.fromkeys(_ANY_SIX_DIGITS_RE.findall(message or "")))
    names = list(candidate_product_names(message or "")) if candidate_product_names else []
    out: dict[str, Any] = {}
    if codes:
        out["product_codes"] = codes
        out["product_reference"] = codes[0]
    elif names:
        out["product_names"] = names
        out["product_reference"] = names[0]
    return out


def _deterministic(message: str, domain: BusinessDomain, registry: Any) -> dict[str, Any]:
    if domain is BusinessDomain.STOCK_RESEARCH:
        return _stock_deterministic(message, registry)
    if domain is BusinessDomain.PRODUCT_RESEARCH:
        return _product_deterministic(message)
    # 市场洞察与账户领域无参数可抽。
    return {}


# ── 模型兜底抽取 ─────────────────────────────────────────────────


def _default_requester() -> Callable[..., Any]:
    return requests.post


def _llm_extract(
    message: str,
    history: str,
    *,
    requester: Callable[..., Any],
    api_key: str,
    base_url: str,
    model: str,
    timeout: float,
) -> dict[str, Any]:
    """调用一次低温模型抽取参数；任何失败返回空字典（由调用方降级）。"""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _EXTRACT_PROMPT},
            {
                "role": "user",
                "content": (
                    f"近期上下文摘要：{history.strip() or '（无）'}\n"
                    f"当前用户消息：{message.strip()}"
                ),
            },
        ],
        "temperature": 0.1,
        "max_tokens": 256,
        "response_format": {"type": "json_object"},
    }
    response = requester(
        base_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=timeout,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    import json as _json

    parsed = _json.loads(content)
    return parsed if isinstance(parsed, dict) else {}


def _apply_llm_payload(
    payload: dict[str, Any],
    domains: Iterable[BusinessDomain],
    values: dict[str, dict[str, Any]],
) -> None:
    for domain in domains:
        if domain is BusinessDomain.STOCK_RESEARCH:
            _apply_stock_values(values, domain, payload)
        elif domain is BusinessDomain.PRODUCT_RESEARCH:
            _apply_product_values(values, domain, payload)
        for name in PROFILE_FIELDS:
            spec = _spec(domain, name)
            if spec is None or values.get(domain.value, {}).get(name):
                continue
            cleaned = _clean_choice(spec, payload.get(name))
            if cleaned:
                _put(values, domain, name, cleaned)


def _apply_stock_values(
    values: dict[str, dict[str, Any]], domain: BusinessDomain, payload: dict[str, Any],
) -> None:
    if values.get(domain.value, {}).get("stock_target"):
        return
    target = str(payload.get("stock_target", "") or "").strip()
    if not target:
        return
    _put(values, domain, "stock_target", target)
    if _CODE_RE.fullmatch(target):
        _put(values, domain, "stock_codes", [target])
    # 只有自由文本标的（名称）时不写槽位：名称→代码由领域既有的搜索解析完成，
    # 这里只把它并进本轮领域子请求文本（见 merge_target_queries）。
    at = str(payload.get("analysis_type", "") or "").strip()
    if at:
        _put(values, domain, "analysis_type", at)


def _apply_product_values(
    values: dict[str, dict[str, Any]], domain: BusinessDomain, payload: dict[str, Any],
) -> None:
    if values.get(domain.value, {}).get("product_reference"):
        return
    target = str(payload.get("product_reference", "") or "").strip()
    if not target:
        return
    _put(values, domain, "product_reference", target)
    if _ANY_SIX_DIGITS_RE.fullmatch(target):
        _put(values, domain, "product_codes", [target])
    else:
        _put(values, domain, "product_names", [target])


def _write_values(
    values: dict[str, dict[str, Any]], domain: BusinessDomain, raw: dict[str, Any],
) -> None:
    """把一次抽取结果写入 ``values``；确定性结果优先，不覆盖已有值。"""
    for name, value in raw.items():
        if name == "analysis_type":
            spec = _spec(domain, name)
            if spec is not None:
                _put(values, domain, name, _clean_choice(spec, value))
            continue
        if values.get(domain.value, {}).get(name):
            continue
        _put(values, domain, name, value)


def extract_params(
    message: str,
    history: str = "",
    *,
    domains: Iterable[BusinessDomain],
    requester: Callable[..., Any] | None = None,
    registry: Any = None,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float | None = None,
) -> ExtractedParams:
    """抽取各领域的参数；确定性优先，必填项仍缺时才调用一次模型兜底。

    ``requester`` 可注入（测试用假对象）；模型未配置或调用失败时只降级为
    "未抽到"，把判定结果交给调用方——**绝不因为抽取失败而抛出**。
    """
    domain_list = list(domains)
    if registry is None:
        registry = _default_registry()

    values: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for domain in domain_list:
        _write_values(values, domain, _deterministic(message, domain, registry))

    params = ExtractedParams(values=values, warnings=warnings)
    missing = find_missing(domain_list, params)
    if not missing:
        return params

    # 仅在"必填项仍缺"时才付一次模型调用；市场/账户领域没有必填项，永远走不到这。
    from finance_agent import config

    key = api_key if api_key is not None else config.INTENT_MODEL_API_KEY
    if not key or not message.strip():
        warnings.append("param_extraction_unavailable")
        return ExtractedParams(
            values=values, warnings=warnings, extraction_available=False,
        )
    try:
        payload = _llm_extract(
            message,
            history,
            requester=requester or _default_requester(),
            api_key=key,
            base_url=base_url or config.INTENT_MODEL_BASE_URL,
            model=model or config.INTENT_MODEL,
            timeout=timeout or config.INTENT_MODEL_TIMEOUT,
        )
    except Exception:  # noqa: BLE001 - 兜底失败只降级，判定权交给调用方
        logger.warning("param_extraction_failed", exc_info=True)
        warnings.append("param_extraction_failed")
        return ExtractedParams(
            values=values, warnings=warnings, extraction_available=False,
        )

    _apply_llm_payload(payload, domain_list, values)
    return ExtractedParams(values=values, warnings=warnings)


def _default_registry() -> Any:
    try:
        from finance_agent.research.theme_registry import default_theme_registry

        return default_theme_registry()
    except Exception:  # noqa: BLE001 - 主题注册表不可用只影响主题抽取
        return None


# ── 校验与追问 ───────────────────────────────────────────────────


def find_missing(
    domains: Iterable[BusinessDomain], params: ExtractedParams,
) -> dict[str, list[str]]:
    """返回每个领域缺失的**必填**字段；无缺参返回空字典。"""
    missing: dict[str, list[str]] = {}
    for domain in domains:
        values = params.for_domain(domain)
        gaps = [spec.name for spec in required_specs(domain) if not _present(values.get(spec.name))]
        if gaps:
            missing[domain.value] = gaps
    return missing


def build_question(domains: Iterable[BusinessDomain], missing: dict[str, list[str]]) -> str:
    """按缺失字段生成确定性的追问文案（服务端模板，不经过模型）。"""
    labels: list[str] = []
    for domain in domains:
        for name in missing.get(domain.value, ()):
            spec = _spec(domain, name)
            label = spec.label if spec is not None else name
            if label not in labels:
                labels.append(label)
    if not labels:
        return ""
    return "为了继续为您分析，请补充：" + "、".join(labels) + "。"


def build_form(domains: Iterable[BusinessDomain], missing: dict[str, list[str]]) -> dict[str, Any]:
    """构造弹窗所需的追问载荷：``question`` + ``fields``（含同领域可选偏好）。"""
    domain_list = list(domains)
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for domain in domain_list:
        if not missing.get(domain.value):
            continue
        for spec in specs_for(domain):
            # 同框收集可选偏好：用户可留空，必填由前端 el-form 规则拦截。
            if spec.name in seen:
                continue
            seen.add(spec.name)
            fields.append(spec.to_field())
    return {
        "question": build_question(domain_list, missing),
        "missing": [f"{dv}:{name}" for dv, names in missing.items() for name in names],
        "fields": fields,
    }


def apply_answers(
    params: ExtractedParams, answers: Any, domains: Iterable[BusinessDomain],
) -> ExtractedParams:
    """把弹窗提交的答案并入参数：只接受登记过的字段，取值非法则丢弃。"""
    if not isinstance(answers, dict):
        return params
    domain_list = list(domains)
    values = {key: dict(value) for key, value in params.values.items()}
    for domain in domain_list:
        for spec in specs_for(domain):
            if spec.name not in answers:
                continue
            raw = answers.get(spec.name)
            if spec.kind == "choice":
                cleaned: Any = _clean_choice(spec, raw)
            else:
                cleaned = str(raw or "").strip()
            if not _present(cleaned):
                continue
            _put(values, domain, spec.name, cleaned)
        _derive_slots(values, domain)
    return ExtractedParams(values=values, warnings=list(params.warnings))


def _derive_slots(values: dict[str, dict[str, Any]], domain: BusinessDomain) -> None:
    """从必填字段派生领域槽位（弹窗提交的代码要能被下游解析器看到）。"""
    if domain is BusinessDomain.STOCK_RESEARCH:
        target = str(values.get(domain.value, {}).get("stock_target", "") or "").strip()
        if target and _CODE_RE.fullmatch(target):
            values.setdefault(domain.value, {}).setdefault("stock_codes", [target])
    elif domain is BusinessDomain.PRODUCT_RESEARCH:
        target = str(values.get(domain.value, {}).get("product_reference", "") or "").strip()
        if target and _ANY_SIX_DIGITS_RE.fullmatch(target):
            values.setdefault(domain.value, {}).setdefault("product_codes", [target])


def is_cancel(answer: Any) -> bool:
    """判断恢复值是否为"放弃追问"的哨兵。"""
    if isinstance(answer, dict):
        return answer.get(CANCEL_SENTINEL) is True
    return answer == CANCEL_SENTINEL


def target_queries(domains: Iterable[BusinessDomain], params: ExtractedParams) -> dict[str, str]:
    """必填字段对应的领域子请求文本（股票标的 / 产品）。

    值直接作为领域子请求下发，由领域既有的确定性解析器（六位代码正则、
    名称→代码搜索、产品名识别）处理，因此**无需改动领域解析逻辑**。
    """
    out: dict[str, str] = {}
    for domain in domains:
        if domain is BusinessDomain.STOCK_RESEARCH:
            value = str(params.for_domain(domain).get("stock_target", "") or "").strip()
        elif domain is BusinessDomain.PRODUCT_RESEARCH:
            value = str(params.for_domain(domain).get("product_reference", "") or "").strip()
        else:
            value = ""
        if value:
            out[domain.value] = value
    return out


def merge_target_queries(
    routing: dict[str, Any],
    params: ExtractedParams,
    domains: Iterable[BusinessDomain],
) -> dict[str, Any]:
    """把必填字段并入 ``routing.domain_queries``，保持分类器子请求的上下文。

    追加而非替换：原有子请求（如"分析贵州茅台"）保留，缺的标的补在后面，
    领域解析器读到的仍是完整需求。
    """
    queries = dict(routing.get("domain_queries") or {})
    merged_any = False
    for domain_value, text in target_queries(domains, params).items():
        existing = str(queries.get(domain_value, "") or "").strip()
        combined = f"{existing} {text}".strip() if existing else text
        if combined != existing:
            queries[domain_value] = combined
            merged_any = True
    if not merged_any:
        return routing
    return {**routing, "domain_queries": queries}


def intent_slots_for(domain: BusinessDomain, params: dict[str, Any]) -> dict[str, Any]:
    """把领域参数映射为领域内既有的 ``intent_slots`` 形状。

    下游解析器按**意图名**取嵌套槽位（``request_parser._market_slots`` 取
    ``stock_analysis``/``stock_recommendation``，``domains/product._slots`` 取
    ``product_analysis``），因此这里必须产出同名嵌套结构，而不是平铺字典。

    必填的标的/产品不走槽位（已并入子请求文本，交给领域解析器），这里只处理
    没有文本等价物的字段：分析维度，以及可直接被产品解析器读取的代码/名称槽。
    """
    values = params or {}
    slots: dict[str, Any] = {}
    if domain is BusinessDomain.STOCK_RESEARCH:
        mapped = _ANALYSIS_TYPE_TO_SLOT.get(str(values.get("analysis_type", "") or "").strip())
        if mapped:
            slots["analysis_type"] = mapped
        if values.get("stock_codes"):
            slots["stock_codes"] = list(values["stock_codes"])
        if values.get("theme"):
            slots["theme"] = values["theme"]
        return {"stock_analysis": slots} if slots else {}
    if domain is BusinessDomain.PRODUCT_RESEARCH:
        if values.get("product_codes"):
            slots["product_codes"] = list(values["product_codes"])
        if values.get("product_names"):
            slots["product_names"] = list(values["product_names"])
        return {"product_analysis": slots} if slots else {}
    return {}


def profile_updates_from_answers(answers: Any) -> dict[str, str]:
    """从弹窗答案中提取可写入长期画像的偏好字段（取值非法则丢弃）。"""
    if not isinstance(answers, dict):
        return {}
    out: dict[str, str] = {}
    for name, spec in (
        ("risk_preference", RISK_PREFERENCE_SPEC),
        ("holding_period", HOLDING_PERIOD_SPEC),
    ):
        cleaned = _clean_choice(spec, answers.get(name))
        if cleaned:
            out[name] = cleaned
    return out


__all__ = [
    "CANCEL_SENTINEL",
    "ExtractedParams",
    "PARAM_SPECS",
    "PROFILE_FIELDS",
    "ParamSpec",
    "apply_answers",
    "build_form",
    "build_question",
    "extract_params",
    "find_missing",
    "intent_slots_for",
    "is_cancel",
    "merge_target_queries",
    "profile_updates_from_answers",
    "required_specs",
    "specs_for",
    "target_queries",
]
