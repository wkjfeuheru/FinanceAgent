# 股票研究 P1/P2 修复实施计划

> **状态：已实施完成。** 本文件既是实施计划，也是完工记录：复选框为实施时的实际状态，
> 文末记录验证证据与遗留事项。

**目标：** 审计可真正复算、质量门禁真正生效、报告层披露真实限制、编排器不再有未定义变量。

**架构：** 快照构建器负责把网关原始数据标准化、执行版本化门禁并产出**可重放证据**
（完整取数输入 + 评估时点 + 逐项溯源 + 内容摘要事实 ID）；研究层新增纯函数门禁模块与
重放模块；交易日历由数据层提供并在生产接线中注入；规则阈值继续只存在于版本化配置文件。

**技术栈：** Python 3.10+、Pydantic v2、pytest、Vue 3 + TypeScript（仅报告展示）。

## 全局约束

- 门禁与评分不得访问网络、调用模型或保存单次调用状态；交易日计数必须可注入。
- 同一份审计记录必须复算出同一行动结论、同一评分与同一事实 ID。
- 缺少可验证的原始数据时保持“数据不足”，不得生成占位评分或伪造结论。
- 不修改 `AnalysisRequest` / `MarketDataSnapshot` 等冻结契约字段；新增信息只落在
  `FactSnapshot.payload` 与新模块内。
- 规则版本：保持 `research_rules/v1`。新鲜度门禁原本就声明在 v1（只是未实现），
  实现它属于补齐 v1；其余新键为披露性（warning）语义，不改变既有评分数值。
  若需严格版本不可变，可改为 `research_rules/v2`（仅 `v1.json` 的 version 字符串
  与测试引用需同步，见"遗留决策"）。

## 决策与假设

| 决策点 | 决定 |
|---|---|
| 严重度分层 | critical（→ 数据不足）：`stale_quote`、`stale_history`、`quote_as_of_missing`、`history_as_of_missing`、`mixed_report_period`；warning（结论不受阻，但状态不再 `complete`）：报告期/披露日/估值依据/跨源/日历降级 |
| 评估时点 | 每次 `build()` 计算一次 `evaluated_at` = 各数据项 `fetched_at` 最大值（缺失时用当前时间），并写入证据；重放注入该值，不使用当前时间 |
| 交易日历 | `SnapshotBuilder` 默认纯工作日估算（离线、测试友好）；生产接线 `production_builder()` 注入 Provider 交易日历；日历不可用回退工作日并记 `trading_calendar_unavailable` |
| 报告期阈值 | `quality_gates.maximum_report_period_age_days: 240`（覆盖 A 股最坏合法披露滞后） |
| `FactSnapshot.valid_until` | 不使用（保持 None），有效期语义由 `evaluated_at` + 交易日门禁表达 |
| 证据存储 | 复用 `research_runs.snapshot_manifest` JSONB，不新建表、不加迁移 |
| 事实 ID | `sha256(canonical JSON)` 前 16 位，摘要只覆盖内容字段（排除逐项 `fetched_at`，保留 `evaluated_at`） |

## 实施任务与完成状态

### 任务 1：可重放证据与确定性事实 ID

- [x] `finance_agent/research/snapshot_builder.py`：`__init__(gateway, *, gate_config, trading_days, evaluated_at)`；`build()` 一次计算评估时点、逐标的构建、再做跨标的门禁。
- [x] 证据 payload 保留原兼容摘要键，并新增 `evaluated_at` / `request` / `cross_security_reasons` / `inputs`（完整网关原始返回，含取数失败时的 `error`）/ `provenance`（逐项 source、as_of、age、日历依据、`price_basis: raw`、报告期、披露日、`valuation_basis`）。
- [x] `fact_id = stock_snapshot:{code}:{digest}`，同一天同数据必得同一 ID。
- [x] `finance_agent/research/rule_engine.py`：新增 `load_rules(version)`（未知版本显式失败，不静默回退 v1）；`RuleEngine.default()` 改用它。
- [x] `finance_agent/research/replay.py`：`EvidenceGateway`、`replay_research_run(...)`、`replay_stored_run(...)`、`main()`（`--research-run-id`、可选 `--provider-calendar`）。比对 action、scores、事实 ID、数据质量、`missing_critical`、`warnings`。
- [x] `finance_agent/data/postgres_repository.py`：`ResearchRunRepository.load()` 与 `PostgresAuditStore.load_research_run()`。
- [x] `finance_agent/orchestrator/context_builder.py`：`_fact_dict` 剥离审计专用重量字段（`inputs`/`snapshot`），避免完整 K 线进入模型上下文。

### 任务 2：数据质量门禁

- [x] 新增 `finance_agent/research/quality_gates.py`：`GateConfig.from_rules`、`market_date`、`weekday_trading_days`、`quote_freshness`、`history_freshness`、`fundamental_provenance`、`valuation_basis`、`source_consistency`、`mixed_report_periods`、`calendar_degradation_reasons`。
- [x] 新增 `finance_agent/data/trading_calendar.py`：`trading_days_between()`（Provider 日历 + 进程内缓存 + 工作日回退），`_manager_factory` 作为测试注入点。
- [x] `finance_agent/data/normalization.py` 增补 `TRADE_CAL_ALIASES` 与 `normalize_trade_cal_records`；Tushare / BaoStock 的 `get_trade_cal` 走统一字段。
- [x] `finance_agent/research/rules/v1.json` 增加 `quality_gates.maximum_report_period_age_days: 240`。
- [x] 生产接线改为 `production_builder(...)`：`agents/stock_analysis.py`（两处）、`research/screener.py`、`research/refresh.py`。

### 任务 3：报告层展示真实限制项（P2）

- [x] `finance_agent/research/narrative.py`：评分按可计算项渲染（全空显示"不可计算"），限制项按原因码翻译并输出"限制与提示：…"，未知原因码原样保留；不再把 `scores.keys()` 当限制项。
- [x] `frontend/src/components/MessageList.vue`：新增"限制与提示"区块与 `restrictionText()` 映射，`types/index.ts` 已声明 `restrictions` 字段。

### 任务 4：编排器死分支（P2）

- [x] `finance_agent/orchestrator/orchestrator.py`：删除 `expert_handler` 中不可达的 `pending_task` 分支（其中引用未定义的 `expert_status`）；保留兼容路径的需求取值、追踪、`completed_experts` 累加与审计。

## 边界情况

- `fetched_at` 缺失 → 用当前市场本地日期；该时点写入证据，重放用证据值。
- naive 时间戳按市场本地时间（Asia/Shanghai）解释；Provider 元数据改为 UTC aware。
- 日期字符串非法/为空 → 视为缺失并给对应原因码，不抛异常。
- 停牌/长假：按交易日计数，`N=1` 容忍假期缺口；日历不可用时回退并披露。
- 比较请求中某标的本无财务数据 → 不参与跨期比较，避免误报。
- 证据缺失或 `inputs` 为空 → 重放标记 `evidence_incomplete`，不伪造结论。
- 证据体积：单标的约 20–60 KB；不会进入 HTTP/SSE 响应（`ChatResponse` 无 `facts`）与专家上下文。

## 验证证据

- `python -m pytest -q`：**181 passed**（P0 收尾时为 147 passed）。
- 新增测试：`tests/test_research_quality_gates.py`（14）、`tests/test_research_replay.py`（8）、`tests/test_research_narrative.py`（5），以及 `tests/test_postgres_audit.py::test_audit_manifest_written_by_stock_agent_can_be_replayed`（真实审计写入 → 重放一致）。
- 关键断言：陈旧报价 → `critical_missing` + "数据不足" + `stale_quote`；缺报告期/披露日 → `warning` 且披露；比较混用报告期 → 拒绝；同一份证据两次重放事实 ID 一致；篡改记录结论/评分 → `mismatched`；未知规则版本 → `rules_unavailable`。
- `cd frontend && npm run build`：通过（vue-tsc + vite）。
- `python -m pyflakes finance_agent tests`：无未定义名（`expert_status` 已消失）。

## 遗留决策与已知限制

- **规则版本**：若坚持"已发布规则集不可变"，把 `rules/v1.json` 的 `version` 改为
  `research_rules/v2` 并同步 `_RULE_FILES` 与 6 处测试引用即可；本次按"补齐 v1"处理。
- **AKShare 部署**：AKShare 不提供日估值接口与披露日期，因此纯 AKShare 部署下
  `data_quality` 恒为 `warning`（含 `valuation_metrics_missing`、
  `fundamental_disclosure_date_missing`），结论不受阻但不再显示 `complete`。
- **日历降级**：Provider 日历不可用时按工作日估算，长假附近可能把有效数据判为陈旧
  （会同时给出 `trading_calendar_unavailable` 提示）。
- **短期记忆体积**：`handle_message` 返回的 facts 仍会随 `memory.update_recent_summary`
  进入短期记忆（与既有 `stock_data` 同级），本次未改变该行为。
- **导入耗时**：`finance_agent.config` → `langchain` → `transformers` 约 14s，属既有开销，
  与本次改动无关。
