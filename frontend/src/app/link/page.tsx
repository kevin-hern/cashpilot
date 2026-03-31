"use client"
import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import PlaidLinkButton from "@/components/PlaidLink"

type Status = "idle" | "connecting" | "success" | "error"

export default function LinkPage() {
  const router = useRouter()
  const [status, setStatus] = useState<Status>("idle")

  // Redirect to login if not authenticated
  useEffect(() => {
    if (typeof window !== "undefined" && !localStorage.getItem("access_token")) {
      router.replace("/login")
    } else {
      setStatus("connecting")
    }
  }, [router])

  function handleSuccess() {
    setStatus("success")
    // Hard navigation so the dashboard remounts and re-fetches accounts.
    // router.push() uses the Next.js router cache and may serve a stale
    // dashboard that never calls loadData() again.
    setTimeout(() => { window.location.href = "/dashboard" }, 1200)
  }

  if (status === "idle") return null

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 flex items-center justify-center px-4">
      <div className="w-full max-w-sm text-center">

        {status === "connecting" && (
          <>
            <div className="w-12 h-12 rounded-full bg-zinc-900 dark:bg-white flex items-center justify-center mx-auto mb-6">
              <svg className="w-6 h-6 text-white dark:text-zinc-900" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
              </svg>
            </div>
            <h1 className="text-2xl font-bold text-zinc-900 dark:text-white mb-2">
              Connect your bank
            </h1>
            <p className="text-sm text-zinc-500 mb-8">
              Securely link your accounts via Plaid. CashPilot only has read access to your transactions and balances.
            </p>
            <PlaidLinkButton
              autoOpen={true}
              onSuccess={handleSuccess}
              className="w-full rounded-full bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 py-3 text-sm font-medium hover:bg-zinc-700 dark:hover:bg-zinc-200 transition-colors disabled:opacity-50"
            >
              Connect Bank Account
            </PlaidLinkButton>
            <p className="mt-4 text-xs text-zinc-400">
              Protected by 256-bit encryption · Plaid-secured
            </p>
          </>
        )}

        {status === "success" && (
          <>
            <div className="w-12 h-12 rounded-full bg-green-500 flex items-center justify-center mx-auto mb-6">
              <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 className="text-xl font-semibold text-zinc-900 dark:text-white mb-2">Account linked!</h2>
            <p className="text-sm text-zinc-500">Taking you to your dashboard…</p>
          </>
        )}

      </div>
    </div>
  )
}
