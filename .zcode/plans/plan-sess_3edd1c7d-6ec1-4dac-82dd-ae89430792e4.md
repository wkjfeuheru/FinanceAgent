## 目标
把能力清单 ④「账户查询」扩展为「查询 + 基于本人持仓的配置诊断与优化参考」，并**新增一套资产配置计算函数（tool）**。保留既有查询模式，新增 `allocation_review` 模式，其核心是一组可复用的纯计算工具。

## 硬约束（决定了计算函数能做什么）
- 仓库**没有产品 NAV 时间序列**：`finance.product_performance` 每产品只有一行快照，且产品间日期不对齐 → 协方差/相关性/VaR/均值-方差优化**在现有数据上不可计算**。
- 可用的只有标量：`return_1m/3m/6m/1y/3y`、`volatility`、`max_drawdown`、`sharpe_ratio`（均为种子常量，非实时计算）。
- **无无风险利率、无基准时序**；`scipy` 不是项目依赖（不引入优化求解器）。
- 因此计算工具采用**对角（零相关）近似**，并把相关性/协方差在签名与返回结构里预留为 `None`，日后补时序即可启用。

## 已定决策（推荐项；不认可请在批准前指出）
1. **计算范围**：标量可行的配置计算集，签名预留协方差（两步走）。
2. **暴露方式**：纯函数模块 + 账户领域确定性调用；模块保持可被 REST/管理端复用（本次不改 REST）。
3. **合规边界**：措辞统一为「参考/测算/区间」，不含 `推荐买入/推荐卖出/买卖点/荐股`，不改敏感词表。
4. **假设参数**：无风险利率、零相关近似、权重上下限做成 config 常量；画像用于选参考区间，缺画像降级为通用区间。账户领域 `PARAM_SPECS` 保持为空（**不追问**）。

## 改动清单

### 1) 新增计算工具模块 `finance_agent/orchestrator/tools/allocation.py`（核心）
纯 Python（仅 `math`/`statistics`），零外部依赖，函数返回 dict，风格对齐 `orchestrator/tools/technical.py`。函数清单：
- 权重工具：`normalize_weights(w)`、`equal_weight(n)`、`inverse_volatility_weights(vols)`、`risk_budget_weights(vols, budgets)`（对角下风险平价 == 逆波动率，注明）。
- 收益/风险：`portfolio_return(w, returns)`、`portfolio_volatility(w, vols, correlations=None)`（`None` → 对角近似 `sqrt(Σ(wᵢσᵢ)²)`；给出相关阵时走完整公式）、`portfolio_sharpe(ret, vol, risk_free)`、`portfolio_max_drawdown(w, drawdowns)`（加权近似，注明口径）、`diversification_ratio(w, vols, correlations=None)`。
- 结构与风险：`concentration_metrics(w)`（HHI / top1 / top3 / effective_n）、`risk_contribution(w, vols, correlations=None)`（对角：`(wᵢσᵢ)²/σ_p²`）。
- 参考区间：`REFERENCE_BANDS`（按风险偏好，复用 `product_research/rules.py` 的 保守→R1…激进→R5 归一）、`band_deviation(weights_by_tier, bands)`。
- 汇总入口：`review_portfolio(positions, account, profile, *, assumptions) -> dict`，产出 `buckets / concentration / risk_contribution / notes / limitations / profile_used`。
- 复用既有数学：`research/scoring.py` 的 `_volatility`（×√252）与 `_maximum_drawdown` 作为同一口径参照（若需从序列计算时）。
- 降级：缺画像 → `profile_used=False`，仅输出集中度与风险暴露；缺净值持仓计入 `pricing_issues`，不静默缩小分母（沿用现有口径）。

### 2) 打通持仓的风险等级（前置）
- `finance_agent/portfolio/contracts.py`：`PositionView` 新增 `risk_level: str = ""`、`product_type: str = ""`（带默认值，向后兼容）。
- `finance_agent/portfolio/service.py`：`_names_for`（159-175）扩展为 `_product_meta_for`，同一次 `library.query_by_codes` 里同时取 `name/risk_level/type`，供 `list_positions` 填充。
- `frontend/src/types/index.ts`：`PositionView` 同步两个可选字段。

### 3) 账户领域接入
- `finance_agent/orchestrator/domains/account.py`：
  - `_MODE_KEYWORDS` 新增 `allocation_review`（关键词：`优化, 配置, 资产配置, 组合, 分散, 集中, 集中度, 风险暴露, 匹配吗, 适合我吗, 合理吗`），顺序 **trade_guidance → allocation_review → position_query → account_overview**（保证"我的持仓怎么优化"不被 `持仓` 抢走，交易词仍最高优先）。
  - 新增 `_allocation_review(context, service)`：调用 `tools/allocation.review_portfolio`，确定性文案 + `structured_data={account, positions, allocation_review, mode}`；读 `context.user_profile`。
  - `default_account_operations` 注册 `DomainOperation(name="allocation_review", modes=frozenset({"allocation_review"}), handler=_safe(...))`。
  - 无持仓 → 固定引导（先到「商品」申购）；异常仍经 `_safe` 收敛为 `ACCOUNT_UNAVAILABLE`。

### 4) 意图/路由/文案登记
- `finance_agent/orchestrator/intent.py`：`_EXECUTION_MODES["account_query"]` 增加 `"allocation_review": False`；分类器 prompt（49、56-59）补"我的持仓怎么优化 / 资产配置是否合理 → allocation_review"。`_INTENTS`/`_INTENT_TO_DOMAIN` 不变。
- `finance_agent/orchestrator/supervisor_graph.py:496-502`：投影带上 `data.get("allocation_review", {})`。
- `finance_agent/orchestrator/conversation_graph.py:36` 改写 ④，**保留 `账户`/`只读`/`不构成投资建议`**（`test_conversation_graph.py:118-123` 锁定），如「④ 查看本人账户资金与持仓，并基于持仓给出配置诊断与优化参考（只读；下单与充值需由用户在页面完成）；」。

### 5) 配置常量
- `finance_agent/config.py`：新增 `ALLOCATION_RISK_FREE_RATE`、`ALLOCATION_WEIGHT_MIN/MAX`、`ALLOCATION_ZERO_CORRELATION`（沿用现有 `ORCHESTRATION_*` / `PORTFOLIO_*` 的 env 覆盖风格）。

### 6) 前端（最小面）
- `frontend/src/types/index.ts`：补上 `ChatResponse.account`（当前缺失）与 `allocation_review` 类型。
- 新增 `frontend/src/components/AllocationCard.vue`（纯 CSS 比例条 + 参考区间，不引图表库），在 `MessageList.vue` 按 `msg.data.account?.allocation_review` 条件渲染；文本仍以 `response` 为准。

### 7) 文档
- `README.md:34 / 45-47 / 453-454 / 465` 与 `docs/orchestration-follow-up.md:358`：账户领域描述补"并基于持仓给出配置诊断与优化参考（仍只读、不代客操作）"。

## 测试
- 新增 `tests/test_allocation_tools.py`：逐函数单测（归一化、对角波动率、集中度、风险贡献、缺失相关性时走近似、画像缺失降级、`check_sensitive_words(summary) == []`）。
- 扩展 `tests/test_account_domain_graph.py`：模式解析新用例（"我的持仓怎么优化"→allocation_review、"我的持仓"仍→position_query、"帮我清仓我的持仓"仍→trade_guidance）+ 处理器输出与无持仓引导；既有 unsupported_mode 用例不受影响。
- `tests/test_conversation_graph.py` 仍通过；`tests/test_param_interrupt_graph.py:150-156`（账户永不追问）仍通过。

## 明确不做（本次范围外）
- 不新建 NAV 时序表/种子/provider，不做协方差、相关性、VaR、有效前沿（接口预留）。
- 不引入 scipy/numpy 到生产计算路径，不引入外部依赖。
- 不改合规敏感词表，不输出买卖或调仓指令；不做画像缺失时的 HITL 追问。
- 不新增资产大类字段（`category`），不改 DDL/种子/管理端。

## 验证
`pytest tests/test_allocation_tools.py tests/test_account_domain_graph.py tests/test_conversation_graph.py tests/test_param_interrupt_graph.py tests/test_portfolio_service.py`
