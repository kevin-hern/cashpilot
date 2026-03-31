"use client"
import { useEffect, useState, useImperativeHandle, forwardRef } from "react"
import { api } from "@/lib/api-client"

export interface WidgetGridHandle {
  addWidget: (widget: { id: string; title: string; component_code: string }) => void
  refresh: () => void
}

interface Widget {
  id: string
  title: string
  description: string | null
  component_code: string
  created_at: string
}

interface FinancialData {
  accounts: Array<{ name: string; type: string; subtype: string | null; current_balance: number | null }>
  liquid_balance: number | null
  monthly_income: number | null
  monthly_expenses: number | null
  monthly_cash_flow: number | null
  transactions: Array<{ date: string; amount: number; name: string; category: string }>
  paychecks: Array<{ amount: number; source: string }>
}

function buildSrcdoc(code: string, data: FinancialData): string {
  // Escape </script> within JSON to avoid early termination of the inline script tag
  const safeJson = JSON.stringify(data).replace(/<\/script>/gi, "<\\/script>")
  const dataScript = `<script>window.CASHPILOT_DATA=${safeJson};</script>`

  if (code.includes("</head>")) {
    return code.replace("</head>", `${dataScript}</head>`)
  }
  if (code.includes("<body")) {
    return code.replace(/<body[^>]*>/, (m) => `${m}${dataScript}`)
  }
  return dataScript + code
}

function WidgetCard({
  widget,
  financialData,
  onDelete,
}: {
  widget: Widget
  financialData: FinancialData | null
  onDelete: (id: string) => void
}) {
  const [deleting, setDeleting] = useState(false)

  async function handleDelete() {
    if (!confirm(`Remove widget "${widget.title}"?`)) return
    setDeleting(true)
    try {
      await api.deleteWidget(widget.id)
      onDelete(widget.id)
    } catch {
      setDeleting(false)
    }
  }

  const srcdoc = financialData ? buildSrcdoc(widget.component_code, financialData) : widget.component_code

  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-hidden flex flex-col">
      {/* Title bar */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-100 dark:border-zinc-800">
        <span className="text-xs font-medium text-zinc-700 dark:text-zinc-300 truncate">{widget.title}</span>
        <button
          onClick={handleDelete}
          disabled={deleting}
          className="shrink-0 ml-2 w-5 h-5 flex items-center justify-center rounded text-zinc-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950 disabled:opacity-40 transition-colors"
          title="Remove widget"
        >
          {deleting ? (
            <span className="text-xs">…</span>
          ) : (
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          )}
        </button>
      </div>

      {/* Sandboxed iframe */}
      <iframe
        srcDoc={srcdoc}
        sandbox="allow-scripts"
        scrolling="no"
        className="w-full border-0"
        style={{ height: 386, display: "block" }}
        title={widget.title}
      />
    </div>
  )
}

const WidgetGrid = forwardRef<WidgetGridHandle, { className?: string }>(
  function WidgetGrid({ className = "" }, ref) {
    const [widgets, setWidgets] = useState<Widget[]>([])
    const [financialData, setFinancialData] = useState<FinancialData | null>(null)
    const [loading, setLoading] = useState(true)

    async function load() {
      setLoading(true)
      try {
        const [w, d] = await Promise.all([
          api.getWidgets(),
          api.getWidgetData(),
        ])
        setWidgets(w as Widget[])
        setFinancialData(d as FinancialData)
      } catch {
        // non-fatal
      } finally {
        setLoading(false)
      }
    }

    useEffect(() => { load() }, [])

    useImperativeHandle(ref, () => ({
      addWidget(w: { id: string; title: string; component_code: string }) {
        setWidgets((prev) => [
          { id: w.id, title: w.title, description: null, component_code: w.component_code, created_at: new Date().toISOString() },
          ...prev,
        ])
      },
      refresh: load,
    }))

    function handleDelete(id: string) {
      setWidgets((prev) => prev.filter((w) => w.id !== id))
    }

    if (loading) {
      return (
        <div className={`grid grid-cols-1 lg:grid-cols-2 gap-4 ${className}`}>
          {[1, 2].map((i) => (
            <div key={i} className="h-[420px] rounded-xl bg-zinc-100 dark:bg-zinc-900 animate-pulse" />
          ))}
        </div>
      )
    }

    if (widgets.length === 0) return null

    return (
      <div className={className}>
        <h2 className="text-sm font-semibold text-zinc-900 dark:text-white mb-3">My Widgets</h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {widgets.map((w) => (
            <WidgetCard
              key={w.id}
              widget={w}
              financialData={financialData}
              onDelete={handleDelete}
            />
          ))}
        </div>
      </div>
    )
  }
)

export default WidgetGrid
