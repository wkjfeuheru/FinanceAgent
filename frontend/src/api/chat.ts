/** API 调用封装：同步对话、流式对话、用户画像、历史记录、健康检查、用户认证 */

import axios from 'axios'
import type {
  ChatRequest,
  ChatResponse,
  HistoryResponse,
  ProfileResponse,
  HealthResponse,
  SSEEvent,
  SSEStageEvent,
  SSEResponseEvent,
  StreamCallbacks,
  LoginRequest,
  LoginResponse,
  RegisterRequest,
  RegisterResponse,
  UserInfo,
  ClearRecordsResponse,
  Conversation,
  ConversationListResponse,
  HistoryMessage,
} from '@/types'

const http = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ── 用户登录态管理（localStorage）──────────────────────────────
const STORAGE_KEY = 'finance_cs_user'

/** 保存登录用户信息到 localStorage */
export function saveUser(user: UserInfo): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(user))
}

/** 获取当前登录用户信息（无则返回 null） */
export function getStoredUser(): UserInfo | null {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as UserInfo
  } catch {
    return null
  }
}

/** 获取当前 token（无则返回空字符串） */
export function getToken(): string {
  return getStoredUser()?.token || ''
}

/** 清除登录态 */
export function clearUser(): void {
  localStorage.removeItem(STORAGE_KEY)
}

// ── axios 请求拦截器：自动注入 Authorization 头与 customer_id ──
http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

/** 同步对话 */
export async function chat(req: ChatRequest): Promise<ChatResponse> {
  const { data } = await http.post<ChatResponse>('/chat', req)
  return data
}

/** 获取用户画像 */
export async function getProfile(customerId: string): Promise<ProfileResponse> {
  const { data } = await http.get<ProfileResponse>(`/profile/${customerId}`)
  return data
}

/** 获取对话历史 */
export async function getHistory(customerId: string, limit = 50): Promise<HistoryResponse> {
  const { data } = await http.get<HistoryResponse>(`/history/${customerId}`, {
    params: { limit },
  })
  return data
}

export async function createConversation(customerId: string): Promise<Conversation> {
  const { data } = await http.post<Conversation>(`/conversations/${customerId}`)
  return data
}

export async function getConversations(customerId: string): Promise<ConversationListResponse> {
  const { data } = await http.get<ConversationListResponse>(`/conversations/${customerId}`)
  return data
}

export async function getConversationMessages(
  customerId: string,
  conversationId: string,
  limit = 100,
): Promise<{ conversation_id: string; messages: HistoryMessage[] }> {
  const { data } = await http.get(`/conversations/${customerId}/${conversationId}/messages`, {
    params: { limit },
  })
  return data
}

export async function deleteConversation(
  customerId: string,
  conversationId: string,
): Promise<void> {
  await http.delete(`/conversations/${customerId}/${conversationId}`)
}

/** 健康检查 */
export async function healthCheck(): Promise<HealthResponse> {
  const { data } = await http.get<HealthResponse>('/health')
  return data
}

/**
 * SSE 流式对话：使用 fetch + ReadableStream（POST 请求）。
 * 后端通过 event: stage / event: response 推送事件。
 */
export async function chatStream(req: ChatRequest, callbacks: StreamCallbacks): Promise<void> {
  let response: Response
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), 300000)
  let terminalEventReceived = false

  const guardedCallbacks: StreamCallbacks = {
    onStage: callbacks.onStage,
    onResponse(event) {
      terminalEventReceived = true
      callbacks.onResponse(event)
    },
    onError(message) {
      terminalEventReceived = true
      callbacks.onError(message)
    },
  }
  try {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    }
    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`

    response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers,
      body: JSON.stringify(req),
      signal: controller.signal,
    })
  } catch (err: any) {
    window.clearTimeout(timeoutId)
    guardedCallbacks.onError(
      err?.name === 'AbortError' ? '分析超时，请稍后重试' : (err?.message || '网络连接失败'),
    )
    return
  }

  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => '')
    window.clearTimeout(timeoutId)
    guardedCallbacks.onError(`请求失败（${response.status}）：${text || response.statusText}`)
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // 按 SSE 事件块分割（每个事件以两个换行结尾）
      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() || ''

      for (const chunk of chunks) {
        const parsed = parseSSEChunk(chunk)
        if (!parsed) continue
        dispatchEvent(parsed, guardedCallbacks)
      }
    }
    // 处理缓冲区中剩余内容
    if (buffer.trim()) {
      const parsed = parseSSEChunk(buffer)
      if (parsed) dispatchEvent(parsed, guardedCallbacks)
    }
  } catch (err: any) {
    guardedCallbacks.onError(
      err?.name === 'AbortError' ? '分析超时，请稍后重试' : (err?.message || '流式读取失败'),
    )
  } finally {
    window.clearTimeout(timeoutId)
    if (!terminalEventReceived) {
      guardedCallbacks.onError('服务端连接已结束，但没有返回分析结果')
    }
  }
}

/** 解析单个 SSE 事件块 */
function parseSSEChunk(chunk: string): SSEEvent | null {
  const lines = chunk.split('\n')
  let eventType = 'message'
  let dataStr = ''
  for (const line of lines) {
    if (line.startsWith('event:')) {
      eventType = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataStr += line.slice(5).trim()
    }
  }
  if (!dataStr) return null
  try {
    const data = JSON.parse(dataStr)
    // 后端 data 内部带 type 字段，优先采用；否则用 SSE event 字段兜底
    const type = data.type || eventType
    return { ...data, type } as SSEEvent
  } catch {
    return null
  }
}

/** 分发 SSE 事件到对应回调 */
function dispatchEvent(event: SSEEvent, callbacks: StreamCallbacks): void {
  switch (event.type) {
    case 'stage':
      callbacks.onStage(event as SSEStageEvent)
      break
    case 'response':
      callbacks.onResponse(event as SSEResponseEvent)
      break
    case 'error':
      callbacks.onError((event as any).message || '服务端错误')
      break
    default:
      break
  }
}

// ── 用户认证 API ──────────────────────────────────────────────

/** 用户注册 */
export async function register(req: RegisterRequest): Promise<RegisterResponse> {
  const { data } = await http.post<RegisterResponse>('/register', req)
  return data
}

/** 用户登录：返回 token 与用户信息 */
export async function login(req: LoginRequest): Promise<LoginResponse> {
  const { data } = await http.post<LoginResponse>('/login', req)
  return data
}

/** 登出（撤销当前 token） */
export async function logout(): Promise<void> {
  try {
    await http.post('/logout')
  } catch {
    // 忽略登出失败
  } finally {
    clearUser()
  }
}

/** 获取当前登录用户信息（校验 token 有效性） */
export async function getCurrentUser(): Promise<UserInfo> {
  const { data } = await http.get<UserInfo>('/me')
  return data
}

/** 清除对话记录（管理接口） */
export async function clearRecords(
  customerId?: string,
  keepUsers = true,
): Promise<ClearRecordsResponse> {
  const { data } = await http.post<ClearRecordsResponse>('/admin/clear-records', null, {
    params: { customer_id: customerId, keep_users: keepUsers },
  })
  return data
}

export default {
  chat,
  chatStream,
  getProfile,
  getHistory,
  healthCheck,
  register,
  login,
  logout,
  getCurrentUser,
  clearRecords,
  saveUser,
  getStoredUser,
  getToken,
  clearUser,
}
