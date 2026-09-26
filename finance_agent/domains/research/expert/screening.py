"""主题/板块筛选：把"某个主题下有哪些标的"变成可取数、可评分的确定性流程。

背景：此前主题/板块筛选被整体下线（固定文案"当前不支持按主题或板块自动筛选股票"），
因为被删掉的实现依赖**人工审核的主题注册表**（``themes`` / ``theme_memberships`` +
管理端审核 + 外部分类服务线索），而不是可自动获取的数据。现在改成两步：

1. ``list_boards``：在东财概念/行业板块表里定位主题（"AI" → "人工智能"），由模型决定
   选哪个板块，工具只给实时候选；**取数失败与关键词不匹配必须区分**（``unavailable``
   vs ``not_found``）——把数据源故障说成"没匹配到"会让模型引导用户白改关键词；
2. ``screen_board_candidates``：板块成分 → 排除 ST/退与缺行情的记录 → 按成交额预筛
   前 N → 复刻既有 ``evaluate_research`` 的确定性评估逐只打分 → 按总分排序取前 K。

为什么按总分排序而不是按涨跌幅：涨跌幅排序等于拿行情当推荐。这里的排序口径与
``evaluate_research`` 完全一致（同一套规则、评分与行动结论），结论只来自工具产出，
并在返回值里带免责说明要求模型原样转述。
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from finance_agent.domains.research.contracts import Action, AnalysisKind, AnalysisRequest
from finance_agent.domains.research.evaluation import evaluate, project_analysis_results
from finance_agent.domains.research.expert.research_gateway import LiveStockDataGateway
from finance_agent.domains.research.expert.stockdata import _meta, _records
from finance_agent.infrastructure.market_data.provider_manager import get_provider_manager
from finance_agent.orchestration.budgets import RunBudgets
from finance_agent.orchestration.experts.base import sink_of, stop_check_of

#: 板块定位失败时的引导文案（旧的"当前不支持…"已不再成立：现在是数据匹配不到）。
NO_MATCH_HINT = (
    "未匹配到对应板块。请给出更具体的概念/板块名称（如“人工智能”“半导体”），"
    "或直接提供股票名称/代码。"
)
#: 板块**数据源**故障时的文案：与 ``NO_MATCH_HINT`` 严格区分——取数失败不是关键词
#: 问题，让模型改词重试只是白白浪费用户的时间，且会掩盖真实故障。
BOARD_UNAVAILABLE_HINT = (
    "板块数据源暂不可用（东财板块接口取数失败），这不是关键词问题："
    "可稍后重试，或直接提供股票名称/代码做个股分析。"
)
#: 清单必须随回答一起给出的免责说明（模型原样转述）。
SCREEN_DISCLAIMER = "以上为公开数据与确定性规则的评分排序，不构成投资建议或推荐。"
#: ``list_boards`` 最多返回多少个匹配板块（避免把整张板块表灌进上下文）。
MAX_BOARD_MATCHES = 8
#: 可用于规则评估的标的少于此数时，不产出清单（照搬被删实现的诚实语义）。
MIN_ELIGIBLE_MEMBERS = 3
#: 预筛口径：按成交额降序取前 N，避免对上百只成分逐个取数。
PRESCREEN_NOTE = "按成交额降序预筛，仅对靠前的有限只数做规则评估"

#: 板块类型：与 ``AkshareDataSource._BOARD_ENDPOINTS`` 同口径。
_BOARD_TYPES = ("concept", "industry")
#: 口语缩写兜底：只为最常见的英文写法补一次中文主题词，其余由模型换词重试。
#: 刻意**不做**主题词→成分的人工注册表（那正是旧实现被下线的原因）。
_KEYWORD_ALIASES = {"ai": "人工智能", "aigc": "人工智能"}
#: 与 ``AnalysisRequest`` 接受的 A 股代码段保持同一口径（北交所 920 段不在其中）。
_A_SHARE_RE = re.compile(r"^(?:60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})$")


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _board_types(board_type: str) -> tuple[str, ...]:
    """把 ``board_type`` 归一为要查询的板块类型；``both`` 表示概念 + 行业。"""
    key = str(board_type or "").strip().lower()
    if key in _BOARD_TYPES:
        return (key,)
    if key in ("", "both"):
        return _BOARD_TYPES
    raise ValueError(f"未知板块类型：{board_type}（只支持 concept / industry）")


def _match_key(value: Any) -> str:
    """匹配用的归一文本：去空白 + 小写（板块名与关键词都过同一道）。"""
    return re.sub(r"\s+", "", str(value or "")).lower()


def _match_boards(keywords: list[str], boards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按"完全相等 → 互相包含"的次序匹配板块，完全相等的排在前面。"""
    exact: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []
    for board in boards:
        name = _match_key(board.get("name"))
        if not name:
            continue
        if any(key == name for key in keywords):
            exact.append(board)
        elif any(key and (key in name or name in key) for key in keywords):
            partial.append(board)
    return exact + partial


def _eligible_members(rows: list[Any]) -> list[dict[str, Any]]:
    """成分 → 可评估候选：排除 ST/退与缺行情，再按成交额降序排列（不截断）。"""
    eligible: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        name = str(row.get("name") or "").strip()
        if not _A_SHARE_RE.fullmatch(code) or not name:
            continue
        # 风险警示与退市整理期标的直接排除；停牌（无最新价/成交额）同样不参与。
        if "ST" in name.upper() or "退" in name:
            continue
        if row.get("price") in (None, "") or row.get("turnover_amount") in (None, ""):
            continue
        eligible.append(
            {**row, "code": code, "name": name, "turnover_amount": float(row.get("turnover_amount") or 0.0)}
        )
    eligible.sort(key=lambda item: item["turnover_amount"], reverse=True)
    return eligible


def _clamp(value: Any, cap: int) -> int:
    """把调用方给的条数收敛到服务端预算内（模型不能自行放大取数量）。"""
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        number = 0
    if number <= 0:
        return cap
    return max(1, min(number, cap))


def _evaluate_one(code: str, profile: dict[str, Any]) -> tuple[Any, list[Any]]:
    """对单只标的做确定性评估（与 ``evaluate_research`` 同一条内核）。"""
    request = AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=[code])
    return evaluate(request, user_profile=profile, gateway=LiveStockDataGateway())


@tool
def list_boards(keyword: str, board_type: str = "both") -> str:
    """按关键词定位板块（概念/行业），返回板块名与实时涨跌幅。

    用户问"某主题/行业有哪些股票"时先调用它：拿到板块名后再调用
    ``screen_board_candidates``。三种结果要区别对待：

    - ``status=ok``：命中板块，继续筛选；
    - ``status=not_found``：**数据取到了但关键词没匹配上**，换中文主题词
      （如"人工智能"）重试一次；
    - ``status=unavailable``：**板块数据源取数失败**，与关键词无关：可用同一
      关键词重试一次，仍失败就如实说明是数据源问题，不要反复换词、不要补候选。

    Args:
        keyword: 主题/行业关键词，如"人工智能""半导体""白酒"。
        board_type: both（默认，概念 + 行业）/ concept / industry。
    """
    text = str(keyword or "").strip()
    if not text:
        return _json({"status": "not_found", "boards": [], "hint": NO_MATCH_HINT})
    try:
        kinds = _board_types(board_type)
    except ValueError as exc:
        return _json({"status": "error", "error": str(exc)})

    keywords = [_match_key(text)]
    alias = _KEYWORD_ALIASES.get(keywords[0])
    if alias:
        keywords.append(_match_key(alias))
    manager = get_provider_manager()
    matched: list[dict[str, Any]] = []
    # 成功取数的类型与失败的类型必须分开记录：混在一起就无法区分"关键词没匹配到"
    # 与"数据源根本没取到"，而这两种情况的正确回答完全不同。
    fetched: list[str] = []
    unavailable: list[str] = []
    reasons: dict[str, str] = {}
    for kind in kinds:
        try:
            boards = _records(manager.get_board_list(kind))
        except Exception as exc:  # noqa: BLE001 - 单类失败不影响另一类
            unavailable.append(kind)
            reasons[kind] = f"{type(exc).__name__}: {exc}"[:200]
            continue
        fetched.append(kind)
        for board in _match_boards(keywords, boards):
            matched.append({
                "name": str(board.get("name") or "").strip(),
                "board_type": kind,
                "change_pct": board.get("change_pct"),
                "up_count": board.get("up_count"),
                "down_count": board.get("down_count"),
                "leader": str(board.get("leader") or "").strip(),
            })

    if matched:
        payload: dict[str, Any] = {
            "status": "ok",
            "keyword": text,
            "boards": matched[:MAX_BOARD_MATCHES],
            "source": _meta(),
        }
    elif fetched:
        payload = {
            "status": "not_found",
            "keyword": text,
            "boards": [],
            "hint": NO_MATCH_HINT,
            "source": _meta(),
        }
    else:
        payload = {
            "status": "unavailable",
            "keyword": text,
            "boards": [],
            "hint": BOARD_UNAVAILABLE_HINT,
            "retryable": True,
            "source": _meta(),
        }
    payload["fetched_types"] = fetched
    payload["unavailable_types"] = unavailable
    if unavailable:
        payload["reasons"] = reasons
        # 只要有类型没取到，结论就建立在**不完整的板块数据**之上：`ok` 只覆盖一半，
        # `not_found` 也可能是漏查导致的假阴性，两种都必须标出来。
        payload["degraded"] = True
    return _json(payload)


@tool
def screen_board_candidates(
    board_name: str,
    config: RunnableConfig,
    board_type: str = "concept",
    max_evaluations: int = 0,
    max_results: int = 0,
) -> str:
    """按板块给出候选标的清单：板块成分 → 确定性评估 → 按综合评分排序。

    排序口径与 ``evaluate_research`` 完全一致（同一套规则、评分与行动结论），
    **不按涨跌幅排序**。只对成交额靠前的有限只数做评估（默认 10 只），最终返回
    前 5 只；回答里必须原样带上返回的 ``disclaimer``，并说明预筛口径，不得把清单
    说成"最值得关注"或推荐。

    Args:
        board_name: 板块名称，必须来自 ``list_boards`` 的返回值。
        board_type: concept（概念板块，默认）或 industry（行业板块）。
        max_evaluations: 本轮最多评估多少只成分；0 表示用服务端默认预算。
        max_results: 最终返回多少只候选；0 表示用服务端默认预算。
    """
    sink = sink_of(config)
    if sink is None:
        return _json({"error": "no_sink"})
    name = str(board_name or "").strip()
    if not name:
        return _json({"status": "error", "error": "缺少板块名称", "hint": NO_MATCH_HINT})
    try:
        kinds = _board_types(board_type)
    except ValueError as exc:
        return _json({"status": "error", "error": str(exc)})
    kind = kinds[0]

    budgets = RunBudgets.from_config()
    limit_eval = _clamp(max_evaluations, budgets.screen_max_evaluations)
    limit_result = min(_clamp(max_results, budgets.screen_max_results), limit_eval)

    manager = get_provider_manager()
    try:
        rows = _records(manager.get_board_constituents(name, kind))
    except Exception:  # noqa: BLE001 - 数据不可用时如实降级，不产出任何名单
        sink.limit("board_data_unavailable")
        return _json({
            "status": "unavailable",
            "board": name,
            "board_type": kind,
            "error": "板块成分数据暂不可用，请稍后重试或直接提供股票名称/代码。",
        })
    # 成分取数成功后立刻取来源元数据：后面的逐只评估会覆盖 last_metadata。
    board_source = _meta()

    eligible = _eligible_members(rows)
    if len(eligible) < MIN_ELIGIBLE_MEMBERS:
        sink.limit("screening_insufficient_coverage")
        return _json({
            "status": "insufficient_coverage",
            "board": name,
            "board_type": kind,
            "universe_size": len(rows),
            "eligible_size": len(eligible),
            "error": f"该板块可用于规则评估的标的不足 {MIN_ELIGIBLE_MEMBERS} 只，无法给出候选清单。",
        })
    # 预筛：只对成交额靠前的有限只数做逐只取数 + 规则评估（口径随返回值明示）。
    prescreened = eligible[:limit_eval]

    stop = stop_check_of(config)
    results: list[Any] = []
    facts: list[Any] = []
    exclusions: list[dict[str, Any]] = []
    halted = ""
    for member in prescreened:
        if stop is not None:
            try:
                halted = str(stop() or "")
            except Exception:  # noqa: BLE001 - 停止查询失败按"继续"处理
                halted = ""
            if halted:
                sink.limit(halted)
                break
        try:
            result, item_facts = _evaluate_one(member["code"], dict(sink.user_profile or {}))
        except Exception:  # noqa: BLE001 - 单只评估失败不阻断整轮筛选
            exclusions.append({"code": member["code"], "name": member["name"], "reason": "evaluate_failed"})
            continue
        results.append(result)
        facts.extend(item_facts)
        if result.action is Action.INSUFFICIENT_DATA:
            exclusions.append({
                "code": member["code"], "name": member["name"], "reason": result.data_quality,
            })

    if not results:
        sink.limit("screening_evaluate_failed")
        return _json({
            "status": "unavailable",
            "board": name,
            "board_type": kind,
            "error": "候选评估暂不可用，请稍后重试或直接提供股票名称/代码。",
        })

    # 排序口径与 ``evaluate_research`` 一致：总分降序，无分值的排在最后。
    scored = [result for result in results if result.action is not Action.INSUFFICIENT_DATA]
    scored.sort(
        key=lambda result: (
            result.scores.get("total") is not None,
            result.scores.get("total") or -1,
        ),
        reverse=True,
    )
    selected = scored[:limit_result]
    status = "complete" if len(selected) >= MIN_ELIGIBLE_MEMBERS else "insufficient_eligible_coverage"
    if status != "complete":
        sink.limit("screening_insufficient_eligible")

    member_names = {member["code"]: member["name"] for member in prescreened}
    listed: list[dict[str, Any]] = []
    for result in selected:
        codes = list(result.request.stock_codes) if result.request else []
        code = codes[0] if codes else ""
        listed.append({
            "code": code,
            "name": member_names.get(code, ""),
            "total": result.scores.get("total"),
            "action": result.action.value,
            "rule_version": result.rule_version,
            "data_quality": result.data_quality,
            "evidence_ids": list(result.evidence_ids),
        })
    projection = project_analysis_results(results)
    payload = {
        "board": name,
        "board_type": kind,
        "status": status,
        "universe_size": len(rows),
        "eligible_size": len(eligible),
        "prescreened_size": len(prescreened),
        "evaluated": len(results),
        "max_evaluations": limit_eval,
        "max_results": limit_result,
        "prescreen": PRESCREEN_NOTE,
        "halted": halted,
        "selected": listed,
        "exclusions": exclusions,
        "source": board_source,
        "disclaimer": SCREEN_DISCLAIMER,
    }
    sink.record(
        "screen_board_candidates",
        payload={
            "analysis_results": projection["analysis_results"],
            "stock_analysis": projection["stock_analysis"],
            "facts": [fact.model_dump(mode="json") for fact in facts],
            "personalization_status": results[0].personalization_status,
            "board_candidates": payload,
        },
    )
    return _json(payload)


__all__ = [
    "BOARD_UNAVAILABLE_HINT",
    "MAX_BOARD_MATCHES",
    "MIN_ELIGIBLE_MEMBERS",
    "NO_MATCH_HINT",
    "PRESCREEN_NOTE",
    "SCREEN_DISCLAIMER",
    "list_boards",
    "screen_board_candidates",
]
