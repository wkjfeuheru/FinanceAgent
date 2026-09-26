"""四个领域专家的装配与分发。

每个专家 = 「工具白名单 + 领域 system prompt + 领域步数预算 + 私有 assemble」
的组合，由 ``build_expert_graph`` 编译为 ``validate → agent → assemble`` 子图。

``build_expert(domain)`` 是唯一的分发入口；``AdvisorSystem`` 与测试都从这里取
专家图，避免"分发口径"与"专家定义"两处漂移。

领域身份与装配信息（顺序、提示词路径、工具工厂）的**唯一定义**在
``domains/registry.py``；本模块只负责按领域编译专家子图，不再各自维护一份规格表。
"""

from __future__ import annotations

from typing import Any

from finance_agent.orchestration.contracts import BusinessDomain
from finance_agent.orchestration.experts.base import (
    DEFAULT_UNAVAILABLE,
    build_expert_graph,
    default_assemble,
)
from finance_agent.domains.registry import DOMAIN_SPECS
from finance_agent.shared.prompts import load_prompt

#: 领域 → 装配规格的登记处（由 domains 侧注册表派生，保持单一事实源）。
#: 保留本名字供既有调用点与测试使用；内容与 ``DOMAIN_SPECS`` 同源。
EXPERT_SPECS: dict[BusinessDomain, dict[str, Any]] = {
    domain: {
        "prompt": load_prompt(spec.prompt_path),
        "tools": spec.tools,
        "unavailable": spec.unavailable,
        # 领域私有后置校验（如"给结论必须经过确定性内核"）由领域侧登记；
        # 未登记的领域用通用汇总。
        "assemble": spec.assemble,
    }
    for domain, spec in DOMAIN_SPECS.items()
}


def step_budget(domain: BusinessDomain) -> int:
    from finance_agent.infrastructure.llm.factory import EXPERT_STEP_BUDGETS

    return EXPERT_STEP_BUDGETS.get(domain.value, 6)


def build_expert(domain: BusinessDomain, *, model: Any = None):
    """编译指定领域的专家子图（``model`` 可注入，测试用假 tool-calling 模型）。

    四个领域默认共用 ``default_assemble``：用户可见正文 = 模型分析；工具 JSON
    写入 ``structured_data`` 供卡片与数字核对。领域侧登记了私有 ``assemble``
    时（目前只有股票域）以它为准。
    """
    spec = EXPERT_SPECS.get(domain)
    if spec is None:
        raise ValueError(f"unknown domain: {domain}")

    assemble_factory = spec.get("assemble")
    assemble = assemble_factory() if callable(assemble_factory) else default_assemble

    return build_expert_graph(
        domain,
        tools=list(spec["tools"]()),
        system_prompt=str(spec["prompt"]),
        max_steps=step_budget(domain),
        model=model,
        assemble=assemble,
        unavailable_text=str(spec.get("unavailable") or DEFAULT_UNAVAILABLE),
    )


__all__ = [
    "EXPERT_SPECS",
    "build_expert",
    "step_budget",
]
