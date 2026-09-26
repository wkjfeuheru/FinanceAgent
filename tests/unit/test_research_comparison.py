"""比较请求必须为每只标的给出独立结论，绝不互相复制评级。

股票领域图（``StockDeps`` / ``invoke_stock``）已删除；比较语义现由
``evaluation.evaluate`` 直接承载，本文件据此重写，
保留逐标的独立结论与审计整批写入的不变量。
"""

from __future__ import annotations

from finance_agent.application.advisor import AdvisorSystem
from finance_agent.domains.research.contracts import AnalysisKind, AnalysisRequest
from finance_agent.domains.research.evaluation import evaluate, project_analysis_results
from finance_agent.domains.research.replay import replay_research_run

FETCHED_AT = "2026-08-28T08:00:00+00:00"


def _security(code: str, *, roe: float, rate: float) -> dict:
    """强票走高 ROE + 上行，弱票走低 ROE + 下行。"""
    closes = [round(10.0 * (1 + rate) ** index, 4) for index in range(60)]
    return {
        "basic_info": {"code": code, "name": f"测试{code}"},
        "quote": {"code": code, "price": closes[-1], "date": "2026-08-28", "adjustment": "raw",
                  "source": "fixture", "fetched_at": FETCHED_AT},
        "history": {"adjustment": "forward", "source": "fixture", "fetched_at": FETCHED_AT,
                    "data": [{"date": "2026-08-28", "close": close} for close in closes]},
        "indicators": {"roe": roe, "revenue_yoy": 20.0, "netprofit_yoy": 20.0, "pe_ttm": 18.0,
                       "pb": 2.0, "end_date": "2026-06-30", "ann_date": "2026-08-25",
                       "source": "fixture", "fetched_at": FETCHED_AT},
    }


class Gateway:
    """强票 600519 + 弱票 600036。"""

    def __init__(self):
        self.payloads = {
            "600519": _security("600519", roe=25.0, rate=0.008),
            "600036": _security("600036", roe=2.0, rate=-0.004),
        }

    def get_security_data(self, stock_code: str) -> dict:
        return self.payloads[stock_code]


def _request() -> AnalysisRequest:
    return AnalysisRequest(kind=AnalysisKind.COMPARISON, stock_codes=["600519", "600036"])


def _evaluate():
    return evaluate(
        _request(), user_profile={}, gateway=Gateway(),
    )


def test_comparison_yields_one_conclusion_per_security():
    results, facts = _evaluate()

    assert [result.request.stock_codes for result in results] == [["600519"], ["600036"]]
    assert {result.request.kind.value for result in results} == {"single_stock"}
    strong, weak = results
    assert strong.action.value == "关注"
    assert weak.action.value == "观望"
    assert strong.scores["total"] > weak.scores["total"]
    # 每条结论只引用自己的证据事实。
    assert [len(result.evidence_ids) for result in results] == [1, 1]
    assert strong.evidence_ids != weak.evidence_ids
    assert {fact.payload["code"] for fact in facts} == {"600519", "600036"}


def test_comparison_legacy_projection_keeps_per_code_conclusions():
    results, _ = _evaluate()

    projected = project_analysis_results(results)
    strong = projected["stock_analysis"]["600519"]
    weak = projected["stock_analysis"]["600036"]

    assert (strong["rating"], weak["rating"]) == ("关注", "观望")
    assert strong["overall_score"] != weak["overall_score"]
    assert len(projected["analysis_results"]) == 2
    assert projected["analysis_results"][0]["request"]["stock_codes"] == ["600519"]


def test_comparison_publishes_two_conclusions_and_run_level_request():
    """多标的运行保留 comparison 形态的请求，供审计归组与重放。"""
    results, facts = _evaluate()
    projected = project_analysis_results(results)
    request = _request()

    assert len(projected["analysis_results"]) == 2
    assert projected["stock_analysis"]["600519"]["rating"] == "关注"
    assert projected["stock_analysis"]["600036"]["rating"] == "观望"
    assert request.kind is AnalysisKind.COMPARISON
    assert request.stock_codes == ["600519", "600036"]
    assert len(facts) == 2


def _audit_state() -> tuple[dict, dict]:
    request = _request()
    results, facts = _evaluate()
    state = {
        "analysis_results": [result.model_dump(mode="json") for result in results],
        "facts": facts,
        "research_request": request.model_dump(mode="json"),
        "run_id": "run-1", "trace_id": "trace-1",
        "customer_id": "CUST001", "thread_id": "conv-1",
    }

    class _RecordingAudit:
        def __init__(self):
            self.run_calls = []
            self.single_calls = []

        def is_available(self):
            return True

        def upsert_expert_result(self, *args):
            pass

        def save_research_run(self, **context):
            self.run_calls.append(context)

        def save_research_result(self, result, **context):
            self.single_calls.append((result, context))

    audit = _RecordingAudit()
    system = object.__new__(AdvisorSystem)
    system.audit = audit
    system._audit_research_results(state)
    return state, audit


def test_comparison_audit_is_one_run_with_two_independent_results():
    """逐条 save 会互相删除同一次运行的结果行，多标的一轮必须整批写入。"""
    _, audit = _audit_state()

    assert audit.single_calls == []
    assert len(audit.run_calls) == 1
    saved = audit.run_calls[0]
    assert saved["request"].kind is AnalysisKind.COMPARISON
    assert [result.request.stock_codes for result in saved["results"]] == [["600519"], ["600036"]]
    assert saved["snapshot_manifest"]
    assert {manifest["payload"]["code"] for manifest in saved["snapshot_manifest"]} == {"600519", "600036"}


def test_comparison_run_replays_per_security():
    state, audit = _audit_state()
    saved = audit.run_calls[0]

    outcome = replay_research_run(
        research_run_id="run-1",
        request_data=saved["request"].model_dump(mode="json"),
        results=[
            {
                "stock_code": result.request.stock_codes[0],
                "action": result.action.value,
                "scores": dict(result.scores),
                "fact_ids": list(result.evidence_ids),
            }
            for result in saved["results"]
        ],
        snapshot_manifest=saved["snapshot_manifest"],
        rule_version=saved["results"][0].rule_version,
    )

    assert outcome.matched is True
    assert outcome.fact_ids_matched is True
    assert outcome.replayed_actions == {"600036": "观望", "600519": "关注"}
