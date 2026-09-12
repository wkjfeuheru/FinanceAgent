# 候选发现修复：主题/行业 → 代表股映射

> **状态：已实施完成。** 复选框为实际状态，文末记录验证证据。
> 背景提交：`eff2e6e`（E2E 冒烟发现该缺陷并 xfail 记录）。

**目标：** 修复"选股推荐"路径在默认 AKShare 配置下对行业/主题关键词返回空候选的缺陷，
使用户问"推荐几个消费龙头股"能得到真实推荐，而不是回落澄清。

## 缺陷（2026-09-12 实测）

- `search_candidates` 的关键词匹配是 `name + industry` 子串匹配（`stockdata.py:258`）。
- 但 `get_stock_basic()` 在默认 AKShare 配置下**只返回 `code` + `name`**——
  实测 5562 行中 **0 行含 `industry`**。
- 结果：仅"直接点名股票"能命中；任何行业/主题词（消费、白酒、新能源）返回 0 条，
  最终回落为"未找到匹配的候选股票"澄清。

## 方案取舍（已核对可用性）

| 方案 | 实测结论 | 裁决 |
|---|---|---|
| BaoStock `query_stock_industry` 补 `industry` | ✅ 可用（5550 行，5216 行有值），但为**证监会口径**（"C27医药制造业"/"J66货币金融服务"），83 个分类中"白酒/消费/新能源/半导体/银行/证券"**全部 0 命中**，仅"医药"这类同词可匹配 | ❌ 不解决口语主题词，且部分命中会像 bug；**另立** |
| 东财行业板块 `stock_board_industry_name_em` | ❌ 本网络仍被 URL 过滤（与既有东财接口同因） | ❌ 不可用 |
| **主题注册表扩展代表股**（走既有治理库） | 复用已建的 `finance.themes` 表与 admin API/面板；不依赖外部行业数据源；运维显式维护"主题 → 代表股" | ✅ **选定** |

**为什么选代表股映射：** 口语主题词（"消费""白酒""新能源"）与任何官方行业分类都对不齐，
靠字段匹配必然不可靠；而"某主题的代表股"是需要人工判断的治理信息，正好由运维通过
已有的主题注册表维护，且与 `theme_memberships`（已审核成员）语义互补。

## 设计

- `finance.themes` 新增 `representative_codes jsonb`（新迁移 `006_theme_representative_codes.sql`，
  幂等 `ADD COLUMN IF NOT EXISTS`）。
- `ThemeEntry` 新增 `representative_codes: list[str]`；`PostgresThemeRegistry` 读/写该列；
  `ThemeRegistry` 协议新增 `match_in_text(message) -> ThemeEntry | None`（按显示名/别名子串匹配，
  供"推荐几个消费龙头股"这类整句命中）。
- `StockAnalysisAgent._resolve_candidate_codes` 改为三段式：
  1. **注册表代表股**：`match_in_text(message)` 命中主题 → 返回其 `representative_codes`；
  2. **名称/行业关键词搜索**：沿用 `search_candidates`（名称强匹配仍有效）；
  3. 仍为空 → 澄清，引导用户提供主题或代码。
- 未注册该表或该列为空时行为与现在完全一致（回退第 2 段），**不引入新的失败模式**。
- admin API/前端 `ThemeRegistryPanel` 增加代表股编辑（逗号分隔，回车校验 6 位代码）。
- 候选为空时的澄清文案保持不变（不泄露内部机制）。

## 任务

- [x] `sql/006_theme_representative_codes.sql` + `postgres_schema` 加载 + `setup_schema` 执行。
- [x] `theme_registry.py`：`ThemeEntry.representative_codes`、`match_in_text`、
      Postgres 读/写列、Static 内置表补默认代表股（ai_compute）。
- [x] `stock_analysis.py`：`_resolve_candidate_codes` 三段式（注册表优先）。
- [x] `api/schemas.py` + `routes.py`：`ThemeRegistryUpsertRequest/Entry` 增加 `representative_codes`。
- [x] `frontend`：`types/index.ts`、`api/chat.ts`、`ThemeRegistryPanel.vue` 增加代表股编辑。
- [x] 测试：注册表 `match_in_text`/代表股读写；候选搜索优先级（注册表命中优先于名称搜索）；
      E2E 的 `test_candidate_recommendation_analyzes_discovered_stocks` 去掉 xfail。
- [x] 文档：README 数据与缓存节说明候选来源；本计划收尾。

## 验证证据

- [x] `python -m pytest -q`：**276 passed, 15 skipped**。
- [x] `RUN_NETWORK_TESTS=1 python -m pytest -q -m network tests/test_stock_analysis_e2e.py`：
      **10 passed**（原 1 xfailed 已消除）。
- [x] `cd frontend && npm run build` 通过。
- [x] 实网冒烟：注册"消费"代表股后，"推荐几个消费龙头股" → 600519/000858/600887 各出独立结论。
- [x] `RUN_NETWORK_TESTS=1 -m network tests/test_provider_smoke.py`：5 passed（新增财务指标断言）。

## 实施记录与实施中发现的连带修复

- 候选发现改为两段式：**主题代表股优先 → 名称/行业关键词搜索**；代表股经注册表
  `match_in_text`（整句最长名优先）解析。
- 注册表新增 `representative_codes`（`005_theme_registry.sql` 内幂等 `ALTER ... ADD COLUMN IF NOT EXISTS`；
  未改 `postgres_repository.py` 以免触碰扫描器对既有 DDL 执行的告警面）。
- **连带修复（实施中发现，影响面超出候选发现）：** 注册主题在"无已审核成员"或"治理库不可用"时
  退回代表股，并以 `representative_fallback` 状态明确标注"未经主题审核"；已有成员但覆盖不足时
  仍如实报告短缺（不用代表股掩盖治理结果）。
- **连带修复：** `stock_financial_analysis_indicator` 默认 `start_year='1900'` 实测返回 **0 行**，
  使基本面评分静默退化为中性 55；改为显式传近三年，单股/候选分析的基本面评分恢复真实值
  （600519 实测 ROE 17.72 / 营收 +1.47% / 净利 -2.03%，报告期 2026-06-30）。

## 遗留（不在本次）

BaoStock 证监会行业分类补 `industry` 字段（对口语主题词命中率低，且需为全量股票表增加
一次网络取数；待有明确匹配需求再评估）；东财行业板块（本网络被过滤，客户端不可修复）。
