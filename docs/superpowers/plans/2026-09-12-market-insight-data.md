# 市场洞察实数据与主题管理

> **状态：已实施完成。** 复选框为实际状态，文末记录验证证据。
> 前置提交：`9577b4d`（路由修复 + market_insight 边界）。

**目标：** 把 `market_insight` 从"诚实降级"升级为真实数据：指数行情、市场宽度、
北向资金三个模式实装；同时补齐 `themes` 表的 admin 管理面与既有文档债。

**架构：** 数据层新增市场级 Provider 能力（指数日线 / 市场宽度 / 北向资金），
与既有逐方法降级链一致；`board_codes` 增加指数符号命名空间（与股票代码隔离，
不共用 `normalize_code`）；工具层新增 `orchestrator/tools/marketdata.py` 聚合取数；
`MarketInsightAgent` 按模式消费并渲染，仍不产出个股结论。

**技术栈：** Python 3.10+、Pydantic v2、pytest、AKShare 1.18.64、BaoStock、Vue 3。

## 本机实测事实（2026-09-12，AKShare 1.18.64）

| 能力 | 接口 | 实测结果 |
|---|---|---|
| 指数日线（新浪） | `stock_zh_index_daily(symbol='sh000001')` | ✅ 8724 行；`sh000001/sz399300/sz399006/sh000688` 均通过 |
| 指数实时（新浪） | `stock_zh_index_spot_sina()` | ✅ 562 行（含上证/深证系列，中文列） |
| 指数实时（东财） | `stock_zh_index_spot_em` | ❌ 本网络环境被按 URL 过滤（与东财 K 线同问题），只用新浪 |
| 市场宽度 | `stock_market_activity_legu()` | ✅ 上涨/下跌/涨停/跌停/平盘/停牌/活跃度/统计日期 |
| 北向汇总 | `stock_hsgt_fund_flow_summary_em()` | ✅ 沪股通/深股通/港股通(沪/深)，含成交净买额、涨跌家数 |
| 北向历史 | `stock_hsgt_hist_em(symbol='北向资金')` | ⚠️ `当日资金流入` 仅到 2024-09-27（披露口径变更），`持股市值` 到 2026-06-30；**历史净流入已停更，只展示最近有效日期并披露** |
| 板块资金流 | `stock_sector_fund_flow_rank` / `stock_market_fund_flow` | ❌ 同被 URL 过滤，不用 |
| BaoStock 指数 | `query_history_k_data_plus('sh.000001')` | ✅ 免 token 可用（指数日线第二来源） |

**单位口径：** 东财北向接口金额列为**亿元**；乐咕涨跌家数为**家**、活跃度为百分比文本。

## 全局约束

- `market_insight` 仍**绝不**输出个股结论、推荐、仓位或配置。
- 北向历史净流入 2024-09 后停更属数据源披露变更，展示时必须带"数据截至"标注，不得伪造近期净流入。
- 指数符号（`sh000001` 等）走独立命名空间，不进 `normalize_code` 股票链，避免 `000001` 被解析成平安银行。
- 所有新 provider 方法沿用 `UnsupportedProviderCapability` / `ProviderUnavailableError` 语义与按方法降级。
- 洞察数据不进研究评分管线（不生成 `FactSnapshot` 重放证据），只做展示层；如未来纳入审计另立需求。

---

## 变更 A：数据层市场能力

- [x] `finance_agent/data/board_codes.py`：新增 `IndexSymbol` 命名空间——`canonical_index(symbol) -> str`（如 `sh000001`）、`is_index_symbol(value)`、内置主要指数表（上证/深证成指/创业板指/科创50/沪深300/中证500/中证1000）。
- [x] `finance_agent/data/providers.py`：`StockDataProvider` 协议新增三个方法：
  - `get_index_daily(index_symbol, start_date, end_date)` → 统一记录 `trade_date/open/high/low/close/vol/amount/pct_chg`（ISO 日期、升序）；
  - `get_market_breadth()` → `{"as_of", "advancing", "declining", "limit_up", "limit_down", "flat", "suspended", "activity"}`；
  - `get_northbound_flow()` → `{"as_of", "channels": [{"board","direction","net_buy_yi","fund_inflow_yi","advancing","declining"}...], "note"}`。
- [x] `finance_agent/data/akshare_provider.py`：实装三方法（指数日线 `stock_zh_index_daily` 新浪源、宽度 `stock_market_activity_legu`、北向 `stock_hsgt_fund_flow_summary_em`；东财接口被本网络过滤，不进链）。
- [x] `finance_agent/data/baostock_provider.py`：实装 `get_index_daily`（`query_history_k_data_plus`）；宽度与北向声明 `UnsupportedProviderCapability`。
- [x] `finance_agent/data/tushare_mcp.py` 与 `finance_agent/data/provider_manager.py`：tushare 不实装（无 token 验证）声明不支持；manager 增加三个路由方法（复用 `_call`，`unsupported` 与 `failures` 分离不变）。
- [x] `finance_agent/data/normalization.py`：`normalize_index_daily_records` / `normalize_breadth_record` / `normalize_northbound_records`（中文列→统一键；活跃度百分比文本→float）。
- [x] 测试：`tests/test_market_data_sources.py`（夹具 DataFrame 驱动真实适配器，断言统一字段与单位；不联网）。

## 变更 B：工具层与 MarketInsightAgent 实装

- [x] `finance_agent/orchestrator/tools/marketdata.py`：
  - `get_market_overview_data()`：主要指数（上证/深证成指/创业板指/科创50/沪深300）最新价、涨跌幅、近 5 日走势 + 市场宽度 + 成交额；
  - `get_market_sentiment_data()`：宽度（涨跌家数/涨停跌停）+ 活跃度 + 指数涨跌；
  - `get_northbound_data()`：当日各通道净买额 + 历史持股市值最近有效点（带数据截至标注）。
  - 全部 best-effort：单项失败降级该项并在 `limitations` 列明，整体失败才报错。
- [x] `finance_agent/agents/market_insight.py`：三个模式实装——确定性文本渲染（不调 LLM 生成数字；模板 + 真实数值），失败/缺数据时按模式分项降级；`sentiment`/`capital_flow` 从"空壳"变为实装。
- [x] supervisor 分类器提示词：`market_insight: market_overview | market_sentiment | capital_flow` 三模式（`_CLASSIFIER_MODES`/`_EXECUTION_MODES` 同步；slots 模式表确认无需槽位）。
- [x] 测试：`tests/test_market_insight.py` 扩展（三模式实数渲染、单项失败降级、北向停更标注、不产出个股结论）。

## 变更 C：themes 管理 API + 前端

- [x] `finance_agent/research/theme_registry.py`：`PostgresThemeRegistry` 增加 `upsert(entry)`/`deactivate(theme_id)` 写方法（含 `updated_at`）。
- [x] `finance_agent/api/routes.py`：`GET /api/admin/themes`（列表）、`POST /api/admin/themes`（新增/更新：`theme_id/display_name/aliases/active`）、`DELETE /api/admin/themes/{theme_id}`（软删 `active=false`）；全部走既有 `_require_admin`。`finance_agent/api/schemas.py` 增加请求/响应模型。
- [x] 前端：`ThemeRegistryPanel.vue`（列表 + 新增/编辑表单 + 停用），挂到管理员可见入口（复用 `ThemeReviewQueue` 的模式）；`api/chat.ts` 增加调用；`types/index.ts` 增加类型。
- [x] 测试：`tests/test_theme_admin_routes.py` 扩展（CRUD、非管理员 403、软删后解析不再命中）。

## 变更 D：文档债

- [x] `docs/superpowers/plans/2026-09-11-stock-analysis-p1-p2.md`：「规则版本（已裁决）」改为记录实际发布 `research_rules/v1.1`（D13 已落地），删除"以本裁决为准"；删除/修正"AKShare 不提供日估值"的过时表述（`stock_value_em` 已接入）。
- [x] `docs/superpowers/plans/2026-09-10-deterministic-stock-analysis.md` 与 `2026-09-10-theme-recommendation-governance.md`：加状态头（"已实施完成，复选框未回填，以 git 历史为准"），不逐个回填复选框。
- [x] `docs/superpowers/plans/2026-09-11-stock-analysis-p0.md`：Task 2 Step 7 的待办注记更新为已随 `437235e` 入库（文件内已有"另注"，核对一致即可）。
- [x] README：市场洞察数据能力、北向披露变更、themes 管理接口补录。

## 验证证据

- [x] `python -m pytest -q`：**266 passed, 4 skipped**（下一阶段前为 238 passed）。
  新增 `tests/test_market_data_sources.py`（16 项），扩展 `test_market_insight.py`（8 项）、
  `test_theme_admin_routes.py`（6 项）。
- [x] `cd frontend && npm run build` 通过（含新增 `ThemeRegistryPanel.vue`）。
- [x] `python -m compileall -q finance_agent` 通过。
- [x] API 路由注册：`app.openapi()` 共 21 条路径，含 `GET/POST /api/admin/themes`、
  `DELETE /api/admin/themes/{theme_id}`。
- [x] 联网冒烟（2026-09-12 实测）：三模式均返回真实数值——
  大盘概览（上证 3,888.11 / -1.18%、宽度 604 涨 / 4567 跌）、
  市场情绪（偏弱、活跃度 11.57%）、北向资金（沪股通/深股通当日快照 + 停更说明）。

## 实施记录

- 变更 A：`board_codes` 新增指数命名空间（`INDEX_SYMBOLS`/`is_index_symbol`/`canonical_index`，
  纯数字一律走股票链）；provider 契约与 AKShare/BaoStock 适配器新增三方法；
  `normalization` 新增 `normalize_index_daily_records`/`normalize_breadth_record`/`normalize_northbound_records`。
- 变更 B：`orchestrator/tools/marketdata.py` 聚合取数（best-effort，逐项 limitations）；
  `MarketInsightAgent` 三模式确定性文本渲染；分类器模式表扩为三模式。
- 变更 C：`PostgresThemeRegistry.upsert/deactivate`；三个 admin 路由（含 `_require_admin`）；
  `ThemeRegistryPanel.vue` 挂载到管理员侧栏。

## 遗留（不在本次）

北向逐日净买额自 2024-08 起停止披露（监管调整，非接口问题；全部口径含个股持股均在同日截断），
已在 2026-09-12 后续修订中改为「融资融券 + 北向季度持仓市值」；`market_insight` 数据纳入审计重放；
Tushare MCP 指数/融资融券能力验证（无 token）。
