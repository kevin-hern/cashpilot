"use client"
import { useEffect, useRef, useState } from "react"
import Link from "next/link"
import { api, streamChat } from "@/lib/api-client"

interface Message {
  role: "user" | "assistant"
  content: string
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
            <div className={`max-w-sm rounded-2xl px-4 py-2.5 text-sm ${
              msg.role === "user"
                ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900"
                : "bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-zinc-900 dark:text-white"
            }`}>
              {msg.content || (streaming && msg.role === "assistant" ? <span className="animate-pulse">…</span> : "")}
            </div>
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
