"use client"
import { useEffect, useState, useCallback } from "react"
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts"
import { api } from "@/lib/api-client"

type Granularity = "day" | "week" | "month" | "quarter"

interface Point {
  label: string
  start: string
  end: string
  total: number
}

// Drill-down stack entry
interface DrillFrame {
  granularity: Granularity
  year: number
  label: string   // breadcrumb label for this frame
}

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n)
}

function fmtFull(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n)
}

// Map a quarter/month label + year → the next granularity + year for drill-down
function drillTarget(granularity: Granularity, point: Point, year: number): { granularity: Granularity; year: number; label: string } | null {
  if (granularity === "quarter") {
    // Quarter → months of that quarter
    return { granularity: "month", year, label: `${point.label} ${year}` }
  }
  if (granularity === "month") {
    // Month → weeks containing that month
    return { granularity: "week", year, label: `${point.label} ${year}` }
  }
  if (granularity === "week") {
    // Week → days of that week
    return { granularity: "day", year, label: point.label }
  }
  return null  // day is the finest granularity
}

const GRANULARITY_LABELS: Record<Granularity, string> = {
  day: "Day",
  week: "Week",
  month: "Month",
  quarter: "Quarter",
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function CustomTooltip({ active, payload }: { active?: boolean; payload?: any[] }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload as Point
  const isSingleDay = d.start === d.end
  return (
    <div className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-md px-3 py-2 text-xs">
      <p className="font-semibold text-zinc-900 dark:text-white mb-0.5">{fmtFull(d.total)}</p>
      <p className="text-zinc-400">
        {isSingleDay
          ? new Date(d.start + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
          : `${new Date(d.start + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })} – ${new Date(d.end + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}`
        }
      </p>
    </div>
  )
}

// Custom dot that dims zero-value points and highlights on hover
function CustomDot(props: { cx?: number; cy?: number; payload?: Point; hoveredLabel?: string | null; onClick?: (p: Point) => void; canDrill?: boolean }) {
  const { cx, cy, payload, hoveredLabel, onClick, canDrill } = props
  if (!cx || !cy || !payload) return null
  const isHovered = hoveredLabel === payload.label
  const r = isHovered ? 5 : 3.5
  const opacity = payload.total === 0 ? 0.2 : 1
  return (
    <circle
      cx={cx} cy={cy} r={r}
      fill={isHovered ? "#3b82f6" : "#60a5fa"}
      stroke="white"
      strokeWidth={isHovered ? 2 : 1.5}
      opacity={opacity}
      style={{ cursor: canDrill ? "pointer" : "default", transition: "r 0.1s ease" }}
      onClick={() => payload && onClick?.(payload)}
    />
  )
}

export default function SpendingChart() {
  const now = new Date()
  const currentYear = now.getFullYear()

  const [stack, setStack] = useState<DrillFrame[]>([])  // breadcrumb history
  const [granularity, setGranularity] = useState<Granularity>("month")
  const [year, setYear] = useState(currentYear)
  const [points, setPoints] = useState<Point[]>([])
  const [loading, setLoading] = useState(true)
  const [hoveredLabel, setHoveredLabel] = useState<string | null>(null)

  const load = useCallback(async (g: Granularity, y: number) => {
    setLoading(true)
    try {
      const d = await api.getSpendingOverTime(g, y)
      setPoints(d.points)
    } catch {
      setPoints([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(granularity, year)
  }, [granularity, year, load])

  function selectTab(g: Granularity) {
    setStack([])
    setGranularity(g)
    setYear(currentYear)
  }

  function handlePointClick(point: Point) {
    const target = drillTarget(granularity, point, year)
    if (!target) return
    setStack((s) => [...s, { granularity, year, label: granularity === "month" ? `${year}` : `${year}` }])
    setGranularity(target.granularity)
    setYear(target.year)
  }

  function handleBack() {
    const prev = stack[stack.length - 1]
    if (!prev) return
    setStack((s) => s.slice(0, -1))
    setGranularity(prev.granularity)
    setYear(prev.year)
  }

  const canDrill = granularity !== "day"
  const maxVal = points.reduce((m, p) => Math.max(m, p.total), 0)
  const gradientId = "spendGrad"

  // Breadcrumb label
  const breadcrumb = stack.length > 0 ? stack.map((f) => GRANULARITY_LABELS[f.granularity]).join(" › ") : null

  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4">
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {stack.length > 0 && (
            <button
              onClick={handleBack}
              className="text-xs text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition-colors flex items-center gap-1"
            >
              ← Back
            </button>
          )}
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-white">
            Spending Over Time
            {stack.length > 0 && (
              <span className="text-zinc-400 font-normal ml-1.5 text-xs">
                {GRANULARITY_LABELS[granularity]} view
              </span>
            )}
          </h2>
        </div>

        {/* Granularity tabs — hide when drilled in */}
        {stack.length === 0 && (
          <div className="flex items-center rounded-lg border border-zinc-200 dark:border-zinc-700 overflow-hidden">
            {(["day", "week", "month", "quarter"] as Granularity[]).map((g) => (
              <button
                key={g}
                onClick={() => selectTab(g)}
                className={`px-2.5 py-1 text-xs font-medium transition-colors ${
                  granularity === g
                    ? "bg-zinc-900 dark:bg-white text-white dark:text-zinc-900"
                    : "text-zinc-500 hover:text-zinc-900 dark:hover:text-white"
                }`}
              >
                {GRANULARITY_LABELS[g]}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Chart */}
      {loading ? (
        <div className="h-48 rounded-lg bg-zinc-100 dark:bg-zinc-800 animate-pulse" />
      ) : points.length === 0 ? (
        <div className="h-48 flex items-center justify-center text-xs text-zinc-400">
          No spending data for this period.
        </div>
      ) : (
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={points}
              margin={{ top: 8, right: 4, left: 0, bottom: 0 }}
              onMouseLeave={() => setHoveredLabel(null)}
              onMouseMove={(state) => {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                const label = (state as any)?.activePayload?.[0]?.payload?.label ?? null
                setHoveredLabel(label)
              }}
            >
              <defs>
                <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.18} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
              </defs>

              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#e4e4e7"
                className="dark:[stroke:#3f3f46]"
                vertical={false}
              />

              <XAxis
                dataKey="label"
                tick={{ fontSize: 11, fill: "#a1a1aa" }}
                axisLine={false}
                tickLine={false}
              />

              <YAxis
                tickFormatter={(v) => `$${v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v}`}
                tick={{ fontSize: 11, fill: "#a1a1aa" }}
                axisLine={false}
                tickLine={false}
                width={48}
                domain={[0, maxVal > 0 ? "auto" : 100]}
              />

              <Tooltip
                content={<CustomTooltip />}
                cursor={{ stroke: "#3b82f6", strokeWidth: 1, strokeDasharray: "4 2" }}
              />

              <Area
                type="monotone"
                dataKey="total"
                stroke="#3b82f6"
                strokeWidth={2}
                fill={`url(#${gradientId})`}
                activeDot={false}
                dot={(dotProps) => (
                  <CustomDot
                    key={dotProps.key}
                    cx={dotProps.cx}
                    cy={dotProps.cy}
                    payload={dotProps.payload}
                    hoveredLabel={hoveredLabel}
                    onClick={handlePointClick}
                    canDrill={canDrill}
                  />
                )}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {canDrill && !loading && points.length > 0 && stack.length === 0 && (
        <p className="text-xs text-zinc-400 mt-1.5 text-center">
          Click any point to drill down
        </p>
      )}
    </div>
  )
}
