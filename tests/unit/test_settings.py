"""Infrastructure settings validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_orchestration_settings_accept_defaults():
    from finance_agent.infrastructure.settings import OrchestrationSettings

    settings = OrchestrationSettings()
    assert settings.react_steps >= 1
    assert settings.max_domains >= 1
    assert settings.clarify_rounds >= 1
    assert settings.compliance_rewrites >= 0
    assert settings.graph_steps >= 1
    assert settings.turn_deadline > 0
    # 不变量：等待上限不得短于执行上限（否则用户先看到超时而执行仍在继续）。
    assert settings.turn_timeout >= settings.turn_deadline


@pytest.mark.parametrize(
    "kwargs",
    [
        {"react_steps": 0},
        {"max_domains": 0},
        {"clarify_rounds": 0},
        {"compliance_rewrites": -1},
        {"graph_steps": 0},
        {"turn_timeout": 0},
        {"turn_deadline": 0},
        {"stream_chunk_size": 0},
        # 执行上限长于等待上限：构造时必须被拒绝。
        {"turn_timeout": 30, "turn_deadline": 60},
    ],
)
def test_orchestration_settings_reject_invalid_values(kwargs):
    from finance_agent.infrastructure.settings import OrchestrationSettings

    with pytest.raises(ValidationError):
        OrchestrationSettings(**kwargs)


def test_orchestration_settings_bounds_screen_budget():
    """板块筛选预算：条数有界，且返回条数不得超过评估条数。"""
    from finance_agent.infrastructure.settings import OrchestrationSettings

    settings = OrchestrationSettings()
    assert settings.screen_max_evaluations >= 1
    assert 1 <= settings.screen_max_results <= settings.screen_max_evaluations
    with pytest.raises(ValidationError):
        OrchestrationSettings(screen_max_evaluations=0)
    with pytest.raises(ValidationError):
        OrchestrationSettings(screen_max_evaluations=99)
    with pytest.raises(ValidationError):
        OrchestrationSettings(screen_max_evaluations=3, screen_max_results=5)


def test_postgres_settings_reject_invalid_values():
    from finance_agent.infrastructure.settings import PostgresSettings

    with pytest.raises(ValidationError):
        PostgresSettings(port="not-a-port")
    with pytest.raises(ValidationError):
        PostgresSettings(pool_min_size=8, pool_max_size=4)
    with pytest.raises(ValidationError):
        PostgresSettings(connect_timeout=-1)


def test_config_still_exports_the_validated_values():
    """兼容导出：config 的常量名保持存在，且与 Settings 的校验口径一致。"""
    from finance_agent.infrastructure import settings as config
    from finance_agent.infrastructure.settings import load_orchestration_settings, load_postgres_settings

    orchestration = load_orchestration_settings()
    postgres = load_postgres_settings()

    assert config.ORCHESTRATION_REACT_STEPS == orchestration.react_steps
    assert config.ORCHESTRATION_MAX_DOMAINS == orchestration.max_domains
    assert config.ORCHESTRATION_CLARIFY_ROUNDS == orchestration.clarify_rounds
    assert config.ORCHESTRATION_COMPLIANCE_REWRITES == orchestration.compliance_rewrites
    assert config.ORCHESTRATION_GRAPH_STEPS == orchestration.graph_steps
    assert config.ORCHESTRATION_TURN_DEADLINE == orchestration.turn_deadline
    assert config.ORCHESTRATION_TURN_TIMEOUT == orchestration.turn_timeout
    assert config.ORCHESTRATION_SCREEN_MAX_EVALUATIONS == orchestration.screen_max_evaluations
    assert config.ORCHESTRATION_SCREEN_MAX_RESULTS == orchestration.screen_max_results
    assert config.POSTGRES_HOST == postgres.host
    assert config.POSTGRES_PORT == postgres.port
    assert config.POSTGRES_POOL_MIN_SIZE == postgres.pool_min_size
    assert config.POSTGRES_POOL_MAX_SIZE == postgres.pool_max_size
