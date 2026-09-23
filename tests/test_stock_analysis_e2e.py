"""可选端到端冒烟测试：真实问题走完整 V2 编排与真实数据源。

**默认不运行**——CI 与离线环境不应依赖第三方接口与外部模型。启用方式：

```bash
RUN_NETWORK_TESTS=1 python -m pytest -q -m network tests/test_stock_analysis_e2e.py
```

覆盖 V2 根图到结论的完整链路：stock_analysis 的不同子路径、市场洞察与澄清兜底。
除首个用例用真实意图分类外，其余用例注入确定性分类结果，使失败可归因到具体子路径。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from finance_agent.orchestrator.domains.market import build_market_domain_graph
from finance_agent.orchestrator.domains.product import build_product_domain_graph
from finance_agent.orchestrator.domains.stock import StockDeps, build_stock_domain_graph
from finance_agent.orchestrator.routing.intent import IntentClassifier
from finance_agent.orchestrator.graphs.supervisor_graph import SupervisorDependencies, build_supervisor_graph
from finance_agent.research.screener import ThemeScreener
from finance_agent.research.theme_models import ThemeLead
from finance_agent.research.theme_repository import InMemoryThemeRepository

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(
        os.getenv("RUN_NETWORK_TESTS", "").strip().lower() not in {"1", "true", "yes", "on"},
        reason="端到端冒烟测试默认跳过；设置 RUN_NETWORK_TESTS=1 启用",
    ),
]

_ALLOWED_ACTIONS = {"关注", "观望", "规避", "数据不足"}


class _RealGateway:
    """主题筛选用的生产网关：逐成员走真实取数。"""

    def get_security_data(self, stock_code: str) -> dict:
        from finance_agent.orchestrator.tools.stockdata import fetch_stock_data

        return fetch_stock_data([stock_code]).get(stock_code, {})


class _DeterministicClassifier(IntentClassifier):
    """注入确定性分类结果，隔离分类模型波动。"""

    def __init__(self, intents):
        super().__init__(classifier=type(
            "C", (), {"classify": lambda self, *a, **k: {"finance_related": True, "intents": intents}},
        )())


def _build_supervisor(*, theme_screener=None, classifier=None):
    stock_deps = StockDeps(theme_screener=theme_screener)

    def domain_runner(context):
        from finance_agent.orchestrator.contracts import BusinessDomain

        if context.task.domain is BusinessDomain.STOCK_RESEARCH:
            graph = build_stock_domain_graph(stock_deps)
        elif context.task.domain is BusinessDomain.MARKET_INSIGHT:
            graph = build_market_domain_graph()
        else:
            graph = build_product_domain_graph()
        return graph.invoke({"context": context})["domain_outcome"]

    return build_supervisor_graph(
        SupervisorDependencies(
            classifier=classifier or IntentClassifier(),
            domain_runner=domain_runner,
        )
    )


def _run(root, question: str) -> dict:
    return root.invoke({"user_message": question, "run_id": "e2e-run", "task_results": {}})


def _actions(result: dict) -> list[str]:
    return [item.get("action") for item in (result.get("analysis_results") or [])]


# ── 子路径 1：真实 NLU + 单股分析 ──────────────────────────────────────────────

def test_live_question_routes_to_single_stock_analysis():
    """不注入分类：真实问题经真实意图分类后走单股研究并给出结论。"""
    root = _build_supervisor()
    result = _run(root, "请分析一下贵州茅台的基本面和最近走势")

    response = result.get("final_response", "")
    assert "validation error" not in response
    assert result.get("analysis_results"), "单股分析必须产出结构化结论"
    assert set(_actions(result)) <= _ALLOWED_ACTIONS


def test_single_stock_analysis_produces_scored_conclusion():
    root = _build_supervisor(classifier=_DeterministicClassifier([{
        "intent": "stock_analysis", "query": "分析600519", "confidence": 0.99,
        "execution_mode": "stock_analysis", "evidence": "分析600519",
    }]))
    result = _run(root, "分析600519")

    analysis = result["analysis_results"][0]
    assert analysis["action"] in _ALLOWED_ACTIONS
    assert analysis["data_quality"] in {"complete", "warning", "critical_missing"}
    assert analysis["rule_version"].startswith("research_rules/")


# ── 子路径 2：股票比较（多标的，逐只独立结论） ─────────────────────────────────

def test_comparison_yields_independent_conclusions_per_stock():
    root = _build_supervisor(classifier=_DeterministicClassifier([{
        "intent": "stock_recommendation", "query": "比较贵州茅台和招商银行",
        "confidence": 0.99, "execution_mode": "stock_comparison",
        "evidence": "比较贵州茅台和招商银行",
    }]))
    result = _run(root, "比较贵州茅台和招商银行哪个更好")

    codes = [item["request"]["stock_codes"] for item in result["analysis_results"]]
    assert ["600519"] in codes and ["600036"] in codes
    evidence = [set(item["evidence_ids"]) for item in result["analysis_results"]]
    assert all(evidence), "每条结论都应引用证据"
    assert evidence[0] != evidence[1]


# ── 子路径 4：主题筛选（已审核成员） ───────────────────────────────────────────

def _theme_repo(codes: list[str]) -> InMemoryThemeRepository:
    repo = InMemoryThemeRepository()
    for index, code in enumerate(codes):
        lead = repo.ingest_lead(ThemeLead(
            theme_id="ai_compute", stock_code=code, industry=f"算力{index}",
            source_name="e2e-fixture", source_class="official",
            source_uri=f"https://example.com/{code}", evidence_excerpt="公告",
            evidence_hash=f"h{code}", discovered_at=datetime.now(timezone.utc) - timedelta(days=1),
        ))
        repo.review_lead(
            lead.id, reviewer_id="admin", decision="approve",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30), note="e2e",
        )
    return repo


def test_theme_screening_scores_approved_members():
    screener = ThemeScreener(_theme_repo(["000977", "002230", "300308", "300502", "603019"]), _RealGateway())
    root = _build_supervisor(theme_screener=screener, classifier=_DeterministicClassifier([{
        "intent": "stock_recommendation", "query": "推荐人工智能主题股票",
        "confidence": 0.99, "execution_mode": "candidate_search",
        "evidence": "推荐人工智能主题股票",
    }]))
    result = _run(root, "推荐人工智能主题股票")

    screening = result.get("theme_screening") or {}
    assert screening, "主题请求应产出筛选结果"
    assert screening["status"] in {
        "complete", "insufficient_active_coverage", "insufficient_eligible_coverage",
    }


# ── 子路径 5：市场洞察 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("question,mode,needle", [
    ("今天大盘怎么样", "market_overview", "上证指数"),
    ("市场情绪怎么样", "market_sentiment", "涨跌家数"),
    ("最近资金面如何", "capital_flow", "融资融券"),
])
def test_market_insight_modes_render_real_data(question, mode, needle):
    root = _build_supervisor(classifier=_DeterministicClassifier([{
        "intent": "market_insight", "query": question, "confidence": 0.99,
        "execution_mode": mode, "evidence": question,
    }]))
    result = _run(root, question)

    response = result.get("final_response", "")
    assert needle in response, f"{mode} 应渲染 {needle}：{response[:200]}"
    # 硬边界：市场洞察不得产出个股结论。
    assert not result.get("stock_analysis")


# ── 子路径 6：分类边界（知识问答 vs 具体产品） ─────────────────────────────────

@pytest.mark.parametrize("question,expected,forbidden", [
    ("如何理解基金的风险等级（R1-R5）？", "casual_chat", "product_analysis"),
    ("基金的风险等级有哪些", "casual_chat", "product_analysis"),
    ("基金的申购费率是多少", "casual_chat", "product_analysis"),
    ("分析一下华夏成长基金", "product_analysis", "casual_chat"),
])
def test_live_classification_splits_knowledge_from_specific_product(question, expected, forbidden):
    """真实分类器：通用规则/概念问答不得被判为产品分析，反之具体产品不得判为闲聊。"""
    from finance_agent.orchestrator.routing.intent import IntentClassifier

    out = IntentClassifier().classify_intents(question)
    intents = [item["intent"] for item in out["intents"]]
    assert out["classification_error"] == {}, out["classification_error"]
    assert expected in intents, f"{question!r} 应判为 {expected}，实际 {intents}"
    assert forbidden not in intents, f"{question!r} 不应判为 {forbidden}，实际 {intents}"
