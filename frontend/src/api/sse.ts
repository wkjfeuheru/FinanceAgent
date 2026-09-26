import { clearUser, getToken } from '@/app/session'
import type {
  ChatRequest,
  SSEEvent,
  SSEStageEvent,
  SSEDeltaEvent,
  SSEResponseEvent,
  StreamCallbacks,
} from '@/features/chat/types'

/** 唯一的 POST SSE 传输，负责读取事件并按类型分发回调。 */
export async function streamSSE(
  path: string,
  payload: ChatRequest,
  callbacks: StreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const controller = new AbortController()
  const abortFromCaller = () => controller.abort(signal?.reason)
  if (signal?.aborted) abortFromCaller()
  else signal?.addEventListener('abort', abortFromCaller, { once: true })
  const idleTimeoutMs = 600000
  let timeoutId = 0
  const resetIdleTimeout = () => {
    if (timeoutId) window.clearTimeout(timeoutId)
    timeoutId = window.setTimeout(() => controller.abort(), idleTimeoutMs)
  }
  resetIdleTimeout()
  let terminalEventReceived = false
  const guardedCallbacks: StreamCallbacks = {
    onStage: callbacks.onStage,
    onDelta: callbacks.onDelta,
    onResponse(event) {
      terminalEventReceived = true
      callbacks.onResponse(event)
    },
    onError(message) {
      terminalEventReceived = true
      callbacks.onError(message)
    },
  }

  let response: Response
  try {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    }
    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`
    response = await fetch(`/api${path}`, {
      method: 'POST', headers, body: JSON.stringify(payload), signal: controller.signal,
    })
    resetIdleTimeout()
  } catch (err: any) {
    window.clearTimeout(timeoutId)
    signal?.removeEventListener('abort', abortFromCaller)
    guardedCallbacks.onError(
      err?.name === 'AbortError' ? '分析超时，请稍后重试' : (err?.message || '网络连接失败'),
    )
    return
  }

  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => '')
    window.clearTimeout(timeoutId)
    signal?.removeEventListener('abort', abortFromCaller)
    if (response.status === 401 && typeof window !== 'undefined') {
      clearUser()
      window.dispatchEvent(new CustomEvent('auth:expired'))
    }
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
      resetIdleTimeout()
      buffer += decoder.decode(value, { stream: true })
      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() || ''
      for (const chunk of chunks) {
        const parsed = parseSSEChunk(chunk)
        if (parsed) dispatchEvent(parsed, guardedCallbacks)
      }
    }
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
    signal?.removeEventListener('abort', abortFromCaller)
    if (!terminalEventReceived) guardedCallbacks.onError('服务端连接已结束，但没有返回分析结果')
  }
}

function parseSSEChunk(chunk: string): SSEEvent | null {
  const lines = chunk.split('\n')
  let eventType = 'message'
  let dataStr = ''
  for (const line of lines) {
    if (line.startsWith('event:')) eventType = line.slice(6).trim()
    else if (line.startsWith('data:')) dataStr += line.slice(5).trim()
  }
  if (!dataStr) return null
  try {
    const data = JSON.parse(dataStr)
    return { ...data, type: data.type || eventType } as SSEEvent
  } catch {
    return null
  }
}

function dispatchEvent(event: SSEEvent, callbacks: StreamCallbacks): void {
  switch (event.type) {
    case 'stage': callbacks.onStage(event as SSEStageEvent); break
    case 'delta': callbacks.onDelta?.(event as SSEDeltaEvent); break
    case 'response': callbacks.onResponse(event as SSEResponseEvent); break
    case 'error': callbacks.onError((event as any).message || '服务端错误'); break
  }
}
