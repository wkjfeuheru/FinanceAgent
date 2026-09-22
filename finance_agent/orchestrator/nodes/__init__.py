"""LangGraph 节点函数的统一收敛目录。

所有图（Supervisor Graph、Plan-and-Execute、领域子图、Conversation、Compliance）
的节点函数都定义在本包：捕获依赖的节点以 ``make_*`` 工厂暴露，纯节点为
模块级函数。宿主图模块（``supervisor_graph``、``plan_execute``、``domains.base``
等）只负责装配节点与边。

防循环导入约定：nodes 不在模块级导入宿主图模块；需要宿主的纯辅助函数
（``classify_domains``、``dispatch_ready_tasks`` 等）时在节点函数体内惰性
导入，与 compliance 节点的既有风格一致。
"""

from finance_agent.orchestrator.nodes.compliance import make_review_node
from finance_agent.orchestrator.nodes.conversation import make_respond_node
from finance_agent.orchestrator.nodes.domain import make_execute_node, make_select_node
from finance_agent.orchestrator.nodes.plan_execute import (
    after_plan,
    make_domain_worker,
    make_evaluate_node,
    make_plan_node as make_pe_plan_node,
    make_replan_node,
    route_after_evaluate,
)
from finance_agent.orchestrator.nodes.supervisor import (
    classification_error_handler,
    clarify_node,
    compliance_error_handler,
    compliance_node,
    degradation_error_handler,
    make_classify_node,
    make_conversation_node,
    make_plan_node,
    make_single_domain_node,
    route,
)

__all__ = [
    "after_plan",
    "classification_error_handler",
    "clarify_node",
    "compliance_error_handler",
    "compliance_node",
    "degradation_error_handler",
    "make_classify_node",
    "make_conversation_node",
    "make_domain_worker",
    "make_evaluate_node",
    "make_pe_plan_node",
    "make_plan_node",
    "make_replan_node",
    "make_respond_node",
    "make_review_node",
    "make_select_node",
    "make_execute_node",
    "route",
    "route_after_evaluate",
]
