"use client"
import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { api } from "@/lib/api-client"
import PlaidLinkButton from "@/components/PlaidLink"

interface FinancialState {
  total_liquid_balance: number
  monthly_income_est: number | null
  monthly_expenses_est: number | null
  last_paycheck_amount: number | null
  pay_frequency: string | null
  emergency_fund_score: number | null
}

interface Account {
  id: string
  name: string
  official_name: string | null
  type: string
  subtype: string | null
  current_balance: number | null
  available_balance: number | null
}

interface PlaidItem {
  id: string
  institution_name: string | null
  status: string
  last_synced_at: string | null
}

function fmt(n: number | null | undefined) {
  if (n == null) return "—"
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n)
}

function AccountTypeIcon({ type }: { type: string }) {
  const base = "w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
  if (type === "depository") return <div className={`${base} bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300`}>$</div>
  if (type === "credit") return <div className={`${base} bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300`}>CC</div>
  return <div className={`${base} bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400`}>?</div>
}

export default function DashboardPage() {
  const router = useRouter()
  const [state, setState] = useState<FinancialState | null>(null)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [items, setItems] = useState<PlaidItem[]>([])
  const [pendingCount, setPendingCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)

  async function loadData() {
    setLoading(true)
    try {
      const [s, a, it, p] = await Promise.all([
        api.getFinancialState() as Promise<FinancialState>,
        api.getAccounts() as Promise<Account[]>,
        api.getPlaidItems() as Promise<PlaidItem[]>,
        api.getPendingApprovals() as Promise<unknown[]>,
      ])
      setState(s)
      setAccounts(a)
      setItems(it)
      setPendingCount(p.length)
    } catch {
      // 401 is handled in api-client (redirects to /login)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!localStorage.getItem("access_token")) {
      router.replace("/login")
      return
    }
    loadData()
  }, [])

  async function syncAll() {
    if (items.length === 0) return
    setSyncing(true)
    try {
      await Promise.all(items.map((item) => api.syncTransactions(item.id)))
      await api.reclassifyTransactions()
      await loadData()
    } catch {
      // errors surfaced via loadData
    } finally {
      setSyncing(false)
    }
  }

  const hasAccounts = accounts.length > 0

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <div className="max-w-4xl mx-auto px-4 py-8">

        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-2xl font-bold text-zinc-900 dark:text-white">Dashboard</h1>
          <nav className="flex items-center gap-4 text-sm font-medium text-zinc-500">
            <Link href="/approvals" className="hover:text-zinc-900 dark:hover:text-white transition-colors">
              Approvals
              {pendingCount > 0 && (
                <span className="ml-1.5 rounded-full bg-blue-500 text-white px-1.5 py-0.5 text-xs">
                  {pendingCount}
                </span>
              )}
            </Link>
            <Link href="/chat" className="hover:text-zinc-900 dark:hover:text-white transition-colors">Chat</Link>
          </nav>
        </div>

        {/* Empty state — no banks linked */}
        {!loading && !hasAccounts && (
          <div className="rounded-2xl border-2 border-dashed border-zinc-200 dark:border-zinc-800 p-12 text-center mb-8">
            <div className="w-14 h-14 rounded-full bg-zinc-100 dark:bg-zinc-900 flex items-center justify-center mx-auto mb-4">
              <svg className="w-7 h-7 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
              </svg>
            </div>
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-white mb-1">No accounts linked yet</h2>
            <p className="text-sm text-zinc-500 mb-6">Connect your bank to start tracking your finances.</p>
            <Link
              href="/link"
              className="inline-flex items-center gap-2 rounded-full bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 px-6 py-2.5 text-sm font-medium hover:bg-zinc-700 dark:hover:bg-zinc-200 transition-colors"
            >
              Connect Bank
            </Link>
          </div>
        )}

        {/* Financial State cards — only shown when accounts are linked */}
        {hasAccounts && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
            {[
              { label: "Liquid Balance", value: fmt(state?.total_liquid_balance) },
              { label: "Monthly Income", value: fmt(state?.monthly_income_est) },
              { label: "Monthly Expenses", value: fmt(state?.monthly_expenses_est) },
              {
                label: "Emergency Fund",
                value: state?.emergency_fund_score != null
                  ? `${Number(state.emergency_fund_score).toFixed(1)} mo`
                  : "—",
              },
            ].map((card) => (
              <div
                key={card.label}
                className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4"
              >
                <p className="text-xs text-zinc-500 mb-1">{card.label}</p>
                <p className="text-xl font-semibold text-zinc-900 dark:text-white">{card.value}</p>
              </div>
            ))}
          </div>
        )}

        {/* Linked Accounts */}
        {hasAccounts && (
          <div className="mb-8">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-base font-semibold text-zinc-900 dark:text-white">Accounts</h2>
              <div className="flex items-center gap-2">
                {items.map((item) => (
                  <span key={item.id} className="text-xs text-zinc-400">
                    {item.institution_name}
                    {item.last_synced_at && (
                      <span className="ml-1 text-zinc-300 dark:text-zinc-600">
                        · {new Date(item.last_synced_at).toLocaleDateString()}
                      </span>
                    )}
                  </span>
                ))}
                <button
                  onClick={syncAll}
                  disabled={syncing}
                  className="text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-white disabled:opacity-40 transition-colors"
                >
                  {syncing ? "Syncing…" : "Sync"}
                </button>
                <PlaidLinkButton onSuccess={loadData} />
              </div>
            </div>

            <div className="space-y-2">
              {accounts.map((acct) => (
                <div
                  key={acct.id}
                  className="flex items-center gap-3 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-4 py-3"
                >
                  <AccountTypeIcon type={acct.type} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-zinc-900 dark:text-white truncate">
                      {acct.official_name ?? acct.name}
                    </p>
                    <p className="text-xs text-zinc-500 capitalize">
                      {acct.type}{acct.subtype ? ` · ${acct.subtype}` : ""}
                    </p>
                  </div>
                  <div className="text-right shrink-0">
                    <p className="text-sm font-semibold text-zinc-900 dark:text-white">
                      {fmt(acct.current_balance)}
                    </p>
                    {acct.available_balance != null && acct.available_balance !== acct.current_balance && (
                      <p className="text-xs text-zinc-400">{fmt(acct.available_balance)} avail</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Loading skeleton */}
        {loading && (
          <div className="space-y-2 mb-8">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-16 rounded-xl bg-zinc-100 dark:bg-zinc-900 animate-pulse" />
            ))}
          </div>
        )}

        {/* Quick action links */}
        {hasAccounts && (
          <div className="flex gap-3">
            <Link
              href="/approvals"
              className="flex-1 text-center rounded-full border border-zinc-200 dark:border-zinc-700 py-2.5 text-sm font-medium text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
            >
              Review Approvals
            </Link>
            <Link
              href="/chat"
              className="flex-1 text-center rounded-full bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 py-2.5 text-sm font-medium hover:bg-zinc-700 dark:hover:bg-zinc-200 transition-colors"
            >
              Ask CashPilot
            </Link>
          </div>
        )}

      </div>
    </div>
  )
}
