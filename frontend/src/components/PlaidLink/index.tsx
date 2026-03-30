"use client"
import { useEffect, useState, useCallback } from "react"
import { usePlaidLink, PlaidLinkOnSuccess } from "react-plaid-link"
import { api } from "@/lib/api-client"

interface Props {
  /** Called after the public token is successfully exchanged */
  onSuccess?: () => void
  /** Auto-open Plaid Link immediately on mount (used by /link page) */
  autoOpen?: boolean
  className?: string
  children?: React.ReactNode
}

export default function PlaidLinkButton({ onSuccess, autoOpen = false, className, children }: Props) {
  const [linkToken, setLinkToken] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Fetch link token on mount when autoOpen is true, or lazily on click
  useEffect(() => {
    if (autoOpen) fetchLinkToken()
  }, [autoOpen])

  async function fetchLinkToken() {
    setLoading(true)
    setError(null)
    try {
      const res = await api.getLinkToken()
      setLinkToken(res.link_token)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start bank connection")
    } finally {
      setLoading(false)
    }
  }

  const handleSuccess: PlaidLinkOnSuccess = useCallback(
    async (public_token, metadata) => {
      try {
        await api.exchangePublicToken({
          public_token,
          institution_name: metadata.institution?.name ?? undefined,
        })
        onSuccess?.()
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to link account")
      }
    },
    [onSuccess],
  )

  const { open, ready } = usePlaidLink({
    token: linkToken ?? "",
    onSuccess: handleSuccess,
    onExit: () => setLinkToken(null), // reset so a fresh token is fetched next time
  })

  // Auto-open as soon as the token is ready (fixes the two-click bug)
  useEffect(() => {
    if (ready && linkToken && autoOpen) {
      open()
    }
  }, [ready, linkToken, autoOpen, open])

  async function handleClick() {
    if (ready && linkToken) {
      open()
      return
    }
    await fetchLinkToken()
    // open() will fire via the useEffect above once ready becomes true
  }

  if (error) {
    return (
      <div className="flex items-center gap-2">
        <span className="text-xs text-red-500">{error}</span>
        <button onClick={fetchLinkToken} className="text-xs text-zinc-500 underline">
          Retry
        </button>
      </div>
    )
  }

  return (
    <button
      onClick={handleClick}
      disabled={loading || (!!linkToken && !ready)}
      className={className ?? "rounded-full border border-zinc-200 dark:border-zinc-700 px-3 py-1.5 text-xs font-medium text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors disabled:opacity-50"}
    >
      {loading ? "Loading…" : (children ?? "+ Connect Bank")}
    </button>
  )
}
