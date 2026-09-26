"""板块筛选端到端：真实 provider + 真实工具 + 真实专家图，只在厂商 HTTP 边界打桩。

为什么要有这一层：单元测试把 provider 和 ``evaluate`` 都替换掉了，无法证明"用户问
『帮我推荐几个AI行业值得关注的股票』"这条链路真的能走通；而联网端到端又受第三方接口
可用性影响（东财 ``*.push2.eastmoney.com`` 在部分网络环境会连续数分钟不可达）。因此
这里起一个本地 HTTP 服务，按东财 clist 的真实响应形状回放数据，并把
``EM_BOARD_BASE_URLS`` 指向它——**只有厂商那一段是假的**，其余（HTTP 客户端、字段映射、
板块名→代码索引、成分取数、确定性评分接线、专家图）全部是真代码。

链路的三种结局各自钉住：命中并产出评分清单；接口正常但关键词无命中（``not_found``，
引导换更具体的板块名）；接口 5xx（``unavailable``，必须说清是数据源问题而不是"没匹配到"）。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from finance_agent.domains.research.contracts import (
    Action,
    AnalysisKind,
    AnalysisRequest,
    AnalysisResult,
)
from finance_agent.infrastructure import settings as config
from finance_agent.infrastructure.market_data.akshare_provider import AkshareDataSource
from finance_agent.infrastructure.market_data.provider_manager import ProviderManager
from finance_agent.orchestration.contracts import (
    BusinessDomain,
    DomainTaskContext,
    PlanTask,
)
from finance_agent.orchestration.experts import build_expert

from tests.conftest import final_message, make_fake_tool_model, tool_call

CONCEPT_LIST_ROWS = [
    {"f12": "BK0800", "f14": "人工智能", "f3": 2.34, "f104": 88, "f105": 12, "f128": "某科技"},
    {"f12": "BK1036", "f14": "半导体", "f3": -1.20, "f104": 30, "f105": 90, "f128": "某芯片"},
    {"f12": "BK0737", "f14": "软件开发", "f3": 0.80, "f104": 40, "f105": 30, "f128": "某软件"},
]
INDUSTRY_LIST_ROWS = [
    {"f12": "BK0737", "f14": "软件开发", "f3": 0.80, "f104": 40, "f105": 30, "f128": "某软件"},
]
CONSTITUENT_ROWS = [
    {"f12": "300308", "f14": "中际旭创", "f2": 123.4, "f3": 5.6, "f6": 2_000_000_000},
    {"f12": "002230", "f14": "科大讯飞", "f2": 55.1, "f3": 1.1, "f6": 1_500_000_000},
    {"f12": "688111", "f14": "金山办公", "f2": 300.0, "f3": 0.5, "f6": 1_200_000_000},
    {"f12": "600519", "f14": "贵州茅台", "f2": 1700.0, "f3": 0.2, "f6": 900_000_000},
    {"f12": "000001", "f14": "平安银行", "f2": 11.0, "f3": 0.0, "f6": 700_000_000},
]


class _StubHandler(BaseHTTPRequestHandler):
    """按 ``fs`` 参数回放东财 clist 响应；``server.fail`` 为真时一律 502。"""

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler 约定
        params = parse_qs(urlparse(self.path).query)
        fs = (params.get("fs") or [""])[0]
        self.server.calls.append(fs)
        if self.server.fail:
            self.send_error(502)
            return
        rows = _rows_for(fs)
        payload = {"rc": 0, "data": {"total": len(rows), "diff": rows}}
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # pragma: no cover - 静音访问日志
        return


def _rows_for(fs: str) -> list[dict]:
    if "t:3" in fs:  # 概念板块列表
        return CONCEPT_LIST_ROWS
    if "t:2" in fs:  # 行业板块列表
        return INDUSTRY_LIST_ROWS
    if "b:BK0800" in fs:  # 人工智能成分
        return CONSTITUENT_ROWS
    return []


class _StubServer:
    """本地东财替身：记录收到的 ``fs`` 表达式，供断言"真的走了板块接口"。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[str] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
        self._server.calls = self.calls
        self._server.fail = fail
        host, port = self._server.server_address[:2]
        self.base_url = f"http://{host}:{port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def stub_board_source(monkeypatch):
    """把板块取数指向本地替身，并隔离系统代理与 provider 单例。"""
    # 127.0.0.1 必须绕过系统代理，否则请求会被转发到本机代理再回环，行为不确定。
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")

    servers: list[_StubServer] = []

    def _start(*, fail: bool = False) -> _StubServer:
        server = _StubServer(fail=fail)
        servers.append(server)
        monkeypatch.setattr(config, "EM_BOARD_BASE_URLS", server.base_url)
        monkeypatch.setattr(config, "EM_BOARD_TIMEOUT", 3.0)
        monkeypatch.setattr(config, "EM_BOARD_DEADLINE", 6.0)
        return server

    yield _start
    for server in servers:
        server.close()


def _real_manager() -> ProviderManager:
    """真实 provider（含真实 HTTP 板块客户端），只把降级链收敛到 akshare。"""
    return ProviderManager(providers={"akshare": AkshareDataSource()}, order=["akshare"])


def _patch_manager(monkeypatch, manager: ProviderManager) -> None:
    """工具层与 _meta 都读同一个 manager：来源元数据因此一致。"""
    from finance_agent.domains.research.expert import screening

    monkeypatch.setattr(screening, "get_provider_manager", lambda: manager)


def _patch_evaluate(monkeypatch, totals: dict[str, float]) -> list[str]:
    """确定性评分接线保持真实，只把逐只取数换成固定结果（那部分有独立测试）。"""
    from finance_agent.domains.research.expert import screening

    evaluated: list[str] = []

    def fake_evaluate(request, *, user_profile, gateway):
        code = request.stock_codes[0]
        evaluated.append(code)
        return (
            AnalysisResult(
                request=AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=[code]),
                action=Action.WATCH,
                data_quality="complete",
                rule_version="research_rules/v1.2",
                scores={
                    "fundamental": 1.0, "technical": 1.0, "risk": 1.0,
                    "suitability": 1.0, "total": totals[code],
                },
                evidence_ids=[f"{code}-fact"],
                personalization_status="research_candidate",
                narrative=f"{code} 的确定性结论。",
            ),
            [],
        )

    monkeypatch.setattr(screening, "evaluate", fake_evaluate)
    return evaluated


def _context(goal: str) -> DomainTaskContext:
    return DomainTaskContext(
        task=PlanTask(
            task_id="t-board", domain=BusinessDomain.STOCK_RESEARCH,
            goal=goal, instruction=goal, expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-board",
        customer_id="CUST1",
        conversation_id="conv-board",
        user_message=goal,
    )


def test_ai_board_request_produces_a_scored_candidate_list(monkeypatch, stub_board_source):
    """截图里的用户问话：板块定位 → 成分取数 → 确定性评分排序 → 候选清单落盘。"""
    server = stub_board_source()
    manager = _real_manager()
    _patch_manager(monkeypatch, manager)
    scores = {"300308": 7.0, "002230": 9.0, "688111": 8.0, "600519": 6.0, "000001": 4.0}
    evaluated = _patch_evaluate(monkeypatch, scores)

    model = make_fake_tool_model([
        tool_call("list_boards", {"keyword": "AI"}, call_id="c1"),
        tool_call(
            "screen_board_candidates",
            {"board_name": "人工智能", "board_type": "concept", "max_evaluations": 5, "max_results": 3},
            call_id="c2",
        ),
        final_message("按确定性评分排序的候选如下（不构成投资建议或推荐）：……"),
    ])
    outcome = build_expert(BusinessDomain.STOCK_RESEARCH, model=model).invoke(
        {"context": _context("帮我推荐几个AI行业值得关注的股票")}
    )["domain_outcome"]

    board = outcome.structured_data["board_candidates"]
    assert board["board"] == "人工智能"
    assert board["board_type"] == "concept"
    assert board["status"] == "complete"
    # 排序口径是确定性总分，不是涨跌幅。
    assert [item["code"] for item in board["selected"]] == ["002230", "688111", "300308"]
    assert board["selected"][0]["name"] == "科大讯飞"
    assert board["disclaimer"]
    assert board["prescreen"]
    # 清单同时落进公开结构化契约：前端卡片与确定性内核守卫都靠它。
    assert set(evaluated) == set(scores)
    assert len(outcome.structured_data["analysis_results"]) == 5
    assert set(outcome.structured_data["stock_analysis"]) == set(scores)
    assert outcome.status == "success"
    # 板块表与成分表确实都是经真实 HTTP 客户端打到替身上的。
    assert any("t:3" in fs for fs in server.calls)
    assert any("b:BK0800" in fs for fs in server.calls)


def test_keyword_without_a_board_keeps_the_rephrase_guidance(monkeypatch, stub_board_source):
    """数据取到了但没有匹配：仍是 not_found，引导换更具体的板块名。"""
    stub_board_source()
    _patch_manager(monkeypatch, _real_manager())
    from finance_agent.domains.research.expert import screening

    payload = json.loads(screening.list_boards.invoke({"keyword": "量子计算"}))

    assert payload["status"] == "not_found"
    assert payload["hint"] == screening.NO_MATCH_HINT
    assert payload["fetched_types"] == ["concept", "industry"]
    assert payload["unavailable_types"] == []


def test_board_endpoint_outage_is_reported_as_a_source_problem(monkeypatch, stub_board_source):
    """接口 5xx：必须说"数据源暂不可用"，不能把故障说成"关键词没匹配到"。"""
    stub_board_source(fail=True)
    _patch_manager(monkeypatch, _real_manager())
    from finance_agent.domains.research.expert import screening

    payload = json.loads(screening.list_boards.invoke({"keyword": "AI"}))

    assert payload["status"] == "unavailable"
    assert payload["hint"] == screening.BOARD_UNAVAILABLE_HINT
    assert "未匹配" not in payload["hint"]
    assert payload["fetched_types"] == []
    assert payload["unavailable_types"] == ["concept", "industry"]
    assert set(payload["reasons"]) == {"concept", "industry"}
