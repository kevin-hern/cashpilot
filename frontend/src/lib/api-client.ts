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
    if (typeof window !== "undefined") {
      localStorage.removeItem("access_token")
      window.location.href = "/login"
    }
    throw new Error("Unauthorized")
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail || `Request failed: ${res.status}`)
  }

  if (res.status === 204) return null as T
  return res.json() as Promise<T>
}

export const api = {
  login: (body: { email: string; password: string }) =>
    request<{ access_token: string; refresh_token: string }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getLinkToken: () =>
    request<{ link_token: string }>("/api/v1/plaid/link-token", { method: "POST" }),

  exchangePublicToken: (body: { public_token: string; institution_name?: string }) =>
    request("/api/v1/plaid/exchange", { method: "POST", body: JSON.stringify(body) }),

  getAccounts: () => request("/api/v1/accounts"),

  getFinancialState: () => request("/api/v1/transactions/state"),

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

  createChatSession: () =>
    request<{ id: string }>("/api/v1/chat/sessions", { method: "POST" }),
}

export function streamChat(
  sessionId: string,
  content: string,
  onDelta: (text: string) => void,
  onDone: () => void,
) {
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
    if (!reader) { onDone(); return }
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const chunk = decoder.decode(value)
      for (const line of chunk.split("\n")) {
        if (!line.startsWith("data: ")) continue
        const data = line.slice(6).trim()
        if (data === "[DONE]") { onDone(); return }
        try {
          const { delta } = JSON.parse(data) as { delta: string }
          onDelta(delta)
        } catch {}
      }
    }
    onDone()
  }).catch(() => onDone())
}
