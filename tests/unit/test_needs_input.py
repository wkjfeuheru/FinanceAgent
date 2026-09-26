"""缺参表单契约：字段登记、表单构造/合并、答案应用、画像字段与取消哨兵。

本文件取代已删除的 ``tests/test_param_extraction.py``。旧 ``routing/params.py``
（``ExtractedParams`` / ``extract_params`` / ``PARAM_SPECS``）被整体删除，参数
提取下沉到领域专家 ReAct 循环；但两条业务不变量仍必须被钉住：

1. **表单形状**：``missing`` 用 ``"{domain}:{field}"`` 便于定位，``fields[].name``
   是裸字段名、答案按裸字段名回传（前端弹窗零改动）；
2. **画像字段持久化**：``risk_preference`` / ``holding_period`` 标记为 profile
   作用域，可从弹窗答案提取用于长期画像。

唯一事实源是 ``finance_agent.orchestration.needs_input``。
"""

from __future__ import annotations

import json

import pytest

from finance_agent.orchestration.contracts import BusinessDomain
from finance_agent.orchestration.needs_input import (
    CANCEL_SENTINEL,
    EXPERT_FIELDS,
    PROFILE_FIELDS,
    FieldSpec,
    apply_answers,
    build_form,
    build_question,
    clean_choice,
    fields_for,
    is_cancel,
    known_field_names,
    merge_forms,
    profile_updates,
)


# ── 登记表 ───────────────────────────────────────────────────────


def test_every_business_domain_is_registered():
    """三个业务领域都必须在字段登记表里出现（含空元组的账户）。"""
    assert set(EXPERT_FIELDS) == set(BusinessDomain)


def test_account_has_no_askable_fields():
    """账户问答没有可追问字段：永不因缺参弹窗。"""
    assert fields_for(BusinessDomain.ACCOUNT_PORTFOLIO) == ()
    assert known_field_names(BusinessDomain.ACCOUNT_PORTFOLIO) == ()


def test_stock_target_is_the_only_required_field():
    """只有股票标的与产品引用是必填；其余字段可选。"""
    stock_required = [
        spec.name for spec in fields_for(BusinessDomain.STOCK_RESEARCH) if spec.required
    ]
    product_required = [
        spec.name for spec in fields_for(BusinessDomain.PRODUCT_RESEARCH) if spec.required
    ]
    assert stock_required == ["stock_target"]
    assert product_required == ["product_reference"]


def test_profile_fields_are_optional_and_profile_scoped():
    """风险偏好与投资期限是可选字段，且标记为可写长期画像。"""
    for domain in (BusinessDomain.STOCK_RESEARCH, BusinessDomain.PRODUCT_RESEARCH):
        profile_specs = [spec for spec in fields_for(domain) if spec.scope == "profile"]
        assert {spec.name for spec in profile_specs} == set(PROFILE_FIELDS)
        assert all(not spec.required for spec in profile_specs)


def test_form_field_projection_is_json_serializable():
    """表单字段投影必须可 JSON 序列化（随 SSE 下发）。"""
    field = FieldSpec(name="x", label="X", required=True).to_field()
    assert json.loads(json.dumps(field))["required"] is True


# ── 表单构造 ─────────────────────────────────────────────────────


def test_build_form_uses_domain_scoped_missing_and_bare_field_names():
    """``missing`` 是 ``{domain}:{field}``；``fields[].name`` 是裸字段名。"""
    form = build_form([(BusinessDomain.STOCK_RESEARCH, ("stock_target",))])

    names = [field["name"] for field in form["fields"]]
    assert names == ["stock_target", "analysis_type", "risk_preference", "holding_period"]
    assert "stock_research:stock_target" not in names
    assert form["missing"] == ["stock_research:stock_target"]
    assert "股票标的" in form["question"]


def test_build_form_includes_optional_profile_fields_with_required_flag():
    """弹窗同框收集可选偏好：必填与可选都在 fields 里，必填标注 required。"""
    form = build_form([(BusinessDomain.STOCK_RESEARCH, ("stock_target",))])

    required = {field["name"]: field["required"] for field in form["fields"]}
    assert required["stock_target"] is True
    assert required["risk_preference"] is False


def test_build_form_returns_none_when_nothing_missing():
    """无缺参返回 None（不发空弹窗）。"""
    assert build_form([]) is None
    assert build_form([(BusinessDomain.STOCK_RESEARCH, ())]) is None
    assert build_form([(BusinessDomain.ACCOUNT_PORTFOLIO, ())]) is None


def test_build_question_is_deterministic_template():
    question = build_question([
        (BusinessDomain.STOCK_RESEARCH, ("stock_target",)),
        (BusinessDomain.PRODUCT_RESEARCH, ("product_reference",)),
    ])

    assert "股票标的" in question and "产品" in question


# ── 表单合并 ─────────────────────────────────────────────────────


def test_merge_forms_dedupes_fields_and_missing():
    stock = build_form([(BusinessDomain.STOCK_RESEARCH, ("stock_target",))])
    product = build_form([(BusinessDomain.PRODUCT_RESEARCH, ("product_reference",))])

    merged = merge_forms([stock, product])

    assert set(merged["missing"]) == {
        "stock_research:stock_target", "product_research:product_reference",
    }
    names = [field["name"] for field in merged["fields"]]
    # risk_preference / holding_period 两域同框，只应出现一次。
    assert names.count("risk_preference") == 1
    assert names.count("holding_period") == 1
    assert "stock_target" in names and "product_reference" in names


def test_merge_forms_ignores_none_entries():
    stock = build_form([(BusinessDomain.STOCK_RESEARCH, ("stock_target",))])

    assert merge_forms([None, stock, None]) == merge_forms([stock])
    assert merge_forms([None, None]) is None


# ── 答案应用 ─────────────────────────────────────────────────────


def test_apply_answers_accepts_bare_field_names():
    merged = apply_answers(
        {"stock_target": "600519"}, domains=[BusinessDomain.STOCK_RESEARCH],
    )

    assert merged == {"stock_target": "600519"}


def test_apply_answers_accepts_domain_scoped_field_names():
    """恢复路径/手工调用可能用 ``missing`` 里的 ``{domain}:{field}`` 形态。"""
    merged = apply_answers(
        {"stock_research:stock_target": "600519"},
        domains=[BusinessDomain.STOCK_RESEARCH],
    )

    assert merged == {"stock_target": "600519"}


def test_apply_answers_ignores_unregistered_fields():
    merged = apply_answers(
        {"stock_target": "600519", "evil_field": "x"},
        domains=[BusinessDomain.STOCK_RESEARCH],
    )

    assert "evil_field" not in merged


def test_apply_answers_drops_unknown_choice_value():
    merged = apply_answers(
        {"stock_target": "600519", "risk_preference": "未知偏好"},
        domains=[BusinessDomain.STOCK_RESEARCH],
    )

    assert "risk_preference" not in merged


def test_apply_answers_keeps_valid_choice_value():
    merged = apply_answers(
        {"risk_preference": "保守"}, domains=[BusinessDomain.STOCK_RESEARCH],
    )

    assert merged == {"risk_preference": "保守"}


def test_apply_answers_does_not_leak_across_domains():
    """只保留所给领域登记的字段，答案不得串域。"""
    merged = apply_answers(
        {"stock_target": "600519"},
        domains=[BusinessDomain.PRODUCT_RESEARCH],
    )

    assert merged == {}


def test_apply_answers_handles_non_dict():
    assert apply_answers(None, domains=[BusinessDomain.STOCK_RESEARCH]) == {}
    assert apply_answers("nope", domains=[BusinessDomain.STOCK_RESEARCH]) == {}


def test_clean_choice_is_lenient_on_unknown():
    spec = next(s for s in fields_for(BusinessDomain.STOCK_RESEARCH) if s.name == "analysis_type")
    assert clean_choice(spec, "技术面") == "技术面"
    assert clean_choice(spec, "不存在") == ""
    assert clean_choice(spec, "") == ""


# ── 画像字段 ─────────────────────────────────────────────────────


def test_profile_updates_extracts_and_normalizes():
    updates = profile_updates({
        "risk_preference": "稳健", "holding_period": "长期", "stock_target": "600519",
    })

    assert updates == {"risk_preference": "稳健", "holding_period": "长期"}


def test_profile_updates_drops_invalid_values():
    assert profile_updates({"risk_preference": "随便"}) == {}
    assert profile_updates({"risk_preference": "超激进"}) == {}
    assert profile_updates(None) == {}


# ── 取消哨兵 ─────────────────────────────────────────────────────


def test_is_cancel_recognizes_sentinel():
    assert CANCEL_SENTINEL == "__cancel__"
    assert is_cancel({CANCEL_SENTINEL: True}) is True
    assert is_cancel(CANCEL_SENTINEL) is True
    assert is_cancel({"stock_target": "600519"}) is False
    assert is_cancel({"__cancel__": False}) is False
    assert is_cancel(None) is False


@pytest.mark.parametrize("domain", list(BusinessDomain))
def test_build_form_never_raises_for_any_domain(domain):
    """任何领域构造表单都不得抛出（空登记域返回 None）。"""
    form = build_form([(domain, known_field_names(domain))])
    if known_field_names(domain):
        assert form is not None
    else:
        assert form is None
