## Why

当前系统的编排器（orchestrator）虽然已经按 6 个 Agent 拆分，但监督者（Supervisor）只做意图分类与任务计划生成，编排器内部仍以固定线性图串联各节点，缺乏"总管"显式调度"专家"的语义；同时资产配置建议完全由单点 MPT 计算得出，缺少多视角对抗，容易在单边行情或极端假设下给出偏颇结论。引入"总管-专家"模式可以让调度逻辑可观测、可扩展；在资产配置节点叠加"看多/看空"辩论模式可以强制系统权衡正反两面，提升建议的稳健性与可解释性。

## What Changes

- 重构编排语义为"总管-专家"模式：`ManagerAgent`（由现有 SupervisorAgent 演进而来）作为总管，只负责意图识别、独立需求描述抽取、任务路由与结果汇总；各专业 Agent 作为专家，统一接受总管调度，并在内部自行完成任务规划与执行。
- 意图识别与需求抽取并入总管 Agent：总管在单一节点内完成意图识别与独立需求描述抽取（忠实转述、不加工），不再做任务拆分加工。
- 总管将完整上下文透传给路由到的专业 Agent，由专业 Agent 内部自行规划并执行任务；总管仅产出轻量 `task_dispatch`（意图 -> 专家映射 + 需求描述）驱动 LangGraph 条件边路由。
- 移除独立的合规风控专家节点：其"最终响应合成"职责由总管承担，总管在专家任务完成后汇总结果并合成面向用户的回复；保留 API 入口已有的输入侧敏感词拦截作为安全边界。
- **移除 SharedWorkingMemory 共享工作内存**：各专业 Agent 采用独立上下文，通过 `AdvisorState` 显式传递数据，不再通过共享内存的发布/订阅机制隐式交换事实。
- **移除画像专家（ProfileAgent）**：不再由统一画像专家预抽取字段；各专业 Agent 在内部自行从用户消息中抽取自身所需字段（股票分析抽取股票名称/代码、资产配置抽取风险偏好/投资金额/年限、产品解读抽取产品名称/代码），字段抽取与领域知识内聚。
- **移除独立的数据获取专家**：数据获取不再单设 Agent 与编排节点，改为各专业 Agent 内部的 tool calling；统一数据源 `data/tushare_mcp.py`（Tushare MCP Server）封装为 LangChain `@tool`，由股票分析、资产配置、产品解读等专家按需自主调用。
- **新增产品解读专家**：负责对单只金融产品（以基金为主，可扩展 ETF 等）进行深度透视与对比评估，回答用户关于产品的具体问题；对接新增的产品库（product library）。
- 在资产配置专家（`AssetAllocationAgent`）内部，套用 AutoGen 驱动的辩论模式：由"看多分析师"根据约束条件提出配置方案，"看空分析师"针对方案进行质疑与风险识别，多轮对抗后由资产配置专家仲裁产出最终配置决策。
- 辩论结束后，仲裁结论（最终权重、仲裁理由、看多方方案、看空方质疑、未解决风险、分歧/共识点）写入资产配置结果，供报告展示与前端消费。
- **BREAKING**：编排图节点语义变更，移除合规专家节点与数据获取专家节点，`AdvisorState` 新增辩论与产品解读相关字段；对外公共 API（`handle_message`/`handle_message_stream`）签名保持兼容，但响应体 `allocation_result` 结构扩展（新增 `debate` 子字段），新增可选 `product_analysis` 结果字段。
- 新增 `autogen` 与 `pyautogen` 相关依赖；新增产品库存储依赖（SQLite 表）。
- 保留现有约束：LangGraph StateGraph + SqliteSaver checkpoint、DeepSeek 作为唯一 LLM、Tushare MCP Server 统一数据源、SSE 流式接口。

## Capabilities

### New Capabilities

- `orchestration/manager-expert-routing`: 总管-专家编排能力。定义总管如何拆分用户需求、选择专家、决定执行顺序与并行度，以及如何将专家结果汇总为最终回复。覆盖任务计划生成、条件路由、专家调度与失败回退；数据获取不单设专家，由各专家内部 tool calling 完成。
- `allocation/bull-bear-debate`: 资产配置辩论能力。定义在资产配置专家输出建议时，"看多"与"看空"两位分析师如何进行多轮对抗辩论，以及辩论结论如何回传给资产配置专家影响最终决策。覆盖辩论轮次、论据结构、超时与收敛判定。
- `product/product-analysis`: 产品解读能力。定义产品解读专家如何对单只金融产品进行深度透视与对比评估、回答用户产品具体问题，以及如何对接产品库获取产品基础信息、持仓与业绩数据。覆盖单产品透视、多产品对比、产品库读写。

### Modified Capabilities

<!-- 本项目此前未建立 openspec/specs，无既有 capability 需要修改。 -->

## Impact

- **核心编排**：`finance_agent/core/orchestrator.py` 重写为总管-专家委托图；`AdvisorState` 新增 `task_dispatch`、`debate_result`、`product_analysis` 等字段；移除合规节点与数据获取节点，最终合成由总管承担。
- **Agent 层**：`agents/supervisor.py` 演进/重命名为 `ManagerAgent`，承担意图识别、独立需求描述抽取、路由与最终结果合成（任务规划与执行下沉到各专家内部）；`agents/asset_allocation.py` 集成辩论调用入口并自行通过 tool calling 获取数据；新增 `agents/product_analysis.py`（产品解读专家）；新增 `agents/casual_chat.py`（闲聊专家，从总管拆出独立节点）；`agents/stock_analysis.py` 改为自行 tool calling 获取数据并内部规划执行。
- **移除/迁移**：`agents/compliance.py` 与 `tools/compliance.py` 的合规专家节点职责并入总管；`agents/data_fetch.py` 数据获取专家节点移除，其数据获取逻辑下沉为 `tools/` 内 `@tool` 供各专家调用；`agents/profile.py` 画像专家节点移除，字段抽取逻辑下沉到各专家内部；`tools/compliance.py` 的 `check_sensitive_words` 作为轻量工具保留供总管可选调用，输入侧敏感词拦截继续由 `middleware` 在 API 入口执行；`core/shared_state.py` 的 `SharedWorkingMemory` 移除，各专家改为通过 `AdvisorState` 显式传递数据。
- **新增辩论模块**：`finance_agent/debate/`（新目录），包含辩论协调器、看多分析师、看空分析师、辩论结论聚合。
- **新增产品库**：`finance_agent/data/product_library.py`（新），产品库 SQLite 表与访问层；`tools/product.py`（新）封装产品库查询为 `@tool` 供产品解读专家调用；可复用现有 MCP `fund_basic_info` 数据源作为产品库的基金数据来源。
- **依赖**：`requirements.txt` 新增 `autogen-agentchat`/`pyautogen`；`config.py` 新增辩论与产品库相关配置项（轮次上限、超时、模型温度、产品库路径）。
- **API/前端**：`api/schemas.py` 响应体扩展 `allocation_result.debate` 与可选 `product_analysis` 字段；前端 `AllocationChart.vue` 可选展示辩论摘要（不阻塞本轮）。
- **测试**：新增辩论流程单测、总管路由与合成单测、产品解读单测、产品库读写单测；适配现有测试以兼容新增 State 字段、移除合规与数据获取节点后的编排图。
