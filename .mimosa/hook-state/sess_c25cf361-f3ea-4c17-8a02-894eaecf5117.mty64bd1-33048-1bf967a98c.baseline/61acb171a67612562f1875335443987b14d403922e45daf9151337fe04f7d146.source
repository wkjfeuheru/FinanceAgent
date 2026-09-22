"""行为等价基准：记录重构前后同一组输入的结构化产出，供 diff 对照。

用法（在仓库根目录）：
    python tools/baseline_snapshot.py > .cache/baseline_before.json
    # 重构后
    python tools/baseline_snapshot.py > .cache/baseline_after.json
    # 再逐项比较两个 JSON

使用固定的夹具数据与注入流水线，不触网、不调模型，因此结果可逐字节比较。
"""

from __future__ import annotations

import json
import sys
import threading
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from finance_agent.agents.stock_analysis import StockAnalysisAgent
from finance_agent.agents.supervisor import ManagerAgent
from finance_agent.orchestrator.orchestrator import AdvisorSystem
from finance_agent.research.pipeline import ResearchPipeline
from finance_agent.research.rule_engine import RuleEngine
from finance_agent.research.snapshot_builder import SnapshotBuilder

FIXTURE_DAY = "2026-08-28"
FIXTURE_FETCHED_AT = "2026-08-28T08:00:00+00:00"

_ROE = {"600519": 25.0, "600036": 2.0, "000858": 15.0}
_RATE = {"600519": 0.008, "600036": -0.004, "000858": 0.003}


def _closes(rate: float) -> list[float]:
    return [round(10.0 * (1 + rate) ** index, 4) for index in range(60)]


class Gateway:
    """强票 600519 / 弱票 600036 / 中等 000858，字段与生产取数层一致。"""

    def get_security_data(self, stock_code: str) -> dict[str, Any]:
        rate = _RATE.get(stock_code, 0.002)
        return {
            "basic_info": {"code": stock_code, "name": f"测试{stock_code}"},
            "quote": {"code": stock_code, "price": 12.0, "date": FIXTURE_DAY,
                      "adjustment": "raw", "source": "fixture", "fetched_at": FIXTURE_FETCHED_AT},
            "history": {"adjustment": "forward", "as_of": FIXTURE_DAY, "source": "fixture",
                        "fetched_at": FIXTURE_FETCHED_AT,
                        "data": [{"date": FIXTURE_DAY, "close": c} for c in _closes(rate)]},
            "indicators": {"roe": _ROE.get(stock_code, 10.0), "revenue_yoy": 20.0,
                           "netprofit_yoy": 20.0, "pe_ttm": 18.0, "pb": 2.0,
                           "end_date": "2026-06-30", "ann_date": "2026-08-25",
                           "source": "fixture", "fetched_at": FIXTURE_FETCHED_AT},
        }


def _build_system() -> AdvisorSystem:
    system = object.__new__(AdvisorSystem)
    system.checkpointer = MemorySaver()
    system.manager = ManagerAgent()
    # 注意：注入 pipeline 是为了离线可比；但它会让专家跳过取数，
    # 因此 `stock_analysis.basic_info` 不会出现（生产路径会合并）。
    # 比较语义字段（结论/评分/证据ID）时应忽略该差异。
    system.stock_agent = StockAnalysisAgent(pipeline=ResearchPipeline(
        snapshot_builder=SnapshotBuilder(Gateway()), rule_engine=RuleEngine.default(),
    ))
    system.allocation_agent = type("A", (), {"invoke": lambda self, s: s})()
    system.product_agent = type("P", (), {"invoke": lambda self, s: s})()
    system.casual_chat_agent = type("C", (), {"invoke": lambda self, s: s})()
    system.slot_extractor = type("Slots", (), {"extract": lambda self, s: s})()
    system._progress_context = type("Context", (), {})()
    system._progress_callbacks = {}
    system._progress_lock = threading.Lock()
    system._trace_lock = threading.Lock()
    system._trace_sequences = {}
    system._workflow_lock = threading.RLock()
    system._stop_requests = {}
    system._active_runs = {}
    system._stop_lock = threading.Lock()
    system.audit = type("_NoopAudit", (), {"is_available": lambda self: False})()
    system._trace_agent = lambda *a, **k: None
    system._emit_progress = lambda *a, **k: None
    return system


_CASES: list[tuple[str, str, list[dict], list[dict]]] = [
    ("single", "分析600519",
     [{"intent": "stock_analysis", "query": "分析600519", "confidence": 0.99,
       "execution_mode": "stock_analysis", "evidence": "分析600519"}],
     [{"code": "600519"}]),
    ("comparison", "比较600519和600036",
     [{"intent": "stock_recommendation", "query": "比较600519和600036", "confidence": 0.99,
       "execution_mode": "stock_comparison", "evidence": "比较600519和600036"}],
     [{"code": "600519"}, {"code": "600036"}]),
    ("candidates", "推荐几只股票",
     [{"intent": "stock_recommendation", "query": "推荐几只股票", "confidence": 0.99,
       "execution_mode": "candidate_search", "evidence": "推荐几只股票"}],
     []),
    ("multi_stock_tasks", "分析600519并推荐几只股票",
     [{"intent": "stock_analysis", "query": "分析600519", "confidence": 0.99,
       "execution_mode": "stock_analysis", "evidence": "分析600519"},
      {"intent": "stock_recommendation", "query": "推荐几只股票", "confidence": 0.99,
       "execution_mode": "candidate_search", "evidence": "推荐几只股票"}],
     [{"code": "600519"}]),
]


def _record(result: dict) -> dict:
    return {
        "agent_response": result.get("agent_response", ""),
        "analysis_results": result.get("analysis_results", []),
        "stock_analysis": result.get("stock_analysis", {}),
        "task_results": {
            k: {"status": v.status.value, "summary": v.summary,
                "expert_name": v.expert_name, "intent": v.intent.value if v.intent else None}
            for k, v in (result.get("task_results") or {}).items()
        },
        "run_status": getattr(result.get("run_status"), "value", result.get("run_status")),
        "warnings": sorted(result.get("warnings", [])),
        "fact_ids": sorted(getattr(f, "fact_id", "") for f in (result.get("facts") or [])),
    }


def main() -> None:
    import finance_agent.agents.stock_analysis as sa
    import finance_agent.orchestrator.orchestrator as orch

    # 候选发现完全离线：固定返回 000858。
    class _StubSearch:
        def invoke(self, _payload):
            return json.dumps([{"code": "000858", "name": "测试000858", "industry": "白酒Ⅱ"}])

    sa.search_candidates = _StubSearch()
    # 取数完全离线：图形取数与专家内部取数都走同一夹具。
    orch.fetch_stock_data = lambda codes: {c: Gateway().get_security_data(c) for c in codes}
    sa.fetch_stock_data = orch.fetch_stock_data

    snapshot: dict[str, Any] = {}
    for name, message, intents, resolved in _CASES:
        system = _build_system()
        system.manager._intent_classifier = type(
            "C", (), {"classify": lambda self, *a, **k: {"finance_related": True, "intents": intents}},
        )()
        graph = system._build_graph()
        state = {"user_message": message, "completed_experts": [], "intent_results": {},
                 "intent_slots": {}, "resolved_stocks": resolved}
        result = graph.invoke(state, config={"configurable": {"thread_id": f"baseline-{name}"}})
        snapshot[name] = _record(result)

    json.dump(snapshot, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
