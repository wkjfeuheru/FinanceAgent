/** 对话与会话 API。 */

import { http } from '@/api/client'
import { streamSSE } from '@/api/sse'
import type {
  ChatRequest,
  ChatResponse,
  Conversation,
  ConversationListResponse,
  HistoryMessage,
  HistoryResponse,
  HealthResponse,
  StreamCallbacks,
} from '@/features/chat/types'
import type { ProfileResponse } from '@/features/auth/types'

export async function chat(req: ChatRequest): Promise<ChatResponse> {
  const { data } = await http.post<ChatResponse>('/chat', req)
  return data
}

export function chatStream(req: ChatRequest, callbacks: StreamCallbacks, signal?: AbortSignal): Promise<void> {
  return streamSSE('/chat/stream', req, callbacks, signal)
}

export interface RunStatusPayload {
  run_status: string
  response?: string
  conversation_id?: string
  warnings?: string[]
}

export async function getRunStatus(taskId: string): Promise<RunStatusPayload> {
  const { data } = await http.get<RunStatusPayload>(`/runs/${encodeURIComponent(taskId)}`)
  return data
}

export async function stopChat(conversationId: string, runId = ''): Promise<void> {
  await http.post('/chat/stop', null, {
    params: { conversation_id: conversationId, run_id: runId },
  })
}

export async function healthCheck(): Promise<HealthResponse> {
  const { data } = await http.get<HealthResponse>('/health')
  return data
}

export async function getProfile(customerId: string): Promise<ProfileResponse> {
  const { data } = await http.get<ProfileResponse>(`/profile/${customerId}`)
  return data
}

export async function getHistory(customerId: string, limit = 50): Promise<HistoryResponse> {
  const { data } = await http.get<HistoryResponse>(`/history/${customerId}`, { params: { limit } })
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

export async function deleteConversation(customerId: string, conversationId: string): Promise<void> {
  await http.delete(`/conversations/${customerId}/${conversationId}`)
}
