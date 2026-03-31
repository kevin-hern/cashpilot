"use client"
import { useState } from "react"

export interface Intent {
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

const STATUS_CONFIG: Record<string, { label: string; classes: string }> = {
  pending_approval: { label: "Pending", classes: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-400" },
  approved:         { label: "Approved ✓", classes: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400" },
  executed:         { label: "Executed ✓", classes: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400" },
  rejected:         { label: "Rejected", classes: "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400" },
  failed:           { label: "Failed", classes: "bg-red-100 text-red-600 dark:bg-red-900/40 dark:text-red-400" },
  expired:          { label: "Expired", classes: "bg-zinc-100 text-zinc-400 dark:bg-zinc-800 dark:text-zinc-500" },
}

function fmt(n: number | null) {
  if (n === null) return null
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n)
}

function relativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

export default function ApprovalCard({ intent, onApprove, onReject }: Props) {
  const [acting, setActing] = useState<"approve" | "reject" | null>(null)
  const [localStatus, setLocalStatus] = useState(intent.status)

  async function handleApprove() {
    setActing("approve")
    try {
      await onApprove()
      setLocalStatus("executed")
    } catch {
      // parent handles error display
    } finally {
      setActing(null)
    }
  }

  async function handleReject() {
    setActing("reject")
    try {
      await onReject()
      setLocalStatus("rejected")
    } catch {
      // parent handles error display
    } finally {
      setActing(null)
    }
  }

  const isPending = localStatus === "pending_approval"
  // Show approve/dismiss for all pending intents except pure informational alerts
  const isActionable = isPending && intent.intent_type !== "alert"
  const statusCfg = STATUS_CONFIG[localStatus] ?? { label: localStatus, classes: "bg-zinc-100 text-zinc-500" }

  return (
    <div className={`rounded-xl border bg-white dark:bg-zinc-900 p-5 transition-colors ${
      localStatus === "executed" ? "border-green-200 dark:border-green-800" :
      localStatus === "rejected" ? "border-zinc-100 dark:border-zinc-800 opacity-60" :
      "border-zinc-200 dark:border-zinc-800"
    }`}>
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="inline-block rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 text-xs font-medium px-2.5 py-0.5">
            {TYPE_LABELS[intent.intent_type] ?? intent.intent_type}
          </span>
          <span className={`inline-block rounded-full text-xs font-medium px-2.5 py-0.5 ${statusCfg.classes}`}>
            {statusCfg.label}
          </span>
        </div>
        {intent.amount != null && (
          <span className="text-lg font-bold text-zinc-900 dark:text-white shrink-0 ml-2">{fmt(intent.amount)}</span>
        )}
      </div>

      {/* Title & explanation */}
      <h3 className="text-base font-semibold text-zinc-900 dark:text-white mb-1">{intent.title}</h3>
      <p className="text-sm text-zinc-600 dark:text-zinc-400 mb-3 leading-relaxed">{intent.explanation}</p>

      {/* Confidence bar */}
      {intent.confidence_score != null && (
        <div className="mb-3">
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

      {/* Footer: timestamp + actions */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-zinc-400">{relativeTime(intent.created_at)}</span>

        {isActionable ? (
          <div className="flex gap-2">
            <button
              onClick={handleApprove}
              disabled={acting !== null}
              className="rounded-full bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 px-4 py-1.5 text-xs font-medium hover:bg-zinc-700 dark:hover:bg-zinc-200 disabled:opacity-50 transition-colors"
            >
              {acting === "approve" ? "Approving…" : "Approve"}
            </button>
            <button
              onClick={handleReject}
              disabled={acting !== null}
              className="rounded-full border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 px-4 py-1.5 text-xs font-medium hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50 transition-colors"
            >
              {acting === "reject" ? "Rejecting…" : "Dismiss"}
            </button>
          </div>
        ) : (
          <span className="text-xs text-zinc-400 capitalize">{intent.generated_by}</span>
        )}
      </div>
    </div>
  )
}
