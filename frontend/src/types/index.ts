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

/** 资产配置结果 */
export interface AllocationResult {
  weights: Record<string, number>
  expected_return: number
  expected_volatility: number
  sharpe_ratio: number
  allocation_amounts: Record<string, number>
}

/** 对话响应（与后端 ChatResponse 对齐） */
export interface ChatResponse {
  response: string
  task_plan: string[]
  user_profile: UserProfile
  stock_data: Record<string, any>
  fundamental_analysis: Record<string, any>
  allocation_result: AllocationResult
  compliance_result: Record<string, any>
  conversation_id: string
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
  stage: string
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
}

/** 登录响应 */
export interface LoginResponse {
  customer_id: string
  username: string
  display_name: string
  token: string
  expires_in: number
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
