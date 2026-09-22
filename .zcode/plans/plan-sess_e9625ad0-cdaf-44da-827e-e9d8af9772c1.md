## 继续完成 Hybrid LangGraph Orchestration 重构（计划 Task 2 收尾 → Task 10）

### 背景与当前状态
- Task 1 已提交（`c18976e`）：`orchestrator/contracts.py`、`orchestrator/thread_key.py`、v2/Celery/FAQ 配置项、`tests/test_orchestrator_contracts_v2.py`。
- Task 2 已实现但未提交（工作区）：`sql/008_hybrid_orchestration.sql`、`finance_agent/faq/repository.py`、`postgres_schema.py`/`postgres_stores.py` 改动、`tests/test_faq_schema.py`、`tests/test_thread_key_migration.py`。
- Task 3–10 完全未开始；`ORCHESTRATION_V2_ENABLED` 等配置项目前无人读取；`celery`/`sentence-transformers` 尚未加入依赖。
- 工作区中 12 个被删的旧 docs 与 `.mimosa/` 产物与本任务无关，**不纳入任何提交**。

### 已锁定的设计决策（未获答复，按推荐默认执行；若实现中发现真正偏离，先询问）
1. **Checkpoint seam**：新增 `finance_agent/orchestrator/run_state.py::RunStateStore`（设计 §6.9），封装复合键读取/旧键迁移/恢复/删除；现有自由函数保留为薄适配层以保证 Task 2 测试与提交完整。
2. **模型策略**：Task 7 Planner 与 Task 9 合规语义校验复用现有 `INTENT_MODEL`（qwen-turbo，低温短超时），不新增模型配置变量。
3. **FAQ 阈值**：新增 `FAQ_MIN_SCORE` 配置项，默认 `0.3`（归一化 RRF 融合分）。
4. **Celery 策略**：软超时 60s / 硬超时 120s / 结果 TTL 3600s，全部配置化。

### 实施步骤（逐任务提交，每个任务先写失败测试再实现）

**Task 2 收尾** — 补 `finance_agent/faq/__init__.py`；新增 `orchestrator/run_state.py`（`RunStateStore`，迁移现有 `load_checkpoint_with_legacy_fallback` 逻辑，自由函数改为委托）；运行 `pytest tests/test_faq_schema.py tests/test_thread_key_migration.py tests/test_postgres_schema.py -v`；提交 `feat: persist faq and async orchestration state`。

**Task 3 FAQ RAG** — 新增 `docs/faq/{investment-basics,risk-and-compliance,trading-rules}.md`（`## FAQ-001 标题` 形式）；`faq/contracts.py`（`FaqSearchMatch`/`FaqSearchResult`）、`documents.py`（`parse_faq_markdown`，重复 ID/空答案/畸形标题拒绝）、`embeddings.py`（`EmbeddingProvider` + 惰性 CPU `SentenceTransformerEmbeddingProvider`，锁定 `BAAI/bge-small-zh-v1.5`、512 维、归一化）、`indexer.py`（三文件全校验后单事务发布索引版本）、`retriever.py`（向量 top-12 + 关键词 top-12，归一化 RRF 融合，`FAQ_MIN_SCORE` 过滤，≤4）、`__main__.py`（`python -m finance_agent.faq index --root docs/faq --model-cache-dir .cache/models`）；config 增加 `FAQ_MIN_SCORE`；`pyproject.toml`/`requirements.txt` 增加 `sentence-transformers`；测试用 FakeEmbedding + 内存仓储，无网络/模型下载。提交 `feat: add local faq retrieval`。

**Task 4 ReAct 内核 + 会话子图** — `orchestrator/react.py`（`ToolSpec`、`run_bounded_react`，仅解析 `ReactDecision`，白名单校验、input/output schema 校验，四轮上限后 `degraded_synthesis`）；`orchestrator/conversation_graph.py`（`build_conversation_graph`，仅暴露 `faq_search`）；`agents/casual_chat.py` 重构为纯文本助手；测试 `test_react_loop.py`、`test_conversation_graph.py`。提交 `feat: add bounded conversation react graph`。

**Task 5 Root Graph 与三领域路由** — `orchestrator/root_graph.py`（`classify_domains` 复用现有分类器映射到三领域：stock_analysis/stock_recommendation→stock_research 等，`build_root_graph`，`single:{run_id}:{domain}`）；`orchestrator/orchestrator.py` 增加 `handle_message_v2`，仅在 `ORCHESTRATION_V2_ENABLED=true` 时启用，异常返回 `run_status="failed"` 且**不得**回退旧路径；`supervisor.py` 的 `ManagerAgent` 收敛为分类/合成助手；`api/routes.py`/`api/schemas.py` 传入已认证 customer_id 并仅追加字段；`thread_id` 全程用 `build_thread_id`；`recursion_limit=32`；测试 `test_root_graph_routing.py`、`test_multitenant_checkpoints.py`、`test_api_compatibility_v2.py` + `test_runtime_controls.py` 回归。提交 `feat: route v2 orchestration by business domain`。

**Task 6 三个 Domain ReAct 子图** — 新增 `orchestrator/domains/{__init__,stock,market,product}.py`，把三个 Agent 类中的确定性 pipeline 抽取为图节点（Stock: ResearchPipeline/技术指标/主题筛选/数据适配；Market: 四个采集器 + 仅受限 `PolicyImpactInterpreter`；Product: `ProductResearchPipeline` + 产品库工具），各域独立工具白名单，统一返回 `DomainOutcome`，失败转安全 limitations；测试三个域图 + `test_stock_analysis_e2e.py`/`test_product_analysis_agent.py`/`test_market_insight.py` 回归。提交 `feat: add domain react subgraphs`。

**Task 7 Plan-and-Execute** — `orchestrator/plan_execute.py`（`validate_execution_plan`：≤8 任务、ID 唯一、允许域、无环、依赖有效、必需 expected_output；`dispatch_ready_tasks` 仅此处使用 LangGraph `Send`，载荷含 task_id/domain/goal/instruction/upstream outcomes/不变 thread_id；`evaluate_plan_results` 完成/部分/≤2 次重规划）；LLM Planner 复用 `INTENT_MODEL`；`root_graph.py` 接线；`scheduler.py` 降为旧路径专用；测试 `test_plan_execute_graph.py` + 更新 `test_orchestrator_fanout.py`。提交 `feat: add cross-domain plan and execute graph`。

**Task 8 Celery Quant Gateway 与恢复** — `finance_agent/celery_app.py`（Redis DB=`CELERY_REDIS_DB`、队列 `CELERY_QUANT_QUEUE`、JSON 序列化、`task_acks_late=True`、软/硬超时 60/120s、结果 TTL 3600s）；`tasks/{__init__,quant}.py`（技术指标、批量评分/主题筛选、回测、重放；纯计算、不 import LangGraph）；`orchestrator/quant.py`（`QuantGateway` Protocol + Celery/内存 Adapter，幂等）；`orchestrator/resume.py`（`ResumeCoordinator.resume_ready` 校验归属后用 `RunStateStore`+`AsyncRunRepository` 恢复原 thread_id/run_id/task_id）；`domains/stock.py` 接入中断 `awaiting_quant` 与预算内轮询；config/pyproject/requirements 增加 `celery`；测试 `test_quant_gateway.py`、`test_resume_coordinator.py`，另加 `celery_integration` 标记、默认 `RUN_CELERY_INTEGRATION=1` 才跑的集成测试。提交 `feat: offload quant work through celery`。

**Task 9 合规出口、响应投影与异步 API** — `orchestrator/compliance.py`（`build_compliance_graph`：确定性规则→语义校验（复用 `INTENT_MODEL`）→最多一次改写→复检→失败阻断 fail-closed；审计存原因码/规则版本/草稿哈希/最终动作）；`root_graph.py` 让 conversation/单域/计划输出全部经合规；`ResponseProjector.project` 保留现有字段并仅追加 `run_status`/`task_id`/`pending_task_ids`/warnings；`api/routes.py` 增加鉴权的 `GET /api/runs/{task_id}`（先校验客户归属，再 `ResumeCoordinator`）；`api/sse.py` 增加 `async_task` 事件；测试 `test_compliance_graph.py`、`test_async_run_api.py`、`test_response_projection_v2.py` + 回归。提交 `feat: enforce compliance graph and async run status`。

**Task 10 退役旧编排与全量验收** — v2 设为唯一 `AdvisorSystem` 路径、移除开关与旧 scheduler 使用；在确定性 helper 被域图引用后删除 `supervisor.py`/`casual_chat.py`/`stock_analysis.py`/`market_insight.py`/`product_analysis.py`；仅当 `agents/base.py` 无生产引用时删除；更新 `README.md` 与设计文档；测试 `test_legacy_agent_retirement.py`、`test_orchestration_e2e_v2.py`；运行 `python -m compileall -q finance_agent` 与 `pytest -q`。提交 `refactor: replace legacy agents with langgraph domains`。

### 验收
每个任务：聚焦测试通过 → 提交；最终 `pytest -q` 全绿（若 Postgres/Redis/Celery 集成测试被环境门控，明确报告跳过条件）。全程遵守：LLM 只分类/规划/选白名单工具/受约束叙述；取数与计算由确定性工具完成；新路径异常不静默回退；不改变现有 `/api/chat` 主响应字段。
