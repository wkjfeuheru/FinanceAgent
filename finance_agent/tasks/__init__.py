"""纯计算量化任务入口。

任务只做 JSON 进 / JSON 出的确定性计算，**不得 import 或调用 LangGraph**。
恢复与图续跑由 ``ResumeCoordinator`` 负责（见设计 §11）。
"""

from __future__ import annotations

from finance_agent.tasks import quant  # noqa: F401  (注册任务)
