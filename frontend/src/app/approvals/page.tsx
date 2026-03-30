"use client"
import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { api } from "@/lib/api-client"
import ApprovalCard, { Intent } from "@/components/ApprovalCard"

type Tab = "pending" | "all"

export default function ApprovalsPage() {
  const router = useRouter()
  const [intents, setIntents] = useState<Intent[]>([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<Tab>("pending")
  const [error, setError] = useState("")

  useEffect(() => {
    if (!localStorage.getItem("access_token")) {
      router.replace("/login")
    }
  }, [router])

  async function load(activeTab: Tab) {
    setLoading(true)
    setError("")
    try {
      const statusFilter = activeTab === "pending" ? "pending_approval" : undefined
      const data = await api.getApprovals(statusFilter)
      setIntents(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load approvals")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load(tab) }, [tab])

  async function handleApprove(id: string) {
    const idempotencyKey = crypto.randomUUID()
    await api.approveIntent(id, idempotencyKey)
    // Don't reload — ApprovalCard updates its own local status
  }

  async function handleReject(id: string) {
    await api.rejectIntent(id)
    // Don't reload — ApprovalCard updates its own local status
  }

  const pendingCount = intents.filter((i) => i.status === "pending_approval").length

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 px-4 py-8">
      <div className="max-w-2xl mx-auto">

        {/* Header */}
        <div className="flex items-center gap-4 mb-6">
          <Link href="/dashboard" className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white transition-colors">
            ← Dashboard
          </Link>
          <div className="flex-1">
            <h1 className="text-2xl font-bold text-zinc-900 dark:text-white">Approvals</h1>
            {pendingCount > 0 && (
              <p className="text-sm text-zinc-500 mt-0.5">{pendingCount} action{pendingCount !== 1 ? "s" : ""} awaiting review</p>
            )}
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mb-6 bg-zinc-100 dark:bg-zinc-900 rounded-lg p-1 w-fit">
          {(["pending", "all"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                tab === t
                  ? "bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white shadow-sm"
                  : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
              }`}
            >
              {t === "pending" ? "Pending" : "All"}
            </button>
          ))}
        </div>

        {/* Content */}
        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-32 rounded-xl bg-zinc-100 dark:bg-zinc-900 animate-pulse" />
            ))}
          </div>
        ) : error ? (
          <div className="rounded-xl border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950 p-4 text-sm text-red-600 dark:text-red-400">
            {error}
          </div>
        ) : intents.length === 0 ? (
          <div className="text-center py-20 text-zinc-500">
            <div className="w-12 h-12 rounded-full bg-zinc-100 dark:bg-zinc-900 flex items-center justify-center mx-auto mb-4">
              <svg className="w-6 h-6 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <p className="text-base font-medium mb-1">
              {tab === "pending" ? "All clear" : "No approvals yet"}
            </p>
            <p className="text-sm">
              {tab === "pending"
                ? "No pending recommendations right now."
                : "Approve an intent from the chat to see it here."}
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {intents.map((intent) => (
              <ApprovalCard
                key={intent.id}
                intent={intent}
                onApprove={() => handleApprove(intent.id)}
                onReject={() => handleReject(intent.id)}
              />
            ))}
          </div>
        )}

      </div>
    </div>
  )
}
