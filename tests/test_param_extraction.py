"""关键参数抽取与入参校验：四领域登记、确定性抽取、模型兜底与偏好归一。"""

from __future__ import annotations

import pytest

from finance_agent.orchestrator.contracts import BusinessDomain
from finance_agent.orchestrator.routing.params import (
    CANCEL_SENTINEL,
    PARAM_SPECS,
    ExtractedParams,
    ParamSpec,
    apply_answers,
    build_form,
    build_question,
    extract_params,
    find_missing,
    intent_slots_for,
    is_cancel,
    merge_target_queries,
    profile_updates_from_answers,
    required_specs,
    specs_for,
    target_queries,
)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": __import__("json").dumps(self._payload)}}]}


def _fake_requester(payload: dict):
    def requester(url, headers=None, json=None, timeout=None):
        return _FakeResponse(payload)

    return requester


def _boom_requester(url, headers=None, json=None, timeout=None):
    raise RuntimeError("network down")


class _FakeRegistry:
    """最小主题注册表：只登记"半导体"这一个主题。"""

    class _Entry:
        theme_id = "semiconductor"

        def names(self) -> list[str]:
            return ["半导体", "芯片"]

    def list_themes(self):
        return [self._Entry()]

    def resolve(self, name: str) -> str | None:
        return "semiconductor" if name in {"半导体", "芯片"} else None


# ── 登记表 ───────────────────────────────────────────────────────


def test_every_business_domain_is_registered():
    """四个业务领域都必须在参数登记表里出现（含空元组的市场/账户）。"""
    assert set(PARAM_SPECS) == set(BusinessDomain)


def test_only_stock_and_product_have_required_params():
    """只有股票与产品有必填项；市场与账户登记为空、永不触发追问。"""
    assert [spec.name for spec in required_specs(BusinessDomain.STOCK_RESEARCH)] == ["stock_target"]
    assert [spec.name for spec in required_specs(BusinessDomain.PRODUCT_RESEARCH)] == ["product_reference"]
    assert required_specs(BusinessDomain.MARKET_INSIGHT) == ()
    assert required_specs(BusinessDomain.ACCOUNT_PORTFOLIO) == ()
    assert specs_for(BusinessDomain.MARKET_INSIGHT) == ()


def test_profile_params_are_optional_and_profile_scoped():
    """风险偏好与投资期限是可选字段，且标记为可写长期画像。"""
    for domain in (BusinessDomain.STOCK_RESEARCH, BusinessDomain.PRODUCT_RESEARCH):
        profile_specs = [spec for spec in specs_for(domain) if spec.scope == "profile"]
        assert {spec.name for spec in profile_specs} == {"risk_preference", "holding_period"}
        assert all(not spec.required for spec in profile_specs)


def test_form_field_projection_is_json_serializable():
    """表单字段投影必须可 JSON 序列化（随 SSE 下发）。"""
    import json

    field = ParamSpec(name="x", label="X", required=True).to_field()
    assert json.loads(json.dumps(field))["required"] is True


# ── 确定性抽取 ───────────────────────────────────────────────────


def test_deterministic_stock_code_extraction_skips_model():
    calls = {"count": 0}

    def requester(*args, **kwargs):
        calls["count"] += 1
        return _FakeResponse({})
    params = extract_params(
        "600519 现在怎么样", domains=[BusinessDomain.STOCK_RESEARCH],
        requester=requester, api_key="k",
    )

    assert params.values["stock_research"]["stock_codes"] == ["600519"]
    assert calls["count"] == 0, "必填项已由确定性抽取命中，不得再调模型"


def test_deterministic_theme_extraction():
    params = extract_params(
        "半导体板块有哪些值得关注", domains=[BusinessDomain.STOCK_RESEARCH],
        requester=_fake_requester({}), api_key="k", registry=_FakeRegistry(),
    )

    # 存消息中出现的主题名（领域侧再解析成 theme_id）。
    assert params.values["stock_research"]["theme"] == "半导体"
    assert find_missing([BusinessDomain.STOCK_RESEARCH], params) == {}


def test_deterministic_product_name_extraction():
    params = extract_params(
        "分析一下华夏成长基金", domains=[BusinessDomain.PRODUCT_RESEARCH],
        requester=_fake_requester({}), api_key="k",
    )

    assert params.values["product_research"]["product_names"] == ["华夏成长基金"]
    assert find_missing([BusinessDomain.PRODUCT_RESEARCH], params) == {}


def test_stock_name_only_still_missing_and_requires_model():
    """只给股票名称时确定性抽取无法命中代码；模型返回时才补齐。"""
    params = extract_params(
        "贵州茅台怎么样", domains=[BusinessDomain.STOCK_RESEARCH],
        requester=_fake_requester({"stock_target": "贵州茅台"}), api_key="k",
    )

    assert params.values["stock_research"]["stock_target"] == "贵州茅台"
    assert "stock_codes" not in params.values["stock_research"], "名称→代码由领域解析，不在此写槽"
    assert find_missing([BusinessDomain.STOCK_RESEARCH], params) == {}


def test_market_and_account_never_need_model_call():
    calls = {"count": 0}

    def requester(*args, **kwargs):
        calls["count"] += 1
        return _FakeResponse({})

    params = extract_params(
        "今天大盘怎么样，我的持仓如何",
        domains=[BusinessDomain.MARKET_INSIGHT, BusinessDomain.ACCOUNT_PORTFOLIO],
        requester=requester, api_key="k",
    )

    assert params.values == {}
    assert calls["count"] == 0
    assert find_missing([BusinessDomain.MARKET_INSIGHT, BusinessDomain.ACCOUNT_PORTFOLIO], params) == {}


# ── 降级 ─────────────────────────────────────────────────────────


def test_missing_api_key_marks_extraction_unavailable():
    """模型未配置时不得把"没抽到"当作"用户没说"：置 extraction_available=False。"""
    params = extract_params(
        "分析贵州茅台", domains=[BusinessDomain.STOCK_RESEARCH], api_key="",
    )

    assert params.extraction_available is False
    assert "param_extraction_unavailable" in params.warnings
    assert find_missing([BusinessDomain.STOCK_RESEARCH], params), "缺参事实仍被记录"


def test_model_failure_degrades_without_raising():
    params = extract_params(
        "分析贵州茅台", domains=[BusinessDomain.STOCK_RESEARCH],
        requester=_boom_requester, api_key="k",
    )

    assert params.extraction_available is False
    assert "param_extraction_failed" in params.warnings


def test_invalid_choice_from_model_is_dropped():
    """模型返回非法偏好取值时丢弃，不写入参数（不阻塞本轮）。"""
    params = extract_params(
        "分析600519", domains=[BusinessDomain.STOCK_RESEARCH],
        requester=_fake_requester({"risk_preference": "超级激进"}), api_key="k",
    )

    assert "risk_preference" not in params.values.get("stock_research", {})


def test_valid_choice_from_model_is_kept():
    params = extract_params(
        "分析贵州茅台，我比较保守", domains=[BusinessDomain.STOCK_RESEARCH],
        requester=_fake_requester({"stock_target": "贵州茅台", "risk_preference": "保守"}),
        api_key="k",
    )

    assert params.values["stock_research"]["risk_preference"] == "保守"


# ── 校验与追问 ───────────────────────────────────────────────────


def test_find_missing_reports_only_required():
    params = ExtractedParams(values={"stock_research": {"analysis_type": "技术面"}})

    assert find_missing([BusinessDomain.STOCK_RESEARCH], params) == {
        "stock_research": ["stock_target"],
    }


def test_build_question_is_deterministic_template():
    params = ExtractedParams(values={})
    missing = find_missing([BusinessDomain.STOCK_RESEARCH, BusinessDomain.PRODUCT_RESEARCH], params)
    question = build_question([BusinessDomain.STOCK_RESEARCH, BusinessDomain.PRODUCT_RESEARCH], missing)

    assert "股票标的" in question and "产品" in question


def test_build_form_includes_optional_profile_fields():
    """弹窗同框收集可选偏好：必填与可选都在 fields 里。"""
    params = ExtractedParams(values={})
    form = build_form([BusinessDomain.STOCK_RESEARCH], find_missing([BusinessDomain.STOCK_RESEARCH], params))

    names = [field["name"] for field in form["fields"]]
    assert names == ["stock_target", "analysis_type", "risk_preference", "holding_period"]
    required = {field["name"]: field["required"] for field in form["fields"]}
    assert required["stock_target"] is True
    assert required["risk_preference"] is False
    assert form["missing"] == ["stock_research:stock_target"]


def test_form_excludes_domains_without_missing_required():
    """市场/账户无必填项，不应出现在任何追问表单里。"""
    params = ExtractedParams(values={})
    missing = find_missing([BusinessDomain.MARKET_INSIGHT, BusinessDomain.ACCOUNT_PORTFOLIO], params)

    assert missing == {}
    assert build_form([BusinessDomain.MARKET_INSIGHT], missing)["fields"] == []


# ── 答案合并 ─────────────────────────────────────────────────────


def test_apply_answers_derives_code_slots():
    params = ExtractedParams(values={})
    merged = apply_answers(params, {"stock_target": "600519"}, [BusinessDomain.STOCK_RESEARCH])

    assert merged.values["stock_research"]["stock_codes"] == ["600519"]
    assert find_missing([BusinessDomain.STOCK_RESEARCH], merged) == {}


def test_apply_answers_ignores_unregistered_fields():
    params = ExtractedParams(values={})
    merged = apply_answers(
        params, {"stock_target": "600519", "evil_field": "x"}, [BusinessDomain.STOCK_RESEARCH],
    )

    assert "evil_field" not in merged.values["stock_research"]


def test_apply_answers_ignores_unknown_choice():
    params = ExtractedParams(values={})
    merged = apply_answers(
        params, {"stock_target": "600519", "risk_preference": "未知偏好"},
        [BusinessDomain.STOCK_RESEARCH],
    )

    assert "risk_preference" not in merged.values["stock_research"]


def test_apply_answers_blank_does_not_overwrite():
    params = ExtractedParams(values={"stock_research": {"risk_preference": "稳健"}})
    merged = apply_answers(params, {"risk_preference": ""}, [BusinessDomain.STOCK_RESEARCH])

    assert merged.values["stock_research"]["risk_preference"] == "稳健"


# ── 取消 ─────────────────────────────────────────────────────────


def test_is_cancel_recognizes_sentinel():
    assert is_cancel({CANCEL_SENTINEL: True}) is True
    assert is_cancel(CANCEL_SENTINEL) is True
    assert is_cancel({"stock_target": "600519"}) is False
    assert is_cancel(CANCEL_SENTINEL) is True and is_cancel({"__cancel__": False}) is False


# ── 流向领域 ─────────────────────────────────────────────────────


def test_target_queries_only_covers_required_target_fields():
    params = ExtractedParams(values={
        "stock_research": {"stock_target": "600519"},
        "product_research": {"product_reference": "华夏成长基金"},
        "market_insight": {"whatever": "x"},
    })
    queries = target_queries(
        [BusinessDomain.STOCK_RESEARCH, BusinessDomain.PRODUCT_RESEARCH, BusinessDomain.MARKET_INSIGHT],
        params,
    )

    assert queries == {"stock_research": "600519", "product_research": "华夏成长基金"}


def test_merge_target_queries_appends_and_preserves_context():
    routing = {"domain_queries": {"stock_research": "分析贵州茅台"}}
    params = ExtractedParams(values={"stock_research": {"stock_target": "600519"}})

    merged = merge_target_queries(routing, params, [BusinessDomain.STOCK_RESEARCH])

    assert merged["domain_queries"]["stock_research"] == "分析贵州茅台 600519"


def test_merge_target_queries_is_noop_without_targets():
    routing = {"domain_queries": {"market_insight": "今天大盘"}}
    merged = merge_target_queries(routing, ExtractedParams(values={}), [BusinessDomain.MARKET_INSIGHT])

    assert merged is routing


def test_intent_slots_maps_analysis_type_for_stock():
    slots = intent_slots_for(
        BusinessDomain.STOCK_RESEARCH,
        {"analysis_type": "技术面", "stock_codes": ["600519"]},
    )

    # 下游解析器按意图名取嵌套槽位（request_parser._market_slots）。
    assert slots == {"stock_analysis": {"analysis_type": "technical", "stock_codes": ["600519"]}}


def test_intent_slots_maps_product_codes_and_names():
    slots = intent_slots_for(
        BusinessDomain.PRODUCT_RESEARCH,
        {"product_codes": ["110011"], "product_names": ["华夏成长基金"]},
    )

    # 下游解析器按 product_analysis 键取槽位（domains/product._slots）。
    assert slots == {"product_analysis": {
        "product_codes": ["110011"], "product_names": ["华夏成长基金"],
    }}


def test_intent_slots_empty_without_mappable_fields():
    assert intent_slots_for(BusinessDomain.STOCK_RESEARCH, {"stock_target": "600519"}) == {}
    assert intent_slots_for(BusinessDomain.PRODUCT_RESEARCH, {}) == {}


def test_intent_slots_empty_for_market_and_account():
    assert intent_slots_for(BusinessDomain.MARKET_INSIGHT, {"stock_target": "x"}) == {}
    assert intent_slots_for(BusinessDomain.ACCOUNT_PORTFOLIO, {"stock_target": "x"}) == {}


def test_profile_updates_from_answers_normalizes():
    updates = profile_updates_from_answers(
        {"risk_preference": "稳健", "holding_period": "长期", "stock_target": "600519"},
    )

    assert updates == {"risk_preference": "稳健", "holding_period": "长期"}


def test_profile_updates_from_answers_drops_invalid():
    assert profile_updates_from_answers({"risk_preference": "随便"}) == {}
    assert profile_updates_from_answers(None) == {}


@pytest.mark.parametrize("domain", list(BusinessDomain))
def test_each_domain_extraction_never_raises(domain):
    """任何领域的抽取都不得抛出（失败只降级）。"""
    params = extract_params("", domains=[domain], api_key="")
    assert isinstance(params, ExtractedParams)
