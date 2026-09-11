"""构建带溯源信息和质量门禁的不可变市场数据快照。

快照构建器同时负责三件事，且全部是确定性的：

1. 把网关原始数据标准化为 ``SecuritySnapshot``，并由 ``scoring`` 生成三项评分；
2. 执行版本化质量门禁（新鲜度、基本面溯源、来源一致性、跨期一致性）；
3. 产出**可重放**的证据事实：``FactSnapshot.payload`` 保存用于评分的完整原始
   财务/估值/行情字段、评估时点与逐项溯源，``fact_id`` 由证据内容摘要决定，
   因此同一份审计记录可以复算出同一结论和同一证据 ID。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Protocol

from finance_agent.contracts import FactSnapshot
from finance_agent.research.contracts import (
    AnalysisRequest,
    DataQuality,
    MarketDataSnapshot,
    QuoteSnapshot,
    SecuritySnapshot,
)
from finance_agent.research.quality_gates import (
    MARKET_TIMEZONE,
    GateConfig,
    TradingDayCounter,
    calendar_degradation_reasons,
    fundamental_provenance,
    history_freshness,
    mixed_report_periods,
    quote_freshness,
    source_consistency,
    weekday_trading_days,
)
from finance_agent.research.rule_engine import CURRENT_RULES_VERSION, load_rules
from finance_agent.research.scoring import build_scores

# 已审定的规则文件里门禁阈值与评分权重同源，避免两处阈值漂移。
_DEFAULT_RULES_VERSION = CURRENT_RULES_VERSION
# 证据摘要只覆盖内容字段：逐项 fetched_at 会随抓取时刻变化，纳入摘要会让
# 同一份市场数据在两次运行中得到不同事实 ID。时点信息由 evaluated_at 承担。
_VOLATILE_KEYS = frozenset({"fetched_at"})
_EVIDENCE_INPUT_KEYS = ("basic_info", "quote", "history", "indicators")


class StockDataGateway(Protocol):
    """快照构建器所需的最小数据网关。"""

    def get_security_data(self, stock_code: str) -> dict[str, Any]: ...


@dataclass
class _BuiltSecurity:
    """单只证券的构建中间结果，跨标的门禁完成后再生成事实。"""

    security: SecuritySnapshot
    raw: dict[str, Any]
    provenance: dict[str, Any]
    report_period: str | None


def _parse_datetime(value: Any) -> datetime | None:
    """容忍 ISO 字符串或 datetime；naive 时间按市场本地时间解释。"""
    if isinstance(value, datetime):
        moment = value
    elif not value:
        return None
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=MARKET_TIMEZONE)
    return moment


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


def _with_cross_reasons(quality: DataQuality, reasons: list[str]) -> DataQuality:
    """把跨标的门禁原因并入快照级质量结论。

    跨标的比较是否成立取决于整批标的的报告期，单只标的无法判定，
    因此只在快照级补齐，避免逐只误报。
    """
    if not reasons:
        return quality
    missing = list(dict.fromkeys([*quality.missing_critical, *reasons]))
    return DataQuality(
        status="critical_missing" if missing else "warning" if quality.warnings else "complete",
        missing_critical=missing,
        warnings=list(quality.warnings),
    )


def _without_volatile(record: Any) -> Any:
    """剔除随抓取时刻变化的字段，供证据摘要使用。"""
    if not isinstance(record, dict):
        return record
    return {key: value for key, value in record.items() if key not in _VOLATILE_KEYS}


def _evidence_digest(projection: dict[str, Any]) -> str:
    """计算证据内容的稳定摘要（同一输入必得同一 ID）。"""
    canonical = json.dumps(
        projection, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _last_bar_date(history: dict[str, Any]) -> Any:
    """取最后一根有效 K 线的日期；无有效记录时返回 None。"""
    rows = history.get("data", []) if isinstance(history, dict) else []
    if not isinstance(rows, list):
        return None
    for row in reversed(rows):
        if isinstance(row, dict):
            moment = row.get("trade_date") or row.get("date")
            if moment:
                return moment
    return None


class SnapshotBuilder:
    """从显式网关数据构建标准化研究快照。"""

    def __init__(
        self,
        gateway: StockDataGateway,
        *,
        gate_config: GateConfig | None = None,
        trading_days: TradingDayCounter = weekday_trading_days,
        evaluated_at: datetime | None = None,
    ):
        self._gateway = gateway
        self._gate_config = gate_config or GateConfig.from_rules(load_rules(_DEFAULT_RULES_VERSION))
        self._trading_days = trading_days
        self._evaluated_at = evaluated_at

    @property
    def gate_config(self) -> GateConfig:
        """当前生效的门禁阈值（供审计与测试读取）。"""
        return self._gate_config

    def build(
        self,
        request: AnalysisRequest,
    ) -> tuple[MarketDataSnapshot, list[FactSnapshot]]:
        raw_by_code = {code: self._fetch(code) for code in request.stock_codes}
        evaluated_at = self._resolve_evaluated_at(raw_by_code)

        built = [
            self._build_security(code, raw_by_code[code], evaluated_at)
            for code in request.stock_codes
        ]
        quality = _combine_quality([item.security.quality for item in built])
        cross_reasons = mixed_report_periods({
            item.security.code: item.report_period for item in built if item.report_period
        })
        quality = _with_cross_reasons(quality, cross_reasons)

        snapshot = MarketDataSnapshot(
            request=request,
            securities=[item.security for item in built],
            quality=quality,
        )
        facts = [
            self._make_fact(item, evaluated_at=evaluated_at, request=request,
                            cross_reasons=cross_reasons, snapshot_status=quality.status)
            for item in built
        ]
        return snapshot, facts

    def _fetch(self, code: str) -> dict[str, Any]:
        """取数异常在此边界转为显式的 ``error`` 字段，不静默吞掉。"""
        try:
            raw = self._gateway.get_security_data(code)
        except Exception as exc:
            return {"error": str(exc)}
        return raw if isinstance(raw, dict) else {"error": "网关返回非对象数据"}

    def _resolve_evaluated_at(self, raw_by_code: dict[str, Any]) -> datetime:
        """评估时点 = 各数据项抓取时刻的最大值；缺失时用当前时间。

        评估时点必须随快照一起记录，否则重放会因“当前时间”漂移而得到不同结论。
        """
        if self._evaluated_at is not None:
            return self._evaluated_at
        moments = [
            moment
            for raw in raw_by_code.values()
            for key in _EVIDENCE_INPUT_KEYS
            if isinstance(raw, dict) and isinstance(raw.get(key), dict)
            and (moment := _parse_datetime(raw[key].get("fetched_at"))) is not None
        ]
        return max(moments) if moments else datetime.now(timezone.utc)

    def _build_security(
        self,
        code: str,
        raw: dict[str, Any],
        evaluated_at: datetime,
    ) -> _BuiltSecurity:
        basic_info = raw.get("basic_info", {}) if isinstance(raw, dict) else {}
        quote_data = raw.get("quote", {}) if isinstance(raw, dict) else {}
        history = raw.get("history", {}) if isinstance(raw, dict) else {}
        raw_indicators = raw.get("indicators", {}) if isinstance(raw, dict) else {}
        indicators = dict(raw_indicators) if isinstance(raw_indicators, dict) else {}

        missing: list[str] = []
        warnings: list[str] = []
        if not isinstance(raw, dict) or raw.get("error"):
            missing.append("stock_data")
        if not isinstance(history, dict) or history.get("adjustment") != "forward":
            missing.append("adjusted_history")
        if not quote_data:
            missing.append("quote")

        scores, score_restrictions = build_scores(indicators, history)
        indicators = {
            key: value for key, value in indicators.items()
            if key not in scores
        }
        indicators.update(scores)
        indicators["score_restrictions"] = score_restrictions

        quote = QuoteSnapshot(
            source=str(quote_data.get("source", "unavailable")),
            fetched_at=_parse_datetime(quote_data.get("fetched_at")),
            fallback_from=quote_data.get("fallback_from"),
            as_of=str(quote_data.get("as_of") or quote_data.get("date") or ""),
            price=quote_data.get("price"),
        )

        # 门禁：新鲜度（硬门禁）+ 基本面溯源与来源一致性（披露性）。
        quote_reasons, quote_provenance = quote_freshness(
            quote.as_of or quote_data.get("date"),
            evaluated_at=evaluated_at, config=self._gate_config, trading_days=self._trading_days,
        )
        history_reasons, history_provenance = history_freshness(
            _last_bar_date(history),
            evaluated_at=evaluated_at, config=self._gate_config, trading_days=self._trading_days,
        )
        fundamental_warnings, fundamental_trace = fundamental_provenance(
            indicators, evaluated_at=evaluated_at, config=self._gate_config,
        )
        history_source = history.get("source") if isinstance(history, dict) else None
        missing.extend(quote_reasons)
        missing.extend(history_reasons)
        warnings.extend(fundamental_warnings)
        warnings.extend(source_consistency({
            "quote": quote.source,
            "history": history_source or "",
            "indicators": indicators.get("source") or "",
        }))
        warnings.extend(calendar_degradation_reasons(quote_provenance, history_provenance))

        missing = list(dict.fromkeys(missing))
        warnings = list(dict.fromkeys(warnings))
        status = "critical_missing" if missing else "warning" if warnings else "complete"
        quality = DataQuality(status=status, missing_critical=missing, warnings=warnings)

        provenance = {
            "evaluated_at": evaluated_at.isoformat(),
            "quote": {
                **quote_provenance,
                "source": quote.source,
                "fetched_at": quote_data.get("fetched_at"),
                "fallback_from": quote.fallback_from,
                # 最新报价保持原始口径，不得冒充前复权价格。
                "price_basis": str(quote_data.get("adjustment") or "raw"),
            },
            "history": {
                **history_provenance,
                "source": history_source,
                "fetched_at": history.get("fetched_at") if isinstance(history, dict) else None,
                "adjustment": history.get("adjustment") if isinstance(history, dict) else None,
            },
            "indicators": {
                **fundamental_trace,
                "source": indicators.get("source"),
                "fetched_at": indicators.get("fetched_at"),
            },
        }
        security = SecuritySnapshot(
            code=code,
            basic_info=basic_info if isinstance(basic_info, dict) else {},
            quote=quote,
            history=history if isinstance(history, dict) else {},
            indicators=indicators,
            quality=quality,
        )
        return _BuiltSecurity(
            security=security,
            raw=raw,
            provenance=provenance,
            report_period=fundamental_trace.get("end_date"),
        )

    def _make_fact(
        self,
        built: _BuiltSecurity,
        *,
        evaluated_at: datetime,
        request: AnalysisRequest,
        cross_reasons: list[str],
        snapshot_status: str,
    ) -> FactSnapshot:
        """生成可重放事实：完整原始输入 + 评估时点 + 逐项溯源 + 内容摘要 ID。"""
        security = built.security
        # 完整保存网关原始返回（含取数失败时的 error 字段），重放才能复现同一次判定。
        evidence_inputs = _without_volatile(built.raw) if isinstance(built.raw, dict) else {}
        digest = _evidence_digest({
            "code": security.code,
            "evaluated_at": evaluated_at.isoformat(),
            "request": request.model_dump(mode="json"),
            "cross_security_reasons": list(cross_reasons),
            "inputs": evidence_inputs,
        })
        payload = {
            "code": security.code,
            "quality_status": security.quality.status,
            "snapshot_quality_status": snapshot_status,
            "missing_critical": list(security.quality.missing_critical),
            "warnings": list(security.quality.warnings),
            "fallback_from": security.quote.fallback_from,
            "quote_as_of": security.quote.as_of,
            "history_adjustment": security.history.get("adjustment") if isinstance(security.history, dict) else None,
            # 以下字段是审计重放输入：完整原始取数字段、评估时点与逐项溯源。
            "evaluated_at": evaluated_at.isoformat(),
            "request": request.model_dump(mode="json"),
            "cross_security_reasons": list(cross_reasons),
            "inputs": evidence_inputs,
            "provenance": built.provenance,
        }
        return FactSnapshot(
            fact_id=f"stock_snapshot:{security.code}:{digest}",
            domain="stock_research_snapshot",
            source=security.quote.source,
            fetched_at=security.quote.fetched_at or evaluated_at,
            payload=payload,
        )


def production_builder(
    gateway: StockDataGateway,
    *,
    gate_config: GateConfig | None = None,
) -> SnapshotBuilder:
    """生产接线：注入 Provider 交易日历，其余参数与默认构建器一致。

    单元测试与离线场景使用默认的工作日估算，因此不会触网；只有这里
    显式引入 ``data.trading_calendar``（延迟导入以避免研究层导入数据层）。
    """
    from finance_agent.data.trading_calendar import trading_days_between

    return SnapshotBuilder(gateway, gate_config=gate_config, trading_days=trading_days_between)


__all__ = ["SnapshotBuilder", "StockDataGateway", "production_builder"]
