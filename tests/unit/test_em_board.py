"""东财板块直连客户端：字段映射、主机轮换、翻页与预算。

为什么单独钉这一层：akshare 1.18.97 的概念板块列表/成分解析器字段数与列名数不一致
（网络正常也抛 ``Length mismatch``），板块取数已改为自建客户端。它一旦错位，"AI 行业"
要么匹配不到板块、要么把别的板块的成分当成候选，而两者在用户侧都表现为"答非所问"。
因此这里逐条锁定：字段码映射、筛选表达式、翻页、主机轮换、预算耗尽与结构异常。
"""

from __future__ import annotations

import pytest

from finance_agent.infrastructure.market_data import em_board


def _policy(**overrides):
    base = {
        "base_urls": ("https://h1.example", "https://h2.example"),
        "timeout": 1.0,
        "deadline": 10.0,
        "max_pages": 4,
    }
    base.update(overrides)
    return em_board.BoardPolicy(**base)


class _Transport:
    """按 (host, pn) 回放响应的假传输层；未登记的组合视为网络错误。"""

    def __init__(self, responses: dict[tuple[str, str], object], failing: set[str] | None = None):
        self.responses = responses
        self.failing = failing or set()
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, params: dict, timeout: float):
        host = url.split("/api/")[0]
        self.calls.append((host, dict(params)))
        if host in self.failing:
            raise RuntimeError(f"proxy error {host}")
        key = (host, str(params.get("pn", "1")))
        if key not in self.responses:
            raise RuntimeError(f"no response for {key}")
        return self.responses[key]


def _payload(rows: list[dict], total: int | None = None):
    return {"rc": 0, "data": {"total": len(rows) if total is None else total, "diff": rows}}


def _board_row(code: str, name: str):
    return {"f12": code, "f14": name, "f3": 2.34, "f104": 88, "f105": 12, "f128": "领涨股"}


# ── 板块列表 ────────────────────────────────────────────────────────────────

def test_board_list_maps_field_codes_to_unified_records():
    transport = _Transport({("https://h1.example", "1"): _payload([_board_row("BK0800", "人工智能")])})

    rows = em_board.fetch_board_list("concept", fetch=transport, policy=_policy())

    assert rows == [{
        "name": "人工智能",
        "code": "BK0800",
        "change_pct": 2.34,
        "up_count": 88.0,
        "down_count": 12.0,
        "leader": "领涨股",
    }]
    # 筛选表达式与字段串必须与东财口径一致：概念用 t:3，字段只用真正消费的 6 个。
    assert transport.calls[0][1]["fs"] == em_board.CONCEPT_FS
    assert transport.calls[0][1]["fields"] == "f12,f14,f3,f104,f105,f128"


def test_industry_uses_its_own_selector():
    transport = _Transport({("https://h1.example", "1"): _payload([_board_row("BK1036", "半导体")])})

    em_board.fetch_board_list("industry", fetch=transport, policy=_policy())

    assert transport.calls[0][1]["fs"] == em_board.INDUSTRY_FS


def test_board_list_rotates_hosts_after_failure():
    transport = _Transport(
        {("https://h2.example", "1"): _payload([_board_row("BK0800", "人工智能")])},
        failing={"https://h1.example"},
    )

    rows = em_board.fetch_board_list("concept", fetch=transport, policy=_policy())

    assert [row["name"] for row in rows] == ["人工智能"]
    assert [call[0] for call in transport.calls] == ["https://h1.example", "https://h2.example"]


def test_board_list_paginates_until_total_is_reached():
    first = [_board_row(f"BK{i:04d}", f"板块{i}") for i in range(100)]
    transport = _Transport({
        ("https://h1.example", "1"): _payload(first, total=150),
        ("https://h1.example", "2"): _payload([_board_row("BK9999", "人工智能")], total=150),
        ("https://h1.example", "3"): _payload([], total=150),
    })

    rows = em_board.fetch_board_list("concept", fetch=transport, policy=_policy())

    assert len(rows) == 101
    # 最后一页为空即收尾：不会因为 total 与实际行数不一致而无限翻页。
    pages = [call[1]["pn"] for call in transport.calls]
    assert pages[:3] == ["1", "2", "3"]
    assert set(pages) == {"1", "2", "3"}


def test_board_list_stops_at_page_cap():
    transport = _Transport({
        ("https://h1.example", "1"): _payload([_board_row("BK0001", "甲")], total=500),
        ("https://h1.example", "2"): _payload([_board_row("BK0002", "乙")], total=500),
    })

    rows = em_board.fetch_board_list("concept", fetch=transport, policy=_policy(max_pages=2))

    assert len(rows) == 2
    assert len(transport.calls) == 2


def test_board_list_returns_empty_when_all_hosts_fail():
    transport = _Transport({}, failing={"https://h1.example", "https://h2.example"})

    assert em_board.fetch_board_list("concept", fetch=transport, policy=_policy()) == []


def test_board_list_returns_empty_when_budget_is_exhausted():
    transport = _Transport({("https://h1.example", "1"): _payload([_board_row("BK0800", "人工智能")])})

    rows = em_board.fetch_board_list("concept", fetch=transport, policy=_policy(deadline=0.0))

    assert rows == []
    assert transport.calls == []


def test_board_list_without_hosts_is_empty_not_an_exception():
    transport = _Transport({})

    assert em_board.fetch_board_list("concept", fetch=transport, policy=_policy(base_urls=())) == []


def test_board_list_tolerates_malformed_payloads():
    transport = _Transport({
        ("https://h1.example", "1"): {"rc": 0, "data": None},
        ("https://h2.example", "1"): {"rc": 0, "data": {"total": 0, "diff": []}},
    })

    assert em_board.fetch_board_list("concept", fetch=transport, policy=_policy()) == []


def test_board_list_accepts_legacy_dict_diff():
    transport = _Transport({
        ("https://h1.example", "1"): {"data": {"total": 1, "diff": {"0": _board_row("BK0800", "人工智能")}}},
    })

    rows = em_board.fetch_board_list("concept", fetch=transport, policy=_policy())

    assert [row["name"] for row in rows] == ["人工智能"]


def test_board_list_drops_rows_without_name_and_keeps_missing_numbers_none():
    transport = _Transport({
        ("https://h1.example", "1"): _payload([
            {"f12": "BK0001", "f14": "", "f3": 1.0},
            {"f12": "BK0002", "f14": "半导体", "f3": "-", "f104": None, "f105": 3, "f128": ""},
        ], total=2),
    })

    rows = em_board.fetch_board_list("concept", fetch=transport, policy=_policy())

    assert [row["name"] for row in rows] == ["半导体"]
    # "-"（停牌/未成交）必须是 None：落成 0 会被误读成"平盘"。归一化层对缺失字段
    # 不写键，因此这里用 get 断言"不是 0"。
    assert rows[0]["change_pct"] is None
    assert rows[0].get("up_count") is None
    assert rows[0].get("leader") is None


# ── 板块成分 ────────────────────────────────────────────────────────────────

def test_constituents_map_field_codes_and_selector():
    transport = _Transport({
        ("https://h1.example", "1"): _payload([
            {"f12": "300308", "f14": "中际旭创", "f2": 123.4, "f3": 5.6, "f6": 2_000_000_000},
        ]),
    })

    rows = em_board.fetch_board_constituents("BK0800", fetch=transport, policy=_policy())

    assert rows == [{
        "code": "300308",
        "name": "中际旭创",
        "price": 123.4,
        "change_pct": 5.6,
        "turnover_amount": 2_000_000_000.0,
    }]
    params = transport.calls[0][1]
    assert params["fs"] == "b:BK0800 f:!50"
    assert params["fields"] == "f12,f14,f2,f3,f6"


def test_constituents_require_a_board_code():
    transport = _Transport({})

    assert em_board.fetch_board_constituents("  ", fetch=transport, policy=_policy()) == []
    assert transport.calls == []


def test_constituents_return_empty_when_page_fails():
    transport = _Transport({}, failing={"https://h1.example", "https://h2.example"})

    assert em_board.fetch_board_constituents("BK0800", fetch=transport, policy=_policy()) == []


# ── 预算来源 ────────────────────────────────────────────────────────────────

def test_policy_reads_settings(monkeypatch):
    from finance_agent.infrastructure import settings as config

    monkeypatch.setattr(config, "EM_BOARD_BASE_URLS", "https://a.example/ , https://b.example")
    monkeypatch.setattr(config, "EM_BOARD_TIMEOUT", 2.5)
    monkeypatch.setattr(config, "EM_BOARD_DEADLINE", 7.5)
    monkeypatch.setattr(config, "EM_BOARD_MAX_PAGES", 3)

    policy = em_board.board_policy()

    assert policy.base_urls == ("https://a.example", "https://b.example")
    assert (policy.timeout, policy.deadline, policy.max_pages) == (2.5, 7.5, 3)


@pytest.mark.parametrize("bad", [None, "", "   ", " , , "])
def test_policy_ignores_blank_hosts(monkeypatch, bad):
    from finance_agent.infrastructure import settings as config

    monkeypatch.setattr(config, "EM_BOARD_BASE_URLS", bad)

    assert em_board.board_policy().base_urls == ()
