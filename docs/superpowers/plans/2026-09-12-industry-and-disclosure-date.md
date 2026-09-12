# 行业字段与披露日补全

> **状态：已实施完成。** 复选框为实际状态，文末记录验证证据。
> 背景：上一轮 `2d05562` 修复候选发现后，实测单股分析的唯一剩余限制项是
> `fundamental_disclosure_date_missing`；另口语行业词仍需人工登记代表股。

**目标：**

1. **披露日（#2，必做）**：补上 `ann_date`，使数据质量从 `warning` 回到 `complete`，
   并消除每个报告期的"缺少披露日期"提示。
2. **行业字段（#1）**：为 A 股清单补 `industry`，使候选搜索的行业关键词匹配生效，
   减少对人工登记代表股的依赖。

## 事实核实（2026-09-12 实测，AKShare 1.18.64）

- `stock_yjbb_em(date=报告期)` 同时提供 **`所处行业`** 与 **`最新公告日期`**；
  东财该接口在本网络**可达**（未被 URL 过滤）。
- 行业覆盖：11449 行全部有行业；与 A 股清单 join 命中 **5561/5562（99%）**。
- 行业口径为**申万二级**（`白酒Ⅱ`／`银行Ⅱ`／`电池`），远贴近口语；
  对比 BaoStock 的证监会口径（`C27医药制造业`，对"白酒/消费/新能源"零命中）不可比。
- 公告日期实测：600519 半年报 `2026-08-15`、年报 `2026-04-17`、一季报 `2026-04-25`，
  均可取且落在报告期之后、评估时点之前（不会触发门禁告警）。
- 报告期推算：`2026-09-12 → 20260630`；季末刚过而报表未出时需向前回退报告期。

## 设计

- 新增 `finance_agent/data/reporting.py`：纯函数 `latest_report_period(today)` 与
  `recent_report_periods(today, n)`（A 股报告期 03-31/06-30/09-30/12-31）。
- `AkshareDataSource` 新增私有 `_earnings_snapshot()`：
  - 取最近报告期的 `stock_yjbb_em`，为空则向前回退（最多 4 期）；
  - 返回 `{code: {"industry", "ann_date"}}` 与命中的 `period`，按报告期缓存。
- `get_stock_basic()`：用快照把 `industry` 并入清单记录（不改变字段契约，仅新增键）。
- `get_financial_indicator()`：按行 `end_date` 匹配快照，回填 `ann_date`。
- 两者共用快照，因此只多一次网络往返（按报告期缓存）。

**边界：** 快照取数失败时 `get_stock_basic` 仍返回不含行业的基础清单、
`get_financial_indicator` 仍返回不含披露日的指标——**绝不让补全失败阻断主流程**，
只是对应限制项继续如实出现。BaoStock/Tushare 不实现该补全（接口不提供）。

## 任务

- [x] `reporting.py` + 单测（跨季末/年初边界）。
- [x] `AkshareDataSource._earnings_snapshot()`（缓存、回退、失败降级）。
- [x] `get_stock_basic` 并行业；`get_financial_indicator` 回填 `ann_date`。
- [x] 测试：夹具驱动断言行业并入与披露日回填；快照失败时降级不抛。
- [x] 联网验证：`data_quality` → `complete`；行业关键词候选命中（无需代表股）。
- [x] 文档：README 数据源节补记行业/披露日来源与口径。

## 验证证据

- [x] `python -m pytest -q`：**286 passed, 15 skipped**（新增 `test_reporting.py` 5 项、
      `test_akshare_earnings.py` 5 项）。
- [x] 联网实测 2026-09-12：
  - 单股 600519 → `data_quality == complete`、`restrictions == []`
    （实施前为 `warning` + `['fundamental_disclosure_date_missing']`）；
  - 披露日回填：2026-06-30 报告期 → `ann_date 2026-08-15`；
  - 行业并入：清单 5562 行中 5561 行含行业（600519 → `白酒Ⅱ`）；
  - 行业关键词候选（无需人工登记代表股）：`推荐几个白酒股` → 泸州老窖/古井贡酒、
    `推荐几个银行股` → 平安/兰州/宁波银行。
- [x] `RUN_NETWORK_TESTS=1 -m network tests/test_provider_smoke.py`：7 passed
      （新增披露日与行业断言）。
- [x] `RUN_NETWORK_TESTS=1 -m network tests/test_stock_analysis_e2e.py`：10 passed。

## 实施记录

- 新增 `finance_agent/data/reporting.py`：`latest_report_period` / `recent_report_periods`
  （纯函数，季末/年初边界已测）。
- `AkshareDataSource._earnings_snapshot()`：取最近报告期 `stock_yjbb_em`（空则向前回退，
  最多 4 期），按报告期缓存；**失败一律降级为空快照，不阻断主流程**。
- `get_stock_basic` 并入 `industry`；`get_financial_indicator` 按 `end_date` 匹配
  回填 `ann_date`。
- **连带修复：** `_candidate_keyword` 噪声词表缺"几个/只/支/龙头/股"等填充词，
  导致"推荐几个白酒股"整串无法作为子串命中行业；补齐后行业关键词匹配生效。

## 遗留（不在本次）

`stock_yjbb_em` 覆盖 1/5562 缺口（002731）——个股缺行业时按无行业处理；
东财 `stock_individual_info_em` 作为单股行业兜底未纳入（按报告期全市场表已足够）。
