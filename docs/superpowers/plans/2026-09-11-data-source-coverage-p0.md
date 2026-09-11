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
- Modify: `tests/conftest.py`（新增，计划外但必需）
- Create: `tests/test_quote_cache.py`

**Interfaces:**
- Produces: `quote_cache.read(namespace, key, ttl_seconds=None)` 与 `quote_cache.write(namespace, key, records, ttl_seconds=None)`；`AkshareDataSource.get_daily` 内部先读缓存、失败时退避重试。

- [x] **Step 1: 写入失败测试**

新建 `tests/test_quote_cache.py`，覆盖：主路径调用 `stock_zh_a_daily(symbol="sh600519", adjust="qfq")`；新浪失败时**重试 3 次后**回退东财；缺少新浪接口时**直接**回退（不浪费重试与退避）；相同请求第二次命中缓存且不再取数；缓存键区分复权口径与窗口；已废止北交所代码在任何请求之前失败；非法复权口径被拒；缓存往返、过期与缺失；numpy 标量可序列化；缓存目录不可用时只警告。

- [x] **Step 2: 验证测试按预期失败**

运行：`python -m pytest -q tests/test_quote_cache.py`

实际：首轮 10 个用例全部 ERROR——但**不是**预期的"模块不存在"，而是 `tmp_path` 写入系统临时目录被拒（`PermissionError: ...\pytest-of-jason`）。这是本次发现的第一个环境限制，见下方"环境发现"。

- [x] **Step 3: 实现**

1. `quote_cache.py`：JSON 落盘，键由调用方给出的元组哈希成文件名；`QUOTE_CACHE_TTL_SECONDS`（默认 3600）**为 0 或负数即关闭缓存**；读写异常一律只记 warning。
2. `config.py`：新增 `QUOTE_CACHE_DIR`（默认锚定**仓库根目录**的 `.cache/quotes`，而非相对路径 `.cache/quotes`——后者会随进程工作目录漂移）与 `QUOTE_CACHE_TTL_SECONDS`。两个键都被真实读取，不违反 D22。
3. `AkshareDataSource.get_daily`：`ensure_current_code()` 先行（已废止北交所代码在打网络前失败）→ 读缓存 → 新浪主路径 → 东财回退 → 写缓存 → 全失败抛 `ProviderUnavailableError`（而非返回空列表，让 `_call` 的降级语义明确）。
4. **偏差说明：** 原稿第 4 条写"仅对网络类异常重试"。实际实现为"只要没拿到有效记录就重试"，但**用 `getattr` 守卫把'接口不存在'排除在重试之外**——否则桩或旧版 AKShare 会白等 2 秒；空记录则视为失败，从而触发回退。两条取值序列共用 `_ADJUST_MAP`（`""`/`qfq`/`hfq`）。

- [x] **Step 4: 验证通过并提交**

运行：`python -m pytest -q tests/test_quote_cache.py`

实际结果：**10 passed**；全量 `python -m pytest -q` → **207 passed**（191 + 10，另有并行写入者的用例同时通过）。

```bash
git commit -m "fix: source daily bars from Sina with retry backoff and a disk cache"
```

**环境发现（记录以备后用）：**

1. `tmp_path` 在本环境**不可用**——pytest 的临时基目录创建即 `PermissionError`（系统临时目录不可写）。
2. `tempfile.mkdtemp()` 创建出的目录**无法在其下再建子目录**（`WinError 5`），而普通 `Path.mkdir()` 建的同级目录完全正常，两者 `st_mode` 都是 `0o777`。已复现，非权限位问题。

因此 `tests/conftest.py` 新增 autouse 夹具，把 `QUOTE_CACHE_DIR` 锚定到 `<repo>/.cache/test-quote-cache/case-<uuid>`，测试结束删除。**这个隔离是必需的**：夹具行情以"今天"结尾，若读到上次运行留下的缓存，新鲜度门禁会失效、测试结果随运行日期漂移。

### 任务 3：北交所代码处理（**已在任务 2 之前执行**）

**执行顺序说明：** 本任务原排在任务 2 之后，实际提前执行——任务 2 把 K 线切到新浪源必须构造 `sh600519`/`bj920799` 这类市场前缀，而这正是本任务的产物，先做任务 2 会导致同一份映射逻辑写两遍。

**Files:**
- Create: `finance_agent/data/board_codes.py`
- Modify: `finance_agent/data/baostock_provider.py`
- Create: `tests/test_board_codes.py`
- （`akshare_provider.py` 的符号接入随任务 2 的 `get_daily` 重写一并落地，避免同一个函数改两次）

**Interfaces:**
- Produces: `board_codes.market_of(code) -> "sh" | "sz" | "bj"`；`sina_symbol(code)`；`baostock_symbol(code)`；`ensure_current_code(code)`。

- [x] **Step 1: 写入失败测试**

断言：`market_of("830799") == "bj"`、`market_of("920799") == "bj"`、`market_of("600519") == "sh"`；`BaostockDataSource.get_daily("920799")` 抛出 `UnsupportedProviderCapability` 而**不是**返回 `[]`；`ensure_current_code("830799")` 抛出可操作的错误。

- [x] **Step 2: 验证测试按预期失败**

运行：`python -m pytest -q tests/test_board_codes.py`

实际：模块不存在而失败（本步骤的"预期失败"体现在 `_code("920799") → "sz.920799"` 这一既有静默空行为上，见 Step 3 的偏差说明）。

- [x] **Step 3: 实现**

1. `board_codes.py`：`43/83/87` 与 `92` 前缀 → `bj`；`6` → `sh`；其余 → `sz`。`normalize_code` 兼容 `600519` / `sh600519` / `sh.600519` / `600519.SH` 四种写法。
2. `baostock_symbol()`：`bj` 市场显式 `raise UnsupportedProviderCapability`；`sh`/`sz` 沿用 `sh.`/`sz.` 前缀。
3. `baostock_provider.py` 删除 `_code()`，改用 `baostock_symbol()`，并把**符号校验移到 `_login()` 之前**——北交所代码要在打网络之前就失败。
4. **偏差说明（推翻 D16 的一半）：原计划"43/83 → 920 重映射"经实测不可实现，已改为显式报错。** 依据：
   - 免费数据源中**不存在**旧→新代码对照表——`stock_info_bj_name_code()` 的 343 行 100% 是 `920` 前缀，东财 clist 同，新浪/BaoStock 根本不服务旧代码；
   - 唯一可行的启发式（取末三位）**已被证伪**：实测 `stock_info_bj_name_code()` 中 `920047` 的名称是**诺思兰德**，而 `920799` 是**另一家公司**；旧代码 `830799` 的名字正是诺思兰德（子代理经 `push2delay` 观测 `0.830799 → 诺思兰德`）。即末三位规则会把 `830799` 指到**错误的公司**上。
   - 因此 `ensure_current_code()` 对 `43/83/87` 前缀抛出含反例的可操作错误，要求用户更新代码表；**不做猜测映射**。猜测映射产生的是静默错数据，比报错危险得多。

- [x] **Step 4: 验证通过并提交**

运行：`python -m pytest -q tests/test_board_codes.py`

实际结果：**6 passed**；全量 `python -m pytest -q` → **191 passed**（185 + 6）。

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

- [x] **Step 1: 写入失败测试**

新建 `tests/test_akshare_valuation.py`（7 个用例）：TTM 与静态 PE 分离；估值**真的改变**基本面分数；窗口在适配器侧裁剪；命中缓存不重复取数；缺少 `stock_value_em` 时报能力缺口；取数失败报 `ProviderUnavailableError`；已废止北交所代码在任何请求前失败。

- [x] **Step 2: 验证测试按预期失败**

实际（**偏离说明**）：本任务的 Step 1 与 Step 3 被合并成一次编辑，因此**没有单独执行"先验证失败"**。首轮运行的失败是漏了 `normalize_valuation_records` 的 import（`NameError`），补齐后 7 passed。这是一次对仓库 TDD 惯例的偏离，记录在此以便复盘——任务 5 恢复了先红后绿。

- [x] **Step 3: 实现**

`get_daily_basic` 的 `raise` 替换为调用 `stock_value_em`。带括号的 PE 两列在适配器内显式映射（`PE(TTM) → pe_ttm`、`PE(静) → pe_lyr`），不进共享别名表；窗口用 `_within_window` 在客户端裁剪（该接口没有日期参数）；取数失败抛 `ProviderUnavailableError` 以便与能力缺口区分；结果写估值缓存。

**关键断言（本次缺口的根因）：** 测试用「含 PE/PB 的输入」与「去掉 PE/PB 的同样输入」两次调用 `build_scores`，断言分数**不相等**。仅断言"非空"是不够的——缺 PE/PB 时分数同样非空，只是由 3 个会计指标各占 1/3 平均而成，**口径被静默换掉**。

- [x] **Step 4: 验证通过并提交**

实际结果：**7 passed**；全量 `python -m pytest -q` → **213 passed**。

```bash
git commit -m "feat: source daily valuation from AKShare stock_value_em"
```

### 任务 5：BaoStock 日估值取数

**Files:**
- Modify: `finance_agent/data/baostock_provider.py`
- Create: `tests/test_baostock_valuation.py`

**Interfaces:**
- Produces: `BaostockDataSource.get_daily_basic` 返回含 `pe_ttm`/`pb`/`ps_ttm` 的规范记录（免 token 的第二路）。

- [x] **Step 1: 写入失败测试**

新建 `tests/test_baostock_valuation.py`（6 个用例）：规范键映射；请求固定 `frequency="d"` 与 `adjustflag="3"`；空串估值行被剔除；全空时报 `ProviderUnavailableError`；命中缓存不重复取数；北交所在估值路径同样被拒。

- [x] **Step 2: 验证测试按预期失败**

实际：首轮 1 failed, 5 passed——`assert '18.0' == 18.0`。这个失败**暴露了一个真实缺陷**：BaoStock 的 socket 协议把所有字段返回为**字符串**，而 AKShare 返回 float。见 Step 3 的第 2 条修正。

- [x] **Step 3: 实现**

1. `get_daily_basic` 的 `raise` 替换为 `query_history_k_data_plus(symbol, "date,peTTM,pbMRQ,psTTM,pcfNcfTTM", frequency="d", adjustflag="3")`。估值字段与行情可在同一次请求返回，但这里只取估值以保持能力边界一致。
2. **新增 `_coerce_valuation()`：在适配器出口把估值字段强转为 float。** 理由是同一能力在不同 provider 之间形状不一致会直接泄漏到报价契约（`quote["pe"]` 变成字符串）。
3. **新增 `_has_valuation()` 过滤：剔除估值字段全为空串的行。** BaoStock 在停牌/无数据日返回空串，不过滤则 `_latest_daily_record` 取到的"最新一根"没有估值，表面上仍像"估值缺失"。

- [x] **Step 4: 验证通过并提交**

实际结果：**6 passed**；全量 `python -m pytest -q` → **220 passed**。

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

- [x] **Step 1: 写入失败测试**

1. `scoring.py`：仅缺 PE/PB 时 `score_restrictions` 含 `fundamental_missing:pe_ttm` 与 `fundamental_missing:pb`，且 `fundamental_score` 不为 `None`、质量状态不是 `critical_missing`。
2. `provider_manager.py`：首个 provider 抛 `UnsupportedProviderCapability` 时 `last_metadata["degraded"] is False`、`"unsupported"` 含该 provider 名、`failures` 为空；并另加一条"真实故障仍然置 `degraded`"的反向断言。

- [x] **Step 2: 验证测试按预期失败**

与本任务合并执行（见 Step 3 的实际改动）。

- [x] **Step 3: 实现**

1. `scoring.py`：把五个基本面输入收集为 `fundamental_inputs`，逐字段生成 `fundamental_missing:<name>`；五项**全缺**时仍只报 `fundamental_metrics`（向后兼容）。PE 槽位按"完全取不到 PE"判定——只有静态 PE 的情况由质量门禁的 `valuation_not_ttm` 负责，评分层不重复报警。
2. `provider_manager._call`：新增 `unsupported` 列表，`except UnsupportedProviderCapability` 单独分支（DEBUG 级日志），`degraded` 只看真实失败。`last_metadata` 新增 `unsupported` 键（全局约束允许）。
3. **计划外但必需的两处一致性修复：**
   - `quality_gates.valuation_basis` 只认 `pe_ttm`/`pe`，因此**只有静态 PE 的数据源会被误判成"完全没有估值"**；已让它识别 `pe_lyr`。
   - `narrative.py` 会翻译原因码，逐字段码会被原样渲染成 `fundamental_missing:pe_ttm`；已补中文标签映射（该模块自身契约要求原因码可读）。

- [x] **Step 4: 验证通过并提交**

实际结果：**7 条新测试**；全量 `python -m pytest -q` → **224 passed**。

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

- [x] **Step 1: 写入失败测试**

1. 快照 payload 的 `provenance.quote.source` 等于桩 provider 的 `provider_name`，且与 `FactSnapshot.source` 一致。
2. `load_rules("research_rules/v1")` 仍然可加载（旧审计可重放），`load_rules()` 返回**新**版本，且两个版本的规则内容除 `version` 外完全相同。

- [x] **Step 2: 验证测试按预期失败**

与本任务合并执行。

- [x] **Step 3: 实现**

**偏差说明（一半的活已经干完了）：** 侦察发现 `payload["provenance"]["quote"]["source"]` 与 `FactSnapshot.source` **已经**由 P1-P2 落地，因此"落 source"这半只需补回归断言，不需要新增管线。真正的改动是版本：

1. **新增** `rules/v1.1.json`（内容与 `v1.json` 完全相同，仅 `version` 不同）。**不替换 v1**：`replay.py` 按审计记录里的版本号精确加载，旧记录必须一直可重放。
2. `rule_engine.py` 新增 `CURRENT_RULES_VERSION` 常量与 `_RULE_FILES` 的第二条目。
3. **把重复三处的默认版本收敛为单一真源**：此前默认值分别声明在 `load_rules` 的参数、`refresh.py` 的服务默认值、`snapshot_builder.py` 的常量里，容易漂移；现在后两者都引用 `CURRENT_RULES_VERSION`。
4. **不改** `theme_repository.py` 的快照主键（D13）。
5. 更新 4 处断言默认版本的测试（`test_research_rule_engine.py`、`test_research_pipeline.py`、`test_research_golden.py`、`test_research_refresh.py`）。测试里用字面量而不是常量，是为了把行为钉住。

- [x] **Step 4: 验证通过并提交**

实际结果：**2 条新测试**；全量 `python -m pytest -q` → **226 passed**。金标夹具（`test_research_golden.py`）分数未变，证明本次改动没有意外改变已有输入的评分。

```bash
git commit -m "chore: add rule version v1.1 and single-source the default version"
```

### 任务 8：回归、联网冒烟与文档收尾

**Files:**
- Create: `tests/test_provider_smoke.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-09-11-stock-analysis-p0.md`

**Interfaces:**
- Produces: 默认跳过的联网冒烟测试；更新后的数据源文档。

- [x] **Step 1: 写入联网冒烟测试**

新建 `tests/test_provider_smoke.py`（4 个用例，默认跳过，`RUN_NETWORK_TESTS=1` 且 `-m network` 启用）：AKShare 前复权 K 线可达且升序；AKShare 日估值含 `pe_ttm`/`pb` 且 `pe_lyr` 键存在；BaoStock 估值与 AKShare **数量级一致（5% 内）**；北交所被 BaoStock 显式拒绝、由 AKShare 正常服务。同时在 `pyproject.toml` 注册 `network` 标记。

- [x] **Step 2: 更新 README 的数据源章节**

新增「股票数据源」小节与 `DATA_PROVIDER_ORDER`/`AKSHARE_ENABLED`/`TUSHARE_ENABLED`/`BAOSTOCK_ENABLED`/`QUOTE_CACHE_*` 环境变量（此前这些键在 README 里**完全没有**）。记录：AKShare 走新浪源、东财接口被按 URL 过滤只作回退；腾讯源不参与前复权；前复权基准为新浪/BaoStock 且跨源比对用收益率；三条估值来源及各自限制（东财起点 2018、BaoStock 无北交所、Tushare 才提供股息率）；BaoStock 的北交所与已废止代码行为；缓存位置与 TTL；规则版本 v1.1 及其原因；以及**仅限个人研究、不得再分发**的使用限制（D7）。

- [x] **Step 3: 修正 p0 文档中的过期结论**

改写 `2026-09-11-stock-analysis-p0.md:169` 的「已知遗留」：标注"AKShare 不提供日估值接口"**已作废**并说明原因是引用的接口被删除，指向本次的事实核查文档；并注明该文件 `:149` 的 Step 7 提交清单已过期（`snapshot_builder.py` 依赖同批次新增的 `quality_gates.py`，按原清单提交会得到无法导入的模块），该批次已随 `437235e` 入库。

- [x] **Step 4: 全量验证并提交**

实际结果：
- 默认全量：**226 passed, 4 skipped**（联网用例正确跳过）。
- 显式启用联网：`RUN_NETWORK_TESTS=1 pytest -q -m network tests/test_provider_smoke.py` → **4 passed**（17.7s）。这是本次唯一的端到端证据：两条估值路径实测互校一致，北交所路由实测正确。

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
