const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

function getToken(): string | null {
  if (typeof window === "undefined") return null
  return localStorage.getItem("access_token")
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken()
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  })

  if (res.status === 401) {
    localStorage.removeItem("access_token")
    window.location.href = "/login"
    throw new Error("Unauthorized")
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Request failed: ${res.status}`)
  }

  if (res.status === 204) return null as T
  return res.json()
}

export const api = {
  // Auth
  register: (body: { email: string; password: string; full_name?: string }) =>
    request("/api/v1/auth/register", { method: "POST", body: JSON.stringify(body) }),

  login: (body: { email: string; password: string }) =>
    request<{ access_token: string; refresh_token: string }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // Plaid
  getLinkToken: () => request<{ link_token: string }>("/api/v1/plaid/link-token", { method: "POST" }),

  exchangePublicToken: (body: { public_token: string; institution_name?: string }) =>
    request("/api/v1/plaid/exchange", { method: "POST", body: JSON.stringify(body) }),

  getItems: () => request("/api/v1/plaid/items"),

  // Accounts & Transactions
  getAccounts: () => request("/api/v1/accounts"),

  getTransactions: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : ""
    return request(`/api/v1/transactions${qs}`)
  },

  getFinancialState: () => request("/api/v1/transactions/state"),

  // Intents & Approvals
  getPendingApprovals: () => request("/api/v1/approvals"),

  approveIntent: (intentId: string, idempotencyKey: string) =>
    request(`/api/v1/approvals/${intentId}/approve`, {
      method: "POST",
      body: JSON.stringify({ idempotency_key: idempotencyKey }),
    }),

  rejectIntent: (intentId: string, reason?: string) =>
    request(`/api/v1/approvals/${intentId}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),

  // Chat
  createChatSession: () => request("/api/v1/chat/sessions", { method: "POST" }),

  getChatSessions: () => request("/api/v1/chat/sessions"),

  getChatMessages: (sessionId: string) => request(`/api/v1/chat/sessions/${sessionId}/messages`),

  sendMessage: (sessionId: string, content: string): EventSource => {
    // Returns raw EventSource for SSE streaming
    const token = getToken()
    // For SSE POST we use fetch with ReadableStream instead
    return new EventSource(
      `${BASE_URL}/api/v1/chat/sessions/${sessionId}/messages?content=${encodeURIComponent(content)}&token=${token}`
    )
  },
}

export function streamChat(sessionId: string, content: string, onDelta: (text: string) => void, onDone: () => void) {
  const token = getToken()
  fetch(`${BASE_URL}/api/v1/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ content }),
  }).then(async (res) => {
    const reader = res.body?.getReader()
    const decoder = new TextDecoder()
    if (!reader) return
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const chunk = decoder.decode(value)
      const lines = chunk.split("\n").filter((l) => l.startsWith("data: "))
      for (const line of lines) {
        const data = line.replace("data: ", "").trim()
        if (data === "[DONE]") { onDone(); return }
        try {
          const { delta } = JSON.parse(data)
          onDelta(delta)
        } catch {}
      }
    }
  })
}
