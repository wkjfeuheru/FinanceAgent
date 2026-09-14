"""股票研究专家（旧编排兼容薄适配）。

实际确定性逻辑已抽取到 ``finance_agent.orchestrator.domains.stock``；本模块保留
``StockAnalysisAgent`` 的构造参数与历史方法名，供旧编排路径与既有测试使用。
"""

from __future__ import annotations

import sys
from typing import Any

from finance_agent.agents.base import AgentProtocol
from finance_agent.orchestrator.domains import stock as stock_domain
from finance_agent.orchestrator.domains.stock import (
    _MIN_TECHNICAL_BARS,
    StockDeps,
    invoke_stock,
)
from finance_agent.orchestrator.domains.stock import run_resolved as _run_resolved
from finance_agent.orchestrator.tools.stockdata import fetch_stock_data, search_candidates
from finance_agent.research.contracts import AnalysisRequest
from finance_agent.research.pipeline import ResearchPipeline

__all__ = ["StockAnalysisAgent"]


class StockAnalysisAgent(AgentProtocol):
    """把编排状态转换为研究请求并执行的兼容包装。"""

    agent_name = "stock_analysis"

    def __init__(
        self,
        checkpointer: Any = None,
        *,
        pipeline: ResearchPipeline | None = None,
        theme_screener: Any = None,
        theme_registry: Any = None,
    ) -> None:
        del checkpointer
        self._injected_pipeline = pipeline is not None
        self._pipeline = pipeline or ResearchPipeline(
            snapshot_builder=stock_domain.production_builder(stock_domain._FetchGateway()),
            rule_engine=stock_domain.RuleEngine.default(),
        )
        self._theme_screener = theme_screener
        self._theme_registry = theme_registry

    # 用当前实例属性（含测试直接赋值的 _pipeline/_injected_pipeline）构造依赖。
    def _deps(self) -> StockDeps:
        module = sys.modules[__name__]
        return StockDeps(
            pipeline=self._pipeline,
            injected_pipeline=getattr(self, "_injected_pipeline", False),
            theme_screener=self._theme_screener,
            theme_registry=self._theme_registry,
            # 运行期从本模块命名空间取名，保留 monkeypatch 注入 search_candidates 的能力。
            candidate_search=getattr(module, "search_candidates", None),
            fetch=getattr(module, "fetch_stock_data", None),
        )

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        return invoke_stock(self._deps(), state)

    def _resolve_candidate_codes(self, user_message: str) -> list[str]:
        """历史兼容入口：委托领域模块候选发现（主题代表股优先）。"""
        return stock_domain.resolve_candidate_codes(self._deps(), user_message)

    def _representative_codes(self, user_message: str) -> list[str]:
        return stock_domain.representative_codes(self._deps(), user_message)

    def _representative_request(self, request: AnalysisRequest) -> AnalysisRequest | None:
        return stock_domain.representative_request(self._deps(), request)

    def run_resolved(self, state: dict[str, Any], request: AnalysisRequest) -> dict[str, Any]:
        return _run_resolved(self._deps(), state, request)

    def _compute_technical_indicators(
        self, stock_data: Any, codes: Any, analysis_type: str = "both",
    ) -> dict[str, Any]:
        """历史兼容入口：委托领域模块的展示层技术指标计算。"""
        return stock_domain.compute_technical_indicators(stock_data, codes, analysis_type)

    def handle_single_stock(
        self,
        code: str,
        user_message: str = "",
        memory_context: str = "",
        chat_history: list[dict] | None = None,
        stock_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del user_message, memory_context, chat_history
        return stock_domain.handle_single_stock(self._deps(), code, stock_data)
