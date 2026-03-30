"use client"
import { useEffect, useState } from "react"
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
  type: string
  subtype: string
  current_balance: number
  available_balance: number | null
}

function fmt(n: number | null) {
  if (n === null) return "—"
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n)
}

export default function DashboardPage() {
  const [state, setState] = useState<FinancialState | null>(null)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [pendingCount, setPendingCount] = useState(0)

  useEffect(() => {
    api.getFinancialState().then((s) => setState(s as FinancialState))
    api.getAccounts().then((a) => setAccounts(a as Account[]))
    api.getPendingApprovals().then((a) => setPendingCount((a as unknown[]).length))
  }, [])

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 px-4 py-8 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-2xl font-bold text-zinc-900 dark:text-white">Dashboard</h1>
        <nav className="flex gap-4 text-sm font-medium text-zinc-500">
          <Link href="/approvals" className="hover:text-zinc-900 dark:hover:text-white">
            Approvals {pendingCount > 0 && <span className="ml-1 rounded-full bg-blue-500 text-white px-1.5 py-0.5 text-xs">{pendingCount}</span>}
          </Link>
          <Link href="/chat" className="hover:text-zinc-900 dark:hover:text-white">Chat</Link>
        </nav>
      </div>

      {/* Financial State Summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
        {[
          { label: "Liquid Balance", value: fmt(state?.total_liquid_balance ?? null) },
          { label: "Monthly Income", value: fmt(state?.monthly_income_est ?? null) },
          { label: "Monthly Expenses", value: fmt(state?.monthly_expenses_est ?? null) },
          { label: "Emergency Fund", value: state?.emergency_fund_score != null ? `${state.emergency_fund_score.toFixed(1)} mo` : "—" },
        ].map((card) => (
          <div key={card.label} className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4">
            <p className="text-xs text-zinc-500 mb-1">{card.label}</p>
            <p className="text-xl font-semibold text-zinc-900 dark:text-white">{card.value}</p>
          </div>
        ))}
      </div>

      {/* Accounts */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold text-zinc-900 dark:text-white">Accounts</h2>
          <PlaidLinkButton onSuccess={() => window.location.reload()} />
        </div>
        {accounts.length === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-300 dark:border-zinc-700 p-8 text-center text-zinc-500">
            No accounts linked yet. Connect your bank to get started.
          </div>
        ) : (
          <div className="space-y-2">
            {accounts.map((acct) => (
              <div key={acct.id} className="flex items-center justify-between rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-zinc-900 dark:text-white">{acct.name}</p>
                  <p className="text-xs text-zinc-500 capitalize">{acct.type} · {acct.subtype}</p>
                </div>
                <p className="text-sm font-semibold text-zinc-900 dark:text-white">{fmt(acct.current_balance)}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Quick links */}
      <div className="flex gap-3">
        <Link href="/approvals" className="flex-1 text-center rounded-full border border-zinc-200 dark:border-zinc-700 py-2.5 text-sm font-medium text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors">
          Review Approvals
        </Link>
        <Link href="/chat" className="flex-1 text-center rounded-full bg-zinc-900 text-white py-2.5 text-sm font-medium hover:bg-zinc-700 dark:bg-white dark:text-zinc-900 transition-colors">
          Ask CashPilot
        </Link>
      </div>
    </div>
  )
}
