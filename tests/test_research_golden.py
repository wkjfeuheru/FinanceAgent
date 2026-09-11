"""固定研究样本的可重放结论测试。"""

import json
from pathlib import Path

from finance_agent.research.contracts import AnalysisRequest
from finance_agent.research.pipeline import ResearchPipeline
from finance_agent.research.rule_engine import RuleEngine
from finance_agent.research.snapshot_builder import SnapshotBuilder


class FixtureGateway:
    """回放夹具中保存的原始取数字段，不做任何补齐或改写。"""

    def __init__(self, security: dict):
        self._security = security

    def get_security_data(self, stock_code: str) -> dict:
        assert stock_code == "600519"
        return dict(self._security)


def load_fixture(name: str) -> tuple[AnalysisRequest, FixtureGateway]:
    path = Path(__file__).parent / "fixtures" / "research" / name
    payload = json.loads(path.read_text(encoding="utf-8"))
    security = payload["security"]
    # 夹具必须自带上限内完整的 K 线：过去用单行复制补足会制造跨周期跳空，
    # 掩盖真实的价格序列形态。
    rows = security.get("history", {}).get("data", [])
    assert len(rows) >= 60, f"{name} 夹具必须自带不少于 60 根 K 线"
    return AnalysisRequest.model_validate(payload["request"]), FixtureGateway(security)


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
    assert first.rule_version == "research_rules/v1.1"
    assert first.data_quality == "complete"
    # 评分必须由夹具里的原始财务/行情字段推导，而不是夹具直接给出的评分。
    assert first.scores["fundamental"] == 80.0
    assert first.scores["total"] == 82.0
    assert first.scores == second.scores


def test_conflicted_fixture_is_wait_not_watch():
    result = _result("conflicted_600519.json")

    assert result.action.value == "观望"
    assert result.scores["fundamental"] == 80.0
    assert result.scores["technical"] == 48.33
    assert result.scores["risk"] == 65.0
