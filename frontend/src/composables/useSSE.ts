import { ref, onUnmounted } from 'vue'
import { useAuthStore } from '@/stores/authStore'

export interface SSEEvent {
  event_type: string
  event_id: number
  correlation_id: string
  timestamp: string
  data: Record<string, unknown>
}

export interface UseSSEOptions {
  onTaskCreated?: (data: SSEEvent['data']) => void
  onTaskStatusChanged?: (data: SSEEvent['data']) => void
  onNodeStatusChanged?: (data: SSEEvent['data']) => void
  onSnapshotUpdated?: (data: SSEEvent['data']) => void
  onError?: (err: Event) => void
  onOpen?: () => void
  reconnectDelay?: number
  heartbeatTimeout?: number
}

export function useSSE(options: UseSSEOptions = {}) {
  const {
    onTaskCreated,
    onTaskStatusChanged,
    onNodeStatusChanged,
    onSnapshotUpdated,
    onError,
    onOpen,
    reconnectDelay = 3000,
    heartbeatTimeout = 60000,
  } = options

  const connected = ref(false)
  const lastEventId = ref(0)
  let source: EventSource | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let heartbeatTimer: ReturnType<typeof setTimeout> | null = null

  function clearTimers() {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (heartbeatTimer !== null) {
      clearTimeout(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  function resetHeartbeat() {
    if (heartbeatTimer !== null) {
      clearTimeout(heartbeatTimer)
    }
    heartbeatTimer = setTimeout(() => {
      if (source) {
        source.close()
        scheduleReconnect()
      }
    }, heartbeatTimeout)
  }

  function scheduleReconnect() {
    clearTimers()
    reconnectTimer = setTimeout(() => {
      connect()
    }, reconnectDelay)
  }

  function handleMessage(event: MessageEvent) {
    resetHeartbeat()
    try {
      const parsed = JSON.parse(event.data) as SSEEvent
      if (parsed.event_id > lastEventId.value) {
        lastEventId.value = parsed.event_id
      }

      switch (parsed.event_type) {
        case 'task:created':
          onTaskCreated?.(parsed.data)
          break
        case 'task:status_changed':
          onTaskStatusChanged?.(parsed.data)
          break
        case 'node:status_changed':
          onNodeStatusChanged?.(parsed.data)
          break
        case 'snapshot:updated':
          onSnapshotUpdated?.(parsed.data)
          break
      }
    } catch {
      // ignore parse errors
    }
  }

  function connect() {
    const auth = useAuthStore()
    if (!auth.accessToken) return

    if (source) {
      source.close()
    }

    // EventSource does not support custom HTTP headers (e.g. Authorization).
    // Pass the JWT token via query parameter so the backend can validate it.
    const url = `/api/v1/events/stream?token=${encodeURIComponent(auth.accessToken)}`
    source = new EventSource(url)

    source.addEventListener('auth:error', () => {
      // Token rejected by the server. Log out and redirect to login.
      connected.value = false
      clearTimers()
      auth.logout()
      window.location.href = '/login'
    })

    source.addEventListener('close', () => {
      if (source) {
        source.close()
        source = null
      }
    })

    source.onopen = () => {
      connected.value = true
      resetHeartbeat()
      onOpen?.()
    }

    source.onmessage = (event) => handleMessage(event)

    source.onerror = () => {
      connected.value = false
      // Note: EventSource.onerror does not expose HTTP status codes.
      // Auth errors are handled via the 'auth:error' SSE event above.
      // For other errors, clear the source and let reconnect logic retry.
      if (source) {
        source.close()
        source = null
      }
      onError?.(new Event('error'))
      scheduleReconnect()
    }
  }

  function disconnect() {
    clearTimers()
    if (source) {
      source.close()
      source = null
    }
    connected.value = false
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    connected,
    lastEventId,
    connect,
    disconnect,
  }
}
