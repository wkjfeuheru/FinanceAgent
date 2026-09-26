import type { UserProfile } from '../auth/types'
import type { AccountPayload } from '../portfolio/types'
import type { ProductAnalysisPayload, ResearchAnalysisResult, TechnicalAnalysis } from '../research/types'

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
  personalization_status?: string
  product_analysis?: ProductAnalysisPayload
  /** 账户领域载荷：资金/持仓查询与配置诊断共用。 */
  account?: AccountPayload
  compliance_result: Record<string, any>
  run_status?: string
  /** 异步量化任务的真实 job id 列表。 */
  pending_task_ids?: string[]
  task_id?: string
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
  /**
   * 落库时随消息一起保存的元数据。
   *
   * 目前只用于**图表最小载荷**：后端写助手消息时把 `analysis_results` /
   * `technical_analysis` 两个键存进来，使历史会话也能复原图表。
   * `conversation_messages.metadata` 是 jsonb，读取接口原本就原样返回它，
   * 前端此前从未消费。旧消息没有这些键，图表自然不显示。
   */
  metadata?: {
    task_plan?: string[]
    analysis_results?: Record<string, any>[]
    technical_analysis?: Record<string, any>
    [key: string]: any
  }
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

export interface RunStatusPayload {
  run_status: string
  response?: string
  conversation_id?: string
  warnings?: string[]
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
  /**
   * 服务端在节点边界下发的阶段标识。
   *
   * - `routing`：正在识别业务领域
   * - `scope`：正在拆解为各领域任务
   * - `domain:<domain>`：某个业务领域正在分析（多领域并行时每个领域一行）
   * - `clarify`：需要用户补充参数（随后会下发 pending_input 弹窗）
   * - `synthesize`：正在汇总结论
   * - `compliance`：正在合规校验
   *
   * 保留 `(string & {})` 以免新增阶段时前端类型阻塞。
   */
  stage: 'routing' | 'scope' | 'clarify' | 'synthesize' | 'compliance' | `domain:${string}` | (string & {})
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
