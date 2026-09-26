"""板块/概念取数能力：归一化、直连客户端接线、能力缺口与熔断语义。

东财板块表是"按主题找标的"的唯一数据入口（概念板块名能命中"人工智能"这类口语主题），
因此这里逐条钉住：中文列 → 统一字段、缺失/停牌值落 ``None``（而不是 0）、非法板块
类型显式失败、**板块取数失败返回空列表且不熔断 akshare**（否则会连带拖垮 K 线/估值），
以及"只有 AKShare 声明该能力时降级链不误熔断"。
"""

from __future__ import annotations

from typing import Any

import pytest

from finance_agent.infrastructure.market_data.normalization import (
    normalize_board_constituents,
    normalize_board_list,
)
from finance_agent.infrastructure.market_data.providers import (
    ProviderUnavailableError,
    UnsupportedProviderCapability,
)


# ── 归一化（不联网） ──────────────────────────────────────────────────────────

def test_board_list_normalizes_eastmoney_columns():
    rows = normalize_board_list([
        {"板块名称": "人工智能", "板块代码": "BK0800", "涨跌幅": 2.34,
         "上涨家数": 88, "下跌家数": 12, "领涨股票": "某科技"},
    ])

    assert rows == [{
        "name": "人工智能", "code": "BK0800", "change_pct": 2.34,
        "up_count": 88.0, "down_count": 12.0, "leader": "某科技",
    }]


def test_board_list_drops_unnamed_rows_and_keeps_missing_numbers_none():
    rows = normalize_board_list([
        {"板块名称": "", "板块代码": "BK0000"},
        {"板块名称": "半导体", "板块代码": "BK1036", "涨跌幅": "-"},
    ])

    assert len(rows) == 1
    assert rows[0]["name"] == "半导体"
    # "-"（停牌/未成交）必须是 None，落成 0 会被误读成"平盘"。
    assert rows[0]["change_pct"] is None


def test_board_constituents_normalize_and_require_code_and_name():
    rows = normalize_board_constituents([
        {"代码": "300308", "名称": "中际旭创", "最新价": 123.4, "涨跌幅": 5.6, "成交额": 1234567890},
        {"代码": "", "名称": "缺代码"},
        {"代码": "600519", "名称": ""},
    ])

    assert [row["code"] for row in rows] == ["300308"]
    assert rows[0]["turnover_amount"] == 1234567890.0
    assert rows[0]["price"] == 123.4


# ── AKShare 适配器：直连客户端 + akshare 兜底 ─────────────────────────────────

CONCEPT_BOARDS = [
    {"name": "人工智能", "code": "BK0800", "change_pct": 2.34, "up_count": 88.0, "down_count": 12.0},
    {"name": "半导体", "code": "BK1036", "change_pct": -1.2, "up_count": 30.0, "down_count": 90.0},
]
CONSTITUENTS = [
    {"code": "300308", "name": "中际旭创", "price": 123.4, "change_pct": 5.6, "turnover_amount": 2_000_000_000.0},
    {"code": "002230", "name": "科大讯飞", "price": 55.1, "change_pct": 1.1, "turnover_amount": 1_000_000_000.0},
]


class _FakeFrame:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def to_dict(self, orient: str = "records"):
        assert orient == "records"
        return self._rows


class _FakeAk:
    """只保留 akshare 那唯一自洽的板块函数（行业列表）。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def stock_board_industry_name_em(self):
        self.calls.append("industry_list")
        return _FakeFrame([{"板块名称": "软件开发", "板块代码": "BK0737", "涨跌幅": 0.8}])

    def stock_board_concept_name_em(self):  # pragma: no cover - 不应被调用
        self.calls.append("concept_list")
        raise AssertionError("概念板块列表必须走自建直连客户端（akshare 解析器已损坏）")


def _akshare():
    from finance_agent.infrastructure.market_data.akshare_provider import AkshareDataSource

    provider = object.__new__(AkshareDataSource)
    provider.ak = _FakeAk()
    return provider


def _patch_direct_client(monkeypatch, *, board_lists, constituents=None):
    """把 ``em_board`` 的直连取数替换成桩，并记录调用。"""
    from finance_agent.infrastructure.market_data import akshare_provider

    calls: list[tuple[str, str]] = []

    def fake_list(board_type: str, **_kwargs):
        calls.append(("list", board_type))
        return list(board_lists.get(board_type) or [])

    def fake_constituents(board_code: str, **_kwargs):
        calls.append(("cons", board_code))
        return list((constituents or {}).get(board_code) or [])

    monkeypatch.setattr(akshare_provider.em_board, "fetch_board_list", fake_list)
    monkeypatch.setattr(akshare_provider.em_board, "fetch_board_constituents", fake_constituents)
    return calls


def test_board_list_and_constituents_use_the_direct_client(monkeypatch):
    provider = _akshare()
    calls = _patch_direct_client(
        monkeypatch,
        board_lists={"concept": CONCEPT_BOARDS},
        constituents={"BK0800": CONSTITUENTS},
    )

    boards = provider.get_board_list("concept")
    members = provider.get_board_constituents("人工智能", "concept")

    assert [row["name"] for row in boards] == ["人工智能", "半导体"]
    assert [row["code"] for row in members] == ["300308", "002230"]
    # 板块名 → 板块代码由列表调用建立的索引解析，不会退化成"按名字查成分"。
    assert calls == [("list", "concept"), ("cons", "BK0800")]
    assert provider.ak.calls == []


def test_board_index_is_reused_within_ttl(monkeypatch):
    provider = _akshare()
    calls = _patch_direct_client(
        monkeypatch, board_lists={"concept": CONCEPT_BOARDS}, constituents={"BK0800": CONSTITUENTS},
    )

    provider.get_board_list("concept")
    provider.get_board_constituents("人工智能", "concept")

    # 索引命中：成分查询不再重复拉一次板块表。
    assert calls == [("list", "concept"), ("cons", "BK0800")]


def test_unknown_board_name_yields_no_constituents(monkeypatch):
    provider = _akshare()
    calls = _patch_direct_client(monkeypatch, board_lists={"concept": CONCEPT_BOARDS}, constituents={})

    assert provider.get_board_constituents("量子计算", "concept") == []
    # 解析不到板块代码时绝不查询成分（否则会返回"别的板块"的股票）。
    assert calls == [("list", "concept")]


def test_industry_list_falls_back_to_akshare(monkeypatch):
    provider = _akshare()
    _patch_direct_client(monkeypatch, board_lists={"industry": []})

    rows = provider.get_board_list("industry")

    assert [row["name"] for row in rows] == ["软件开发"]
    assert provider.ak.calls == ["industry_list"]


def test_concept_list_has_no_akshare_fallback(monkeypatch):
    provider = _akshare()
    _patch_direct_client(monkeypatch, board_lists={"concept": []})

    assert provider.get_board_list("concept") == []
    # akshare 概念解析器实测损坏，兜底只会把 ValueError 混进失败原因里。
    assert provider.ak.calls == []


def test_board_fetch_failure_returns_empty_not_an_exception(monkeypatch):
    provider = _akshare()
    _patch_direct_client(monkeypatch, board_lists={"concept": []})

    assert provider.get_board_list("concept") == []


def test_unknown_board_type_and_empty_board_name_are_capability_gaps(monkeypatch):
    provider = _akshare()
    _patch_direct_client(monkeypatch, board_lists={"concept": CONCEPT_BOARDS})

    with pytest.raises(UnsupportedProviderCapability):
        provider.get_board_list("theme")
    with pytest.raises(UnsupportedProviderCapability):
        provider.get_board_constituents("  ", "concept")


# ── 降级链与熔断语义 ──────────────────────────────────────────────────────────

def test_manager_reports_unavailable_but_does_not_break_the_circuit(monkeypatch):
    """板块取数失败 → manager 抛不可用；空结果不计失败、不熔断。"""
    from finance_agent.infrastructure.market_data.provider_manager import ProviderManager

    provider = _akshare()
    _patch_direct_client(monkeypatch, board_lists={"concept": []})
    manager = ProviderManager(
        providers={"akshare": provider}, order=["akshare"], failure_threshold=1, cooldown=60,
    )

    with pytest.raises(ProviderUnavailableError):
        manager.get_board_list("concept")

    assert manager.last_metadata["failures"] == [{"provider": "akshare", "error": "返回空数据"}]
    assert manager.last_metadata["unsupported"] == []
    # 阈值=1 时，如果空结果被算作故障，这里就已经熔断；没有熔断是刻意的。
    assert manager._circuit_open("akshare") is False


def test_board_outage_does_not_freeze_daily_quotes():
    """板块主机故障不得把 akshare 整体熔断（否则 K 线/估值会被连带拖垮 60 秒）。"""
    from finance_agent.infrastructure.market_data.provider_manager import ProviderManager

    class _Provider:
        provider_name = "akshare"

        def __init__(self) -> None:
            self.daily_calls = 0

        def is_available(self) -> bool:
            return True

        def get_board_list(self, board_type: str = "concept"):
            return []  # 板块主机 URL 级故障的出口形态

        def get_daily(self, *args, **kwargs):
            self.daily_calls += 1
            return [{"trade_date": "2026-09-25", "close": 10.0}]

    provider = _Provider()
    manager = ProviderManager(
        providers={"akshare": provider}, order=["akshare"], failure_threshold=1, cooldown=60,
    )

    for _ in range(3):
        with pytest.raises(ProviderUnavailableError):
            manager.get_board_list("concept")

    assert manager.get_daily("600519") == [{"trade_date": "2026-09-25", "close": 10.0}]
    assert provider.daily_calls == 1


def test_raising_board_provider_would_trip_the_breaker():
    """对照组：抛异常的实现会被熔断——这正是空列表出口要避免的行为。"""
    from finance_agent.infrastructure.market_data.provider_manager import ProviderManager

    class _RaisingProvider:
        provider_name = "akshare"

        def is_available(self) -> bool:
            return True

        def get_board_list(self, board_type: str = "concept"):
            raise ProviderUnavailableError("板块接口挂了")

    manager = ProviderManager(
        providers={"akshare": _RaisingProvider()}, order=["akshare"],
        failure_threshold=1, cooldown=60,
    )

    with pytest.raises(ProviderUnavailableError):
        manager.get_board_list("concept")

    assert manager._circuit_open("akshare") is True


# ── 其它源显式声明能力缺口 ────────────────────────────────────────────────────

def test_other_providers_declare_board_capability_unsupported():
    from finance_agent.infrastructure.market_data.baostock_provider import BaostockDataSource
    from finance_agent.infrastructure.market_data.fuyao_mcp import FuyaoMcpDataSource

    for provider in (object.__new__(BaostockDataSource), object.__new__(FuyaoMcpDataSource)):
        with pytest.raises(UnsupportedProviderCapability):
            provider.get_board_list("concept")
        with pytest.raises(UnsupportedProviderCapability):
            provider.get_board_constituents("人工智能", "concept")


def test_provider_manager_routes_boards_and_does_not_trip_breaker_on_capability_gap():
    """能力缺口进 ``unsupported`` 而不进 ``failures``：不熔断、后续调用仍会尝试。"""
    from finance_agent.infrastructure.market_data.provider_manager import ProviderManager

    class BoardlessProvider:
        provider_name = "fuyao"

        def is_available(self):
            return True

        def get_board_list(self, board_type: str = "concept"):
            raise UnsupportedProviderCapability("不支持板块取数")

        def get_board_constituents(self, board_name: str, board_type: str = "concept"):
            raise UnsupportedProviderCapability("不支持板块取数")

    calls: list[str] = []

    class BoardProvider:
        provider_name = "akshare"

        def is_available(self):
            return True

        def get_board_list(self, board_type: str = "concept"):
            calls.append(board_type)
            return [{"name": "人工智能", "change_pct": 2.34}]

    manager = ProviderManager(
        providers={"fuyao": BoardlessProvider(), "akshare": BoardProvider()},
        order=["fuyao", "akshare"],
    )

    rows = manager.get_board_list("concept")

    assert rows == [{"name": "人工智能", "change_pct": 2.34}]
    assert calls == ["concept"]
    assert manager.last_metadata["unsupported"] == ["fuyao"]
    assert manager.last_metadata["failures"] == []
    # 第二次调用仍然尝试（能力缺口没有被当成故障熔断）。
    manager.get_board_list("concept")
    assert calls == ["concept", "concept"]


def test_provider_manager_reports_unavailable_when_no_board_source():
    from finance_agent.infrastructure.market_data.provider_manager import ProviderManager

    class BoardlessProvider:
        provider_name = "baostock"

        def is_available(self):
            return True

        def get_board_list(self, board_type: str = "concept"):
            raise UnsupportedProviderCapability("不支持板块取数")

    manager = ProviderManager(providers={"baostock": BoardlessProvider()}, order=["baostock"])

    with pytest.raises(ProviderUnavailableError):
        manager.get_board_list("concept")
