"use client"
import { useState } from "react"

interface Intent {
  id: string
  intent_type: string
  title: string
  explanation: string
  amount: number | null
  confidence_score: number | null
  expires_at: string | null
}

interface Props {
  intent: Intent
  onApprove: () => Promise<void>
  onReject: () => Promise<void>
}

const TYPE_LABELS: Record<string, string> = {
  transfer_to_savings: "Savings Transfer",
  pay_bill: "Bill Payment",
  invest: "Investment",
  alert: "Alert",
  suggestion: "Suggestion",
}

function fmt(n: number | null) {
  if (n === null) return null
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n)
}

export default function ApprovalCard({ intent, onApprove, onReject }: Props) {
  const [acting, setActing] = useState<"approve" | "reject" | null>(null)

  async function handleApprove() {
    setActing("approve")
    try { await onApprove() } finally { setActing(null) }
  }

  async function handleReject() {
    setActing("reject")
    try { await onReject() } finally { setActing(null) }
  }

  const isActionable = intent.intent_type !== "alert" && intent.intent_type !== "suggestion"

  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5">
      <div className="flex items-start justify-between mb-3">
        <div>
          <span className="inline-block rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 text-xs font-medium px-2.5 py-0.5 mb-2">
            {TYPE_LABELS[intent.intent_type] ?? intent.intent_type}
          </span>
          <h3 className="text-base font-semibold text-zinc-900 dark:text-white">{intent.title}</h3>
        </div>
        {intent.amount && (
          <span className="text-lg font-bold text-zinc-900 dark:text-white">{fmt(intent.amount)}</span>
        )}
      </div>

      <p className="text-sm text-zinc-600 dark:text-zinc-400 mb-4 leading-relaxed">{intent.explanation}</p>

      {intent.confidence_score && (
        <div className="mb-4">
          <div className="flex items-center justify-between text-xs text-zinc-500 mb-1">
            <span>Confidence</span>
            <span>{Math.round(intent.confidence_score * 100)}%</span>
          </div>
          <div className="h-1.5 rounded-full bg-zinc-100 dark:bg-zinc-800">
            <div
              className="h-1.5 rounded-full bg-blue-500"
              style={{ width: `${intent.confidence_score * 100}%` }}
            />
          </div>
        </div>
      )}

      {isActionable && (
        <div className="flex gap-2">
          <button
            onClick={handleApprove}
            disabled={acting !== null}
            className="flex-1 rounded-full bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 py-2 text-sm font-medium hover:bg-zinc-700 dark:hover:bg-zinc-200 disabled:opacity-50 transition-colors"
          >
            {acting === "approve" ? "Approving…" : "Approve"}
          </button>
          <button
            onClick={handleReject}
            disabled={acting !== null}
            className="flex-1 rounded-full border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 py-2 text-sm font-medium hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50 transition-colors"
          >
            {acting === "reject" ? "Rejecting…" : "Reject"}
          </button>
        </div>
      )}
    </div>
  )
}
