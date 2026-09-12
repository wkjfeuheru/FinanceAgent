# 股票分析路由修复与市场洞察拆分

> **状态：已实施完成。** 复选框为实际状态，文末记录验证证据。
> 设计经 grill 访谈确认，决策表见下。

**目标：** 修复 `stock_analysis` 专家与 Supervisor 关联中三条用户可见的坏路径，并按已确认的命名边界把市场概览拆成独立意图与新专家。

**范围（三个可独立合并的变更）：**

1. **变更 ③（最小）**：槽位 `themes` 键被解析器忽略；未知主题无法使用。
2. **变更 ①**：多候选推荐把 N 只当成一个单股请求导致必然降级；改为逐标的结论 + LangGraph `Send` 扇出。
3. **变更 ②**：`market_overview` 声明支持但无实现；拆为独立意图 `market_insight` + 新专家「市场洞察」，并统一 `security_* → stock_*`、`market_query → stock_analysis` 命名。

## 全局约束与决策

| 决策点 | 裁决 |
|---|---|
| `market_overview` | 拆为独立意图 `market_insight` + 新专家。**本轮只做边界 + 诚实降级**，指数/市场宽度数据另立需求 |
| 意图集合 | `market_insight` / `stock_analysis` / `stock_recommendation` / `asset_allocation` / `product_analysis` / `casual_chat` |
| 模式改名 | `security_analysis→stock_analysis`、`security_comparison→stock_comparison`；`market_overview` 迁入 `market_insight` |
| 旧值兼容 | **硬切，不做兼容**（旧 checkpoint/审计字符串不再解析） |
| `market_insight` 模式 | 预留多模式（本轮仅实现 `market_overview`，`sentiment`/`capital_flow` 为空壳） |
| 多候选推荐 | 逐标的出结论，复用 `analyze_per_security` |
| 并行 | LangGraph `Send` 逐标的扇出；最小 reducer 集 + 显式聚合节点 |
| Send 边界 | Send 只管股票逐标的；配置/产品/闲聊仍走现有 task DAG |
| 扇出上限 | 最多 5 只，并发限 5 |
| 主题名映射 | 新建 `themes` 表（`theme_id/display_name/aliases/active`），仅迁移 + 读路径，运维改库 |
| 未知主题 | 该文本走 `search_candidates`；无候选再澄清 |
| 旧专家节点 | 删除 `route_expert` / `expert_handler` 等已不可达路径 |

- 不修改 `AnalysisRequest` / `MarketDataSnapshot` 冻结契约字段；新增信息落在新模块与状态 reducer。
- 主题注册表读路径失败不得阻断主流程；无 DB 时回退内置静态别名表。
- `market_insight` 绝不得输出个股结论、推荐、仓位或配置。

---

## 变更 ③：主题槽位与注册表

- [x] `sql/005_theme_registry.sql`：新增 `finance.themes(theme_id PK, display_name, aliases, active, created_at, updated_at)`。
- [x] `finance_agent/data/postgres_schema.py`：加载 `THEME_REGISTRY_SCHEMA_SQL`，并在 `postgres_repository._ensure_schema` 中执行。
- [x] 新增 `finance_agent/research/theme_registry.py`：`ThemeEntry`、`ThemeRegistry` 协议、`InMemoryThemeRegistry`、`PostgresThemeRegistry`（读路径）、`StaticThemeRegistry`、`default_theme_registry()`。
- [x] `finance_agent/research/request_parser.py`：`_resolve_theme_id` 同时读取槽位 `theme_id`、`theme`、`themes`；经注册表做名称/别名 → `theme_id`；未注册主题在**无代码**时抛 `UnknownThemeError`（携带主题文本），**有代码**时忽略该主题文本。
- [x] `finance_agent/agents/stock_analysis.py`：捕获 `UnknownThemeError` 用主题文本调用 `search_candidates`，无候选再澄清。
- [x] 更新 `tests/test_research_request_parser.py`（未知主题不再直接抛一般 ValueError）与 `tests/test_research_pipeline.py`（新能源 → 候选搜索/澄清）。
- [x] 新增 `tests/test_theme_registry.py`。

**验收：** `themes=['白酒']` → 候选搜索；`themes=['人工智能']` 或 `ai_compute` → 主题筛选；注册表读路径生效；无候选 → 澄清且不泄露内部异常。

## 变更 ①：多候选逐标的 + Send 扇出

- [x] `finance_agent/orchestrator/state.py`：为并发写键增加最小 reducer（`task_results`/`intent_results`/专家通道按 dict 合并；`facts` 按 `fact_id` 去重；`completed_*`/`warnings`/`analysis_results`/`theme_candidates` 拼接去重）。
- [x] `finance_agent/orchestrator/orchestrator.py`：图改为 `manager → slot_extraction → plan_tasks → (Send analyze_security × N) → aggregate → task_batch(非股票) → manager_synthesis`；新增 `plan_tasks`（请求解析 + 候选发现）与 `analyze_security` 单标的节点；`run_status`/`tasks.status` 在聚合节点统一推导。
- [x] 删除 legacy 专家节点、`route_expert`、`expert_handler` 回退；更新依赖旧分派的测试。
- [x] 上限 5、并发限 5；候选为空时明确降级。
- [x] 主题筛选路径保持不动（不纳入 Send）。
- [x] 新增/更新测试：`tests/test_research_comparison.py`、`tests/test_core_chain.py`、新增 Send 扇出与 reducer 测试。

**验收：** 3 候选 → 3 条各带代码/行动/证据的结论；并发分支不丢 `facts`/`task_results`；重复 `fact_id` 去重；上限 5。

## 变更 ②：market_insight + 统一改名

- [x] 新增 `finance_agent/agents/market_insight.py`：`MarketInsightAgent`（`agent_name="market_insight"`），硬边界；`market_overview` 返回结构化「市场概览数据尚未接入」。
- [x] `finance_agent/contracts/schema/enums.py`：`IntentKind` 加 `MARKET_INSIGHT`、去 `MARKET_QUERY`→`STOCK_ANALYSIS`；`TaskKind` 加 `MARKET_INSIGHT`。
- [x] `finance_agent/contracts/adapters.py`：`_EXPERT_BY_INTENT` 更新。
- [x] `finance_agent/contracts/schema/models.py`：`ExpertResult.normalize_legacy_intent` 加映射。
- [x] `finance_agent/agents/supervisor.py`：提示词、`_CLASSIFIER_MODES`、`_INTENTS`、`_EXECUTION_MODES`、`synthesize_response` 顺序。
- [x] `finance_agent/orchestrator/orchestrator.py`：实例化、experts/agents 字典、`_audit_expert_result`、`_make_task_result`、`_capture_task_facts`、state 初始化与输出。
- [x] `finance_agent/orchestrator/slots.py`、`context_builder.py`、`config.py`（`AGENT_TEMPERATURES`）、`agents/__init__.py`。
- [x] API/frontend：复用文本通道，不加新结构化字段。
- [x] 全量硬切改名 `market_query→stock_analysis`、`security_*→stock_*`，同步测试。

**验收：** 「今天大盘怎么样」→ `market_insight` 诚实降级、无个股结论、审计落到 `market_insight`；改名后全量测试通过。

---

## 验证证据

- [x] `python -m pytest -q`：**238 passed, 4 skipped**（实施前为 234 passed）。
- [x] `cd frontend && npm run build`：通过（vue-tsc + vite）。
- [x] `python -m compileall -q finance_agent`：通过。
- [x] 三条原始缺陷回归：
  - 选股推荐 3 候选 → 3 条各自结论，`task_results` 保留，全部取数失败时降级不崩溃（`tests/test_orchestrator_fanout.py`）。
  - 「今天大盘怎么样」→ `market_insight` 诚实降级、`agent_response` 不含 `validation error`、不产出个股结论（`tests/test_market_insight.py`）。
  - `themes=['人工智能']` → 主题筛选；未知主题 `UnknownThemeError` 携带文本并改走候选搜索；有代码时忽略未知主题（`tests/test_research_request_parser.py`、`tests/test_theme_registry.py`）。
- [x] 跨标的门禁保持：逐标的 Send 只并行**取数**，聚合节点仍对整批请求只构建一次快照，`mixed_report_period` 语义不变（`tests/test_research_comparison.py`）。

## 遗留（不在本次）

真实指数/市场宽度数据（新 provider 能力 + `board_codes` 指数符号）；`market_insight` 的 `sentiment`/`capital_flow`；`themes` 表 admin API/前端；北向数据；文档债（P1/P2 计划仍称保持 `research_rules/v1`，实际已发布 `v1.1`）。
