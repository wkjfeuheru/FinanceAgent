"""行为基准：记录一组固定输入在 V2 编排下的结构化产出，供回归对照。

用法（在仓库根目录）：
    python tools/baseline_snapshot.py > .cache/baseline_v2.json

使用固定夹具数据与注入流水线，不触网、不调模型，因此结果可逐字节比较。
"""

from __future__ import annotations

import json
import sys
from typing import Any

from finance_agent.orchestrator.contracts import BusinessDomain, DomainTaskContext
from finance_agent.orchestrator.domains.stock import StockDeps, build_stock_domain_graph
from finance_agent.orchestrator.graphs.supervisor_graph import SupervisorDependencies, build_supervisor_graph
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


class _StaticClassifier:
    def __init__(self, intents: list[dict]) -> None:
        self._intents = intents

    def classify_intents(self, message: str, context_summary: str = "") -> dict:
        return {
            "intents": self._intents,
            "uncertain_intents": [],
            "finance_related": True,
            "intent_source": "fixture",
            "classification_error": {},
        }


def _build_root(intents: list[dict]) -> Any:
    stock_deps = StockDeps(
        pipeline=ResearchPipeline(
            snapshot_builder=SnapshotBuilder(Gateway()), rule_engine=RuleEngine.default(),
        ),
        injected_pipeline=True,
    )

    def domain_runner(context: DomainTaskContext):
        assert context.task.domain is BusinessDomain.STOCK_RESEARCH
        return build_stock_domain_graph(stock_deps).invoke({"context": context})["domain_outcome"]

    return build_supervisor_graph(
        SupervisorDependencies(classifier=_StaticClassifier(intents), domain_runner=domain_runner)
    )


_CASES: list[tuple[str, str, list[dict]]] = [
    ("single", "分析600519",
     [{"intent": "stock_analysis", "query": "分析600519", "confidence": 0.99,
       "execution_mode": "stock_analysis", "evidence": "分析600519"}]),
    ("comparison", "比较600519和600036",
     [{"intent": "stock_recommendation", "query": "比较600519和600036", "confidence": 0.99,
       "execution_mode": "stock_comparison", "evidence": "比较600519和600036"}]),
]


def _record(result: dict) -> dict:
    return {
        "final_response": result.get("final_response", ""),
        "run_status": result.get("run_status"),
        "task_results": result.get("task_results", {}),
        "warnings": sorted(result.get("warnings", []) or []),
    }


def main() -> None:
    snapshot: dict[str, Any] = {}
    for name, message, intents in _CASES:
        root = _build_root(intents)
        result = root.invoke(
            {"user_message": message, "run_id": f"baseline-{name}", "task_results": {}}
        )
        snapshot[name] = _record(result)

    json.dump(snapshot, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
