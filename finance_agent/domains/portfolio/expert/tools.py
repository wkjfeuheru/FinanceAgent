"""账户/持仓领域的只读工具：取快照与配置测算 JSON，不写中文模板。"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from finance_agent.orchestration.experts.base import sink_of

ACCOUNT_UNAVAILABLE = "账户数据暂不可用，请稍后在「账户」页面查看，或稍后重试。"


def _service() -> Any:
    from finance_agent.application.portfolio_service import get_portfolio_service

    return get_portfolio_service()


def _account_payload(service: Any, customer_id: str) -> dict[str, Any]:
    snapshot = service.get_account(customer_id)
    return snapshot.model_dump(mode="json") if hasattr(snapshot, "model_dump") else dict(snapshot)


def _positions_payload(service: Any, customer_id: str) -> list[dict[str, Any]]:
    positions = service.list_positions(customer_id)
    return [
        item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        for item in positions
    ]


def _holdings(service: Any, customer_id: str) -> list[dict[str, Any]]:
    """持仓与其产品风险事实（波动率/近一年收益/最大回撤）合并。"""
    positions = _positions_payload(service, customer_id)
    try:
        facts = service.position_risk_facts(customer_id)
    except Exception:  # noqa: BLE001 - 事实缺失只降级为更少的指标
        facts = {}
    merged: list[dict[str, Any]] = []
    for item in positions:
        code = str(item.get("product_code") or "")
        fact = facts.get(code, {}) if isinstance(facts, dict) else {}
        merged.append({
            **item,
            "volatility": item.get("volatility", fact.get("volatility")),
            "return_1y": item.get("return_1y", fact.get("return_1y")),
            "max_drawdown": item.get("max_drawdown", fact.get("max_drawdown")),
        })
    return merged


@tool
def get_positions(config: RunnableConfig) -> str:
    """获取当前登录用户的账户快照与持仓明细（只读）。"""
    sink = sink_of(config)
    if sink is None:
        return json.dumps({"error": "no_sink"}, ensure_ascii=False)
    try:
        service = _service()
        account = _account_payload(service, sink.customer_id)
        positions = _positions_payload(service, sink.customer_id)
    except Exception:  # noqa: BLE001
        sink.fail("account_service_failed")
        return json.dumps({"error": ACCOUNT_UNAVAILABLE}, ensure_ascii=False)

    sink.record("get_positions", payload={"account": account, "positions": positions})
    return json.dumps(
        {"account": account, "positions": positions},
        ensure_ascii=False, default=str,
    )


@tool
def review_allocation(config: RunnableConfig) -> str:
    """基于用户本人持仓做配置测算（只读），返回结构化数字。"""
    sink = sink_of(config)
    if sink is None:
        return json.dumps({"error": "no_sink"}, ensure_ascii=False)
    from finance_agent.domains.portfolio import allocation

    try:
        service = _service()
        account = _account_payload(service, sink.customer_id)
        positions = _positions_payload(service, sink.customer_id)
    except Exception:  # noqa: BLE001
        sink.fail("account_service_failed")
        return json.dumps({"error": ACCOUNT_UNAVAILABLE}, ensure_ascii=False)

    if not positions:
        sink.record("review_allocation", payload={
            "account": account, "positions": [], "allocation_review": {},
        })
        return json.dumps(
            {"account": account, "positions": [], "allocation_review": {}},
            ensure_ascii=False, default=str,
        )

    try:
        review = allocation.review_portfolio(
            _holdings(service, sink.customer_id), account, sink.user_profile,
        )
    except Exception:  # noqa: BLE001
        sink.fail("allocation_review_failed")
        return json.dumps({"error": "配置测算暂不可用"}, ensure_ascii=False)

    if not (review.get("position_count") or 0):
        sink.record("review_allocation", payload={
            "account": account, "positions": positions, "allocation_review": review,
        })
        sink.limit("no_priced_holdings")
        return json.dumps(
            {"account": account, "positions": positions, "allocation_review": review},
            ensure_ascii=False, default=str,
        )

    for code in list(review.get("limitations") or []):
        sink.limit(code)
    sink.record("review_allocation", payload={
        "account": account, "positions": positions, "allocation_review": review,
    })
    return json.dumps(
        {"account": account, "positions": positions, "allocation_review": review},
        ensure_ascii=False, default=str,
    )


__all__ = [
    "ACCOUNT_UNAVAILABLE",
    "get_positions",
    "review_allocation",
]
