"""固定研究样本的可重放结论测试。"""

import json
from pathlib import Path

from finance_agent.research.contracts import AnalysisRequest
from finance_agent.research.pipeline import ResearchPipeline
from finance_agent.research.rule_engine import RuleEngine
from finance_agent.research.snapshot_builder import SnapshotBuilder


class FixtureGateway:
    def __init__(self, security: dict):
        self._security = security

    def get_security_data(self, stock_code: str) -> dict:
        assert stock_code == "600519"
        security = dict(self._security)
        history = dict(security.get("history", {}))
        rows = list(history.get("data", []))
        history["data"] = rows * 60
        security["history"] = history
        return security


def load_fixture(name: str) -> tuple[AnalysisRequest, FixtureGateway]:
    path = Path(__file__).parent / "fixtures" / "research" / name
    payload = json.loads(path.read_text(encoding="utf-8"))
    return AnalysisRequest.model_validate(payload["request"]), FixtureGateway(payload["security"])


def _result(name: str):
    request, gateway = load_fixture(name)
    pipeline = ResearchPipeline(
        snapshot_builder=SnapshotBuilder(gateway),
        rule_engine=RuleEngine.default(),
    )
    return pipeline.analyze(
        request,
        user_profile={"risk_preference": "稳健", "holding_period": "3个月"},
    )


def test_complete_fixture_is_watch_and_replayable():
    first = _result("complete_600519.json")
    second = _result("complete_600519.json")

    assert first.action.value == "关注"
    assert first.rule_version == "research_rules/v1"
    assert first.scores == second.scores


def test_conflicted_fixture_is_wait_not_watch():
    result = _result("conflicted_600519.json")

    assert result.action.value == "观望"
