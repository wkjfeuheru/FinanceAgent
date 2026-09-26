"""从审计记录复算确定性研究结论。

审计记录包含三部分：运行级 ``request_data``、标的级结论（``research_results``）
以及 ``snapshot_manifest``（每只标的的完整取数输入、评估时点与逐项溯源）。
本模块据此**离线**重建快照并重跑同一版本的规则，然后与当时记录的结论逐项
比对：行动结论、分项评分、事实 ID、数据质量与质量原因。

比对语义：

- ``mismatched``：重算结论与记录不一致（规则或门禁实现漂移，需要人工核查）。
- ``evidence_incomplete``：审计记录缺少重放所需的输入。
- ``rules_unavailable``：审计记录的规则版本在当前代码库中不可用（不静默回退）。
- ``advisories``：仅当原运行使用 Provider 交易日历、而重放退回工作日估算时，
  新鲜度相关的差异降级为提示，避免把日历口径差异误报为逻辑漂移。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from finance_agent.domains.research.contracts import AnalysisRequest
from finance_agent.domains.research.quality_gates import GateConfig, TradingDayCounter, weekday_trading_days
from finance_agent.domains.research.rule_engine import RuleEngine, load_rules
from finance_agent.domains.research.snapshot_builder import SnapshotBuilder

MATCHED = "matched"
MISMATCHED = "mismatched"
RULES_UNAVAILABLE = "rules_unavailable"
EVIDENCE_INCOMPLETE = "evidence_incomplete"

_FLOAT_TOLERANCE = 1e-9


@dataclass(frozen=True)
class ReplayOutcome:
    """一次审计重放的比对结果。"""

    research_run_id: str
    status: str
    rule_version: str
    matched: bool
    stored_actions: dict[str, str] = field(default_factory=dict)
    replayed_actions: dict[str, str] = field(default_factory=dict)
    mismatches: tuple[str, ...] = ()
    advisories: tuple[str, ...] = ()
    fact_ids_matched: bool = False
    calendar_basis: str = ""


class EvidenceGateway:
    """从证据 payload 重建的取数网关，重放全程不访问网络。"""

    def __init__(self, inputs_by_code: dict[str, Any]):
        self._inputs = {
            str(code): value for code, value in (inputs_by_code or {}).items()
        }

    def get_security_data(self, stock_code: str) -> dict[str, Any]:
        value = self._inputs.get(str(stock_code), {})
        return dict(value) if isinstance(value, dict) else {}


def _parse_moment(value: Any) -> datetime | None:
    """解析证据里的评估时点；naive 时间按市场本地时间解释。"""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=ZoneInfo("Asia/Shanghai"))


def _entry_for(
    stored: dict[str, Any],
    facts_by_id: dict[str, dict[str, Any]],
    owners: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """按证据 ID 定位标的对应的事实记录，回退按股票代码匹配。"""
    for fact_id in stored.get("fact_ids") or []:
        if isinstance(fact_id, str) and fact_id in facts_by_id:
            return facts_by_id[fact_id]
    return owners.get(str(stored.get("stock_code") or ""))


def _evaluated_at_of(members: list[tuple[str, dict[str, Any], dict[str, Any]]]) -> datetime | None:
    """取同一次构建的评估时点：与快照层一致，取各数据项的最大值。"""
    moments = [
        moment
        for _, payload, _ in members
        if (moment := _parse_moment(payload.get("evaluated_at"))) is not None
    ]
    return max(moments) if moments else None


def _member_request(
    payload: dict[str, Any], request_data: Any, code: str,
) -> AnalysisRequest | None:
    """还原该证据所属的请求：优先使用记录值，其次由运行级请求派生。"""
    recorded = payload.get("request")
    if isinstance(recorded, dict):
        try:
            return AnalysisRequest.model_validate(recorded)
        except ValueError:
            pass
    try:
        base = AnalysisRequest.model_validate(request_data)
    except (ValueError, TypeError):
        return None
    return base.for_security(code)


def _request_signature(payload: dict[str, Any], request_data: Any, code: str) -> str:
    """按"同一次构建"给证据分组：同一个请求一起重建才能复现跨标的门禁。"""
    recorded = payload.get("request")
    if isinstance(recorded, dict):
        return json.dumps(recorded, sort_keys=True, ensure_ascii=False, default=str)
    return f"__run_level__:{json.dumps(request_data, sort_keys=True, ensure_ascii=False, default=str)}:{code}"


def _calendar_for(
    payload: dict[str, Any], *, provider_calendar: bool,
    provider_calendar_counter: TradingDayCounter | None = None,
) -> tuple[TradingDayCounter, str, bool]:
    """按证据记录的日历口径选择计数器，返回 (计数器, 口径, 是否降级)。"""
    provenance = payload.get("provenance")
    quote_trace = provenance.get("quote") if isinstance(provenance, dict) else None
    recorded = quote_trace.get("trading_calendar") if isinstance(quote_trace, dict) else None
    if recorded == "provider":
        if not provider_calendar or provider_calendar_counter is None:
            return weekday_trading_days, "weekday(offline)", True
        return provider_calendar_counter, "provider", False
    return weekday_trading_days, "weekday", False


def _assessment_scores(assessment: Any) -> dict[str, float | None]:
    scores = assessment.scores
    return {
        "fundamental": scores.fundamental,
        "technical": scores.technical,
        "risk": scores.risk,
        "suitability": scores.suitability,
        "total": scores.total,
    }


def _numbers_equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        return abs(float(left) - float(right)) <= _FLOAT_TOLERANCE
    except (TypeError, ValueError):
        return False


def _scores_equal(stored: Any, replayed: dict[str, float | None]) -> bool:
    if not isinstance(stored, dict):
        return False
    return all(
        _numbers_equal(stored.get(key), value)
        for key, value in replayed.items()
    )


def _list_diff(expected: Any, actual: list[str]) -> str:
    expected_list = [str(item) for item in expected] if isinstance(expected, list) else []
    if expected_list == list(actual):
        return ""
    return f"{expected_list} -> {list(actual)}"


def replay_research_run(
    *,
    research_run_id: str,
    request_data: Any,
    results: list[dict[str, Any]],
    snapshot_manifest: list[dict[str, Any]],
    rule_version: str = "",
    provider_calendar: bool = False,
    provider_calendar_counter: TradingDayCounter | None = None,
) -> ReplayOutcome:
    """复算一次已审计的研究运行，返回与记录结论的比对结果。

    参数名与 ``ResearchRunRepository.load`` 的返回键一致，便于直接解包复核。
    """
    version = str(rule_version or "").strip()
    if not version:
        return ReplayOutcome(
            research_run_id=research_run_id, status=RULES_UNAVAILABLE,
            rule_version="", matched=False,
            mismatches=("rule_version_missing",),
        )
    try:
        rules = load_rules(version)
    except (ValueError, OSError) as exc:
        return ReplayOutcome(
            research_run_id=research_run_id, status=RULES_UNAVAILABLE,
            rule_version=version, matched=False, mismatches=(str(exc),),
        )

    engine = RuleEngine(rules)
    gate_config = GateConfig.from_rules(rules)
    mismatches: list[str] = []
    advisories: list[str] = []
    stored_actions: dict[str, str] = {}
    replayed_actions: dict[str, str] = {}
    fact_ids_matched = True
    calendars = set()
    handled: set[str] = set()

    # 按"同一次构建"分组：比较请求的全部标的必须一起重建，跨标的门禁
    # （如报告期混用）与评估时点都取决于整批标的，逐只重建会复现不出原结论。
    groups: dict[str, list[tuple[str, dict[str, Any], dict[str, Any]]]] = {}
    owners: dict[str, dict[str, Any]] = {}
    facts_by_id: dict[str, dict[str, Any]] = {}
    for entry in snapshot_manifest or []:
        if not isinstance(entry, dict):
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        code = str(payload.get("code") or "")
        if code:
            owners[code] = entry
        fact_id = str(entry.get("fact_id") or "")
        if fact_id:
            facts_by_id[fact_id] = entry
        groups.setdefault(_request_signature(payload, request_data, code), []).append(
            (code, payload, entry)
        )

    for members in groups.values():
        request = _member_request(members[0][1], request_data, members[0][0])
        member_codes = {code for code, _, _ in members}
        if request is None:
            mismatches.extend(f"{code}:{EVIDENCE_INCOMPLETE}" for code in sorted(member_codes))
            handled.update(member_codes)
            continue

        inputs_by_code = {
            code: payload["inputs"] for code, payload, _ in members
            if isinstance(payload.get("inputs"), dict) and payload["inputs"]
        }
        counter, basis, degraded = _calendar_for(
            members[0][1], provider_calendar=provider_calendar,
            provider_calendar_counter=provider_calendar_counter,
        )
        calendars.add(basis)
        builder = SnapshotBuilder(
            EvidenceGateway(inputs_by_code),
            gate_config=gate_config,
            trading_days=counter,
            evaluated_at=_evaluated_at_of(members),
        )
        snapshot, replayed_facts = builder.build(request)
        replayed_by_code = {
            str(fact.payload.get("code")): fact for fact in replayed_facts
        }
        securities = {security.code: security for security in snapshot.securities}

        for stored in results or []:
            if not isinstance(stored, dict):
                continue
            code = str(stored.get("stock_code") or "")
            entry = _entry_for(stored, facts_by_id, owners)
            payload = entry.get("payload") if isinstance(entry, dict) else None
            if not isinstance(payload, dict) or str(payload.get("code") or "") not in member_codes:
                continue
            if code not in inputs_by_code:
                mismatches.append(f"{code}:{EVIDENCE_INCOMPLETE}")
                handled.add(code)
                continue

            security = securities.get(code)
            replayed_fact = replayed_by_code.get(code)
            item_request = request.for_security(code)
            if security is None:
                mismatches.append(f"{code}:{EVIDENCE_INCOMPLETE}")
                handled.add(code)
                continue
            handled.add(code)
            item_snapshot = snapshot.model_copy(
                update={"securities": [security], "request": item_request},
            )
            assessment = engine.evaluate(item_snapshot, item_request)

            stored_actions[code] = str(stored.get("action", ""))
            replayed_actions[code] = assessment.action.value
            if stored_actions[code] != replayed_actions[code]:
                mismatches.append(f"{code}:action {stored_actions[code]} -> {replayed_actions[code]}")
            if not _scores_equal(stored.get("scores"), _assessment_scores(assessment)):
                mismatches.append(f"{code}:scores")

            # 事实 ID 必须与审计记录里引用的完全一致，否则记录无法复算同一证据。
            if replayed_fact is None or replayed_fact.fact_id not in set(stored.get("fact_ids") or []):
                fact_ids_matched = False
                mismatches.append(f"{code}:fact_id")

            # 质量结论与限制原因都是门禁与评分的确定性产物。
            target = advisories if degraded else mismatches
            expected_status = payload.get("snapshot_quality_status") or payload.get("quality_status")
            if expected_status != snapshot.quality.status:
                target.append(f"{code}:data_quality {expected_status} -> {snapshot.quality.status}")
            expected_missing = payload.get("missing_critical")
            if isinstance(expected_missing, list) and expected_missing != list(security.quality.missing_critical):
                target.append(
                    f"{code}:missing_critical {_list_diff(expected_missing, security.quality.missing_critical)}"
                )
            expected_warnings = payload.get("warnings")
            if isinstance(expected_warnings, list) and expected_warnings != list(security.quality.warnings):
                target.append(
                    f"{code}:warnings {_list_diff(expected_warnings, security.quality.warnings)}"
                )

    # 记录里存在结论但证据缺失的标的必须显式标记，不能因为没进任何分组而"matched"。
    for stored in results or []:
        if not isinstance(stored, dict):
            continue
        code = str(stored.get("stock_code") or "")
        if code and code not in handled:
            mismatches.append(f"{code}:{EVIDENCE_INCOMPLETE}")

    matched = not mismatches
    return ReplayOutcome(
        research_run_id=research_run_id,
        status=MATCHED if matched else MISMATCHED,
        rule_version=version,
        matched=matched,
        stored_actions=stored_actions,
        replayed_actions=replayed_actions,
        mismatches=tuple(mismatches),
        advisories=tuple(advisories),
        fact_ids_matched=fact_ids_matched,
        calendar_basis=",".join(sorted(calendars)),
    )


__all__ = [
    "EVIDENCE_INCOMPLETE",
    "MATCHED",
    "MISMATCHED",
    "RULES_UNAVAILABLE",
    "EvidenceGateway",
    "ReplayOutcome",
    "replay_research_run",
]
