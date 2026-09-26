"""把专家取数工具的输出适配为 ``SnapshotBuilder`` 所需的网关接口。

``SnapshotBuilder`` 需要 ``StockDataGateway.get_security_data(code)`` 返回
``{basic_info, quote, history(前复权), indicators}``。既有取数工具
（``stockdata.fetch_stock_data``）已产出同构字段，本适配器只做最小桥接，
不重复实现取数逻辑，也不缓存。

保持确定性可重放的关键：``quote`` / ``history`` / ``indicators`` 都带有
``source`` 与 ``fetched_at``（由工具层 ``_meta()`` 写入），快照据此判定新鲜度
并记录评估时点；缺失时由快照层显式披露，绝不静默补造。
"""

from __future__ import annotations

from typing import Any


class LiveStockDataGateway:
    """基于在线取数工具的网关实现（``StockDataGateway`` 的结构化子集）。"""

    def get_security_data(self, stock_code: str) -> dict[str, Any]:
        from finance_agent.domains.research.expert import stockdata as _stockdata

        try:
            fetched = _stockdata.fetch_stock_data([stock_code])
        except Exception as exc:  # noqa: BLE001 - 取数失败转显式 error，交由快照层判关键缺失
            return {"error": str(exc)}
        entry = fetched.get(stock_code)
        return entry if isinstance(entry, dict) else {"error": "未获取到该股票数据"}


__all__ = ["LiveStockDataGateway"]
