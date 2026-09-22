"""可选端到端冒烟测试：真实问题走完整编排与真实数据源。

**默认不运行**——CI 与离线环境不应依赖第三方接口与外部模型。启用方式：

```bash
RUN_NETWORK_TESTS=1 python -m pytest -q -m network tests/test_stock_analysis_e2e.py
```

与 ``test_provider_smoke.py``（只验证单条取数路径）不同，本文件验证的是**编排层到结论**
的完整链路，覆盖 stock_analysis 的不同子路径：

- 单股分析（名称 → 代码解析 → 真实取数 → 确定性评分 → 行动结论）
- 股票比较（多标的 Send 扇出 → 逐只独立结论）
- 选股推荐（候选发现 → 逐只结论）
- 主题筛选（已审核成员 → 逐成员研究）
- 市场洞察（大盘/情绪/资金面）
- 澄清兜底（无标的时不泄露内部异常）

除**首个用例用真实意图分类**外，其余用例注入确定性分类结果，使失败可归因到具体子路径，
而不受分类模型波动影响。
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone

import pytest
from langgraph.checkpoint.memory import MemorySaver

from finance_agent.agents.market_insight import MarketInsightAgent
from finance_agent.agents.stock_analysis import StockAnalysisAgent
from finance_agent.agents.supervisor import ManagerAgent
from finance_agent.orchestrator import slots as slots_module
from finance_agent.orchestrator.orchestrator import AdvisorSystem
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


class _NoopAudit:
    def is_available(self) -> bool:
        return False


class _StubAgent:
    def __init__(self, name: str) -> None:
        self.agent_name = name

    def invoke(self, state):
        return state


def _build_system(*, theme_repo=None) -> AdvisorSystem:
    """构造真实编排系统；只用 MemorySaver 替换需要 PostgreSQL 的 checkpoint。"""
    system = object.__new__(AdvisorSystem)
    system.checkpointer = MemorySaver()
    system.manager = ManagerAgent()
    system.stock_agent = StockAnalysisAgent(
        theme_screener=(
            ThemeScreener(theme_repo, _RealGateway()) if theme_repo is not None else None
        ),
    )
    system.market_insight_agent = MarketInsightAgent()
    system.allocation_agent = _StubAgent("asset_allocation")
    system.product_agent = _StubAgent("product_analysis")
    system.casual_chat_agent = _StubAgent("casual_chat")
    system.slot_extractor = slots_module.SlotExtractor()
    # 槽位抽取走确定性路径：本测试关注编排与分析，不引入额外模型调用。
    system.slot_extractor._extract_one = (
        lambda msg, intent, schema, prior, ctx: slots_module._deterministic_extract(msg, intent)
    )
    system._progress_context = type("Context", (), {})()
    system._progress_callbacks = {}
    system._progress_lock = threading.Lock()
    system._trace_lock = threading.Lock()
    system._trace_sequences = {}
    system._workflow_lock = threading.RLock()
    system._stop_requests = {}
    system._active_runs = {}
    system._stop_lock = threading.Lock()
    system.audit = _NoopAudit()
    system._trace_agent = lambda *a, **k: None
    system._emit_progress = lambda *a, **k: None
    return system


class _RealGateway:
    """主题筛选用的生产网关：逐成员走真实取数。"""

    def get_security_data(self, stock_code: str) -> dict:
        from finance_agent.orchestrator.tools.stockdata import fetch_stock_data

        return fetch_stock_data([stock_code]).get(stock_code, {})


def _classify_as(system, intents):
    """注入确定性分类结果，隔离分类模型波动。"""
    system.manager._intent_classifier = type(
        "C", (), {"classify": lambda self, *a, **k: {"finance_related": True, "intents": intents}},
    )()


def _run(system, question: str, thread: str) -> dict:
    graph = system._build_graph()
    return graph.invoke(
        {"user_message": question, "completed_experts": [], "intent_results": {}, "intent_slots": {}},
        config={"configurable": {"thread_id": thread}},
    )


def _actions(result: dict) -> list[str]:
    return [item.get("action") for item in (result.get("analysis_results") or [])]


# ── 子路径 1：真实 NLU + 单股分析 ──────────────────────────────────────────────

def test_live_question_routes_to_single_stock_analysis():
    """不注入分类：真实问题经真实意图分类后走单股研究并给出结论。"""
    system = _build_system()
    result = _run(system, "请分析一下贵州茅台的基本面和最近走势", "e2e-single-live")

    response = result.get("agent_response", "")
    assert "validation error" not in response
    assert result.get("analysis_results"), "单股分析必须产出结构化结论"
    assert set(_actions(result)) <= _ALLOWED_ACTIONS
    assert "600519" in response or "贵州茅台" in response


def test_single_stock_analysis_produces_scored_conclusion():
    system = _build_system()
    _classify_as(system, [{
        "intent": "stock_analysis", "query": "分析600519", "confidence": 0.99,
        "execution_mode": "stock_analysis", "evidence": "分析600519",
    }])
    result = _run(system, "分析600519", "e2e-single")

    analysis = result["analysis_results"][0]
    assert analysis["action"] in _ALLOWED_ACTIONS
    assert analysis["data_quality"] in {"complete", "warning", "critical_missing"}
    assert analysis["rule_version"].startswith("research_rules/")
    # 真实取数下应至少有一项评分可计算（除非数据源整体不可用）。
    assert any(value is not None for value in analysis["scores"].values())


# ── 子路径 2：股票比较（多标的扇出，逐只独立结论） ─────────────────────────────

def test_comparison_yields_independent_conclusions_per_stock():
    system = _build_system()
    _classify_as(system, [{
        "intent": "stock_recommendation", "query": "比较贵州茅台和招商银行",
        "confidence": 0.99, "execution_mode": "stock_comparison",
        "evidence": "比较贵州茅台和招商银行",
    }])
    result = _run(system, "比较贵州茅台和招商银行哪个更好", "e2e-comparison")

    codes = [item["request"]["stock_codes"] for item in result["analysis_results"]]
    assert ["600519"] in codes and ["600036"] in codes
    assert set(_actions(result)) <= _ALLOWED_ACTIONS
    # 逐只结论必须各自引用证据，不得互相复制。
    evidence = [set(item["evidence_ids"]) for item in result["analysis_results"]]
    assert all(evidence), "每条结论都应引用证据"
    assert evidence[0] != evidence[1]


# ── 子路径 3：选股推荐（候选发现） ─────────────────────────────────────────────
#
# 候选发现是「主题代表股 → 关键词搜索」两段式。默认 AKShare 股票列表不含
# ``industry``，行业/主题口语词（消费）靠字段匹配命不中，因此代表股在注册表中
# 显式维护——下面用例即验证该路径真实可用。

def test_candidate_search_without_match_asks_for_clarification():
    system = _build_system()
    _classify_as(system, [{
        "intent": "stock_recommendation", "query": "推荐几个完全未登记的主题股",
        "confidence": 0.99, "execution_mode": "candidate_search",
        "evidence": "推荐几个完全未登记的主题股",
    }])
    result = _run(system, "推荐几个完全未登记的主题股", "e2e-candidates-clarify")

    response = result.get("agent_response", "")
    assert "validation error" not in response, "候选发现不得回落成单股校验错误"
    assert "补充主题" in response or "股票代码" in response


def test_candidate_recommendation_uses_registered_representative_codes():
    """注册"消费"代表股后，"推荐几个消费龙头股"应产出逐只结论。"""
    from finance_agent.research.theme_registry import InMemoryThemeRegistry, ThemeEntry

    registry = InMemoryThemeRegistry([
        ThemeEntry(theme_id="consumer", display_name="消费", aliases=["消费龙头", "消费股"],
                   representative_codes=["600519", "000858", "600887"]),
    ])
    system = _build_system()
    system.stock_agent = StockAnalysisAgent(theme_registry=registry)
    _classify_as(system, [{
        "intent": "stock_recommendation", "query": "推荐几个消费龙头股",
        "confidence": 0.99, "execution_mode": "candidate_search",
        "evidence": "推荐几个消费龙头股",
    }])
    result = _run(system, "推荐几个消费龙头股", "e2e-candidates")

    codes = [item["request"]["stock_codes"][0] for item in result["analysis_results"]]
    assert set(codes) == {"600519", "000858", "600887"}, "代表股应逐只产出结论"
    assert set(_actions(result)) <= _ALLOWED_ACTIONS


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
    system = _build_system(theme_repo=_theme_repo(
        ["000977", "002230", "300308", "300502", "603019"]
    ))
    _classify_as(system, [{
        "intent": "stock_recommendation", "query": "推荐人工智能主题股票",
        "confidence": 0.99, "execution_mode": "candidate_search",
        "evidence": "推荐人工智能主题股票",
    }])
    result = _run(system, "推荐人工智能主题股票", "e2e-theme")

    screening = result.get("theme_screening") or {}
    assert screening, "主题请求应产出筛选结果"
    assert screening["status"] in {
        "complete", "insufficient_active_coverage", "insufficient_eligible_coverage",
    }
    if screening["status"] == "complete":
        assert 3 <= len(screening["candidates"]) <= 5
        assert all(candidate["action"] in _ALLOWED_ACTIONS for candidate in screening["candidates"])


# ── 子路径 5：市场洞察 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("question,mode,needle", [
    ("今天大盘怎么样", "market_overview", "上证指数"),
    ("市场情绪怎么样", "market_sentiment", "涨跌家数"),
    ("最近资金面如何", "capital_flow", "融资融券"),
])
def test_market_insight_modes_render_real_data(question, mode, needle):
    system = _build_system()
    _classify_as(system, [{
        "intent": "market_insight", "query": question, "confidence": 0.99,
        "execution_mode": mode, "evidence": question,
    }])
    result = _run(system, question, f"e2e-insight-{mode}")

    response = result.get("agent_response", "")
    assert needle in response, f"{mode} 应渲染 {needle}：{response[:200]}"
    assert "validation error" not in response
    # 硬边界：市场洞察不得产出个股结论。
    assert not result.get("stock_analysis")


# ── 子路径 6：澄清兜底 ─────────────────────────────────────────────────────────

def test_stock_analysis_without_target_asks_for_clarification():
    """无标的的个股请求应引导澄清，而不是暴露内部校验异常。"""
    system = _build_system()
    _classify_as(system, [{
        "intent": "stock_analysis", "query": "分析一下它", "confidence": 0.99,
        "execution_mode": "stock_analysis", "evidence": "分析一下它",
    }])
    result = _run(system, "分析一下它", "e2e-clarify")

    response = result.get("agent_response", "")
    assert "validation error" not in response
    assert "股票代码" in response or "确认" in response or "股票名称" in response
