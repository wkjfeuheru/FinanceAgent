# 数据源覆盖修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让日估值（PE/PB）与前复权 K 线在生产配置下真实可得，并让"取不到"变得可观测，同时不引入任何新的商业数据供应商。

**Architecture:** 沿用既有 `StockDataProvider` 鸭子类型契约与 `ProviderManager` 按方法降级的路由，不新增抽象层。改动集中在三处：适配器出口的字段归一化（混合方案：非歧义列进共享别名表，歧义列由适配器显式映射）、K 线与估值的取源选择、`_call` 对"未声明能力"与"调用失败"的区分。

**Tech Stack:** Python 3.10+、pandas、AKShare 1.18.94（可选依赖）、BaoStock（可选依赖）、pytest。

**前置：** 本计划基于提交 `437235e`（互咬基线快照）。基线验证：全量 `pytest -q` → **182 passed**。

## 全局约束

- 不改动 `StockDataProvider` 协议、`ProviderManager` 的公开方法与 `last_metadata` 的既有键；`unsupported` 为新增键。
- 适配器仍在出口调用 `normalize_*`；不把 AKShare/BaoStock 的估值列全部塞进共享别名表。
- 评分函数不得访问网络、调用模型或保存状态（沿用 P0 全局约束）。
- 不引入腾讯源 `stock_zh_a_hist_tx` 进任何降级链。
- 不新增任何 iTick 相关的配置键、适配器或环境变量。
- 每个任务的实现前先写失败测试，实现后跑该任务的验证命令。

## 决策与假设

本计划的每一项都来自一次实测驱动的评审，决策编号沿用评审记录。

| # | 决策 |
|---|---|
| D1 | 前提「AKShare 不提供日估值接口」被推翻：该结论引用的 `stock_a_indicator_lg` 已从 AKShare 1.18.94 删除；改用 `stock_value_em`。 |
| D2 | 前提「Tushare 拒绝 forward」是 `tushare_mcp.py:227-230` 的自设 raise，非供应商限制。 |
| D3 | 前提「AKShare K 线可用」在本环境不成立：`stock_zh_a_hist` 被网络边缘按 URL 过滤，客户端无解。 |
| D4 | 不引入 iTick 或任何新供应商；iTick 降级为候选，触发条件见 spec 末节。 |
| D5 | 若将来接入 iTick，角色限定为定向补丁源：仅声明 `get_daily(forward)` 与 `get_daily_basic`，其余方法继续 `raise UnsupportedProviderCapability`。 |
| D6 | 基准口径 = 新浪 / BaoStock；交叉验证比对区间收益率，不比绝对价格。 |
| D7 | 仅个人研究用途 + 本地缓存；不进对外分发或开源示例的默认配置，文档注明数据来源与使用限制。 |
| D8 | 股息率（`dv_ratio`/`dv_ttm`）不是硬需求，因此不为它引入供应商，也不为它充 Tushare 积分。 |
| D9 | `pe_ttm` 是唯一评分输入；静态 PE 映射为 `pe_lyr` 且不参与评分。 |
| D10 | 接受估值历史起点为 `max(2018-01-02, 上市日)`，不做双源拼接。 |
| D11 | 归一化采用混合方案：非歧义列进别名表，PE 两列由适配器显式映射。 |
| D12 | 缺失 PE/PB **逐字段**记入 `score_restrictions`，但不得升级为 `critical_missing`。 |
| D13 | bump `rule_version` 并把 `last_metadata.source` 落进 payload；**不**给快照主键加 provider 维度。 |
| D14 | 网络型 provider 用「构造真实适配器后替换内部句柄」的桩（`provider.bs = StubBaostock()`），另加一个默认跳过的联网冒烟测试。 |
| D15 | K 线主路径 → `stock_zh_a_daily`；`stock_zh_a_hist` 降为该适配器内回退；腾讯源不用。 |
| D16 | 北交所进范围：`_code()` 对 BJ 前缀显式报错；`43`/`83` → `920` 重映射。 |
| D17 | 加最小落盘缓存（键 `provider, code, adjust, start, end`）+ 退避，只覆盖 K 线与估值。 |
| D18 | `_call` 把「未声明能力」记入独立的 `unsupported`，不参与 `degraded`。 |
| D19 | `get_income` 归一化、AKShare `get_trade_cal` 不在本次范围。 |
| D20 | 执行顺序：归一化接缝与 PE 口径 → K 线换源与缓存 → 北交所 → AKShare 估值 → BaoStock 估值 → 限制项与可观测性 → 规则版本 → 回归收尾。 |
| D21 | 本次开工前先提交互咬基线 `437235e`（已完成），并在其中停止跟踪 `frontend/tsconfig.tsbuildinfo`。 |
| D22 | 不再新增声明了却从不被读取的配置键（现有死配置见 spec「已知遗留与死配置」）。 |

## 实施任务

### 任务 1：归一化混合接缝与 PE 口径统一

**Files:**
- Modify: `finance_agent/data/normalization.py`
- Modify: `finance_agent/data/akshare_provider.py`
- Modify: `finance_agent/data/baostock_provider.py`
- Modify: `finance_agent/orchestrator/tools/stockdata.py`
- Modify: `finance_agent/research/scoring.py`
- Modify: `tests/test_data_normalization.py`

**Interfaces:**
- Consumes: 各适配器的厂商原生列名。
- Produces: 规范估值键 `pe_ttm`、`pe_lyr`、`pb`、`ps`、`ps_ttm`、`total_mv`、`circ_mv`、`trade_date`。

- [x] **Step 1: 写入失败测试**

在 `tests/test_data_normalization.py` 增加三组断言。**执行更正：** 本步骤原稿要求把 `{"数据日期", "PE(TTM)", "PE(静)", "市净率"}` 直接送入 `normalize_valuation_records` 并期望得到 `pe_ttm`/`pe_lyr`，这与决策 D11（PE 两列由适配器显式映射、不进别名表）自相矛盾。已按 D11 修正为：

1. `{"trade_date": ..., "pe_ttm": 18.0}` → 输出含 `pe_ttm` 且**不含** `pe`；同时给出 `pe` 与 `pe_ttm` 时两者各自保留（证明 `pe` 不再以 `pe_ttm` 兜底）。
2. 东财 `{"数据日期", "市净率", "总市值", "流通市值"}` 与 BaoStock `{"date", "peTTM", "pbMRQ", "psTTM"}` 均命中统一键。
3. `pe_lyr` 可携带静态 PE 但 `build_scores` 不采信：只给 `pe_lyr` 时 `fundamental_score is None`，给 `pe_lyr + pb` 时等于 `_pb_score(2.0) == 75.0`。

带括号的 `PE(TTM)`/`PE(静)` 由 `AkshareDataSource` 的估值出口显式映射（落地于任务 4），不在本任务的测试范围内。

- [x] **Step 2: 验证测试按预期失败**

运行：`python -m pytest -q tests/test_data_normalization.py -k "never_conflated or columns_are_unified or static_pe_is_carried"`

实际结果：2 failed, 1 passed——`pe` 仍被 `pe_ttm` 兜底（`assert 'pe' not in {...}` 失败），`数据日期` 未命中（`KeyError: 'trade_date'`）；第三条本已通过，因为 `pe_lyr` 作为未识别键会被原样保留，它断言的是评分侧不采信。

- [x] **Step 3: 实现**

实际改动（`normalization.py:36-53`、`stockdata.py:98`）：

1. `VALUATION_ALIASES["pe"]` 摘除 `pe_ttm`，改为 `("pe", "市盈率")`；`pe_ttm` 保留 `pe` 作为"厂商原生 pe 即 TTM"的兜底。
2. 新增规范键 `pe_lyr`（仅声明自身），并在表头注释中写明它是静态 PE、不参与评分。
3. 补非歧义别名：`trade_date += ("数据日期",)`、`pe_ttm += ("peTTM",)`、`pb += ("pbMRQ",)`、`ps_ttm += ("psTTM",)`（`市净率`/`总市值`/`流通市值` 原本已在表中）。
4. `stockdata.py` 的 `pe` 优先级改为 `_first_value(valuation, "pe_ttm", "pe")`，与 `scoring.py:147` 一致；**未改动** `scoring.py:147`（其 `pe` 兜底语义与 D9 的"厂商原生 pe 即 TTM"一致）。
5. **偏差说明：** 原稿第 3、4 条要求 AKShare/BaoStock 适配器出口做显式列改名。实施后 AKShare 的部分**后移到任务 4**（其 `get_daily_basic` 在任务 4 才存在，提前加映射助手会成为死代码）；BaoStock 的部分**改为走别名表**（`peTTM`/`pbMRQ`/`psTTM` 是大小写明确的非歧义标签，放进共享表更省代码且已被测试覆盖）。

- [x] **Step 4: 验证通过并提交**

运行：`python -m pytest -q tests/test_data_normalization.py tests/test_research_snapshot_builder.py`

实际结果：通过；全量 `python -m pytest -q` → **185 passed**（基线 182 + 3 条新增）。

```bash
git add finance_agent/data/normalization.py finance_agent/data/akshare_provider.py \
        finance_agent/data/baostock_provider.py finance_agent/orchestrator/tools/stockdata.py \
        finance_agent/research/scoring.py tests/test_data_normalization.py
git commit -m "refactor: unify valuation field mapping and pin pe_ttm as the scored input"
```

### 任务 2：K 线取源切换与最小缓存退避

**Files:**
- Modify: `finance_agent/data/akshare_provider.py`
- Create: `finance_agent/data/quote_cache.py`
- Modify: `finance_agent/config.py`
- Create: `tests/test_quote_cache.py`
- Modify: `tests/test_data_normalization.py`

**Interfaces:**
- Produces: `quote_cache.read(namespace, key) -> list[dict] | None` 与 `quote_cache.write(namespace, key, records, ttl_seconds)`；`AkshareDataSource.get_daily` 内部先读缓存、失败时退避重试。

- [ ] **Step 1: 写入失败测试**

用桩替换 `ak.stock_zh_a_daily` 与 `ak.stock_zh_a_hist`，断言：正常路径调用 `stock_zh_a_daily(symbol="sh600519", adjust="qfq")`；`stock_zh_a_daily` 抛错时回退到 `stock_zh_a_hist`；两次相同请求第二次命中缓存且不再调用桩。

- [ ] **Step 2: 验证测试按预期失败**

运行：`python -m pytest -q tests/test_quote_cache.py`

预期：失败，`quote_cache` 尚不存在。

- [ ] **Step 3: 实现**

1. 新建 `quote_cache.py`：落盘目录由 `config.py` 的 `QUOTE_CACHE_DIR`（默认 `.cache/quotes`）与 `QUOTE_CACHE_TTL_SECONDS`（默认 3600）控制；键为 `(provider, code, adjust, start, end)` 的哈希；`read` 过期返回 `None`。
2. `AkshareDataSource.get_daily` 的符号转换：`6`/`68` → `sh`，`0`/`3` → `sz`，`43/83/87/92/920` → `bj`（北交所细节见任务 3）。
3. 主调用改为 `ak.stock_zh_a_daily(symbol=..., start_date=..., end_date=..., adjust=...)`，`adjust` 直接使用 `""`/`qfq`/`hfq`（不再走东财的 `adjust` 映射）；异常时回退 `stock_zh_a_hist` 的现有实现。
4. 退避：最多 3 次尝试，间隔 0.5s/1.5s，仅对网络类异常重试。
5. 结果写缓存；`normalize_daily_records` 仍在出口调用。

- [ ] **Step 4: 验证通过并提交**

运行：`python -m pytest -q tests/test_quote_cache.py tests/test_data_normalization.py tests/test_provider_manager.py`

```bash
git commit -m "fix: source daily bars from Sina with cache and backoff"
```

### 任务 3：北交所代码处理

**Files:**
- Modify: `finance_agent/data/baostock_provider.py`
- Create: `finance_agent/data/board_codes.py`
- Modify: `finance_agent/data/akshare_provider.py`
- Create: `tests/test_board_codes.py`

**Interfaces:**
- Produces: `board_codes.market_of(code) -> "sh" | "sz" | "bj"`；`board_codes.normalize_bj(code) -> str`（43/83 → 920 重映射）。

- [ ] **Step 1: 写入失败测试**

断言：`market_of("830799") == "bj"`、`market_of("920799") == "bj"`、`market_of("600519") == "sh"`；`BaostockDataSource.get_daily("920799")` 抛出 `UnsupportedProviderCapability` 而**不是**返回 `[]`。

- [ ] **Step 2: 验证测试按预期失败**

运行：`python -m pytest -q tests/test_board_codes.py`

预期：失败，`board_codes` 不存在；且当前 `_code("920799")` 返回 `sz.920799`（静默空）。

- [ ] **Step 3: 实现**

1. `board_codes.py`：`43/83/87/92/920` 前缀 → `bj`；`6`/`68` → `sh`；`0`/`3` → `sz`。
2. 43/83 前缀的重映射用 `ak.stock_info_bj_name_code()`（343 行、100% `920` 前缀）构建一次进程内映射，失败时降级为原值并记 warning。
3. `baostock_provider.py:20-25` 的 `_code()` 改为：`bj` 市场直接 `raise UnsupportedProviderCapability("BaoStock 不支持北交所")`；`sh`/`sz` 沿用 `sh.`/`sz.` 前缀。
4. `akshare_provider.py` 生成 `bj920xxx` 格式符号。

- [ ] **Step 4: 验证通过并提交**

运行：`python -m pytest -q tests/test_board_codes.py tests/test_provider_manager.py`

```bash
git commit -m "fix: route Beijing exchange codes explicitly and never silently empty"
```

### 任务 4：AKShare 日估值取数

**Files:**
- Modify: `finance_agent/data/akshare_provider.py`
- Create: `tests/test_akshare_valuation.py`

**Interfaces:**
- Consumes: `ak.stock_value_em(symbol)`。
- Produces: `AkshareDataSource.get_daily_basic` 返回规范估值记录（`trade_date` 升序）。

- [ ] **Step 1: 写入失败测试**

用桩让 `provider.ak.stock_value_em` 返回带真实列名（`数据日期`/`PE(TTM)`/`PE(静)`/`市净率`/`市销率`/`总市值`/`流通市值`）的 DataFrame，断言：`get_daily_basic("600519")` 不再抛 `UnsupportedProviderCapability`，且首条记录含 `pe_ttm` 与 `pb`。

**关键断言（本次缺口的根因）：** 把该记录送入 `build_scores`，断言 `pe`、`pb` 两个子分**确实参与**了基本面均值——用「含 PE/PB 的输入」与「去掉 PE/PB 的同样输入」两次调用的分数**不相等**来证明。

- [ ] **Step 2: 验证测试按预期失败**

运行：`python -m pytest -q tests/test_akshare_valuation.py`

预期：失败于 `UnsupportedProviderCapability`。

- [ ] **Step 3: 实现**

`akshare_provider.py:79-81` 的 `raise` 替换为调用 `stock_value_em`，按任务 1 的映射产出规范键，出口调用 `normalize_valuation_records`。网络异常时抛 `ProviderUnavailableError`（而非 `UnsupportedProviderCapability`），以便 `_call` 语义正确。

- [ ] **Step 4: 验证通过并提交**

运行：`python -m pytest -q tests/test_akshare_valuation.py tests/test_data_normalization.py tests/test_research_snapshot_builder.py`

```bash
git commit -m "feat: source daily valuation from AKShare stock_value_em"
```

### 任务 5：BaoStock 日估值取数

**Files:**
- Modify: `finance_agent/data/baostock_provider.py`
- Create: `tests/test_baostock_valuation.py`

**Interfaces:**
- Produces: `BaostockDataSource.get_daily_basic` 返回含 `pe_ttm`/`pb`/`ps_ttm` 的规范记录（免 token 的第二路）。

- [ ] **Step 1: 写入失败测试**

按仓库既有风格构造真实适配器再替换内部句柄（`provider.bs = StubBaostock()`，对应 `tests/test_data_normalization.py:125-135` 的 `provider.ak = StubAkshare()`），桩返回 `peTTM/pbMRQ/psTTM` 列，断言出口含 `pe_ttm`/`pb`/`ps_ttm`。

- [ ] **Step 2: 验证测试按预期失败**

运行：`python -m pytest -q tests/test_baostock_valuation.py`

预期：失败于 `UnsupportedProviderCapability("BaoStock 不支持统一日估值接口")`。

- [ ] **Step 3: 实现**

`baostock_provider.py:98-100` 的 `raise` 替换为 `query_history_k_data_plus(code, "date,peTTM,pbMRQ,psTTM,pcfNcfTTM", frequency="d", adjustflag="3")`。**注意：估值字段在 `3/2/1` 三种口径下数值完全相同（实测），且 `frequency` 只能是 `d`**——周线/月线带估值字段会被服务端以 `10004012` 拒绝。出口调用 `normalize_valuation_records`。

- [ ] **Step 4: 验证通过并提交**

运行：`python -m pytest -q tests/test_baostock_valuation.py`

```bash
git commit -m "feat: source daily valuation from BaoStock without a token"
```

### 任务 6：限制项逐字段记录与能力缺口可观测性

**Files:**
- Modify: `finance_agent/research/scoring.py`
- Modify: `finance_agent/data/provider_manager.py`
- Modify: `tests/test_research_snapshot_builder.py`
- Modify: `tests/test_provider_manager.py`

**Interfaces:**
- Produces: `score_restrictions` 含逐字段项（如 `fundamental_missing:pe_ttm`）；`last_metadata` 新增 `unsupported` 列表。

- [ ] **Step 1: 写入失败测试**

1. `scoring.py`：仅缺 PE/PB 时 `score_restrictions` 含 `pe_ttm` 与 `pb` 的逐字段项，且 `fundamental_score` 不为 `None`。
2. `provider_manager.py`：首个 provider 抛 `UnsupportedProviderCapability` 时，`last_metadata["degraded"] is False` 且 `"unsupported"` 含该 provider 名。

- [ ] **Step 2: 验证测试按预期失败**

运行：`python -m pytest -q tests/test_research_snapshot_builder.py tests/test_provider_manager.py -k "restriction or unsupported"`

- [ ] **Step 3: 实现**

1. `scoring.py:149-160`：收集缺失项到限制列表，仅当五项**全缺**时保留既有 `fundamental_metrics`（向后兼容），否则追加逐字段项。PE/PB 缺失**不得**升级为 `critical_missing`。
2. `provider_manager.py:73`：`except UnsupportedProviderCapability` 分支记入 `unsupported`，`degraded` 只在真实失败时置 `True`。

- [ ] **Step 4: 验证通过并提交**

运行：`python -m pytest -q tests/test_research_snapshot_builder.py tests/test_provider_manager.py tests/test_research_rule_engine.py`

```bash
git commit -m "feat: record per-field score restrictions and separate unsupported from failure"
```

### 任务 7：规则版本递增与来源溯源

**Files:**
- Modify: `finance_agent/research/rules/v1.json`
- Modify: `finance_agent/research/snapshot_builder.py`
- Modify: `tests/test_research_snapshot_builder.py`

**Interfaces:**
- Produces: 新的 `rule_version`；快照 payload 含 `quote.source`。

- [ ] **Step 1: 写入失败测试**

断言快照 payload 的 `quote.source` 等于桩 provider 的 `provider_name`；断言 `rule_version` 已递增（不等于旧值）。

- [ ] **Step 2: 验证测试按预期失败**

运行：`python -m pytest -q tests/test_research_snapshot_builder.py -k "source or version"`

- [ ] **Step 3: 实现**

bump `rules/v1.json` 的 `rule_version`（因为补上 PE/PB 会改变分数口径），并在 `snapshot_builder.py` 落 `last_metadata["source"]`。**不改** `theme_repository.py` 的快照主键。

- [ ] **Step 4: 验证通过并提交**

运行：`python -m pytest -q tests/test_research_snapshot_builder.py tests/test_research_golden.py tests/test_research_refresh.py`

```bash
git commit -m "chore: bump rule version and persist quote provenance"
```

### 任务 8：回归、联网冒烟与文档收尾

**Files:**
- Create: `tests/test_provider_smoke.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-09-11-stock-analysis-p0.md`

**Interfaces:**
- Produces: 默认跳过的联网冒烟测试；更新后的数据源文档。

- [ ] **Step 1: 写入联网冒烟测试**

`pytest.mark.skipif` 在缺少 `RUN_NETWORK_TESTS=1` 时跳过；断言 `AkshareDataSource.get_daily("600519", adjustment="forward")` 返回 ≥200 行且按日期升序，`get_daily_basic("600519")` 含 `pe_ttm`。标记为网络测试，不进默认 CI。

- [ ] **Step 2: 更新 README 的数据源章节**

记录：默认顺序仍为 `akshare,tushare_mcp,baostock`；AKShare 路径使用新浪源；BaoStock 不支持北交所；估值起点为 `max(2018-01-02, 上市日)`；腾讯源不用于前复权；仅个人研究用途与本地缓存，并注明数据来源与使用限制。同时把 `DATA_PROVIDER_ORDER`、`AKSHARE_ENABLED`、`TUSHARE_ENABLED`、`BAOSTOCK_ENABLED` 补进 README 的环境变量示例块（当前缺失）。

- [ ] **Step 3: 修正 p0 文档中的过期结论**

改写 `docs/superpowers/plans/2026-09-11-stock-analysis-p0.md:169` 的「已知遗留」：把"AKShare 仍不提供日估值接口"改为指向本计划与 spec 的事实核查结论，并注明该结论曾引用的 `stock_a_indicator_lg` 已从 AKShare 1.18.94 删除。同时标注 `:146-151` 的 Step 7 提交清单已过期（`snapshot_builder.py` 依赖 `quality_gates.py`，按原清单提交会得到无法导入的模块），该批次已由 `437235e` 一并入库。

- [ ] **Step 4: 全量验证并提交**

运行：`python -m pytest -q`

预期：全部通过（基线 182 passed，加上本次新增测试）。

```bash
git commit -m "test: add opt-in network smoke test and refresh data source docs"
```

## 边界情况

- **AKShare 未安装**：`ProviderManager._build_providers` 已捕获 `ImportError`，但仅在 INFO 级记录——静默降级。若 AKShare 缺席，估值仍可由 BaoStock 提供。
- **BaoStock 与 AKShare 都缺席**：`get_daily_basic` 抛 `ProviderUnavailableError`，`stockdata.py:79-84` 的 best-effort 语义保证行情不受连累。
- **北交所股票**：不会路由到 BaoStock；若 AKShare 也失败，得到显式的 `ProviderUnavailableError` 而不是空数据。
- **`stock_value_em` 对已废止的 43/83 代码返回空**：重映射后应命中 `920` 代码；若重映射表构建失败，降级为原值并记 warning。
- **新浪源封 IP**：退避 3 次仍失败时抛 `ProviderUnavailableError`，由 `_call` 继续降级到 BaoStock。
- **缓存目录不可写**：`quote_cache.write` 失败只记 warning，不影响取数。

## 验证证据

- 基线：`437235e`，全量 `pytest -q` → 182 passed（2026-09-11）。
- 本机实测（AKShare 1.18.94 / BaoStock / tushare 1.4.29）：
  - `stock_value_em("600519")` → 2111 行 × 13 列，0.6s；`("000651")` → 2111 行，0.4s。
  - `stock_zh_a_daily("sh600519", adjust="qfq")` → 242 行 / 2024 全年 / 0.74s；全历史 6003 行（2001-08-27 起）。
  - `stock_zh_a_daily("bj920799", adjust="qfq")` → 242 行，1979 行全历史（2015-03-10 起）。
  - `stock_zh_a_hist` → 4/4 `RemoteDisconnected`；25 个镜像域名、`:80`/`:443`、浏览器 header 全部同样失败；同主机 `trends2/get` 与 `clist/get` 正常。
  - BaoStock `adjustflag=3/2/1` 下 `peTTM` 数值完全一致且非空；`frequency="w"` → `10004012`。
  - qfq 跨源差异：腾讯 1444.42 / 新浪 1435.70 / BaoStock 1435.704012（600519，2024-12-31）。
- 未验证（不得当作已知）：Tushare 的联网调用（本机无 token）、iTick 的 A 股覆盖与基本面接口形态、BaoStock 官网文档（站点现返回 SPA shell，实测数据与文档措辞不一致时以实测为准）。

## 遗留决策与已知限制

- 股息率在免费源中不可得；若将来成为硬需求，需在「充 Tushare 2000 积分」与「放弃字段」之间选择，不引入新供应商。
- `get_income` 归一化、AKShare `get_trade_cal` 仍不在范围内。
- 腾讯源 qfq 口径差异仅通过"不进降级链"规避，未做换算归一。
- 估值历史起点受 `max(2018-01-02, 上市日)` 限制；需要更早历史时须另立需求。
- iTick 触发条件与"不留占位物"约定见 spec 末节。
- 本次不解决 `TushareMcpDataSource`/`BaostockDataSource` 缺少集成测试的更大范围问题（任务 5、8 只覆盖新写的估值路径）。
