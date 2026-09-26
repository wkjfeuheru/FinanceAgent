"""缺参追问（needs_input）的表单契约与答案应用。

领域专家改为 ReAct 后，参数提取下沉到专家内部：专家在循环中通过
``request_user_input`` 工具声明"我需要这些字段"。本模块是那套字段登记处与
表单构造／合并／答案应用的**唯一事实源**。

职责边界：

- ``FieldSpec`` / ``EXPERT_FIELDS``：每域可声明的字段规格（控件类型、可选项、
  是否写入长期画像）。**字段定义由专家侧声明，模型只能引用字段名**——它没有
  权力发明字段或改写控件类型，因此弹窗内容始终是服务端确定性模板。
- ``build_form`` / ``merge_forms``：把一个或多个领域的缺参合并成**一张**弹窗
  表单（``{question, missing, fields}``），契约与旧 ``routing/params.py``
  完全同构，前端零改动（``missing`` 为 ``"{domain}:{field}"``，``fields[].name``
  为裸字段名，答案按裸字段名回传）。
- ``apply_answers``：把弹窗答案并入 ``clarification_answers``，供专家重跑时读取。
- ``profile_updates``：把 ``scope="profile"`` 的偏好字段交付长期画像持久化。

本模块只做纯数据变换，不调模型、不写库、不读图状态。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal

from finance_agent.orchestration.contracts import BusinessDomain

FieldKind = Literal["text", "code", "choice", "number"]
#: ``turn`` 参数只影响本轮；``profile`` 参数同时可写入长期用户画像。
FieldScope = Literal["turn", "profile"]

#: 取消追问的哨兵：前端"取消"按钮回传；supervisor 的 ``ask`` 节点据此收尾而非重跑领域。
#: 保留与旧 ``routing/params.py`` 相同的字面量——``AdvisorSystem._invoke_with_resume``
#: 用它取消挂起 run，历史 checkpoint 里也可能残留该值。
CANCEL_SENTINEL = "__cancel__"


@dataclass(frozen=True)
class FieldSpec:
    """一个可追问的字段规格（前端表单字段与后端合并逻辑共用）。"""

    name: str
    label: str
    required: bool = False
    kind: FieldKind = "text"
    options: tuple[str, ...] = ()
    default: str = ""
    scope: FieldScope = "turn"
    placeholder: str = ""

    def to_field(self) -> dict[str, Any]:
        """投影为 JSON 可序列化的表单字段规格（随响应下发）。"""
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

STOCK_TARGET_FIELD = FieldSpec(
    name="stock_target", label="股票标的", required=True, kind="code",
    placeholder="股票名称或6位代码，如 600519",
)
PRODUCT_REFERENCE_FIELD = FieldSpec(
    name="product_reference", label="产品", required=True, kind="text",
    placeholder="基金/理财产品名称或6位代码",
)
ANALYSIS_TYPE_FIELD = FieldSpec(
    name="analysis_type", label="分析维度", kind="choice",
    options=_ANALYSIS_TYPE_OPTIONS, default="综合",
)
RISK_PREFERENCE_FIELD = FieldSpec(
    name="risk_preference", label="风险偏好", kind="choice", options=_RISK_OPTIONS,
    scope="profile", placeholder="可选，留空按非个性化研究处理",
)
HOLDING_PERIOD_FIELD = FieldSpec(
    name="holding_period", label="投资期限", kind="choice", options=_HORIZON_OPTIONS,
    scope="profile", placeholder="可选",
)

#: 各领域**允许追问**的字段登记处。空元组表示该领域没有可追问字段——市场洞察的
#: 采集器零入参（时间窗口读配置），账户问答只需会话里的客户身份，二者都不会缺参。
EXPERT_FIELDS: dict[BusinessDomain, tuple[FieldSpec, ...]] = {
    BusinessDomain.STOCK_RESEARCH: (
        STOCK_TARGET_FIELD, ANALYSIS_TYPE_FIELD,
        RISK_PREFERENCE_FIELD, HOLDING_PERIOD_FIELD,
    ),
    BusinessDomain.PRODUCT_RESEARCH: (
        PRODUCT_REFERENCE_FIELD, RISK_PREFERENCE_FIELD, HOLDING_PERIOD_FIELD,
    ),
    BusinessDomain.MARKET_INSIGHT: (),
    BusinessDomain.ACCOUNT_PORTFOLIO: (),
}

#: 会被写入长期画像的字段（与 ``UserProfileCard`` 同名）。
PROFILE_FIELDS = ("risk_preference", "holding_period")

_DOMAIN_LABELS: dict[BusinessDomain, str] = {
    BusinessDomain.STOCK_RESEARCH: "股票",
    BusinessDomain.MARKET_INSIGHT: "市场",
    BusinessDomain.PRODUCT_RESEARCH: "产品",
    BusinessDomain.ACCOUNT_PORTFOLIO: "账户",
}


def fields_for(domain: BusinessDomain) -> tuple[FieldSpec, ...]:
    return EXPERT_FIELDS.get(domain, ())


def field_spec(domain: BusinessDomain, name: str) -> FieldSpec | None:
    for spec in fields_for(domain):
        if spec.name == name:
            return spec
    return None


def domain_label(domain: BusinessDomain) -> str:
    return _DOMAIN_LABELS.get(domain, domain.value)


def known_field_names(domain: BusinessDomain) -> tuple[str, ...]:
    return tuple(spec.name for spec in fields_for(domain))


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def clean_choice(spec: FieldSpec, raw: Any) -> str:
    """把取值归一到 ``spec.options``；不可识别返回空串（不阻塞本轮）。"""
    text = str(raw or "").strip()
    if not text:
        return ""
    for option in spec.options:
        if text == option:
            return option
    return ""


def build_question(requests: Iterable[tuple[BusinessDomain, tuple[str, ...]]]) -> str:
    """按缺失字段生成确定性的追问文案（服务端模板，不经过模型）。"""
    labels: list[str] = []
    for domain, names in requests:
        for name in names:
            spec = field_spec(domain, name)
            label = spec.label if spec is not None else name
            if label not in labels:
                labels.append(label)
    if not labels:
        return ""
    return "为了继续为您分析，请补充：" + "、".join(labels) + "。"


def build_form(
    requests: Iterable[tuple[BusinessDomain, tuple[str, ...]]],
) -> dict[str, Any] | None:
    """把 (领域, 缺失字段名) 列表合并为一张弹窗表单；无缺参返回 None。

    表单形状与旧 ``routing/params.py.build_form`` 完全一致：
    ``missing`` 用 ``"{domain}:{field}"`` 便于定位；``fields`` 收集同领域的
    可选偏好字段一同展示（用户可留空，必填由前端表单规则拦截）。
    """
    request_list = [(domain, tuple(names)) for domain, names in requests if names]
    if not request_list:
        return None

    fields: list[dict[str, Any]] = []
    missing: list[str] = []
    seen: set[str] = set()
    for domain, names in request_list:
        if not names:
            continue
        for spec in fields_for(domain):
            # 同框收集可选偏好：用户可留空，必填由前端 el-form 规则拦截。
            if spec.name in seen:
                continue
            seen.add(spec.name)
            fields.append(spec.to_field())
        missing.extend(f"{domain.value}:{name}" for name in names)

    return {
        "question": build_question(request_list),
        "missing": missing,
        "fields": fields,
    }


def merge_forms(forms: Iterable[dict[str, Any] | None]) -> dict[str, Any] | None:
    """把多张缺参表单合并为一张（去重字段与 missing 条目）。"""
    merged_fields: list[dict[str, Any]] = []
    merged_missing: list[str] = []
    questions: list[str] = []
    seen_fields: set[str] = set()
    seen_missing: set[str] = set()
    for form in forms:
        if not isinstance(form, dict):
            continue
        for entry in form.get("missing") or []:
            text = str(entry)
            if text and text not in seen_missing:
                seen_missing.add(text)
                merged_missing.append(text)
        for field in form.get("fields") or []:
            if not isinstance(field, dict):
                continue
            name = str(field.get("name", ""))
            if not name or name in seen_fields:
                continue
            seen_fields.add(name)
            merged_fields.append(dict(field))
        question = str(form.get("question", "") or "").strip()
        if question and question not in questions:
            questions.append(question)
    if not merged_fields and not merged_missing:
        return None
    return {
        "question": questions[0] if questions else "",
        "missing": merged_missing,
        "fields": merged_fields,
    }


def apply_answers(
    answers: Any,
    *,
    domains: Iterable[BusinessDomain],
) -> dict[str, Any]:
    """把弹窗答案归一化为 ``{字段名: 值}``（只接受登记字段，取值非法则丢弃）。

    答案键兼容两种写法：裸字段名（前端实际提交的形态）与 ``"{domain}:{field}"``
    （``missing`` 列表的形态），便于恢复路径与手工调用。
    """
    if not isinstance(answers, dict):
        return {}
    out: dict[str, Any] = {}
    for domain in domains:
        for spec in fields_for(domain):
            raw = answers.get(spec.name)
            if raw is None:
                raw = answers.get(f"{domain.value}:{spec.name}")
            if raw is None:
                continue
            if spec.kind == "choice":
                cleaned: Any = clean_choice(spec, raw)
            else:
                cleaned = str(raw or "").strip()
            if _present(cleaned):
                out.setdefault(spec.name, cleaned)
    return out


def is_cancel(answer: Any) -> bool:
    """判断恢复值是否为"放弃追问"的哨兵。"""
    if isinstance(answer, dict):
        return answer.get(CANCEL_SENTINEL) is True
    return answer == CANCEL_SENTINEL


def profile_updates(answers: Any) -> dict[str, str]:
    """从弹窗答案中提取可写入长期画像的偏好字段（取值非法则丢弃）。"""
    if not isinstance(answers, dict):
        return {}
    out: dict[str, str] = {}
    for name in PROFILE_FIELDS:
        spec = next(
            (spec for specs in EXPERT_FIELDS.values() for spec in specs if spec.name == name),
            None,
        )
        if spec is None:
            continue
        cleaned = clean_choice(spec, answers.get(name))
        if cleaned:
            out[name] = cleaned
    return out


__all__ = [
    "CANCEL_SENTINEL",
    "EXPERT_FIELDS",
    "FieldKind",
    "FieldScope",
    "FieldSpec",
    "PROFILE_FIELDS",
    "apply_answers",
    "build_form",
    "build_question",
    "clean_choice",
    "domain_label",
    "field_spec",
    "fields_for",
    "is_cancel",
    "known_field_names",
    "merge_forms",
    "profile_updates",
]
