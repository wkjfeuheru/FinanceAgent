/** 前端 TypeScript 类型定义 */

/** 角色类型 */
export type Role = 'user' | 'assistant' | 'system'

/** 单条聊天消息 */
export interface ChatMessage {
  role: Role
  content: string
  timestamp: string
  /** 该条助手消息关联的完整结构化数据 */
  data?: ChatResponse
  /** 流式阶段提示 */
  stage?: string
  progressSteps?: Array<{
    stage: string
    message: string
    status: 'active' | 'completed'
  }>
  /** 是否处于加载中 */
  loading?: boolean
}

/** 用户画像 */
export interface UserProfile {
  risk_preference: string
  budget_amount: number
  stock_codes: string[]
  holding_period: string
  investment_goal: string
}

/** 用户画像响应（含元信息） */
export interface ProfileResponse {
  customer_id: string
  risk_preference: string
  budget_amount: number
  stock_codes: string[]
  holding_period: string
  investment_goal: string
  updated_at: string
}

/** 单个标的的技术指标（展示层，来自股票专家的确定性计算）。 */
export interface TechnicalIndicatorSet {
  /** 移动均线：latest 含 MA5/MA10/MA20/MA60。 */
  MA?: {
    latest?: Record<string, number>
    trend?: Record<string, string>
    position?: string
  }
  /** MACD：信号与背离仅在有明确结论时给出。 */
  MACD?: {
    latest?: Record<string, number>
    signal?: string | null
    divergence?: string | null
    trend?: string
  }
  KDJ?: {
    latest?: Record<string, number>
    signal?: string | null
    zone?: string
  }
  RSI?: {
    latest?: Record<string, number>
    zones?: Record<string, string>
  }
  BOLL?: {
    latest?: Record<string, number>
    bandwidth?: number
    position?: string
  }
  WR?: {
    latest?: Record<string, number>
    zones?: Record<string, string>
  }
  /** 汇总：综合趋势、看多信号、风险信号与最新价。 */
  summary?: {
    trend?: string
    signals?: string[]
    risks?: string[]
    latest_price?: number
  }
}

/** 技术指标按标的代码组织；K 线不足时该标的会缺失。 */
export interface TechnicalAnalysis {
  [code: string]: TechnicalIndicatorSet
}

/** 对话响应（与后端 ChatResponse 对齐） */
export interface ChatResponse {
  response: string
  task_plan: string[]
  user_profile: UserProfile
  stock_data: Record<string, any>
  fundamental_analysis: Record<string, any>
  stock_analysis: Record<string, any>
  technical_analysis: TechnicalAnalysis
  analysis_results: ResearchAnalysisResult[]
  theme_screening?: Record<string, any>
  theme_screening_status?: string
  theme_candidates?: ThemeLead[]
  pending_leads?: ThemeLead[]
  personalization_status?: string
  product_analysis?: ProductAnalysisPayload
  market_insight?: Record<string, any>
  /** 账户领域载荷：资金/持仓查询与配置诊断共用。 */
  account?: AccountPayload
  compliance_result: Record<string, any>
  run_status?: string
  warnings?: string[]
  tasks?: Record<string, any>[]
  task_results?: Record<string, any>
  conversation_id: string
  /** 缺参追问：run_status=awaiting_input 时携带弹窗表单。 */
  pending_input?: PendingInput | null
  interrupt_id?: string
}

/** 缺参追问的表单字段规格（与后端 ParamSpec.to_field() 对齐）。 */
export interface ParamField {
  name: string
  label: string
  required: boolean
  kind: 'text' | 'code' | 'choice' | 'number'
  options: string[]
  default: string
  scope: 'turn' | 'profile'
  placeholder?: string
}

/** 缺参追问载荷：问题文案 + 待填字段。 */
export interface PendingInput {
  question: string
  missing: string[]
  fields: ParamField[]
}

/** 产品专家确定性研究结果；保留索引签名以兼容历史字典响应。 */
export interface ProductAnalysisPayload {
  schema_version?: string
  type?: 'single' | 'question' | 'deep_dive' | 'comparison' | (string & {})
  product_codes?: string[]
  products?: ProductAssessmentPayload[]
  assessments?: ProductAssessmentPayload[]
  evidence_ids?: string[]
  data_quality?: 'complete' | 'warning' | 'critical_missing' | (string & {})
  personalization_status?: 'personalized' | 'research_candidate' | (string & {})
  ambiguities?: string[]
  report?: string
  [key: string]: any
}

export interface ProductAssessmentPayload {
  code: string
  name?: string
  risk_level?: string | null
  risk_source?: string
  suitability_status?: 'matched' | 'unmatched' | 'unavailable' | 'not_evaluated' | (string & {})
  suitability_reasons?: string[]
  usable_for_comparison?: boolean
  missing_fields?: string[]
  restrictions?: string[]
  evidences?: Record<string, ProductFieldEvidencePayload>
  [key: string]: any
}

export interface ProductFieldEvidencePayload {
  field: string
  value?: any
  source?: string
  as_of?: string
  freshness?: 'fresh' | 'stale' | 'unknown' | (string & {})
  fact_id?: string
  [key: string]: any
}

/** 已计算的确定性研究结论；与待核验线索分离。 */
export interface ResearchAnalysisResult {
  action: '关注' | '观望' | '规避' | '数据不足'
  data_quality: 'complete' | 'warning' | 'critical_missing'
  rule_version: string
  scores: Record<string, number | null>
  evidence_ids: string[]
  personalization_status: 'personalized' | 'research_candidate'
  restrictions: string[]
  /** 该结论对应的研究请求；比较请求会为每只标的各出一条结论。 */
  request?: {
    stock_codes?: string[]
    /** 分析维度：both（默认）不改变呈现，收窄时前端标注视角。 */
    analysis_type?: 'fundamental' | 'technical' | 'both'
  }
}

/** 仅供管理员审核的外部研究线索；不含评分或行动结论。 */
export interface ThemeLead {
  id: string
  theme_id: string
  stock_code: string
  industry: string
  source_name: string
  source_class: 'official' | 'licensed_classification' | 'public_lead'
  source_uri: string
  evidence_excerpt: string
  evidence_hash: string
  discovered_at: string
  evidence_expires_at: string
}

export interface ThemeLeadReviewRequest {
  decision: 'approve' | 'reject'
  evidence_expires_at: string
  note: string
}

/** 主题注册记录：名称/别名 → theme_id 的解析来源。 */
export interface ThemeRegistryEntry {
  theme_id: string
  display_name: string
  aliases: string[]
  representative_codes: string[]
  active: boolean
}

export interface ThemeRegistryUpsertRequest {
  theme_id: string
  display_name: string
  aliases: string[]
  representative_codes: string[]
  active: boolean
}

// ── 管理后台 ──────────────────────────────────────────────────

/** 管理端用户列表的一行：账号信息 + 账户概览。 */
export interface AdminUserEntry {
  customer_id: string
  username: string
  display_name: string
  created_at: string
  is_admin: boolean
  /** 账户口径与用户端同源；读取失败时为 null，不伪造 0。 */
  account: AccountSnapshot | null
}

export interface AdminUserListResponse {
  users: AdminUserEntry[]
  simulated: boolean
}

export interface AdminUserPortfolioResponse {
  customer_id: string
  user: AdminUserEntry | null
  account: AccountSnapshot | null
  positions: PositionView[]
  simulated: boolean
}

export interface AdminProductListResponse {
  products: ProductView[]
  simulated: boolean
}

/** 新增/编辑商品请求；上下架状态不在此表达。 */
export interface AdminProductUpsertRequest {
  code: string
  name: string
  type?: string
  risk_level?: string
  company?: string
  manager?: string
  scale?: number | null
  subscription_fee?: number | null
  redemption_fee?: string
  recommended_holding_period?: string
  investment_target?: string
  investment_strategy?: string
  /** 最新净值；必须为正，缺失则不写业绩区块。 */
  nav?: number | null
  /** 净值日期，对应后端 product_performance.update_date。 */
  nav_date?: string
  /** 收益率/回撤是小数（0.126 表示 12.6%），与产品库存储口径一致。 */
  return_1y?: number | null
  max_drawdown?: number | null
  volatility?: number | null
  sharpe_ratio?: number | null
}

/** 对话请求体 */
export interface ChatRequest {
  message: string
  customer_id: string
  chat_history: Array<{ role: string; content: string }>
  conversation_id?: string
  /** 本轮是否为对上一轮缺参追问的答复；true 时后端在挂起线程上续跑。 */
  resume?: boolean
  /** 弹窗提交的结构化参数，键与 pending_input.fields[].name 对应。 */
  answers?: Record<string, any>
}

/** 历史消息 */
export interface HistoryMessage {
  role: string
  content: string
  timestamp?: string
}

/** 历史响应 */
export interface HistoryResponse {
  customer_id: string
  messages: HistoryMessage[]
}

export interface Conversation {
  conversation_id: string
  customer_id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface ConversationListResponse {
  customer_id: string
  conversations: Conversation[]
}

/** 健康检查响应 */
export interface HealthResponse {
  status: string
  redis_available: boolean
  agents_initialized: boolean
}

/** SSE 阶段事件 */
export interface SSEStageEvent {
  type: 'stage'
  stage: 'product_analysis' | (string & {})
  message: string
}

/** SSE 流式增量事件：定稿答复的分块下发，前端按序累积渲染。 */
export interface SSEDeltaEvent {
  type: 'delta'
  content: string
}

/** SSE 响应事件 */
export interface SSEResponseEvent {
  type: 'response'
  content: string
  data: ChatResponse
}

/** SSE 错误事件 */
export interface SSEErrorEvent {
  type: 'error'
  message: string
}

export type SSEEvent = SSEStageEvent | SSEDeltaEvent | SSEResponseEvent | SSEErrorEvent

/** SSE 事件回调 */
export interface StreamCallbacks {
  onStage: (event: SSEStageEvent) => void
  /** 增量文本回调；服务端未分块下发（旧版本）时不会触发，可选。 */
  onDelta?: (event: SSEDeltaEvent) => void
  onResponse: (event: SSEResponseEvent) => void
  onError: (error: string) => void
}

// ── 用户认证相关类型 ─────────────────────────────────────────

/** 注册请求 */
export interface RegisterRequest {
  username: string
  password: string
  display_name?: string
}

/** 登录请求 */
export interface LoginRequest {
  username: string
  password: string
}

/** 已登录用户信息（持久化到 localStorage） */
export interface UserInfo {
  customer_id: string
  username: string
  display_name: string
  token: string
  expires_in?: number
  login_at?: number
  is_admin?: boolean
}

/** 登录响应 */
export interface LoginResponse {
  customer_id: string
  username: string
  display_name: string
  token: string
  expires_in: number
  is_admin?: boolean
}

/** 注册响应 */
export interface RegisterResponse {
  customer_id: string
  username: string
  display_name: string
}

/** 清除记录响应 */
export interface ClearRecordsResponse {
  status: string
  cleared_keys: number
  message: string
}

// ── 模拟交易类型（与后端 finance_agent/portfolio/contracts.py 对齐）────

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
