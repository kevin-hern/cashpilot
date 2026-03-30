"use client"
import { useCallback, useState } from "react"
import { usePlaidLink } from "react-plaid-link"
import { api } from "@/lib/api-client"

interface Props {
  onSuccess?: () => void
}

export default function PlaidLinkButton({ onSuccess }: Props) {
  const [linkToken, setLinkToken] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const { open, ready } = usePlaidLink({
    token: linkToken ?? "",
    onSuccess: async (public_token, metadata) => {
      try {
        await api.exchangePublicToken({
          public_token,
          institution_name: metadata.institution?.name,
        })
        onSuccess?.()
      } catch (err) {
        console.error("Exchange failed:", err)
      }
    },
  })

  async function handleClick() {
    if (linkToken) {
      open()
      return
    }
    setLoading(true)
    try {
      const res = await api.getLinkToken() as { link_token: string }
      setLinkToken(res.link_token)
      // usePlaidLink will re-initialize with the new token; open on next click
    } catch (err) {
      console.error("Link token error:", err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <button
      onClick={handleClick}
      disabled={loading}
      className="rounded-full border border-zinc-200 dark:border-zinc-700 px-3 py-1.5 text-xs font-medium text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors disabled:opacity-50"
    >
      {loading ? "Loading…" : "+ Connect Bank"}
    </button>
  )
}
