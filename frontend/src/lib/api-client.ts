// NEXT_PUBLIC_API_URL must be set in Vercel → Settings → Environment Variables
// before building. It is baked into the JS bundle at build time; changing it
// in the dashboard requires a new deployment to take effect.
const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

if (typeof window !== "undefined") {
  console.log("[CashPilot] API base URL:", BASE_URL)
  if (!process.env.NEXT_PUBLIC_API_URL) {
    console.warn("[CashPilot] NEXT_PUBLIC_API_URL not set at build time — using localhost fallback. In production, set this in Vercel and redeploy.")
  }
}

function getToken(): string | null {
  if (typeof window === "undefined") return null
  return localStorage.getItem("access_token")
}

function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null
  return localStorage.getItem("refresh_token")
}

async function tryRefresh(): Promise<string | null> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return null
  try {
    const res = await fetch(`${BASE_URL}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!res.ok) return null
    const data = await res.json() as { access_token: string; refresh_token: string }
    localStorage.setItem("access_token", data.access_token)
    localStorage.setItem("refresh_token", data.refresh_token)
    console.log("[CashPilot] Token refreshed successfully")
    return data.access_token
  } catch {
    return null
  }
}

async function request<T>(path: string, options: RequestInit = {}, retry = true): Promise<T> {
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
    if (retry && typeof window !== "undefined") {
      // Try to refresh the access token once, then retry the request
      const newToken = await tryRefresh()
      if (newToken) {
        return request<T>(path, options, false)
      }
      // Refresh failed — clear tokens and redirect to login
      localStorage.removeItem("access_token")
      localStorage.removeItem("refresh_token")
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
  // ── Auth ──────────────────────────────────────────────────────────────────
  login: (body: { email: string; password: string }) =>
    request<{ access_token: string; refresh_token: string }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  register: (body: { email: string; password: string; full_name?: string }) =>
    request("/api/v1/auth/register", { method: "POST", body: JSON.stringify(body) }),

  // ── Plaid ─────────────────────────────────────────────────────────────────
  getLinkToken: () =>
    request<{ link_token: string }>("/api/v1/plaid/link-token", { method: "POST" }),

  exchangePublicToken: (body: { public_token: string; institution_name?: string }) =>
    request("/api/v1/plaid/exchange", { method: "POST", body: JSON.stringify(body) }),

  getPlaidItems: () =>
    request<Array<{ id: string; institution_name: string | null; status: string; last_synced_at: string | null }>>("/api/v1/plaid/items"),

  syncTransactions: (itemId: string) =>
    request(`/api/v1/plaid/sync/${itemId}`, { method: "POST" }),

  reclassifyTransactions: () =>
    request<{
      reclassified: number
      paychecks_created: number
      monthly_income_est: number
      monthly_expenses_est: number
      total_liquid_balance: number
    }>("/api/v1/transactions/reclassify", { method: "POST" }),

  // ── Accounts ──────────────────────────────────────────────────────────────
  getAccounts: () =>
    request<Array<{
      id: string
      name: string
      official_name: string | null
      type: string
      subtype: string | null
      current_balance: number | null
      available_balance: number | null
      plaid_item_id: string
    }>>("/api/v1/accounts/"),

  // ── Transactions & State ──────────────────────────────────────────────────
  getFinancialState: () =>
    request<{
      total_liquid_balance: number
      monthly_income_est: number | null
      monthly_expenses_est: number | null
      last_paycheck_amount: number | null
      pay_frequency: string | null
      emergency_fund_score: number | null
    }>("/api/v1/transactions/state"),

  // ── Approvals ─────────────────────────────────────────────────────────────
  getPendingApprovals: () => request<unknown[]>("/api/v1/approvals?status=pending_approval"),

  getApprovals: (status?: string) =>
    request<Array<{
      id: string
      intent_type: string
      status: string
      title: string
      explanation: string
      amount: number | null
      confidence_score: number | null
      generated_by: string
      expires_at: string | null
      created_at: string
    }>>(`/api/v1/approvals${status ? `?status=${status}` : ""}`),

  approveChatIntent: (body: {
    intent_type: string
    title: string
    explanation: string
    amount: number | null
    confidence: number | null
    idempotency_key: string
  }) =>
    request<{ id: string; status: string; provider_txn_id: string | null }>("/api/v1/approvals/", {
      method: "POST",
      body: JSON.stringify(body),
    }),

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

  // ── Chat ──────────────────────────────────────────────────────────────────
  createChatSession: () =>
    request<{ id: string }>("/api/v1/chat/sessions", { method: "POST" }),

  getChatSessions: () => request("/api/v1/chat/sessions"),

  getChatMessages: (sessionId: string) =>
    request(`/api/v1/chat/sessions/${sessionId}/messages`),
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
