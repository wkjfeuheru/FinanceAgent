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
  compliance_result: Record<string, any>
  run_status?: string
  warnings?: string[]
  tasks?: Record<string, any>[]
  task_results?: Record<string, any>
  conversation_id: string
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

/** 对话请求体 */
export interface ChatRequest {
  message: string
  customer_id: string
  chat_history: Array<{ role: string; content: string }>
  conversation_id?: string
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

export type SSEEvent = SSEStageEvent | SSEResponseEvent | SSEErrorEvent

/** SSE 事件回调 */
export interface StreamCallbacks {
  onStage: (event: SSEStageEvent) => void
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
