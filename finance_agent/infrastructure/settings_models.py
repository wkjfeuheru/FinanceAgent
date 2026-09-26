"""经校验的编排和 PostgreSQL 设置模型。"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return float(raw)


class OrchestrationSettings(BaseModel):
    """LangGraph 编排预算与流式呈现参数（全部为正/非负整数域）。

    字段默认值与 ``config`` 的历史默认一致，便于直接构造与测试。

    ``turn_deadline`` 是**整轮**（分类 + 各领域专家 + 汇合 + 合规）的墙钟上限，
    单领域与多领域共用同一个值；``turn_timeout`` 是 API/SSE 层的等待上限。两者
    必须满足 ``turn_timeout >= turn_deadline``：等待上限比执行上限更短，只会
    让用户先看到"超时"而执行线程仍在跑（历史缺陷），因此在此显式拒绝。
    """

    model_config = ConfigDict(frozen=True)

    react_steps: int = Field(default=4, ge=1)
    #: 单轮最多扇出的业务领域数（领域总数为 4，此处是防御性上限）。
    max_domains: int = Field(default=4, ge=1)
    compliance_rewrites: int = Field(default=1, ge=0)
    graph_steps: int = Field(default=64, ge=1)
    #: 缺参追问的总弹窗上限（首次 + 重问次数），确定性计数，不依赖模型自觉。
    clarify_rounds: int = Field(default=2, ge=1)
    turn_timeout: float = Field(default=180.0, gt=0)
    turn_deadline: float = Field(default=120.0, gt=0)
    stream_chunk_size: int = Field(default=12, ge=1)
    stream_chunk_delay_ms: float = Field(default=18.0, ge=0)
    stream_max_seconds: float = Field(default=3.0, ge=0)

    @model_validator(mode="after")
    def _turn_budget_ordering(self) -> "OrchestrationSettings":
        if self.turn_timeout < self.turn_deadline:
            raise ValueError(
                "ORCHESTRATION_TURN_TIMEOUT 不得小于 ORCHESTRATION_TURN_DEADLINE"
                "（等待上限短于执行上限会让用户先看到超时而执行仍在继续）"
            )
        return self


class PostgresSettings(BaseModel):
    """PostgreSQL 连接与连接池参数。"""

    model_config = ConfigDict(frozen=True)

    dsn: str = ""
    host: str = "localhost"
    port: str = "5432"
    user: str = "postgres"
    password: str = ""
    database: str = "advisor"
    connect_timeout: float = Field(default=10.0, gt=0)
    pool_min_size: int = Field(default=4, ge=1)
    pool_max_size: int = Field(default=16, ge=1)
    pool_timeout: float = Field(default=30.0, gt=0)

    @field_validator("port")
    @classmethod
    def _port_is_numeric(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("POSTGRES_PORT 必须是数字")
        return value

    @field_validator("pool_max_size")
    @classmethod
    def _pool_max_not_below_min(cls, value: int, info) -> int:
        minimum = info.data.get("pool_min_size")
        if minimum is not None and value < minimum:
            raise ValueError("POSTGRES_POOL_MAX_SIZE 不得小于 POSTGRES_POOL_MIN_SIZE")
        return value


def load_orchestration_settings() -> OrchestrationSettings:
    """从环境变量装配并校验编排设置。"""
    return OrchestrationSettings(
        react_steps=_env_int("ORCHESTRATION_REACT_STEPS", 4),
        max_domains=_env_int("ORCHESTRATION_MAX_DOMAINS", 4),
        compliance_rewrites=_env_int("ORCHESTRATION_COMPLIANCE_REWRITES", 1),
        graph_steps=_env_int("ORCHESTRATION_GRAPH_STEPS", 64),
        clarify_rounds=_env_int("ORCHESTRATION_CLARIFY_ROUNDS", 2),
        turn_timeout=_env_float("ORCHESTRATION_TURN_TIMEOUT", 180.0),
        turn_deadline=_env_float("ORCHESTRATION_TURN_DEADLINE", 120.0),
        stream_chunk_size=_env_int("ORCHESTRATION_STREAM_CHUNK_SIZE", 12),
        stream_chunk_delay_ms=_env_float("ORCHESTRATION_STREAM_CHUNK_DELAY_MS", 18.0),
        stream_max_seconds=_env_float("ORCHESTRATION_STREAM_MAX_SECONDS", 3.0),
    )


def load_postgres_settings() -> PostgresSettings:
    """从环境变量装配并校验 PostgreSQL 设置。"""
    return PostgresSettings(
        dsn=os.getenv("POSTGRES_DSN", "").strip(),
        host=os.getenv("POSTGRES_HOST", "localhost").strip(),
        port=os.getenv("POSTGRES_PORT", "5432").strip(),
        user=os.getenv("POSTGRES_USER", "postgres").strip(),
        password=os.getenv("POSTGRES_PASSWORD", "").strip(),
        database=os.getenv("POSTGRES_DB", "advisor").strip(),
        connect_timeout=_env_float("POSTGRES_CONNECT_TIMEOUT", 10.0),
        pool_min_size=_env_int("POSTGRES_POOL_MIN_SIZE", 4),
        pool_max_size=_env_int("POSTGRES_POOL_MAX_SIZE", 16),
        pool_timeout=_env_float("POSTGRES_POOL_TIMEOUT", 30.0),
    )


def settings_dump(settings: BaseModel) -> dict[str, Any]:
    """便于诊断/日志的只读字典视图。"""
    return settings.model_dump()


__all__ = [
    "OrchestrationSettings",
    "PostgresSettings",
    "load_orchestration_settings",
    "load_postgres_settings",
    "settings_dump",
]
