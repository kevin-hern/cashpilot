"use client"
import { useEffect, useState } from "react"
import Link from "next/link"
import { api } from "@/lib/api-client"
import ApprovalCard from "@/components/ApprovalCard"

interface Intent {
  id: string
  intent_type: string
  title: string
  explanation: string
  amount: number | null
  confidence_score: number | null
  expires_at: string | null
  created_at: string
}

export default function ApprovalsPage() {
  const [intents, setIntents] = useState<Intent[]>([])
  const [loading, setLoading] = useState(true)

  async function load() {
    setLoading(true)
    try {
      const data = await api.getPendingApprovals()
      setIntents(data as Intent[])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function handleApprove(id: string) {
    const idempotencyKey = crypto.randomUUID()
    await api.approveIntent(id, idempotencyKey)
    await load()
  }

  async function handleReject(id: string) {
    await api.rejectIntent(id)
    await load()
  }

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 px-4 py-8 max-w-2xl mx-auto">
      <div className="flex items-center gap-4 mb-8">
        <Link href="/dashboard" className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white">← Dashboard</Link>
        <h1 className="text-2xl font-bold text-zinc-900 dark:text-white">Pending Approvals</h1>
      </div>

      {loading ? (
        <p className="text-zinc-500 text-sm">Loading…</p>
      ) : intents.length === 0 ? (
        <div className="text-center py-16 text-zinc-500">
          <p className="text-lg font-medium mb-2">All clear</p>
          <p className="text-sm">No pending recommendations right now.</p>
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
  )
}
