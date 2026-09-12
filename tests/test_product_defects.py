"""产品分析四项缺陷的回归护栏。

这些缺陷都在"产品专家纳入确定性流水线"时暴露，且都属于用户可见/审计正确性：

1. 流水线崩溃写 ``status="failed"``，但编排层只认 ``degraded`` → 崩溃被报成 SUCCESS；
2. 产品请求从不回填用户画像 → 产品适配判断对本轮请求永远不可用；
3. 产品名抽取把请求短语当产品名（"帮我看看华夏成长基金"整串），且类型词空壳也算命中；
4. 异常原文（可能含连接串）进入用户可见报告。
"""

from __future__ import annotations

from finance_agent.agents.product_analysis import ProductAnalysisAgent
from finance_agent.contracts import ExpertStatus, IntentKind, Task
from finance_agent.orchestrator import slots as slots_module
from finance_agent.orchestrator.orchestrator import AdvisorSystem
from finance_agent.product_research.rules import normalize_horizon

_REQUIRED = ("code", "name", "type", "scale")


class _BoomPipeline:
    def analyze(self, request):
        raise RuntimeError("DB_PASSWORD=secret-connection-detail")


def _system_with_no_audit() -> AdvisorSystem:
    system = object.__new__(AdvisorSystem)
    system.audit = type("N", (), {"is_available": lambda self: False})()
    system._capture_task_facts = lambda state, task: []
    return system


# ── 缺陷 1：崩溃必须报 failed，不得报 success ──────────────────────────────────

def test_product_pipeline_failure_maps_to_failed_expert_status():
    state = ProductAnalysisAgent(pipeline=_BoomPipeline()).invoke({
        "user_message": "分析110011基金", "intent_slots": {}, "user_profile": {}, "facts": [],
    })

    assert state["intent_results"]["product_analysis"]["status"] == "failed"

    task = Task(task_id="t1", intent=IntentKind.PRODUCT_ANALYSIS, expert_name="product_analysis")
    result = _system_with_no_audit()._make_task_result(state, task, "product_analysis")

    assert result.status is ExpertStatus.FAILED, "崩溃不得被映射为 SUCCESS"


def test_intent_status_mapping_covers_failure_vocabulary():
    """失败词汇必须逐一映射，未列出的才回退 SUCCESS。"""
    mapping = AdvisorSystem._INTENT_STATUS_TO_EXPERT
    assert mapping["failed"] is ExpertStatus.FAILED
    assert mapping["error"] is ExpertStatus.FAILED
    assert mapping["timeout"] is ExpertStatus.TIMEOUT
    assert mapping["degraded"] is ExpertStatus.DEGRADED
    assert mapping["success"] is ExpertStatus.SUCCESS


# ── 缺陷 4：异常原文不得外泄 ───────────────────────────────────────────────────

def test_product_failure_does_not_leak_internal_exception_text():
    state = ProductAnalysisAgent(pipeline=_BoomPipeline()).invoke({
        "user_message": "分析110011基金", "intent_slots": {}, "user_profile": {}, "facts": [],
    })

    report = state["agent_response"]
    assert "secret-connection-detail" not in report
    assert "DB_PASSWORD" not in report
    assert "暂不可用" in report


# ── 缺陷 3：产品名抽取剥离噪声 ─────────────────────────────────────────────────

def test_product_name_extraction_strips_request_noise():
    cases = {
        "帮我看看华夏成长基金": ["华夏成长基金"],
        "请分析易方达蓝筹精选基金": ["易方达蓝筹精选基金"],
        "对比华夏成长基金和易方达蓝筹精选基金": ["华夏成长基金", "易方达蓝筹精选基金"],
        "我想了解沪深300指数": ["沪深300指数"],
    }
    for message, expected in cases.items():
        assert slots_module._candidate_product_names(message) == expected, message


def test_product_name_extraction_drops_bare_type_words():
    """只剩类型词（无实际名称）不得算作产品名。"""
    for message in ("推荐几只基金", "分析110011", "给我推荐一些ETF"):
        assert slots_module._candidate_product_names(message) == [], message


# ── 缺陷 2：产品请求回填画像，且期限可被归一 ───────────────────────────────────

def test_product_slots_capture_profile_for_suitability():
    slots = slots_module._deterministic_extract(
        "分析华夏成长基金，我稳健型，持有一年", "product_analysis",
    )["slots"]

    assert slots["product_names"] == ["华夏成长基金"]
    assert slots["risk_preference"].startswith("R2")
    assert normalize_horizon(slots["holding_period"]) == "long"


def test_product_slot_schema_declares_profile_fields():
    schema = slots_module._INTENT_SLOT_SCHEMAS["product_analysis"]
    keys = {slot["key"] for slot in schema["slots"]}
    assert {"product_codes", "product_names", "risk_preference", "holding_period"} <= keys


def test_horizon_normalization_covers_common_phrasings():
    assert normalize_horizon("3年") == "long"
    assert normalize_horizon("18个月") == "long"
    assert normalize_horizon("6个月") == "medium"
    assert normalize_horizon("2周") == "short"
    assert normalize_horizon("很久") is None


def test_chinese_horizon_numbers_are_extracted():
    assert slots_module._extract_horizon("持有一年") == "1年"
    assert slots_module._extract_horizon("打算持有半年") == "半年"
    assert slots_module._extract_horizon("长期持有") == "长期"
    assert slots_module._extract_horizon("持有二十四个月") == "24个月"
