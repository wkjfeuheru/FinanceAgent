# 在 agent 模块上补齐交易业务：商品展示 / 购买 / 持仓 / 清仓 / 账户面板

## 结论先说

现有代码库是 A 股投顾系统：LangGraph 编排（`orchestrator/`）+ PostgreSQL 业务层（无 ORM，手写 SQL）+ Vue 3 SPA。**全库不存在** order / position / account-cash / transaction 任何概念——`user_profiles.stock_codes` 只是自选代码，`product_holdings` 是基金的披露重仓股。所以要新建一层业务域，而不是复用。

关键设计判断：**一个确定性服务层，两条展示路径**。`PortfolioService` 是唯一的资金与持仓计算核心，REST 路由和 agent 领域工具都调它。这样"账户数据面板"和"对话里问我的持仓"永远不可能给出两个不同的数字。

---

## 一、数据层：`sql/011_portfolio.sql`

（006 号缺号，011 是下一个可用编号。）

```sql
finance.accounts        (customer_id PK→users CASCADE, cash_balance numeric(18,2),
                         frozen_balance, total_deposit, created_at, updated_at)
finance.cash_transactions (txn_id uuid PK, customer_id→users CASCADE,
                         kind CHECK IN (deposit|buy|sell|fee), amount numeric(18,2),
                         balance_after, ref_id, note, idempotency_key, created_at)
finance.orders          (order_id uuid PK, customer_id→users CASCADE,
                         product_code→finance.products(code), side CHECK IN (buy|sell),
                         shares double precision, price double precision,
                         gross_amount/fee/realized_pnl numeric(18,2), net_amount,
                         fee_limitations jsonb, created_at)
finance.positions       (customer_id→users CASCADE, product_code→products,
                         shares double precision, cost_amount numeric(18,2),
                         avg_cost double precision, opened_at, updated_at,
                         PRIMARY KEY (customer_id, product_code))
```

- 全部 `ON DELETE CASCADE` 到 `users(customer_id)`，所以 `PostgresAuthStore.delete_user` 的注销链路自动覆盖新表（无需像 `research_runs` 那样补删除顺序）。
- `cash_transactions` 加**部分唯一索引** `(customer_id, idempotency_key) WHERE idempotency_key <> ''` —— 充值/下单是资金操作，网络重试不能重复扣加。
- DDL 用 `CREATE TABLE IF NOT EXISTS`，与既有 `sql/*.sql` 一致；`finance_agent/data/postgres_schema.py` 新增 `PORTFOLIO_SCHEMA_SQL = _load_sql("011_portfolio.sql")`。

**接进现有建表路径**（两处，保持幂等）：
- `data/postgres_stores.py::_PostgresBaseStore._ensure_schema` 追加执行该脚本
- `data/postgres_repository.py::PostgresRuntimeRepository.setup_schema` 追加执行该脚本

## 二、服务层：新增 `finance_agent/portfolio/`

| 文件 | 内容 |
|---|---|
| `contracts.py` | `AccountSnapshot` / `PositionView` / `OrderView` / `TradeResult`（frozen pydantic，`extra="forbid"`，与 `research/contracts.py` 同风格） |
| `fees.py` | `parse_percent()` + 申购/赎回费计算 |
| `pricing.py` | `NavSource` Protocol，`ProductLibraryNavSource` 从 `product_performance` 取最新净值；测试注入 fake |
| `service.py` | `PortfolioService` —— 唯一核心 |

**费率**：`finance.products.subscription_fee` 是数字（1.5 表示 1.5%），`redemption_fee` 是**字符串**（`'0.5%'` / `'0'`）。`parse_percent` 统一处理两者。基金用外扣法：

```
申购: fee = amount × r/(1+r);  shares = (amount − fee) / nav
赎回: gross = shares × nav;    fee = gross × r;  net = gross − fee
```

费率未披露（NULL/空）时**不静默按 0 处理**：照常成交，但在订单与响应里带 `fee_limitations: ["fee_unavailable:subscription_fee"]`，前端显式提示。这符合仓库既有的 no-silent-fallback 原则。

**成本与盈亏**：买入 `cost_amount += net_amount`（含费的实际现金支出）；卖出按份额比例结转成本（移动加权），`realized_pnl = net_amount − 结转成本`。

**账户口径**（`AccountSnapshot`）：
- `cash_balance` / `market_value` = Σ shares×nav / `total_assets` = 两者之和
- `total_deposit` / `total_pnl = total_assets − total_deposit` / `total_pnl_pct`
- `realized_pnl`、`position_pnl`（浮动）
- `pricing_issues: list[str]` —— **任一持仓取不到净值时，把代码列出来**，不把市值静默算小。`market_value_complete: bool` 供前端标注口径不完整。

**核心方法**：`get_account` / `list_positions` / `list_products` / `deposit` / `buy` / `sell(shares|all)` / `liquidate_all` / `list_orders` / `list_transactions`。

**专用异常**（与 `ProviderError` 等既有约定一致，不用裸 raise）：`ProductNotFoundError` / `PricingUnavailableError` / `InsufficientFundsError` / `InsufficientSharesError` / `InvalidAmountError`。路由映射 400/404/409；agent 工具映射为安全 limitation。

**资金安全**：每个写操作在**单个 `_transaction()`** 内完成「读余额 → 校验 → 写 orders/positions/accounts/transactions」，用 `SELECT ... FOR UPDATE` 锁账户行，避免并发双花。

**存储**：`data/postgres_stores.py` 加 `PostgresPortfolioStore(_PostgresBaseStore)`（与 `PostgresProductLibrary` 同风格）；`data/portfolio_store.py` 加 `get_portfolio_store()` 单例（镜像 `product_library.py`）。

## 三、REST API：新增 `finance_agent/api/portfolio_routes.py`

单独 APIRouter，在 `main.py` 里 `include_router`，不塞进已经很长的 `routes.py`。**全部从 Bearer token 解析 `customer_id`**（复用 `_require_customer_id`），路径里不带 customer_id —— 从根上消除越权读写：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/portfolio/products` | 商品货架（名称/代码/类型/风险等级/最新净值/近1年收益/费率） |
| GET | `/api/portfolio/products/{code}` | 单品详情（含费率与业绩，复用产品库 `_build_product`） |
| GET | `/api/portfolio/account` | 账户数据面板 |
| GET | `/api/portfolio/positions` | 持仓（含最新净值、市值、浮动盈亏、收益率、占比） |
| POST | `/api/portfolio/deposit` | 充值 `{amount, idempotency_key}` |
| POST | `/api/portfolio/orders` | 下单 `{product_code, side, amount\|shares, all, idempotency_key}` |
| POST | `/api/portfolio/liquidate` | 一键清仓 |
| GET | `/api/portfolio/orders` | 委托/成交记录 |
| GET | `/api/portfolio/transactions` | 资金流水 |

请求/响应模型放 `api/portfolio_schemas.py`（保持文件聚焦）。充值限单笔 > 0 且 ≤ 1000 万；所有响应带 `simulated: true`，文案标注"模拟交易，不构成投资建议"。

## 四、Agent 接入（你选了"接入 Agent"）

新增第 4 个业务领域，走现有 `domains/base.py` 的 mode 白名单机制，**纯确定性、只读**：

1. `orchestrator/contracts.py`：`BusinessDomain` 加 `ACCOUNT_PORTFOLIO = "account_portfolio"`。
2. `root_graph.py`：`_INTENT_TO_DOMAIN` 加 `"account_query" → ACCOUNT_PORTFOLIO`；`_DOMAIN_ORDER` **必须**同步加该成员（该元组被 `.index` 当排序键，漏加会 ValueError）。
3. `intent.py`：`_INTENTS`、`_EXECUTION_MODES` 加 `account_query`；`_INTENT_CLASSIFIER_PROMPT` 补一段说明——account_query 只处理**用户自己的**账户/持仓/资产/盈亏；否则"我的持仓"会被误判成个股或产品分析。
4. 新增 `orchestrator/domains/account.py`：`build_account_domain_graph()`，三个 mode
   - `account_overview` → 账户总览摘要
   - `position_query` → 持仓明细摘要
   - `trade_guidance` → 命中 买入/卖出/清仓/充值 时返回固定文案："交易需在「商品」「持仓」页面完成，投顾对话不代客下单。"
   
   mode 由 `keyword_mode()` 确定性解析，不由 LLM 决定。摘要在**服务层拼接时就带风险提示与"模拟盘"字样**，不依赖合规出口的改写分支（只有命中敏感词才会触发 `_default_rewrite` 补免责声明）。
5. `orchestrator.py::_domain_runner`：加 `elif context.task.domain == BusinessDomain.ACCOUNT_PORTFOLIO` 分支。
6. `root_graph.project_root_state` + `_V2_RESPONSE_KEYS`：把 `account` 投进响应；`api/schemas.py::ChatResponse` 加 `account: dict = {}`（纯追加，向后兼容）。

**只读不变量**：account 领域只调用 `get_account`/`list_positions`，结构上无法下单。**下单只能走 REST + UI**，这也和既有 `_ACTION_MARKERS`（"帮我买"/"带我操作" 拦截）的取向一致。补一条测试锁死这个不变量。

## 五、前端：引入 vue-router + 3 个新页面

现在没有路由，`App.vue` 是单体 shell。改造：

- `npm i vue-router`；`src/router/index.ts` 定义 `/chat`、`/market`、`/positions`、`/account` + 未登录守卫（读 `getStoredUser()`）。
- 把 `App.vue` 里已登录的布局（header + 聊天区 70% + 侧边栏 30%）**原样搬进新 `src/views/ChatView.vue`**，`App.vue` 退化为「登录门 + 顶部导航 + `<router-view>`」。现有 `ChatWindow`/`ProfilePanel`/`HistoryPanel`/管理抽屉全部不动。
- `src/views/ProductMarketView.vue` —— 商品货架卡片/表格（风险等级、最新净值、近1年、费率）+ 购买弹窗（输入金额 → 预览份额与费用 → 确认）。
- `src/views/PositionsView.vue` —— 持仓表（份额/成本/净值/市值/浮动盈亏/收益率/占比）+ 单只卖出（部分/全部）+ **一键清仓**（二次确认）。
- `src/views/AccountView.vue` —— 账户面板：总资产/可用资金/持仓市值/累计盈亏/累计充值 指标卡 + 充值弹窗 + 资金流水与成交记录。
- `src/api/portfolio.ts`（axios 封装，复用现有 token 拦截器）+ `src/types/index.ts` 追加类型。

## 六、测试（`tests/` 扁平，pytest，手写 fake + monkeypatch）

- `test_portfolio_fees.py` —— 外扣法费率、`'0.5%'` 字符串解析、未披露费率的 limitation
- `test_portfolio_service.py` —— 充值→买入→持仓→部分卖出→清仓全链路；余额/份额不足；无净值产品必须失败；**重复 idempotency_key 不重复扣加**；移动加权成本与已实现盈亏
- `test_portfolio_api.py` —— 无 token 401、跨用户隔离、清仓接口、账户口径
- `test_account_domain_graph.py` —— 领域确定性输出、未注册 mode 安全失败、`trade_guidance` 拒单、**断言只读（调用后余额与持仓不变）**
- 更新断言领域闭集的既有测试（`test_orchestrator_contracts_v2.py` 等）

## 七、文档

`README.md` 更新 API 表、新增 `sql/011` 说明、项目结构树补 `finance_agent/portfolio/` 与新增前端页面、领域列表补第 4 个领域；澄清"模拟交易"边界。

---

## 需要你知道的两个取舍

1. **`redemption_fee` 是字符串字段**（`'0.5%'`/`'0'`），且种子数据里 `999999` 产品费率为 NULL 且无净值。我让它取不到净值就**报错**（`PricingUnavailableError`），而不是回退到 1.0 或跳过 —— 这也是为什么 `position 999999` 不可交易。
2. **充值**是用户要求的，但无限充值会让"账户收益"失去意义。我加了单笔上限与幂等键，面板里同时展示 `total_deposit` 与"相对累计本金收益"，避免把充值误当成收益。

开工后我会先落 SQL + 服务层 + 测试（可独立验证），再做 API，最后做前端页面与 agent 领域接入。
