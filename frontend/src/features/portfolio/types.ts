// ── 模拟交易类型（与后端 finance_agent/domains/portfolio/contracts.py 对齐）────

/** 带来源与截止日的数值 */
export interface SourcedValue {
  value: number | null
  source: string
  as_of: string
}

/** 商品货架上的一项 */
export interface ProductView {
  code: string
  name: string
  type: string
  risk_level: string
  company: string
  manager: string
  scale: number | null
  nav: SourcedValue
  return_1y: number | null
  max_drawdown: number | null
  sharpe_ratio: number | null
  subscription_fee: number | null
  redemption_fee: string
  recommended_holding_period: string
  investment_target: string
  /** 上架状态；false 时不可申购，但既有持仓仍可赎回。 */
  is_active: boolean
  /** 是否有可用净值且已上架；为 false 时不可交易。 */
  tradable: boolean
  limitations: string[]
}

/** 一笔持仓及其浮动盈亏 */
export interface PositionView {
  product_code: string
  product_name: string
  /** 产品类型与风险等级（透传自产品库），供配置诊断分档。 */
  product_type?: string
  risk_level?: string
  shares: number
  cost_amount: number
  avg_cost: number
  nav: number | null
  nav_as_of: string
  market_value: number | null
  unrealized_pnl: number | null
  return_rate: number | null
  weight: number | null
  opened_at: string | null
  updated_at: string | null
  pricing_status: 'priced' | 'unavailable'
  limitations: string[]
}

/** 三档占比与参考区间的偏离（配置诊断）。 */
export interface AllocationDeviation {
  tier: string
  weight: number
  reference_low: number
  reference_high: number
  status: 'below' | 'within' | 'above'
  distance: number
}

/** 单只持仓的配置诊断条目。 */
export interface AllocationHolding {
  product_code: string
  product_name: string
  weight: number
  risk_level: string
  tier: string
  volatility: number | null
  return_1y: number | null
}

/** 单只持仓的优化方向参考（当前→目标与方向）。 */
export interface AllocationOptimizationTarget {
  product_code: string
  product_name: string
  tier: string
  volatility: number | null
  current: number
  target: number
  delta: number
  direction: '提高' | '降低' | '维持'
}

/** 优化前后指标对比（同一测算子集）。 */
export interface AllocationOptimizationMetrics {
  expected_return: number | null
  volatility: number | null
  max_drawdown: number | null
}

/** 档位层相对参考区间的偏离（含"当前无对应档位标的"）。 */
export interface AllocationTierGap {
  tier: string
  current: number
  reference_low: number
  reference_high: number
  status: 'below' | 'within' | 'above' | 'absent'
}

/** 配置优化参考：目标权重、方向与前后指标（非交易指令）。 */
export interface AllocationOptimization {
  basis: 'risk_band' | 'inverse_volatility' | 'none'
  coverage: { covered: number; total: number; uncovered: string[] }
  targets: AllocationOptimizationTarget[]
  before: AllocationOptimizationMetrics
  after: AllocationOptimizationMetrics
  tier_targets: Record<string, number>
  /** 档位层偏离；"全部集中在单一档位"时的关键建议来源。 */
  tier_gaps: AllocationTierGap[]
  unrealizable_tiers: string[]
  notes: string[]
}

/** 配置诊断与优化参考载荷（与后端 allocation.review_portfolio 输出对齐）。 */
export interface AllocationReview {
  profile_used: boolean
  risk_preference: string | null
  reference_basis: string
  position_count: number
  total_market_value?: number
  holdings: AllocationHolding[]
  /** 三档占比（小数点，非百分数）。 */
  tiers: Record<string, number>
  concentration: {
    position_count: number
    hhi: number | null
    effective_n: number | null
    top1_weight: number | null
    top3_weight: number | null
  }
  portfolio: {
    expected_return: number | null
    volatility: number | null
    sharpe: number | null
    max_drawdown: number | null
    diversification_ratio: number | null
  }
  deviations: AllocationDeviation[]
  /** 配置优化参考（目标权重/方向/前后指标）；旧响应可能缺失。 */
  optimization?: AllocationOptimization
  cash_ratio: number | null
  notes: string[]
  limitations: string[]
  approximation: string
  unpriced?: string[]
}

/** 账户领域载荷。 */
export interface AccountPayload {
  account: Record<string, any>
  positions: PositionView[]
  mode: string
  /** 仅 allocation_review 模式携带；其它模式为空对象。 */
  allocation_review?: AllocationReview
}

/** 一条已成交委托 */
export interface OrderView {
  order_id: string
  product_code: string
  product_name: string
  side: 'buy' | 'sell'
  shares: number
  price: number
  gross_amount: number
  fee: number
  net_amount: number
  realized_pnl: number | null
  /** 费率未披露等需要提示的限制项。 */
  fee_limitations: string[]
  created_at: string | null
}

/** 一条资金流水 */
export interface TransactionView {
  txn_id: string
  kind: 'deposit' | 'buy' | 'sell' | 'fee'
  amount: number
  balance_after: number
  ref_id: string
  note: string
  created_at: string | null
}

/** 账户数据面板口径 */
export interface AccountSnapshot {
  customer_id: string
  cash_balance: number
  frozen_balance: number
  market_value: number
  total_assets: number
  total_deposit: number
  total_pnl: number
  total_pnl_pct: number | null
  realized_pnl: number
  position_pnl: number
  position_cost: number
  position_count: number
  /** 为 false 时市值只覆盖可定价持仓，缺失项见 pricing_issues。 */
  market_value_complete: boolean
  pricing_issues: string[]
  updated_at: string | null
  simulated: boolean
  disclaimer: string
}

export interface ProductShelfResponse {
  products: ProductView[]
  simulated: boolean
}

export interface PositionListResponse {
  customer_id: string
  positions: PositionView[]
  account: AccountSnapshot
  simulated: boolean
}

export interface OrderListResponse {
  customer_id: string
  orders: OrderView[]
  simulated: boolean
}

export interface TransactionListResponse {
  customer_id: string
  transactions: TransactionView[]
  simulated: boolean
}

export interface DepositRequest {
  amount: number
  idempotency_key?: string
}

export interface DepositResponse {
  transaction: TransactionView
  account: AccountSnapshot
  idempotent_replay: boolean
  simulated: boolean
}

export interface OrderRequest {
  product_code: string
  side: 'buy' | 'sell'
  amount?: number
  shares?: number
  all?: boolean
  idempotency_key?: string
}

export interface TradeResponse {
  order: OrderView
  account: AccountSnapshot
  position: PositionView | null
  idempotent_replay: boolean
}

export interface LiquidationResponse {
  orders: OrderView[]
  cleared_codes: string[]
  /** 无法定价等原因未清仓的商品 → 错误码。 */
  failed: Record<string, string>
  total_cash_in: number
  total_realized_pnl: number
  account: AccountSnapshot
}
