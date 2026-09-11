# 数据源覆盖的事实核查与设计

## 目标

用实测替换仓库内两条来源不明、已过期且经核实为**错误**的"数据覆盖限制"结论，并据此补齐日估值（PE/PB）与前复权 K 线的免费取数路径。不引入新的商业数据供应商。

## 范围与非目标

**覆盖：**

- `finance_agent/data/` 三个适配器与 `normalization.py` 的字段归一化接缝。
- `data/provider_manager.py` 的能力缺口与失败的可观测性区分。
- `orchestrator/tools/stockdata.py` 的估值取数与 PE 优先级。
- `research/scoring.py` 的限制项记录粒度。
- `research/rules/v1.json` 的规则版本递增。

**非目标：**

- `get_income` 的厂商原生字段归一化（研究路径未消费）。
- AKShare 的 `get_trade_cal`（当前无消费方）。
- 股息率（`dv_ratio`/`dv_ttm`）字段本身。
- K 线全量缓存框架、批量抓取调度。
- 前端呈现、主题发现改动、管理员审核与审计重放。
- iTick 或任何新数据源的接入（见末节决策记录）。

## 事实核查结论：被推翻的三个前提

本次讨论的起因是 `docs/superpowers/plans/2026-09-11-stock-analysis-p0.md:169` 的两句话。逐条实测后，三个前提都不成立。

### 前提一「AKShare 不提供日估值接口」——错误

该结论引用的接口 `ak.stock_a_indicator_lg` 在 **AKShare 1.18.94 中已被删除**：全树正则扫描无 `def stock_a_indicator_lg`，仅在 `akshare/__init__.py:2760` 残留一行 changelog（`1.13.47 fix: fix stock_a_indicator_lg interface`）。原模块 `akshare/stock_feature/stock_a_indicator.py` 现在只剩 `get_cookie_csrf`、`get_token_lg`、`stock_hk_indicator_eniu`。

实际可用的是 `ak.stock_value_em(symbol)`：

```
实测（本机，2026-09-11）：
  stock_value_em("600519") → 2111 行 × 13 列，0.6s
  stock_value_em("000651") → 2111 行 × 13 列，0.4s
  列：数据日期 / 当日收盘价 / 当日涨跌幅 / 总市值 / 流通市值 / 总股本 /
      流通股本 / PE(TTM) / PE(静) / 市净率 / PEG值 / 市现率 / 市销率
  起点 = max(2018-01-02, 上市日)：600519/000001 → 2018-01-02
                              300750 → 2018-06-11
                              688981 → 2020-07-16
                              920799 → 2020-07-27
  6 次突发调用 6/6 成功，无 429
```

另有 `ak.stock_zh_valuation_baidu(symbol, indicator, period)` 可取 PE/PB 历史，但单次只返回一个指标（`['date','value']`），且实测出现过一次 `SSLEOFError`，仅作次选。

**唯一真正缺失的字段是股息率**：`stock_a_indicator_lg` 被删除后，AKShare 已无任何按股票代码返回 `dv_ratio`/`dv_ttm` 的接口（`stock_hk_indicator_eniu` 只覆盖港股）。唯一供给方是 Tushare `daily_basic`（官方文档：≥2000 积分可调，5000 积分无总量限制，单次最多 6000 行）。**本次已确认股息率不是硬需求，因此不为此引入任何供应商。**

### 前提二「Tushare 拒绝 adjustment="forward"」——项目自设限制

`finance_agent/data/tushare_mcp.py:227-230`：

```python
if adjustment != "raw":
    raise UnsupportedProviderCapability(
        "Tushare MCP 当前日线接口未声明复权口径"
    )
```

复权参数**从未传给** MCP 工具 `get_daily_data`。Tushare 自身完全支持前复权：`ts.pro_bar(ts_code, ..., adj='qfq')` 存在，且 `tushare/pro/data_pro.py` 显示它就是 `daily()` + `adj_factor()` 现算的 `price × adj_factor / adj_factor[0]`。另外 BaoStock 适配器**早就已经支持**（`baostock_provider.py:69` 已映射 `forward → "2"`），所以"拿不到前复权 K 线"在默认配置下也不成立。

### 前提三「AKShare 的 K 线路径可用」——在本环境不成立

`ak.stock_zh_a_hist` 实测 4/4 失败：`ConnectionError: RemoteDisconnected`。根因排查（原始 socket 级）：

- TCP 连通（10–21ms）、TLS 1.3 握手成功，随后 `/api/qt/stock/kline/get` **拿到零字节并被关闭**。
- 不是 header 问题：AKShare 源码 `akshare/stock_feature/stock_hist_em.py:952-1039` 是 `requests.get(url, params=params, timeout=timeout)`，**不发任何自定义 header**；补上 Chrome UA + `Referer: https://quote.eastmoney.com/` 后失败完全一致。
- 不是 host 问题：`push2his`、`push2`、`82.push2` 外加 24 个编号镜像域名、跨多个不同 IP，全部同样失败。
- 不是协议问题：`:80` 与 `:443`、HTTP/1.0、裸路径无参数，全部失败。
- 同一主机上 `/api/qt/stock/trends2/get`（200，39409 字节）与 `/api/qt/clist/get`（200，355 只北交所股票）**正常返回**。
- 唯一应答 kline 路径的 `push2delay.eastmoney.com` 对任何 `fqt`/参数组合都返回 `"dktotal":0,"klines":[]`。

**结论：这是网络边缘按 URL 的 DPI/过滤，客户端无解（header/参数/镜像/host rewrite 均无效），除非走代理。** 因此不能依赖 `stock_zh_a_hist`，改用同包内的新浪源（见设计）。

## 设计

### 供应商能力矩阵（本机实测）

| 能力 | akshare 现状 | akshare 可用路径 | tushare_mcp | baostock |
|---|---|---|---|---|
| `get_daily` raw | ❌ `stock_zh_a_hist` 被 URL 过滤 | ✅ `stock_zh_a_daily` | ⚠️ 仅 raw | ✅ `adjustflag=3` |
| `get_daily` forward | ❌ 同上 | ✅ `stock_zh_a_daily(adjust="qfq")` | ❌ 自设 raise | ✅ `adjustflag=2` |
| `get_daily_basic` | ❌ 适配器直接 raise | ✅ `stock_value_em` | ✅ 唯一现役来源 | ✅ `peTTM/pbMRQ` 可同请求返回 |
| 北交所（920 前缀） | — | ✅ `stock_zh_a_daily` / `stock_value_em` | ✅ | ❌ **零支持** |
| 股息率 | ❌ | ❌ | ✅（≥2000 积分） | ❌ |

`stock_zh_a_daily` 实测细节：

```
stock_zh_a_daily(symbol="sh600519", adjust="qfq"|""|"hfq") → 242 行 / 2024 全年 / 0.3–0.8s
覆盖：sh600519 · sz000001 · sz300750(创业板) · sh688981(科创板) · bj920799/bj920047(北交所)
全历史一次返回，不分页（600519 = 6003 行，2001-08-27 起；bj920799 = 1979 行，2015-03-10 起）
列：date, open, high, low, close, volume, amount, outstanding_share, turnover
```

BaoStock 实测细节：

```
rs.fields = date, code, open, high, low, close, preclose, volume, amount, adjustflag,
            turn, tradestatus, pctChg, peTTM, pbMRQ, psTTM, pcfNcfTTM, isST
adjustflag=3/2/1 三种口径下 peTTM/pbMRQ/psTTM/pcfNcfTTM 全部非空且数值完全一致（close 则不同）
  → 估值字段按不复权价计算，与复权口径无关，因此可与 qfq 行情在同一次请求中同时取回
唯一限制是 frequency：周线/月线带估值字段时服务端硬拒，error_code=10004012
  「周线指标参数传入错误:peTTM」
```

### K 线取源

主路径改为 `ak.stock_zh_a_daily`，`ak.stock_zh_a_hist` 降为该适配器内的**回退**（其它网络环境下它可能是好的）。**腾讯源 `stock_zh_a_hist_tx` 不得进入降级链**——它的 qfq 口径与新浪/BaoStock 不同（见下），混入同一序列会让回测结果不可复现。

### 前复权口径的不可比性

实测同一天 600519 前复权收盘价：

| 来源 | 2024-12-31 qfq 收盘 | 同日 raw 收盘 |
|---|---|---|
| 腾讯 `stock_zh_a_hist_tx` | 1444.42 | 1524.00 |
| 新浪 `stock_zh_a_daily` | **1435.70** | 1524.00 |
| BaoStock `adjustflag=2` | **1435.704012** | 1524.00 |

差异来自复权锚点/基准日的选择，是**合法的口径差异，不是数据错误**。因此：

- **基准口径 = 新浪 / BaoStock**（两者逐字节一致，是当前唯一的多数派）。
- 交叉验证一律**比对区间收益率/涨跌幅**，不比绝对价格；绝对价格只在确认锚点一致后才比。
- 任何新增数据源（含 iTick）的 qfq 与基准不一致时，先判定是锚点差异还是数据错误，不得直接判为失败。

### 归一化接缝：混合方案

`finance_agent/data/normalization.py:37-46` 的 `VALUATION_ALIASES` 目前**只映射 Tushare**：AKShare 的 `数据日期/PE(TTM)/PE(静)/市净率/总市值/流通市值` 与 BaoStock 的 `peTTM/pbMRQ/psTTM` 一个都不命中。

采用混合方案：

- **非歧义列进共享别名表**：`数据日期`、`市净率`、`总市值`、`流通市值`、`psTTM`。
- **有歧义的 PE 两列由适配器显式映射**：`PE(TTM)` → `pe_ttm`，`PE(静)` → `pe_lyr`。

理由：别名表是模糊匹配，把语义不同的 `PE(TTM)` 与 `PE(静)` 塞进同一个表必然产生歧义；但让每个适配器重新实现日期排序与类型转换又是重复劳动。适配器出口调用 `normalize_*` 的既有契约（`normalization.py` 模块 docstring）不变。

### PE 口径统一

现状三处优先级互相矛盾：

| 位置 | 现状 | 问题 |
|---|---|---|
| `research/scoring.py:147` | `_first_number(raw, "pe_ttm", "pe")` | TTM 优先 |
| `orchestrator/tools/stockdata.py:96` | `_first_value(valuation, "pe", "pe_ttm")` | 恰好相反 |
| `data/normalization.py:37-46` | `VALUATION_ALIASES["pe"]` 含 `pe_ttm` | 一旦兜底，取到哪个不确定 |

统一为：**`pe_ttm` 是唯一评分输入**；静态 PE 映射为独立键 `pe_lyr` 且不参与评分；把 `pe_ttm` 从 `VALUATION_ALIASES["pe"]` 中摘除；`stockdata.py:96` 的优先级改为与 `scoring.py:147` 一致。

### 北交所

- BaoStock **完全不支持北交所**：`bj.430047` 报 `error_code=10004011 股票代码未识别sh、sz`；而 `sh.830799`/`sz.830799` 返回 `error_code=0` 但 **0 行**——静默空数据，最危险的失败方式。
- 现有 `baostock_provider.py:20-25` 的 `_code()` 是「`6`/`68` 开头 → `sh`，其余 → `sz`」，对北交所代码会静默返回空。改为对 `43/83/87/92/920` 前缀**显式报错**，保证北交所永不被路由到 BaoStock。
- `43`/`83` 开头是**已废止代码**：`ak.stock_info_bj_name_code()` 返回 343 行，**100% 为 `920` 前缀**，`830799`/`430047` 均已不在列。加 43/83→920 重映射，映射源优先用 `stock_info_bj_name_code()`（免 token），Tushare `stock_basic` 作为二期。

### 缓存与退避（最小版本）

现状**零 K 线缓存**（`orchestrator/memory.py:196-221` 的短缓存零调用点），且 `orchestrator/tools/stockdata.py:244,260` 的 `search_candidates` 是**每个候选股一次请求**的 N+1 模式。切换到新浪源后新增"大量抓取容易封 IP"的风险（新浪源 docstring 自带该警告）。因此加最小落盘缓存，键为 `(provider, code, adjust, start, end)`，配合简单退避重试，**只覆盖 K 线与估值两条路径**，不做全量缓存框架。

### 可观测性：能力缺口 ≠ 失败

`provider_manager.py:73` 用 `except Exception` 把 `UnsupportedProviderCapability` 与网络异常**一视同仁**记入 `failures` 并置 `degraded: true`。后果：每次 AKShare 优先的估值请求都显示"降级"，而实际上那只是"该源从未声明这个能力"。改为把未声明能力记入独立的 `unsupported` 字段，不参与 `degraded` 判定。

### 评分限制项与快照版本

- `research/scoring.py:159-160` 只在这五项**全缺**时才记 `fundamental_metrics`。改为**逐字段**记录（如 `fundamental_missing: ["pe_ttm", "pb"]`），但**不得**升级为 `critical_missing`——否则纯单源部署会大面积变成"数据不足"。
- 补上 PE/PB 会**改变分数口径**，而 `research/theme_repository.py:252-253` 的唯一键是 `(theme_id, stock_code, rule_version, as_of)` 且为 `ON CONFLICT DO UPDATE`。因此 bump `research/rules/v1.json` 的 `rule_version`，并把 `last_metadata.source` 落进 payload。**不**给快照主键加 provider 维度（过度设计）。

## 错误处理

- 数据抓取或字段解析失败不抛出伪造评分；评分保持缺失，由现有规则引擎输出"数据不足"。
- 单只股票的估值取数失败不得连累行情本身（保持 `stockdata.py:79-84` 的 best-effort 语义）。
- 北交所代码路由到不支持它的 provider 时显式报错，绝不返回空列表——空列表会被 `_call` 当作"返回空数据"继续降级，最终表现为"这只票没数据"，而根因是代码映射错误。

## 验收与测试

1. 真实 `AkshareDataSource` 经 `stock_value_em` 取到估值后，`build_scores` 的基本面分数**确实包含** `pe_ttm` 与 `pb` 两项输入（这是本次缺口能藏这么久的漏洞所在，必须有断言）。
2. `akshare_provider.get_daily(adjustment="forward")` 走 `stock_zh_a_daily` 并返回按日期升序的前复权记录。
3. 北交所代码经 `BaostockDataSource` 得到显式错误而非空列表；`43`/`83` 前缀代码被重映射到 `920`。
4. 缺少 PE/PB 时 `score_restrictions` 逐字段记录，且行动结论**不是**"数据不足"。
5. `_call` 在 provider 未声明能力时不再置 `degraded: true`。
6. 既有研究契约、流水线、主题筛选、审计重放与图路由测试继续通过。

## 已知遗留与死配置

**已知遗留（本次不做）：**

- `get_income` 在 AKShare/Tushare 两侧仍返回厂商原生字段。
- AKShare 的 `get_trade_cal` 仍 `raise UnsupportedProviderCapability`。
- 股息率（`dv_ratio`/`dv_ttm`）在免费源中不可得。
- 腾讯源的 qfq 口径差异未做归一，仅通过"不进降级链"规避。

**仓库内的死配置（声明了但从不被读取，本次不做，且不再新增同类）：**

| 键 | 位置 | 状态 |
|---|---|---|
| `DEFAULT_DATA_PROVIDER` | `config.py:83` | 无任何读取方 |
| `BAOSTOCK_USERNAME` / `BAOSTOCK_PASSWORD` | `config.py:94-95` | 无读取方；BaoStock 登录实为匿名 |
| `maximum_data_age_trading_days` | `research/rules/v1.json:11` | 声明但从未被读取 |
| `_SCORE_KEYS` | `research/scoring.py:10` | 死代码 |

**测试覆盖盲区（本次补齐）：** `TushareMcpDataSource` 与 `BaostockDataSource` 在任何测试中都未被实例化；`ProviderManager._build_providers`（配置驱动构造）从未被覆盖。

## 决策记录：不接入 iTick

原提议是接入 [iTick](https://docs.itick.io/sdk/python-sdk) 以补上两个缺口。核查后确认**两个缺口都不需要新供应商**（见事实核查），且 22 项决策中 itick 被降级为候选、角色限定为"仅声明 `get_daily(forward)` 与 `get_daily_basic` 的定向补丁源"。

**重新升级为方案的条件（须同时成立）：**

1. 实测证明本机与部署环境里 BaoStock 与新浪源都给不出 qfq 或估值（例如新浪持续封 IP 且缓存/退避无法解决）。
2. 存在一个新浪/BaoStock 都给不了的**字段需求**——注意**当前该清单为空**：股息率已确认非硬需求，总市值/流通市值 `stock_value_em` 有，前复权两源都有。
3. 一次 ≤30 分钟可行性核查通过：A 股覆盖 + 基本面接口形态（是否为日频 PE/PB 时间序列）+ 免费额度 + 能否自助注册拿到 key。

**未验证事项（不得当作已知）：** iTick 的 A 股覆盖范围、其"公司基本面"接口是否为日频 PE/PB 时间序列、免费额度与注册门槛。已确认存在的仅是接口**存在性**：[K 线接口](https://docs.itick.io/zh-cn/rest-api/stocks/stock-kline)、[stock-info](https://docs.itick.io/zh-cn/rest-api/stocks/stock-info)、[Adjusted Close & Adjustment Factor](https://docs.itick.io/en/rest-api/stocks/stock-split)。一个待核实的观察：可见的 iTick 内容以越南、英股 LSE、以色列 TASE、新加坡 SGX 为主，更像面向全球市场的行情商，A 股未必在核心覆盖内。

**搁置期间不留任何占位物**：不加 `ITICK_*` 环境变量、不写空适配器、不在 `DATA_PROVIDER_ORDER` 里留名字。
