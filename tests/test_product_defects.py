"""产品分析的缺陷回归护栏（面向产品领域模块与产品名抽取）。

这四项缺陷都属于用户可见/审计正确性：

1. 流水线崩溃不得被当成成功；
2. 产品请求必须回填用户画像；
3. 产品名抽取必须剥离请求噪声、剔除类型词空壳；
4. 异常原文（可能含连接串）不得进入用户可见报告。
"""

from __future__ import annotations

from finance_agent.orchestrator.domains.product import (
    ProductDomainDeps,
    candidate_product_names,
    invoke_product,
)
from finance_agent.product_research.rules import normalize_horizon


class _BoomPipeline:
    def analyze(self, request):
        raise RuntimeError("DB_PASSWORD=secret-connection-detail")


# ── 缺陷 1：崩溃必须报 failed，不得报 success ──────────────────────────────────

def test_product_pipeline_failure_maps_to_failed_status():
    state = invoke_product(ProductDomainDeps(pipeline=_BoomPipeline()), {
        "user_message": "分析110011基金", "intent_slots": {}, "user_profile": {}, "facts": [],
    })

    assert state["intent_results"]["product_analysis"]["status"] == "failed"


# ── 缺陷 4：异常原文不得外泄 ───────────────────────────────────────────────────

def test_product_failure_does_not_leak_internal_exception_text():
    state = invoke_product(ProductDomainDeps(pipeline=_BoomPipeline()), {
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
        assert candidate_product_names(message) == expected, message


def test_product_name_extraction_drops_bare_type_words():
    """只剩类型词（无实际名称）不得算作产品名。"""
    for message in ("推荐几只基金", "分析110011", "给我推荐一些ETF"):
        assert candidate_product_names(message) == [], message


# ── 缺陷 2：期限可被归一 ───────────────────────────────────────────────────────

def test_horizon_normalization_covers_common_phrasings():
    assert normalize_horizon("3年") == "long"
    assert normalize_horizon("18个月") == "long"
    assert normalize_horizon("6个月") == "medium"
    assert normalize_horizon("2周") == "short"
    assert normalize_horizon("很久") is None
