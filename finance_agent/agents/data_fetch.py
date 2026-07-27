"""金融数据获取 Agent。

职责：根据用户输入的股票代码和期限从 BaoStock 获取金融数据
- 实时行情
- 历史K线数据
- 财务分析指标
- 股票基本信息

数据写入共享内存供下游Agent使用。

每只股票的数据获取有独立的超时保护，不会因为单只股票
卡住而阻塞整个用户请求。

当 BaoStock 无法返回某些基本面/财务数据时，自动用千帆搜索
从公开来源获取兜底数据。
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List

from finance_agent.agents.base import BaseFinanceAgent
from finance_agent.tools.stock_data import (
    get_stock_basic_info,
    get_financial_indicators,
    get_stock_history,
    get_stock_realtime_quote,
)
from finance_agent.tools.qianfan_search import QianfanStockSearch

# 单只股票数据获取的总超时（秒）。BaoStock 的 TCP 超时为 15s，
# 一个 stock 最多做 4 次远端查询（basic + quote + indicators + history），
# 加上千帆兜底搜索的额外时间。
_PER_STOCK_TIMEOUT = 120

_DATA_FETCH_PROMPT = """你是金融数据获取专家。

## 身份
你负责从 BaoStock 获取A股金融数据，包括最近交易日行情、历史K线、财务指标和基本信息。

## 工作流程
1. 从共享上下文中读取用户画像（stock_codes、holding_period）
2. 对每只股票依次获取：基本信息 → 实时行情 → 财务指标 → 历史K线
3. 数据自动发布到共享内存供下游Agent使用

## 工具
- get_stock_basic_info: 股票基本信息（名称、行业、市值）
- get_stock_realtime_quote: 实时行情（最新价、涨跌幅）
- get_financial_indicators: 财务指标（PE/PB/ROE等）
- get_stock_history: 历史K线数据（用于计算收益率/波动率）

## 规则
- 股票代码为6位数字：60xxxx(沪市主板)/00xxxx(深市主板)/30xxxx(创业板)/68xxxx(科创板)
- 历史数据默认取最近一年
- 数据获取失败时说明原因，不要编造数据
- 所有数据都已写入共享内存，下游Agent可直接引用"""


def _invoke_with_timeout(tool, args: dict, timeout: float) -> tuple[Any, Exception | None]:
    """在子线程中调用工具，带硬超时保护。

    返回 (result, error)。超时时 error 为 TimeoutError。
    """
    result: list[Any] = []
    error: list[Exception | None] = [None]
    done = threading.Event()

    def _run() -> None:
        try:
            result.append(tool.invoke(args))
        except Exception as exc:
            error[0] = exc
        finally:
            done.set()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    if done.wait(timeout):
        if error[0] is not None:
            return None, error[0]
        return result[0] if result else None, None
    return None, TimeoutError(f"工具 {getattr(tool, 'name', tool)} 超时（{timeout:.0f}s）")


class DataFetchAgent(BaseFinanceAgent):
    """金融数据获取 Agent。"""

    agent_name: str = "data_fetch"

    def __init__(self, shared_memory=None, checkpointer=None):
        super().__init__(shared_memory=shared_memory, checkpointer=checkpointer)
        self._qianfan: QianfanStockSearch | None = None

    @property
    def qianfan(self) -> QianfanStockSearch:
        """懒初始化千帆搜索实例。"""
        if self._qianfan is None:
            self._qianfan = QianfanStockSearch()
        return self._qianfan

    def _get_tools(self) -> list:
        return [
            get_stock_basic_info,
            get_stock_realtime_quote,
            get_financial_indicators,
            get_stock_history,
        ]

    def _get_system_prompt(self) -> str:
        return _DATA_FETCH_PROMPT

    @staticmethod
    def _has_data(result: Any) -> bool:
        """检查 BaoStock 返回的结果是否包含有效数据（非空、无error）。"""
        if not isinstance(result, dict):
            return True
        return "error" not in result

    @staticmethod
    def _missing_indicator_fields(data: dict[str, Any]) -> list[str]:
        """检查财务指标字典中哪些关键字段缺失或为零。"""
        if not isinstance(data, dict) or "error" in data:
            # 全部缺失
            return [
                "roe", "net_profit_margin", "gross_margin",
                "net_profit_growth", "total_asset_growth", "debt_ratio",
                "current_ratio", "quick_ratio", "eps", "net_profit",
                "pe", "pb",
            ]
        missing = []
        for field in [
            "roe", "net_profit_margin", "gross_margin",
            "net_profit_growth", "total_asset_growth", "debt_ratio",
            "current_ratio", "quick_ratio", "eps", "net_profit",
        ]:
            val = data.get(field)
            if val is None or val == 0:
                missing.append(field)
        # PE/PB 来自 quote，检查 quote 中的值
        return missing

    @staticmethod
    def _missing_quote_fields(data: dict[str, Any]) -> list[str]:
        """检查行情数据中哪些关键字段缺失。"""
        if not isinstance(data, dict) or "error" in data:
            return ["pe", "pb", "price", "change_pct"]
        missing = []
        for field in ["pe", "pb"]:
            val = data.get(field)
            if val is None or val == 0:
                missing.append(field)
        return missing

    @staticmethod
    def _merge_fallback(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        """将千帆兜底数据合并到主数据中，不覆盖已有的有效值。"""
        if not isinstance(fallback, dict) or "error" in fallback:
            return primary
        merged = dict(primary)
        for key, val in fallback.items():
            if key in ("code", "source", "error", "source_urls"):
                continue
            existing = merged.get(key)
            if existing is None or existing == 0 or existing == "":
                merged[key] = val
        # 标记使用了兜底数据
        if fallback.get("source") == "qianfan_fallback":
            merged["fallback_source"] = "qianfan_fallback"
            merged.setdefault("fallback_fields", [])
            if isinstance(merged["fallback_fields"], list):
                for key in fallback:
                    if key not in ("code", "source", "error", "source_urls", "date", "name", "industry"):
                        if key not in merged["fallback_fields"] and fallback.get(key) is not None:
                            merged["fallback_fields"].append(key)
            merged["fallback_source_urls"] = fallback.get("source_urls", [])
        return merged

    def _qianfan_fallback_for_stock(self, code: str, missing_fields: list[str]) -> dict[str, Any]:
        """为单只股票从千帆搜索获取兜底数据。"""
        try:
            from finance_agent.config import QIANFAN_API_KEY
            if not QIANFAN_API_KEY:
                return {"error": "未配置 QIANFAN_API_KEY", "source": "qianfan_fallback", "code": code}
            return self.qianfan.search_financial_fallback(code, missing_fields)
        except Exception as exc:
            return {"error": f"千帆兜底查询失败: {exc}", "source": "qianfan_fallback", "code": code}

    def handle_single_stock(self, code: str) -> dict[str, Any]:
        """获取单只股票的全部金融数据并写入共享内存。

        供 LangGraph Send 并行节点调用。无 inter-stock 依赖，可并发执行。

        每只股票有独立超时保护：单个工具调用超时 25s，整只股票超时 90s。
        超时不会阻塞其他股票的数据获取。

        Args:
            code: 6位A股代码

        Returns:
            包含 basic_info / quote / indicators / history 及可能的 *_error 字段
        """
        entry: dict[str, Any] = {"code": code}
        deadline = time.monotonic() + _PER_STOCK_TIMEOUT

        def _remaining() -> float:
            return max(5.0, deadline - time.monotonic())

        # 基本信息 — 如果 BaoStock 失败，用千帆兜底名称/行业
        try:
            remaining = _remaining()
            raw, err = _invoke_with_timeout(
                get_stock_basic_info, {"stock_code": code}, remaining
            )
            if err is not None:
                raise err
            data = json.loads(raw) if isinstance(raw, str) else raw
            if not self._has_data(data):
                # BaoStock basic_info 失败，尝试千帆兜底
                fb = self._qianfan_fallback_for_stock(code, ["name", "industry"])
                data = self._merge_fallback(data, fb)
            entry["basic_info"] = data
            if self.shared_memory and isinstance(data, dict) and "error" not in data:
                self.shared_memory.publish_fact(
                    f"stock_basic_info_{code}", data, source=self.agent_name,
                )
        except TimeoutError as exc:
            entry["basic_info_error"] = f"获取超时: {exc}"
        except Exception as exc:
            entry["basic_info_error"] = str(exc)

        # 实时行情 — BaoStock 失败用千帆兜底 PE/PB
        try:
            remaining = _remaining()
            raw, err = _invoke_with_timeout(
                get_stock_realtime_quote, {"stock_code": code}, remaining
            )
            if err is not None:
                raise err
            data = json.loads(raw) if isinstance(raw, str) else raw
            if not self._has_data(data):
                fb = self._qianfan_fallback_for_stock(code, ["pe", "pb", "price"])
                data = self._merge_fallback(data, fb)
            elif self._missing_quote_fields(data):
                missing = self._missing_quote_fields(data)
                fb = self._qianfan_fallback_for_stock(code, missing)
                data = self._merge_fallback(data, fb)
            entry["quote"] = data
            if self.shared_memory and isinstance(data, dict) and "error" not in data:
                self.shared_memory.publish_fact(
                    f"stock_quote_{code}", data, source=self.agent_name,
                )
        except TimeoutError as exc:
            entry["quote_error"] = f"获取超时: {exc}"
        except Exception as exc:
            entry["quote_error"] = str(exc)

        # 财务指标 — BaoStock 失败或缺失用千帆兜底
        try:
            remaining = _remaining()
            raw, err = _invoke_with_timeout(
                get_financial_indicators, {"stock_code": code}, remaining
            )
            if err is not None:
                raise err
            data = json.loads(raw) if isinstance(raw, str) else raw
            if not self._has_data(data):
                # 全部缺失，搜索所有字段
                fb = self._qianfan_fallback_for_stock(code, [])
                data = self._merge_fallback(data, fb)
            else:
                missing = self._missing_indicator_fields(data)
                if missing:
                    fb = self._qianfan_fallback_for_stock(code, missing)
                    data = self._merge_fallback(data, fb)
            entry["indicators"] = data
            if self.shared_memory and isinstance(data, dict) and "error" not in data:
                self.shared_memory.publish_fact(
                    f"financial_indicator_{code}", data, source=self.agent_name,
                )
        except TimeoutError as exc:
            entry["indicators_error"] = f"获取超时: {exc}"
        except Exception as exc:
            entry["indicators_error"] = str(exc)

        # 历史K线
        try:
            remaining = _remaining()
            raw, err = _invoke_with_timeout(
                get_stock_history, {"stock_code": code}, remaining
            )
            if err is not None:
                raise err
            data = json.loads(raw) if isinstance(raw, str) else raw
            entry["history"] = data
            if self.shared_memory and isinstance(data, dict):
                # 无论成功还是失败都写入 shared_memory，让下游能读到错误详情
                self.shared_memory.publish_fact(
                    f"stock_history_{code}", data, source=self.agent_name,
                )
        except TimeoutError as exc:
            entry["history_error"] = f"获取超时: {exc}"
            if self.shared_memory:
                self.shared_memory.publish_fact(
                    f"stock_history_{code}",
                    {"error": f"工具调用超时：{exc}", "code": code},
                    source=self.agent_name,
                )
        except Exception as exc:
            entry["history_error"] = str(exc)
            if self.shared_memory:
                self.shared_memory.publish_fact(
                    f"stock_history_{code}",
                    {"error": f"工具调用异常：{exc}", "code": code},
                    source=self.agent_name,
                )

        return entry

    def handle(
        self,
        message: str,
        customer_id: str = "",
        chat_history: List[Dict[str, str]] | None = None,
        thread_id: str | None = None,
        memory_context: str = "",
    ) -> str:
        """获取金融数据并写入共享内存。"""
        # 从共享内存读取用户画像中的股票代码
        stock_codes: list[str] = []
        if self.shared_memory:
            user_profile = self.shared_memory.query("user_profile", {})
            if isinstance(user_profile, dict):
                stock_codes = user_profile.get("stock_codes", [])

        if not stock_codes:
            # 从用户消息中提取
            import re
            stock_codes = re.findall(r"(?<!\d)(60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)", message)

        if not stock_codes:
            return "未识别到股票代码，请提供A股代码（如600519、000001）后再获取数据。"

        # 获取每只股票的数据（复用 handle_single_stock，保持非并行场景兼容）
        results: list[dict[str, Any]] = [
            self.handle_single_stock(code) for code in stock_codes[:5]  # 限制最多5只
        ]

        # 生成摘要
        parts = [f"已获取 {len(results)} 只股票的金融数据："]
        for entry in results:
            code = entry["code"]
            quote = entry.get("quote", {})
            name = quote.get("name", entry.get("basic_info", {}).get("name", code))
            try:
                price = float(quote.get("price") or 0)
            except (TypeError, ValueError):
                price = 0.0
            try:
                change = float(quote.get("change_pct") or 0)
            except (TypeError, ValueError):
                change = 0.0
            errors = []
            if "error" in (entry.get("quote") or {}):
                errors.append(f"行情失败({entry['quote']['error']})")
            if "indicators_error" in entry:
                errors.append(f"财务失败({entry['indicators_error']})")
            if "history_error" in entry:
                errors.append(f"历史失败({entry['history_error']})")
            status = "成功" if not errors else "; ".join(errors)
            parts.append(f"  - {code}「{name}」价格:{price:.2f} 涨跌:{change:+.2f}% [{status}]")

        return "\n".join(parts)
