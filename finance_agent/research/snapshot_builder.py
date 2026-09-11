"""构建带溯源信息和质量门禁的不可变市场数据快照。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from finance_agent.contracts import FactSnapshot
from finance_agent.research.contracts import (
    AnalysisRequest,
    DataQuality,
    MarketDataSnapshot,
    QuoteSnapshot,
    SecuritySnapshot,
)


class StockDataGateway(Protocol):
    """快照构建器所需的最小数据网关。"""

    def get_security_data(self, stock_code: str) -> dict[str, Any]: ...


def _parse_datetime(value: Any) -> datetime | None:
    """容忍 ISO 字符串或 datetime，解析失败返回 None。"""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _combine_quality(items: list[DataQuality]) -> DataQuality:
    """按关键缺失优先级合并多只股票的数据质量。"""
    missing = list(dict.fromkeys(
        reason for item in items for reason in item.missing_critical
    ))
    warnings = list(dict.fromkeys(
        reason for item in items for reason in item.warnings
    ))
    status = "critical_missing" if missing else "warning" if warnings else "complete"
    return DataQuality(status=status, missing_critical=missing, warnings=warnings)


class SnapshotBuilder:
    """从显式网关数据构建标准化研究快照。"""

    def __init__(self, gateway: StockDataGateway):
        self._gateway = gateway

    def build(
        self,
        request: AnalysisRequest,
    ) -> tuple[MarketDataSnapshot, list[FactSnapshot]]:
        securities: list[SecuritySnapshot] = []
        facts: list[FactSnapshot] = []
        for code in request.stock_codes:
            security, fact = self._build_security(code)
            securities.append(security)
            facts.append(fact)
        quality = _combine_quality([security.quality for security in securities])
        return (
            MarketDataSnapshot(
                request=request,
                securities=securities,
                quality=quality,
            ),
            facts,
        )

    def _build_security(self, code: str) -> tuple[SecuritySnapshot, FactSnapshot]:
        try:
            raw = self._gateway.get_security_data(code)
        except Exception as exc:
            raw = {"error": str(exc)}

        basic_info = raw.get("basic_info", {}) if isinstance(raw, dict) else {}
        quote_data = raw.get("quote", {}) if isinstance(raw, dict) else {}
        history = raw.get("history", {}) if isinstance(raw, dict) else {}
        indicators = raw.get("indicators", {}) if isinstance(raw, dict) else {}

        missing: list[str] = []
        warnings: list[str] = []
        if not isinstance(raw, dict) or raw.get("error"):
            missing.append("stock_data")
        if not isinstance(history, dict) or history.get("adjustment") != "forward":
            missing.append("adjusted_history")
        if not quote_data:
            missing.append("quote")

        status = "critical_missing" if missing else "warning" if warnings else "complete"
        quality = DataQuality(
            status=status,
            missing_critical=missing,
            warnings=warnings,
        )
        quote = QuoteSnapshot(
            source=str(quote_data.get("source", "unavailable")),
            fetched_at=_parse_datetime(quote_data.get("fetched_at")),
            fallback_from=quote_data.get("fallback_from"),
            as_of=str(quote_data.get("as_of") or quote_data.get("date") or ""),
            price=quote_data.get("price"),
        )
        security = SecuritySnapshot(
            code=code,
            basic_info=basic_info if isinstance(basic_info, dict) else {},
            quote=quote,
            history=history if isinstance(history, dict) else {},
            indicators=indicators if isinstance(indicators, dict) else {},
            quality=quality,
        )
        fetched_at = quote.fetched_at or datetime.now(timezone.utc)
        fact = FactSnapshot(
            fact_id=f"stock_snapshot:{code}:{uuid4()}",
            domain="stock_research_snapshot",
            source=quote.source,
            fetched_at=fetched_at,
            payload={
                "code": code,
                "quality_status": status,
                "missing_critical": missing,
                "fallback_from": quote.fallback_from,
                "quote_as_of": quote.as_of,
                "history_adjustment": history.get("adjustment") if isinstance(history, dict) else None,
            },
        )
        return security, fact
