"""Compliance 子图的节点函数（统一合规出口）。"""

from __future__ import annotations

from typing import Any, Callable


def make_review_node(
    policy: Any,
    model: Any,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """review 节点工厂；``policy``/``model`` 由 build_compliance_graph 注入。"""

    def review(state: dict[str, Any]) -> dict[str, Any]:
        from finance_agent.orchestrator.compliance import run_compliance

        result = run_compliance(
            draft=str(state.get("draft", "")),
            evidence=list(state.get("evidence", []) or []),
            policy=policy,
            model=model,
        )
        return {"compliance": result.model_dump(mode="json")}

    return review
