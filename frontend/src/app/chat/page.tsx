"use client"
import { useEffect, useRef, useState } from "react"
import Link from "next/link"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { api, streamChat } from "@/lib/api-client"

interface Message {
  role: "user" | "assistant"
  content: string
}

interface Intent {
  type: string
  title: string
  explanation: string
  amount: number | null
  confidence: number
}

type Segment =
  | { kind: "text"; content: string }
  | { kind: "intent"; data: Intent }

function parseSegments(raw: string): Segment[] {
  const segments: Segment[] = []
  const regex = /<intent>([\s\S]*?)<\/intent>/g
  let cursor = 0
  let match: RegExpExecArray | null

  while ((match = regex.exec(raw)) !== null) {
    if (match.index > cursor) {
      const text = raw.slice(cursor, match.index).trim()
      if (text) segments.push({ kind: "text", content: text })
    }
    try {
      const data = JSON.parse(match[1].trim()) as Intent
      segments.push({ kind: "intent", data })
    } catch {
      segments.push({ kind: "text", content: match[0] })
    }
    cursor = match.index + match[0].length
  }

  const remaining = raw.slice(cursor).trim()
  if (remaining) segments.push({ kind: "text", content: remaining })

  return segments
}

const INTENT_ICONS: Record<string, string> = {
  transfer_to_savings: "→",
  pay_bill: "📄",
  invest: "📈",
  alert: "⚠",
  suggestion: "💡",
}

type ApproveStatus = "idle" | "loading" | "approved" | "error"

function IntentCard({ data }: { data: Intent }) {
  const [status, setStatus] = useState<ApproveStatus>("idle")
  const [errorMsg, setErrorMsg] = useState("")
  const icon = INTENT_ICONS[data.type] ?? "💡"
  const confidencePct = Math.round((data.confidence ?? 0) * 100)

  async function handleApprove() {
    setStatus("loading")
    setErrorMsg("")
    try {
      await api.approveChatIntent({
        intent_type: data.type,
        title: data.title,
        explanation: data.explanation,
        amount: data.amount,
        confidence: data.confidence,
        idempotency_key: crypto.randomUUID(),
      })
      setStatus("approved")
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Approval failed")
      setStatus("error")
    }
  }

  return (
    <div className={`mt-3 rounded-xl border p-4 transition-colors ${
      status === "approved"
        ? "border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950"
        : "border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800"
    }`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-base leading-none">{icon}</span>
            <span className="text-sm font-semibold text-zinc-900 dark:text-white">{data.title}</span>
          </div>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-2">{data.explanation}</p>
          <div className="flex items-center gap-3 text-xs text-zinc-400">
            {data.amount != null && (
              <span className="font-medium text-zinc-600 dark:text-zinc-300">
                ${Math.abs(data.amount).toLocaleString("en-US", { minimumFractionDigits: 2 })}
              </span>
            )}
            <span>{confidencePct}% confidence</span>
          </div>
          {status === "error" && (
            <p className="mt-1.5 text-xs text-red-500">{errorMsg}</p>
          )}
        </div>

        {status === "approved" ? (
          <span className="shrink-0 flex items-center gap-1 text-xs font-medium text-green-600 dark:text-green-400">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
            Approved
          </span>
        ) : (
          <button
            onClick={handleApprove}
            disabled={status === "loading"}
            className="shrink-0 rounded-full bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 px-3 py-1.5 text-xs font-medium hover:bg-zinc-700 dark:hover:bg-zinc-200 disabled:opacity-50 transition-colors"
          >
            {status === "loading" ? "Approving…" : "Approve"}
          </button>
        )}
      </div>
    </div>
  )
}

function AssistantContent({ content, streaming }: { content: string; streaming: boolean }) {
  if (!content) {
    return streaming ? <span className="animate-pulse text-zinc-400">…</span> : null
  }

  const segments = parseSegments(content)

  return (
    <div className="space-y-1">
      {segments.map((seg, i) => {
        if (seg.kind === "intent") {
          return (
            <IntentCard
              key={i}
              data={seg.data}
            />
          )
        }
        return (
          <div key={i} className="prose prose-sm dark:prose-invert max-w-none prose-p:my-1 prose-headings:my-2 prose-table:text-xs">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {seg.content}
            </ReactMarkdown>
          </div>
        )
      })}
    </div>
  )
}

export default function ChatPage() {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [streaming, setStreaming] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.createChatSession().then((s) => {
      const session = s as { id: string }
      setSessionId(session.id)
    })
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  async function sendMessage() {
    if (!sessionId || !input.trim() || streaming) return
    const content = input.trim()
    setInput("")
    setMessages((prev) => [...prev, { role: "user", content }])
    setMessages((prev) => [...prev, { role: "assistant", content: "" }])
    setStreaming(true)

    streamChat(
      sessionId,
      content,
      (delta) => {
        setMessages((prev) => {
          const updated = [...prev]
          updated[updated.length - 1] = {
            role: "assistant",
            content: updated[updated.length - 1].content + delta,
          }
          return updated
        })
      },
      () => setStreaming(false),
    )
  }

  return (
    <div className="flex flex-col h-screen bg-zinc-50 dark:bg-zinc-950">
      {/* Header */}
      <div className="border-b border-zinc-200 dark:border-zinc-800 px-4 py-3 flex items-center gap-4">
        <Link href="/dashboard" className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white">← Dashboard</Link>
        <h1 className="text-base font-semibold text-zinc-900 dark:text-white">CashPilot Chat</h1>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4 max-w-2xl mx-auto w-full">
        {messages.length === 0 && (
          <div className="text-center text-zinc-500 mt-16">
            <p className="text-lg font-medium mb-2">Ask me anything about your finances</p>
            <p className="text-sm">Try: "How much did I spend last month?" or "Should I move money to savings?"</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            {msg.role === "user" ? (
              <div className="max-w-sm rounded-2xl px-4 py-2.5 text-sm bg-zinc-900 text-white dark:bg-white dark:text-zinc-900">
                {msg.content}
              </div>
            ) : (
              <div className="max-w-prose w-full rounded-2xl px-4 py-3 text-sm bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-zinc-900 dark:text-white">
                <AssistantContent
                  content={msg.content}
                  streaming={streaming && i === messages.length - 1}
                />
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-zinc-200 dark:border-zinc-800 px-4 py-3 max-w-2xl mx-auto w-full">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage()}
            placeholder="Ask about your finances…"
            disabled={streaming || !sessionId}
            className="flex-1 rounded-full border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-4 py-2 text-sm text-zinc-900 dark:text-white outline-none focus:ring-2 focus:ring-zinc-500 disabled:opacity-50"
          />
          <button
            onClick={sendMessage}
            disabled={streaming || !input.trim() || !sessionId}
            className="rounded-full bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 px-4 py-2 text-sm font-medium disabled:opacity-40 hover:bg-zinc-700 dark:hover:bg-zinc-200 transition-colors"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  )
}
