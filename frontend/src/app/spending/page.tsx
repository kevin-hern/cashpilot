"use client"
import { useEffect, useState } from "react"
import Link from "next/link"
import { api } from "@/lib/api-client"

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

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
]

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n)
}

function formatCategory(cat: string) {
  return cat
    .toLowerCase()
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function DonutChart({ categories, total }: { categories: CategoryBreakdown[]; total: number }) {
  const R = 70
  const cx = 90
  const cy = 90
  const circumference = 2 * Math.PI * R

  let offset = 0
  const slices = categories.map((cat, i) => {
    const pct = total > 0 ? cat.total / total : 0
    const dash = pct * circumference
    const gap = circumference - dash
    const slice = { offset, dash, gap, color: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }
    offset += dash
    return slice
  })

  if (total === 0) {
    return (
      <div className="flex items-center justify-center h-[180px] text-zinc-400 text-sm">
        No spending data
      </div>
    )
  }

  return (
    <svg width={180} height={180} className="mx-auto">
      <circle cx={cx} cy={cy} r={R} fill="none" stroke="#f4f4f5" strokeWidth={28} />
      {slices.map((s, i) => (
        <circle
          key={i}
          cx={cx}
          cy={cy}
          r={R}
          fill="none"
          stroke={s.color}
          strokeWidth={28}
          strokeDasharray={`${s.dash} ${s.gap}`}
          strokeDashoffset={circumference / 4 - s.offset}
          strokeLinecap="butt"
        />
      ))}
      <text x={cx} y={cy - 8} textAnchor="middle" className="fill-zinc-900 dark:fill-white" fontSize={11} fontWeight={500}>Total</text>
      <text x={cx} y={cy + 10} textAnchor="middle" className="fill-zinc-900 dark:fill-white" fontSize={13} fontWeight={700}>{fmt(total)}</text>
    </svg>
  )
}

function ChangeIndicator({ current, prev }: { current: number; prev: number | null }) {
  if (prev === null || prev === 0) return null
  const pct = ((current - prev) / prev) * 100
  const up = pct > 0
  return (
    <span className={`text-xs font-medium ${up ? "text-red-500" : "text-green-600"}`}>
      {up ? "▲" : "▼"} {Math.abs(pct).toFixed(0)}%
    </span>
  )
}

export default function SpendingPage() {
  const now = new Date()
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [year, setYear] = useState(now.getFullYear())
  const [data, setData] = useState<SpendingData | null>(null)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    api.getSpendingBreakdown(month, year)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [month, year])

  function prevMonth() {
    if (month === 1) { setMonth(12); setYear((y) => y - 1) }
    else setMonth((m) => m - 1)
  }

  function nextMonth() {
    const isCurrentMonth = month === now.getMonth() + 1 && year === now.getFullYear()
    if (isCurrentMonth) return
    if (month === 12) { setMonth(1); setYear((y) => y + 1) }
    else setMonth((m) => m + 1)
  }

  const isCurrentMonth = month === now.getMonth() + 1 && year === now.getFullYear()

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <div className="max-w-2xl mx-auto px-4 py-8">

        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <Link href="/dashboard" className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white">
              ← Dashboard
            </Link>
            <h1 className="text-xl font-bold text-zinc-900 dark:text-white">Spending</h1>
          </div>

          {/* Month selector */}
          <div className="flex items-center gap-2">
            <button
              onClick={prevMonth}
              className="rounded-full w-7 h-7 flex items-center justify-center border border-zinc-200 dark:border-zinc-700 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors text-sm"
            >
              ‹
            </button>
            <span className="text-sm font-medium text-zinc-900 dark:text-white w-32 text-center">
              {MONTH_NAMES[month - 1]} {year}
            </span>
            <button
              onClick={nextMonth}
              disabled={isCurrentMonth}
              className="rounded-full w-7 h-7 flex items-center justify-center border border-zinc-200 dark:border-zinc-700 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-30 transition-colors text-sm"
            >
              ›
            </button>
          </div>
        </div>

        {loading && (
          <div className="space-y-3">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-16 rounded-xl bg-zinc-100 dark:bg-zinc-900 animate-pulse" />
            ))}
          </div>
        )}

        {!loading && data && (
          <>
            {/* Donut chart */}
            <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 mb-4">
              <DonutChart categories={data.categories} total={data.total_spending} />
            </div>

            {/* Category list */}
            <div className="space-y-2">
              {data.categories.length === 0 && (
                <div className="text-center text-zinc-500 text-sm py-12">
                  No spending recorded for {MONTH_NAMES[month - 1]} {year}.
                </div>
              )}
              {data.categories.map((cat, i) => (
                <div
                  key={cat.category}
                  className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-hidden"
                >
                  <button
                    className="w-full px-4 py-3 flex items-center gap-3 text-left hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors"
                    onClick={() => setExpanded(expanded === cat.category ? null : cat.category)}
                  >
                    {/* Color dot */}
                    <span
                      className="w-3 h-3 rounded-full shrink-0"
                      style={{ backgroundColor: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }}
                    />

                    {/* Category name */}
                    <span className="flex-1 text-sm font-medium text-zinc-900 dark:text-white">
                      {formatCategory(cat.category)}
                    </span>

                    {/* Count */}
                    <span className="text-xs text-zinc-400 mr-2">{cat.count} txn{cat.count !== 1 ? "s" : ""}</span>

                    {/* Change vs prev month */}
                    <ChangeIndicator current={cat.total} prev={cat.prev_month_total} />

                    {/* Amount + percentage */}
                    <div className="text-right ml-2 shrink-0">
                      <p className="text-sm font-semibold text-zinc-900 dark:text-white">{fmt(cat.total)}</p>
                      <p className="text-xs text-zinc-400">{cat.percentage}%</p>
                    </div>

                    {/* Expand chevron */}
                    <svg
                      className={`w-4 h-4 text-zinc-400 ml-1 shrink-0 transition-transform ${expanded === cat.category ? "rotate-180" : ""}`}
                      fill="none" viewBox="0 0 24 24" stroke="currentColor"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>

                  {/* Progress bar */}
                  <div className="h-0.5 bg-zinc-100 dark:bg-zinc-800 mx-4">
                    <div
                      className="h-0.5 rounded-full"
                      style={{
                        width: `${cat.percentage}%`,
                        backgroundColor: CATEGORY_COLORS[i % CATEGORY_COLORS.length],
                      }}
                    />
                  </div>

                  {/* Top transactions (expanded) */}
                  {expanded === cat.category && cat.top_transactions.length > 0 && (
                    <div className="px-4 py-2 border-t border-zinc-100 dark:border-zinc-800">
                      <p className="text-xs text-zinc-400 mb-2">Top transactions</p>
                      <div className="space-y-1.5">
                        {cat.top_transactions.map((txn) => (
                          <div key={txn.id} className="flex items-center justify-between">
                            <span className="text-xs text-zinc-600 dark:text-zinc-400 truncate flex-1 mr-2">
                              {txn.merchant_name ?? txn.raw_name ?? "Unknown"}
                            </span>
                            <span className="text-xs text-zinc-500 mr-3 shrink-0">
                              {new Date(txn.posted_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                            </span>
                            <span className="text-xs font-medium text-zinc-900 dark:text-white shrink-0">
                              {fmt(txn.amount)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </>
        )}

        {!loading && !data && (
          <div className="text-center text-zinc-500 text-sm py-16">
            Failed to load spending data.
          </div>
        )}
      </div>
    </div>
  )
}
