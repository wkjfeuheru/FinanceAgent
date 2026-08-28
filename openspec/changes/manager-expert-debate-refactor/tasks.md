## 1. 基础设施与配置

- [ ] 1.1 在 `requirements.txt` 新增 AutoGen 依赖（`autogen-agentchat`、`pyautogen`），运行 `pip install -r requirements.txt` 验证安装成功且与现有 LangChain/LangGraph 版本不冲突
- [x] 1.2 在 `finance_agent/config.py` 新增辩论配置项：`DEBATE_ENABLED`（默认 true）、`DEBATE_MAX_ROUNDS`（默认 2）、`DEBATE_TIMEOUT`（默认 60.0）、`DEBATE_BULL_TEMPERATURE`（0.4）、`DEBATE_BEAR_TEMPERATURE`（0.4）、`DEBATE_SYNTHESIS_TEMPERATURE`（0.1），运行 `python -m compileall -q finance_agent/config.py` 验证编译通过
- [x] 1.3 在 `AGENT_TEMPERATURES` 中补充辩论 Agent 温度条目（`debate_bull`、`debate_bear`、`debate_synthesis`），验证 `get_model_for_agent("debate_bull")` 返回正确温度的 DeepSeek 实例
- [x] 1.4 在 `finance_agent/config.py` 新增产品库配置项：`PRODUCT_LIBRARY_DB_PATH`（默认 SQLite 路径）、`PRODUCT_ANALYSIS_TEMPERATURE`（0.2），并在 `AGENT_TEMPERATURES` 中补充 `product_analysis` 条目，运行 `python -m compileall -q finance_agent/config.py` 验证通过

## 2. 总管（ManagerAgent）演进

- [x] 2.1 将 `finance_agent/agents/supervisor.py` 中的 `SupervisorAgent` 演进为 `ManagerAgent`（保留类名或新增别名以保证向后兼容），保留 `DeepSeekIntentClassifier`、`classify_intents`，验证 `python -m compileall -q finance_agent/agents/supervisor.py` 通过
- [x] 2.2 为 `ManagerAgent` 新增 `dispatch_tasks(state) -> List[Dict]` 方法：在单一节点内先调用 `classify_intents` 完成意图识别，再为每个意图抽取独立需求描述（忠实转述、不加工），产出轻量 `task_dispatch`，每项仅含 `{intent, expert, requirement}`，其中 `expert` 可取值含 `product_analysis`（产品解读）与 `casual_chat`（闲聊），编写单测验证多意图请求在单节点内识别并抽取为多条独立需求描述且映射到正确专家
- [ ] 2.3 验证纯闲聊（casual_chat）场景下总管将需求路由到闲聊专家（CasualChatAgent），`dispatch_tasks` 不调度任何数据获取、分析、资产配置或产品解读专家，也不产生合规专家任务，单测覆盖该场景
- [ ] 2.4 为 `ManagerAgent` 新增 `synthesize_response(state) -> str` 方法：承担原合规专家的"最终响应合成"职责，按用户友好顺序合并各专家结果片段并合成面向用户的回复，回复 MUST 包含风险提示，单测验证多专家结果合并并附加风险提示
- [ ] 2.5 在 `finance_agent/agents/__init__.py` 导出 `ManagerAgent`（并保留 `SupervisorAgent` 别名），验证 `from finance_agent.agents import ManagerAgent` 可正常导入
- [ ] 2.6 创建 `finance_agent/agents/casual_chat.py`：闲聊专家（CasualChatAgent），接收总管路由的闲聊需求，直接生成自然闲聊回复，不调用任何金融数据工具；保留原 `supervisor.chat()` 的金融边界约束（闲聊偏离金融主题时温和引导），验证单测覆盖纯闲聊与偏题引导场景

## 3. 数据获取下沉为 tool calling

- [x] 3.1 将统一数据源 `finance_agent/data/tushare_mcp.py`（`TushareMcpDataSource`）的获取能力封装为 LangChain `@tool` 函数（如 `get_stock_quote`、`get_stock_history`、`get_financial_indicators`、`get_stock_basic_info`、`get_valuation_indicators`、`get_income_statement`、`search_candidates`），替代原 `data/baostock.py`、`data/market.py` 与 `tools/web_search.py` 的获取能力，验证每个 `@tool` 可独立调用并返回结构化数据
- [ ] 3.2 删除 `finance_agent/agents/data_fetch.py` 作为独立专家，并移除 `data_fetch_batch` 编排节点引用，验证 `python -m compileall -q finance_agent/` 无残留 `DataFetchAgent` 导入错误
- [ ] 3.3 修改 `finance_agent/agents/stock_analysis.py`：移除对 `DataFetchAgent` 与 `ProfileAgent` 的依赖，改为 ReAct `_get_tools()` 返回数据获取 `@tool`，并在内部自行从用户消息中抽取股票名称/代码，由模型自主决定调用哪个工具取数，验证股票分析单测在 mock 工具下能完成"字段抽取 -> 取数 -> 分析"流程
- [ ] 3.4 修改 `finance_agent/agents/asset_allocation.py`：移除对 `ProfileAgent` 的依赖，改为在内部自行从用户消息中抽取风险偏好/投资金额/投资年限等字段，并通过数据获取 `@tool` 自行读取历史价数据（或直接从 `AdvisorState` 的 `stock_data` 字段查询），验证资产配置在历史数据就绪时能正常计算 MPT
- [ ] 3.5 实现 `AdvisorState` 数据复用去重：专家调用工具前先查 `AdvisorState` 已有字段（如 `stock_data`、`stock_analysis`）命中即跳过取数，避免多专家重复获取，单测验证同一 run 内第二只专家不再重复调用底层数据源

## 4. 产品库与产品解读专家

- [x] 4.1 创建 `finance_agent/data/product_library.py`：实现产品库 SQLite 关系型数据库表（产品基础信息、持仓、业绩、费率等结构化字段）与访问层（按代码/名称查询、写入、列表），验证建表与增删查改通过，不引入 RAG/向量库依赖
- [x] 4.2 创建 `finance_agent/tools/product.py`：将产品库查询封装为 LangChain `@tool`（如 `query_product`、`list_products`），验证工具能按产品代码返回结构化产品数据
- [x] 4.3 创建 `finance_agent/agents/product_analysis.py`：产品解读专家（ReActAgent，`_get_tools()` 返回产品库查询工具），在内部自行从用户消息中抽取产品名称/代码，实现单产品深度透视、多产品对比评估与产品具体问题问答，验证单测覆盖三类请求
- [x] 4.4 产品库数据接入：可选复用现有 MCP `fund_basic_info` 数据源填充基金基础信息，验证产品库可导入一批基金基础数据
- [x] 4.5 在 `finance_agent/agents/__init__.py` 导出 `ProductAnalysisAgent`，验证 `from finance_agent.agents import ProductAnalysisAgent` 可正常导入

## 5. 辩论模块（debate/）

- [x] 5.1 创建 `finance_agent/debate/__init__.py`，导出 `run_debate`、`DebateResult`、`DebateCoordinator`
- [x] 5.2 创建 `finance_agent/debate/coordinator.py` 实现 `DebateCoordinator`：使用 AutoGen `AssistantAgent` + `GroupChat` 编排"看多分析师"与"看空分析师"多轮辩论，LLM 通过 AutoGen `LLMConfig` 指向 DeepSeek OpenAI 兼容端点（复用 `DEEPSEEK_API_KEY`），验证单元测试 mock LLM 后能跑完默认 2 轮
- [x] 5.3 实现 `run_debate(context: Dict) -> DebateResult` 入口函数：接收 MPT 结果与基本面/技术面材料，返回结构化 `DebateResult`（含 `bull_arguments`、`bear_arguments`、`disagreements`、`convergences`），单测验证输出字段齐全
- [x] 5.4 实现轮次上限强制收敛：辩论达到 `DEBATE_MAX_ROUNDS` 后协调器停止发言并进入结论聚合，单测验证不产生超出轮次的发言
- [x] 5.5 实现总超时保护：辩论总耗时超过 `DEBATE_TIMEOUT` 时终止辩论并返回 `DebateResult(status="timeout")`，单测验证超时路径返回降级标记
- [x] 5.6 验证辩论模块仅使用 DeepSeek：grep 确认 `debate/` 目录不引入其他 LLM 厂商 import，所有 LLM 调用经 `get_model_for_agent` 或同一 `LLMConfig`

## 6. 资产配置专家集成辩论

- [ ] 6.1 修改 `finance_agent/agents/asset_allocation.py`：移除 MPT 作为唯一优化步骤，改为辩论驱动决策流程--看多方根据约束条件提出配置方案（含权重与成长逻辑），看空方针对方案逐项质疑（含风险清单与调整建议），多轮对抗后由主 Agent 仲裁产出最终配置权重，仲裁后调用 `calculate_portfolio_metrics` 验证组合指标（收益/波动率/夏普/最大回撤），将辩论结论写入 `allocation_result["debate"]`，验证报告新增"辩论摘要"与"仲裁理由"小节
- [ ] 6.2 实现仲裁时对未解决风险的显式标注：当 `DebateResult.unresolved_risks` 中存在未被看多方有效反驳的重大风险时，主 Agent 在仲裁中对该标的降低权重或标注风险提示并记录"辩论提示风险"，单测覆盖仲裁降权场景
- [ ] 6.3 实现辩论降级：当 `DEBATE_ENABLED=false` 或辩论返回 `status="timeout"` 时，跳过辩论由主 Agent 直接根据参考指标与基本面生成配置方案并标注"辩论未执行/超时"，单测验证降级路径
- [ ] 6.4 验证 `allocation_result.debate` 为可选字段：未触发辩论时该字段缺失，已有 `allocation_result` 消费者不报错

## 7. 编排器（orchestrator）重写为总管-专家委托图

- [ ] 7.1 在 `AdvisorState`（`core/state.py` 或 orchestrator 内联）新增 `task_dispatch: List[Dict]`（每项 `{intent, expert, requirement}`）、`debate_result: Dict` 与 `product_analysis: Dict` 字段，保留 `task_plan` 向后兼容（取自 dispatch 的专家名列表），验证 `python -m compileall -q finance_agent/core/orchestrator.py` 通过
- [ ] 7.2 重写 `_build_graph`：删除 `compliance`、`data_fetch` 与 `profile` 节点，supervisor 节点调用 `ManagerAgent.dispatch_tasks` 写入 `task_dispatch`，条件路由函数改为读取 `task_dispatch` 决定下一专家（含 `product_analysis`），并将完整上下文透传给路由到的专家，专家任务完成后进入总管合成节点调用 `ManagerAgent.synthesize_response`，验证 `task_plan` 仍由 dispatch 派生保持兼容
- [ ] 7.3 将原 `compliance_handler` 的最终合成逻辑（`_compose_intent_draft` + `_synthesize_response` + `_clean_user_facing_response`）迁入 `ManagerAgent.synthesize_response`，删除编排器中对 `compliance_agent.review` 的调用，验证回复仍经 LLM 重写并附加风险提示
- [ ] 7.4 实现按 `task_dispatch` 的 `expert` 字段路由：股票分析、资产配置、产品解读各自内部自行规划执行并独立取数分析；编排器不再维护子任务依赖、执行顺序或并行分组，验证 candidate_search 由股票分析专家内部规划两阶段 tool calling 完成
- [ ] 7.5 实现专家失败回退：当某专家任务标记降级时，总管基于已有结果生成可交付回复而非中断，单测覆盖专家内数据获取失败降级为"暂无可用数据"提示语
- [ ] 7.6 保留公共 API 不变：`handle_message` / `handle_message_stream` 签名兼容，API 入口的输入侧 `find_sensitive_word` 拦截保留，响应体新增可选 `debate` 与 `product_analysis` 字段，验证既有调用方无需改动
- [ ] 7.7 移除合规专家、数据获取专家与画像专家依赖：从编排器与 `agents/__init__.py` 移除对 `ComplianceAgent`、`DataFetchAgent`、`ProfileAgent` 的引用，`tools/compliance.py` 的 `check_sensitive_words` 保留为轻量工具供总管可选调用，验证 `python -m compileall -q finance_agent/` 无残留合规节点、数据获取节点与画像节点引用
- [ ] 7.8 移除 SharedWorkingMemory：删除 `finance_agent/core/shared_state.py` 及编排器内所有 `publish_fact`/`query`/`shared_memory_snapshot`/`self.shared_memory` 注入点，各专家改为从 `AdvisorState` 读取输入、将结果写回 `AdvisorState` 对应字段，验证 `python -m compileall -q finance_agent/` 无残留 `SharedWorkingMemory` 导入，且资产配置专家能从 `AdvisorState` 读取股票分析历史价完成 MPT 计算

## 8. API 与前端

- [x] 8.1 在 `finance_agent/api/schemas.py` 响应体中将 `allocation_result.debate` 与 `product_analysis` 声明为可选字段，验证 OpenAPI/响应序列化不因缺失该字段报错
- [x] 8.2 在 SSE 进度回调中新增 "debate" 与 "product_analysis" 阶段事件，验证流式接口能推送该阶段且不破坏既有阶段事件
- [x] 8.3 前端 `AllocationChart.vue` 可选读取 `debate` 字段展示辩论摘要；当字段缺失时正常展示配置结果不报错，验证前端构建通过

## 9. 测试与验证

- [ ] 9.1 新增 `tests/test_manager.py`：覆盖单节点意图识别+独立需求描述抽取、纯闲聊路由到闲聊专家、专家映射、最终合成合并并附加风险提示，运行 `python -m pytest tests/test_manager.py -v --timeout=30` 全部通过
- [ ] 9.2 新增 `tests/test_debate_flow.py`：覆盖默认 2 轮辩论、轮次上限收敛、超时降级、结论字段齐全、DeepSeek-only 约束，运行 `python -m pytest tests/test_debate_flow.py -v --timeout=30` 全部通过
- [ ] 9.3 新增 `tests/test_allocation_debate_integration.py`：覆盖辩论支持/冲突两类最终报告、降级标注，运行该测试全部通过
- [ ] 9.4 新增 `tests/test_product_analysis.py`：覆盖单产品深度透视、多产品对比评估、产品具体问题问答、产品库缺失降级，运行 `python -m pytest tests/test_product_analysis.py -v --timeout=30` 全部通过
- [ ] 9.5 新增 `tests/test_tool_calling.py`：覆盖股票分析/资产配置专家内部 tool calling 取数、`AdvisorState` 数据复用去重，运行 `python -m pytest tests/test_tool_calling.py -v --timeout=30` 全部通过
- [ ] 9.6 适配现有测试：更新 `tests/` 下涉及 `AdvisorState` 新字段的初始化、`allocation_result` 结构断言，并移除对 `ComplianceAgent`/`compliance` 节点、`DataFetchAgent`/`data_fetch` 节点、`ProfileAgent`/`profile` 节点与 `SharedWorkingMemory` 的引用，运行 `python -m pytest tests/ --timeout=60 -v` 全部通过
- [ ] 9.7 全量编译与回归：运行 `python -m compileall -q finance_agent/` 无错误，并验证 SSE 流式接口、API 入口输入侧敏感词拦截与 checkpoint 跨轮恢复行为不变
