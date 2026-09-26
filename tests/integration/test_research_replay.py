"""审计重放测试：同一份审计记录必须复算出同一结论与同一证据 ID。"""

from __future__ import annotations

from finance_agent.domains.research.contracts import AnalysisKind, AnalysisRequest
from finance_agent.domains.research.evaluation import evaluate
from finance_agent.domains.research.replay import (
    EVIDENCE_INCOMPLETE,
    MISMATCHED,
    RULES_UNAVAILABLE,
    replay_research_run,
)

FIXTURE_FETCHED_AT = "2026-08-28T08:00:00+00:00"


class Gateway:
    """固定夹具网关；重放不会再触发它（证据里已含完整输入）。"""

    def __init__(self, codes=("600519",)):
        self._codes = list(codes)

    def get_security_data(self, stock_code: str) -> dict:
        closes = [round(10.0 * 1.004 ** index, 4) for index in range(60)]
        return {
            "basic_info": {"code": stock_code, "name": f"测试{stock_code}"},
            "quote": {
                "code": stock_code, "price": closes[-1], "date": "2026-08-28",
                "adjustment": "raw", "source": "fixture", "fetched_at": FIXTURE_FETCHED_AT,
            },
            "history": {
                "adjustment": "forward", "source": "fixture", "fetched_at": FIXTURE_FETCHED_AT,
                "data": [{"date": "2026-08-28", "close": close} for close in closes],
            },
            "indicators": {
                "roe": 18.0, "revenue_yoy": 20.0, "netprofit_yoy": 20.0,
                "pe_ttm": 18.0, "pb": 2.0, "end_date": "2026-06-30", "ann_date": "2026-08-25",
                "source": "fixture", "fetched_at": FIXTURE_FETCHED_AT,
            },
        }


def _request(codes=("600519",)) -> AnalysisRequest:
    request_codes = list(codes)
    kind = AnalysisKind.SINGLE_STOCK if len(request_codes) == 1 else AnalysisKind.COMPARISON
    return AnalysisRequest(kind=kind, stock_codes=request_codes)


def _run(codes=("600519",)):
    """跑一次真实评估，并把它投影成审计存储的形状。"""
    request = _request(codes)
    results, facts = evaluate(
        request,
        user_profile={},
        gateway=Gateway(codes),
    )
    result = results[0]
    stored_results = [
        {
            "stock_code": code,
            "action": result.action.value,
            "scores": dict(result.scores),
            "fact_ids": [fact.fact_id for fact in facts if fact.payload.get("code") == code],
            "exclusion_reason": "",
        }
        for code in codes
    ]
    return {
        "research_run_id": "run-fixture",
        "request_data": request.model_dump(mode="json"),
        "results": stored_results,
        "snapshot_manifest": [fact.model_dump(mode="json") for fact in facts],
        "rule_version": result.rule_version,
    }


def test_replay_reproduces_conclusion_and_evidence_ids():
    record = _run()

    outcome = replay_research_run(**record)

    assert outcome.matched is True
    assert outcome.status == "matched"
    assert outcome.fact_ids_matched is True
    assert outcome.replayed_actions == outcome.stored_actions == {"600519": "关注"}
    assert outcome.mismatches == ()


def test_replay_detects_drifted_stored_conclusion():
    """记录的结论被篡改（或实现漂移）时必须报出具体差异。"""
    record = _run()
    record["results"][0]["action"] = "观望"

    outcome = replay_research_run(**record)

    assert outcome.matched is False
    assert outcome.status == MISMATCHED
    assert any("action" in item for item in outcome.mismatches)
    assert outcome.replayed_actions == {"600519": "关注"}


def test_replay_detects_score_drift():
    record = _run()
    record["results"][0]["scores"] = {**record["results"][0]["scores"], "total": 1.0}

    outcome = replay_research_run(**record)

    assert outcome.matched is False
    assert "600519:scores" in outcome.mismatches


def test_replay_is_idempotent_across_two_runs():
    """同一份证据重复重放必须得到同一事实 ID（决定化 ID 的意义）。"""
    record = _run()
    first = replay_research_run(**record)
    second = replay_research_run(**record)

    assert first.fact_ids_matched and second.fact_ids_matched
    assert first.replayed_actions == second.replayed_actions


def test_replay_refuses_unknown_rule_version():
    record = _run()
    record["rule_version"] = "research_rules/v99"

    outcome = replay_research_run(**record)

    assert outcome.status == RULES_UNAVAILABLE
    assert outcome.matched is False
    assert "research_rules/v99" in outcome.mismatches[0]


def test_replay_reports_incomplete_evidence():
    """证据缺失时必须显式标记，不能伪造结论。"""
    record = _run()
    record["snapshot_manifest"] = []

    outcome = replay_research_run(**record)

    assert outcome.matched is False
    assert f"600519:{EVIDENCE_INCOMPLETE}" in outcome.mismatches


def test_replay_reproduces_insufficient_data_conclusion():
    """取数失败时审计记录同样可重放出“数据不足”。"""
    request = _request()

    class FailingGateway:
        def get_security_data(self, stock_code: str) -> dict:
            raise RuntimeError("provider down")

    results, facts = evaluate(
        request,
        user_profile={},
        gateway=FailingGateway(),
    )
    result = results[0]
    record = {
        "research_run_id": "run-degraded",
        "request_data": request.model_dump(mode="json"),
        "results": [{
            "stock_code": "600519", "action": result.action.value,
            "scores": dict(result.scores), "fact_ids": [fact.fact_id for fact in facts],
            "exclusion_reason": "",
        }],
        "snapshot_manifest": [fact.model_dump(mode="json") for fact in facts],
        "rule_version": result.rule_version,
    }

    outcome = replay_research_run(**record)

    assert outcome.matched is True
    assert outcome.replayed_actions == {"600519": "数据不足"}
    assert record["snapshot_manifest"][0]["payload"]["inputs"]["error"] == "provider down"


def test_replay_compares_snapshot_quality_recorded_in_evidence():
    """证据里记录的数据质量必须与重算结果一致（门禁实现才可审计）。"""
    record = _run()
    for entry in record["snapshot_manifest"]:
        entry["payload"]["snapshot_quality_status"] = "critical_missing"

    outcome = replay_research_run(**record)

    assert outcome.matched is False
    assert any("data_quality" in item for item in outcome.mismatches)
