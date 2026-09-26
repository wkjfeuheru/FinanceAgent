"""东方财富板块（概念/行业）直连取数。

**为什么不用 akshare 的板块函数**（本机实测 akshare 1.18.97，2026-09-26）：

1. 解析器自身损坏：``stock_board_concept_name_em`` 只请求 24 个字段却给 27 个列名
   （``Length mismatch: Expected axis has 25 elements, new values have 27 elements``），
   ``stock_board_concept_cons_em`` / ``stock_board_industry_cons_em`` 请求 30 个字段
   却给 33 个列名。用合成载荷打桩实测确认：网络正常时这三个函数也会抛 ``ValueError``，
   只有 ``stock_board_industry_name_em``（41 字段/42 列）是自洽的。
2. 主机单一：板块列表/成分只走 ``*.push2.eastmoney.com``，而该域名在部分网络环境
   （本机经系统代理 127.0.0.1:7890）会连续数分钟返回 502/RemoteDisconnected，
   实测 30 秒内 12 次请求全部失败，同期 ``datacenter-web/sina/10jqka`` 均正常。

因此板块取数改为本模块自己发请求：**按字段码显式映射**（不再用位置赋列名，彻底绕开
上面第 1 条），并做**主机轮换 + 有界重试 + 总预算**（缓解第 2 条）。归一化仍复用
``normalization.normalize_board_list`` / ``normalize_board_constituents``，保证统一
记录字段只有一处定义。

**取数失败返回空列表，不抛异常**：板块故障是"某台行情主机的 URL 级故障"，不是
akshare 适配器整体故障。``ProviderManager`` 对"provider 返回空结果"只记 ``failures``
元数据、不计失败、不熔断，所以返回空能让板块故障不污染 K 线/估值路径的熔断计数；
真正的不可用语义由 manager 在降级链末尾统一抛 ``ProviderUnavailableError`` 表达。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

from finance_agent.infrastructure import settings as config
from finance_agent.infrastructure.market_data.normalization import (
    normalize_board_constituents,
    normalize_board_list,
)

logger = logging.getLogger(__name__)

#: 东财 clist 的公开固定令牌（与 akshare 同口径）。
UT_TOKEN = "bd1d9ddb04089700cf9c27f6f7426281"
#: 概念板块 / 行业板块的筛选表达式。
CONCEPT_FS = "m:90 t:3 f:!50"
INDUSTRY_FS = "m:90 t:2 f:!50"
#: 板块列表接口路径（主机来自 ``EM_BOARD_BASE_URLS``）。
CLIST_PATH = "/api/qt/clist/get"

#: 字段码 → 统一字段。用字段码映射而不是位置赋列名：东财按 `fields` 原样返回
#: 字段码键，位置映射一旦字段串与列名表不同步就会静默错位（akshare 的故障形态）。
_LIST_FIELDS = "f12,f14,f3,f104,f105,f128"
_LIST_MAP = {
    "f12": "code",
    "f14": "name",
    "f3": "change_pct",
    "f104": "up_count",
    "f105": "down_count",
    "f128": "leader",
}
#: 成分表只需评分与预筛真正用到的字段（代码/名称/最新价/涨跌幅/成交额）。
_CONSTITUENT_FIELDS = "f12,f14,f2,f3,f6"
_CONSTITUENT_MAP = {
    "f12": "code",
    "f14": "name",
    "f2": "price",
    "f3": "change_pct",
    "f6": "turnover_amount",
}

_PAGE_SIZE = 100
#: 最多轮换几轮主机；总时长仍由 ``EM_BOARD_DEADLINE`` 兜底。
_MAX_ROUNDS = 2
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}


@dataclass(frozen=True)
class BoardPolicy:
    """板块取数的预算：主机列表 + 单请求超时 + 单类型总预算 + 翻页上限。"""

    base_urls: tuple[str, ...]
    timeout: float
    deadline: float
    max_pages: int
    page_size: int = _PAGE_SIZE
    max_rounds: int = _MAX_ROUNDS


def board_policy() -> BoardPolicy:
    """从配置构造取数预算；每次调用都重读配置，便于测试替换。"""
    urls = tuple(
        item.strip().rstrip("/")
        for item in str(getattr(config, "EM_BOARD_BASE_URLS", "") or "").split(",")
        if item.strip()
    )
    return BoardPolicy(
        base_urls=urls,
        timeout=float(getattr(config, "EM_BOARD_TIMEOUT", 4.0)),
        deadline=float(getattr(config, "EM_BOARD_DEADLINE", 10.0)),
        max_pages=int(getattr(config, "EM_BOARD_MAX_PAGES", 8)),
    )


Fetch = Callable[[str, dict[str, Any], float], Any]


def _http_get(url: str, params: dict[str, Any], timeout: float) -> Any:
    """发一次 GET 并解析 JSON；非 2xx 或非 JSON 由 ``requests`` 抛错。"""
    response = requests.get(url, params=params, timeout=timeout, headers=_HEADERS)
    response.raise_for_status()
    return response.json()


def _diff_rows(payload: Any) -> list[dict[str, Any]]:
    """取出 clist 响应里的数据行；结构不符时返回空列表。"""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    diff = data.get("diff")
    if isinstance(diff, dict):  # 旧版接口按序号返回字典
        diff = list(diff.values())
    if not isinstance(diff, list):
        return []
    return [row for row in diff if isinstance(row, dict)]


def _total(payload: Any) -> int:
    data = payload.get("data") if isinstance(payload, dict) else None
    total = data.get("total") if isinstance(data, dict) else None
    try:
        return int(total)
    except (TypeError, ValueError):
        return 0


def _map_row(row: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """按字段码映射成统一字段；缺字段码一律落 ``None``（由归一化层判定缺失）。"""
    return {target: row.get(source) for source, target in mapping.items()}


def _is_well_formed(payload: Any) -> bool:
    """结构上是不是一个 clist 响应（``data.diff`` 存在）。

    区分"结构坏"与"这一页就是空的"：前者是主机/代理故障（要换主机重试），后者是
    翻页正常收尾。混为一谈要么误判故障、要么把截断当成功。
    """
    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    if not isinstance(data, dict):
        return False
    return isinstance(data.get("diff"), (list, dict))


def _fetch_page(
    params: dict[str, Any],
    *,
    fetch: Fetch,
    policy: BoardPolicy,
    deadline: float,
    require_rows: bool = True,
) -> tuple[Any, str]:
    """在 deadline 内按主机轮换取一页；返回 ``(payload, base_url)`` 或 ``(None, "")``。

    ``require_rows=True``（首页）时优先返回**有数据行**的响应，把所有主机都试一遍；
    ``require_rows=False``（后续页）时只轮一轮主机：非空响应立即采用，全部主机都只给
    合法空页就返回空页（翻页收尾的正常形态），避免为"确认列表结束"反复打所有主机。
    """
    if not policy.base_urls:
        logger.warning("未配置板块数据主机（EM_BOARD_BASE_URLS），跳过板块取数")
        return None, ""
    empty_payload: Any = None
    empty_url = ""
    for _ in range(max(1, policy.max_rounds) if require_rows else 1):
        for base_url in policy.base_urls:
            # 预算判断要预留一次请求的超时，否则最后一次尝试会拖过 EM_BOARD_DEADLINE。
            if time.monotonic() + max(0.0, policy.timeout) > deadline:
                logger.warning("板块取数预算用尽（EM_BOARD_DEADLINE=%ss）", policy.deadline)
                return empty_payload, empty_url
            try:
                payload = fetch(f"{base_url}{CLIST_PATH}", dict(params), policy.timeout)
            except Exception as exc:  # provider 边界统一处理第三方异常
                logger.warning("东财板块接口失败 host=%s: %s", base_url, exc)
                continue
            if _diff_rows(payload):
                return payload, base_url
            if _is_well_formed(payload):
                if empty_payload is None:
                    empty_payload, empty_url = payload, base_url
                logger.debug("东财板块接口本页无数据 host=%s", base_url)
                continue
            logger.warning("东财板块接口响应结构异常 host=%s", base_url)
    return empty_payload, empty_url


def _paginated_rows(
    base_params: dict[str, Any],
    *,
    fetch: Fetch,
    policy: BoardPolicy,
    deadline: float,
) -> list[dict[str, Any]]:
    """按页取全表；中途任何一页取不到就整体失败（不返回被静默截断的板块表）。"""
    rows: list[dict[str, Any]] = []
    page = 1
    total = 0
    max_pages = max(1, policy.max_pages)
    capped = False
    while page <= max_pages:
        params = {**base_params, "pn": str(page), "pz": str(policy.page_size)}
        payload, base_url = _fetch_page(
            params,
            fetch=fetch,
            policy=policy,
            deadline=deadline,
            require_rows=page == 1,
        )
        if payload is None:
            logger.warning("板块表第 %d 页取数失败，放弃本次板块取数", page)
            return []
        if page == 1:
            total = _total(payload)
        page_rows = _diff_rows(payload)
        if page == 1 and not page_rows and total:
            logger.warning("板块表首页无数据但 total=%d，按空表处理 host=%s", total, base_url)
        rows.extend(page_rows)
        if not page_rows or (total and len(rows) >= total):
            break
        page += 1
        capped = page > max_pages
        logger.debug("板块表继续翻页 page=%d host=%s 已取 %d/%d", page, base_url, len(rows), total)
    if total and len(rows) < total:
        # 少一截必须留痕：静默截断会让"关键词没匹配到"变成假象，至少要能排障。
        if capped:
            logger.warning(
                "板块表受翻页上限截断：已取 %d/%d 行（EM_BOARD_MAX_PAGES=%d）",
                len(rows), total, max_pages,
            )
        else:
            logger.debug("板块表行数与 total 不一致：已取 %d/%d 行", len(rows), total)
    return rows


def fetch_board_list(
    board_type: str,
    *,
    fetch: Fetch | None = None,
    policy: BoardPolicy | None = None,
) -> list[dict[str, Any]]:
    """取板块列表并归一为统一记录（``concept`` 概念 / ``industry`` 行业）。

    失败返回空列表，由调用方（适配器/降级链）决定不可用语义。
    """
    resolved = policy or board_policy()
    getter = fetch or _http_get
    fs = CONCEPT_FS if str(board_type).strip().lower() == "concept" else INDUSTRY_FS
    deadline = time.monotonic() + max(0.0, resolved.deadline)
    base_params = {
        "po": "1",
        "np": "1",
        "ut": UT_TOKEN,
        "fltt": "2",
        "invt": "2",
        "fid": "f12",  # 按代码稳定排序：同一轮重复取数得到可复现的顺序
        "fs": fs,
        "fields": _LIST_FIELDS,
    }
    rows = _paginated_rows(base_params, fetch=getter, policy=resolved, deadline=deadline)
    if not rows:
        return []
    return normalize_board_list([_map_row(row, _LIST_MAP) for row in rows])


def fetch_board_constituents(
    board_code: str,
    *,
    fetch: Fetch | None = None,
    policy: BoardPolicy | None = None,
) -> list[dict[str, Any]]:
    """取指定板块（东财板块代码，如 ``BK0800``）的成分股并归一。失败返回空列表。"""
    code = str(board_code or "").strip()
    if not code:
        logger.warning("板块成分查询缺少板块代码")
        return []
    resolved = policy or board_policy()
    getter = fetch or _http_get
    deadline = time.monotonic() + max(0.0, resolved.deadline)
    base_params = {
        "po": "1",
        "np": "1",
        "ut": UT_TOKEN,
        "fltt": "2",
        "invt": "2",
        "fid": "f12",
        "fs": f"b:{code} f:!50",
        "fields": _CONSTITUENT_FIELDS,
    }
    rows = _paginated_rows(base_params, fetch=getter, policy=resolved, deadline=deadline)
    if not rows:
        return []
    return normalize_board_constituents([_map_row(row, _CONSTITUENT_MAP) for row in rows])


__all__ = [
    "CLIST_PATH",
    "CONCEPT_FS",
    "INDUSTRY_FS",
    "UT_TOKEN",
    "BoardPolicy",
    "board_policy",
    "fetch_board_constituents",
    "fetch_board_list",
]
