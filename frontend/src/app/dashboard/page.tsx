"use client"
import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { api } from "@/lib/api-client"
import PlaidLinkButton from "@/components/PlaidLink"
import SpendingChart from "@/components/SpendingChart"
import WidgetGrid from "@/components/WidgetGrid"

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
  plaid_account_id: string
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

interface TopTransaction {
  id: string
  raw_name: string | null
  merchant_name: string | null
  amount: number
  posted_at: string
}

interface CategoryBreakdown {
  category: string
  total: number
  count: number
  percentage: number
  prev_month_total: number | null
  top_transactions: TopTransaction[]
}

interface SpendingData {
  month: number
  year: number
  total_spending: number
  categories: CategoryBreakdown[]
}

const CATEGORY_COLORS = [
  "#3b82f6", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444",
  "#06b6d4", "#f97316", "#84cc16", "#ec4899", "#6366f1",
]

function fmt(n: number | null | undefined) {
  if (n == null) return "—"
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n)
}

function formatCategory(cat: string) {
  return cat.toLowerCase().replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
}

function AccountTypeIcon({ type }: { type: string }) {
  const base = "w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
  if (type === "depository") return <div className={`${base} bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300`}>$</div>
  if (type === "credit") return <div className={`${base} bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300`}>CC</div>
  return <div className={`${base} bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400`}>?</div>
}

function ChangeIndicator({ current, prev }: { current: number; prev: number | null }) {
  if (prev === null || prev === 0) return null
  const pct = ((current - prev) / prev) * 100
  const up = pct > 0
  return (
    <span className={`text-xs ${up ? "text-red-500" : "text-green-600"}`}>
      {up ? "▲" : "▼"}{Math.abs(pct).toFixed(0)}%
    </span>
  )
}

interface DonutChartProps {
  categories: CategoryBreakdown[]
  total: number
  selected: string | null
  onSelect: (cat: string | null) => void
}

function DonutChart({ categories, total, selected, onSelect }: DonutChartProps) {
  const R = 52
  const cx = 68
  const cy = 68
  const circumference = 2 * Math.PI * R
  const hasSelection = selected !== null

  if (total === 0) {
    return (
      <div className="flex items-center justify-center h-[136px] text-zinc-400 text-xs">
        No spending data
      </div>
    )
  }

  let offset = 0
  const slices = categories.slice(0, 10).map((cat, i) => {
    const pct = total > 0 ? cat.total / total : 0
    const dash = pct * circumference
    const gap = circumference - dash
    const slice = {
      cat: cat.category,
      offset,
      dash,
      gap,
      color: CATEGORY_COLORS[i % CATEGORY_COLORS.length],
      isSelected: selected === cat.category,
    }
    offset += dash
    return slice
  })

  return (
    <svg
      width={136}
      height={136}
      className="cursor-pointer shrink-0"
      onClick={() => onSelect(null)}
    >
      {/* Background track */}
      <circle cx={cx} cy={cy} r={R} fill="none" stroke="#f4f4f5" strokeWidth={22}
        className="dark:[stroke:#27272a]" />

      {slices.map((s, i) => (
        <circle
          key={i}
          cx={cx} cy={cy} r={R}
          fill="none"
          stroke={s.color}
          strokeWidth={s.isSelected ? 28 : 22}
          strokeDasharray={`${s.dash} ${s.gap}`}
          strokeDashoffset={circumference / 4 - s.offset}
          strokeLinecap="butt"
          opacity={hasSelection && !s.isSelected ? 0.25 : 1}
          style={{ transition: "opacity 0.15s ease, stroke-width 0.15s ease" }}
          className="cursor-pointer"
          onClick={(e) => {
            e.stopPropagation()
            onSelect(s.isSelected ? null : s.cat)
          }}
        />
      ))}

      {/* Center label */}
      {selected ? (
        <>
          <text x={cx} y={cy - 8} textAnchor="middle" fontSize={8} fontWeight={500}
            className="fill-zinc-500 pointer-events-none" style={{ userSelect: "none" }}>
            {formatCategory(selected).split(" ")[0]}
          </text>
          <text x={cx} y={cy + 7} textAnchor="middle" fontSize={11} fontWeight={700}
            className="fill-zinc-900 dark:fill-white pointer-events-none" style={{ userSelect: "none" }}>
            {fmt(categories.find((c) => c.category === selected)?.total ?? 0)}
          </text>
        </>
      ) : (
        <>
          <text x={cx} y={cy - 6} textAnchor="middle" fontSize={9} fontWeight={500}
            className="fill-zinc-500 pointer-events-none" style={{ userSelect: "none" }}>
            Total
          </text>
          <text x={cx} y={cy + 9} textAnchor="middle" fontSize={12} fontWeight={700}
            className="fill-zinc-900 dark:fill-white pointer-events-none" style={{ userSelect: "none" }}>
            {fmt(total)}
          </text>
        </>
      )}
    </svg>
  )
}

export default function DashboardPage() {
  const router = useRouter()
  const [state, setState] = useState<FinancialState | null>(null)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [items, setItems] = useState<PlaidItem[]>([])
  const [pendingCount, setPendingCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [unlinking, setUnlinking] = useState<string | null>(null)
  const [accountsOpen, setAccountsOpen] = useState(false)
  const [spending, setSpending] = useState<SpendingData | null>(null)
  const [spendingLoading, setSpendingLoading] = useState(false)
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)

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
      const seen = new Set<string>()
      setAccounts((a as Account[]).filter((acct) => {
        if (seen.has(acct.plaid_account_id)) return false
        seen.add(acct.plaid_account_id)
        return true
      }))
      setItems(it)
      setPendingCount(p.length)
    } catch {
      // 401 handled in api-client (redirects to /login)
    } finally {
      setLoading(false)
    }
  }

  async function loadSpending() {
    setSpendingLoading(true)
    const now = new Date()
    try {
      const d = await api.getSpendingBreakdown(now.getMonth() + 1, now.getFullYear())
      setSpending(d as SpendingData)
    } catch {
      // non-fatal
    } finally {
      setSpendingLoading(false)
    }
  }

  useEffect(() => {
    if (typeof window !== "undefined" && !localStorage.getItem("access_token")) {
      router.replace("/login")
      return
    }
    loadData()
    loadSpending()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function unlinkItem(itemId: string) {
    if (!confirm("Remove this bank connection? All associated accounts and transactions will be deleted.")) return
    setUnlinking(itemId)
    try {
      await api.unlinkItem(itemId)
      await loadData()
    } catch {
      // errors handled by api-client
    } finally {
      setUnlinking(null)
    }
  }

  async function syncAll() {
    if (items.length === 0) return
    setSyncing(true)
    try {
      await Promise.all(items.map((item) => api.syncTransactions(item.id)))
      await api.reclassifyTransactions()
      await Promise.all([loadData(), loadSpending()])
    } catch {
      // errors surfaced via loadData
    } finally {
      setSyncing(false)
    }
  }

  function handleSelectCategory(cat: string | null) {
    setSelectedCategory((prev) => (prev === cat ? null : cat))
  }

  const hasAccounts = accounts.length > 0
  const selectedCat = spending?.categories.find((c) => c.category === selectedCategory) ?? null

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

        {/* Empty state */}
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

        {/* Financial State cards */}
        {hasAccounts && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
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

        {/* Accounts — collapsible */}
        {hasAccounts && (
          <div className="mb-6 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-hidden">
            <button
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors"
              onClick={() => setAccountsOpen((o) => !o)}
            >
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-zinc-900 dark:text-white">
                  Accounts ({accounts.length})
                </span>
                {items.map((item) => (
                  <span key={item.id} className="text-xs text-zinc-400">
                    {item.institution_name}
                    {item.last_synced_at && (
                      <span className="text-zinc-300 dark:text-zinc-600">
                        {" "}· {new Date(item.last_synced_at).toLocaleDateString()}
                      </span>
                    )}
                  </span>
                ))}
              </div>
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                  {accountsOpen && items.map((item) => (
                    <button
                      key={item.id}
                      onClick={() => unlinkItem(item.id)}
                      disabled={unlinking === item.id}
                      className="text-xs text-red-400 hover:text-red-600 disabled:opacity-40 transition-colors"
                    >
                      {unlinking === item.id ? "Removing…" : "Remove"}
                    </button>
                  ))}
                  {accountsOpen && (
                    <button
                      onClick={syncAll}
                      disabled={syncing}
                      className="text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-white disabled:opacity-40 transition-colors"
                    >
                      {syncing ? "Syncing…" : "Sync"}
                    </button>
                  )}
                  {accountsOpen && <PlaidLinkButton onSuccess={loadData} />}
                </div>
                <svg
                  className={`w-4 h-4 text-zinc-400 transition-transform duration-200 ${accountsOpen ? "rotate-180" : ""}`}
                  fill="none" viewBox="0 0 24 24" stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </div>
            </button>

            <div
              className="overflow-hidden transition-all duration-300 ease-in-out"
              style={{ maxHeight: accountsOpen ? `${accounts.length * 72 + 16}px` : "0px" }}
            >
              <div className="px-3 pb-3 space-y-2">
                {accounts.map((acct) => (
                  <div
                    key={acct.id}
                    className="flex items-center gap-3 rounded-lg border border-zinc-100 dark:border-zinc-800 px-3 py-2.5"
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
          </div>
        )}

        {/* Loading skeleton */}
        {loading && (
          <div className="space-y-2 mb-6">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-16 rounded-xl bg-zinc-100 dark:bg-zinc-900 animate-pulse" />
            ))}
          </div>
        )}

        {/* Spending breakdown */}
        {hasAccounts && (
          <div className="mb-6 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-zinc-900 dark:text-white">
                Spending — {new Date().toLocaleString("default", { month: "long", year: "numeric" })}
              </h2>
              {selectedCategory && (
                <button
                  onClick={() => setSelectedCategory(null)}
                  className="text-xs text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 transition-colors"
                >
                  Clear
                </button>
              )}
            </div>

            {spendingLoading && (
              <div className="h-24 rounded-lg bg-zinc-100 dark:bg-zinc-800 animate-pulse" />
            )}

            {!spendingLoading && spending && spending.categories.length > 0 && (
              <>
                {/* Chart + legend row */}
                <div className="flex gap-5 items-start">
                  <DonutChart
                    categories={spending.categories}
                    total={spending.total_spending}
                    selected={selectedCategory}
                    onSelect={handleSelectCategory}
                  />

                  <div className="flex-1 min-w-0 space-y-1.5 py-1">
                    {spending.categories.slice(0, 8).map((cat, i) => {
                      const isSelected = selectedCategory === cat.category
                      const dimmed = selectedCategory !== null && !isSelected
                      return (
                        <button
                          key={cat.category}
                          className={`w-full flex items-center gap-2 rounded-md px-1.5 py-1 text-left transition-all ${
                            isSelected
                              ? "bg-zinc-100 dark:bg-zinc-800"
                              : "hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
                          } ${dimmed ? "opacity-40" : ""}`}
                          onClick={() => handleSelectCategory(cat.category)}
                        >
                          <span
                            className="w-2 h-2 rounded-full shrink-0"
                            style={{ backgroundColor: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }}
                          />
                          <span className="text-xs text-zinc-600 dark:text-zinc-400 flex-1 truncate">
                            {formatCategory(cat.category)}
                          </span>
                          <ChangeIndicator current={cat.total} prev={cat.prev_month_total} />
                          <span className="text-xs font-medium text-zinc-900 dark:text-white shrink-0">
                            {fmt(cat.total)}
                          </span>
                          <span className="text-xs text-zinc-400 w-8 text-right shrink-0">
                            {cat.percentage}%
                          </span>
                        </button>
                      )
                    })}
                    {spending.categories.length > 8 && (
                      <p className="text-xs text-zinc-400 pl-4">+{spending.categories.length - 8} more</p>
                    )}
                  </div>
                </div>

                {/* Transaction drill-down */}
                {selectedCat && (
                  <div className="mt-4 pt-4 border-t border-zinc-100 dark:border-zinc-800">
                    <p className="text-xs font-medium text-zinc-500 mb-2">
                      {selectedCat.count} transaction{selectedCat.count !== 1 ? "s" : ""} totaling{" "}
                      <span className="text-zinc-900 dark:text-white">{fmt(selectedCat.total)}</span>
                    </p>
                    <div className="space-y-1 max-h-52 overflow-y-auto pr-1">
                      {selectedCat.top_transactions.map((txn) => (
                        <div
                          key={txn.id}
                          className="flex items-center gap-3 py-1.5 text-xs border-b border-zinc-50 dark:border-zinc-800/60 last:border-0"
                        >
                          <span className="text-zinc-400 shrink-0 w-16">
                            {new Date(txn.posted_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                          </span>
                          <span className="flex-1 text-zinc-700 dark:text-zinc-300 truncate">
                            {txn.merchant_name ?? txn.raw_name ?? "Unknown"}
                          </span>
                          <span className="font-medium text-zinc-900 dark:text-white shrink-0">
                            {fmt(txn.amount)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}

            {!spendingLoading && spending && spending.categories.length === 0 && (
              <p className="text-xs text-zinc-400 py-4 text-center">No spending recorded this month.</p>
            )}

            {!spendingLoading && !spending && (
              <p className="text-xs text-zinc-400 py-4 text-center">Could not load spending data.</p>
            )}
          </div>
        )}

        {/* Spending over time chart */}
        {hasAccounts && (
          <div className="mb-6">
            <SpendingChart />
          </div>
        )}

        {/* AI-generated widgets */}
        {hasAccounts && (
          <div className="mb-6">
            <WidgetGrid />
          </div>
        )}

        {/* Quick action links */}
        {hasAccounts && (
          <div className="flex gap-3">
            <Link
              href="/approvals"
              className="flex-1 text-center rounded-full border border-zinc-200 dark:border-zinc-700 py-2.5 text-sm font-medium text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
            >
              Approvals
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
