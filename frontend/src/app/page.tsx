import Link from "next/link"

export default function Home() {
  return (
    <div className="flex flex-1 items-center justify-center min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <div className="text-center max-w-md px-6">
        <h1 className="text-4xl font-bold tracking-tight text-zinc-900 dark:text-white mb-4">
          CashPilot
        </h1>
        <p className="text-zinc-500 dark:text-zinc-400 text-lg mb-8">
          Your AI-powered financial co-pilot. Connect your accounts, detect income, and act with confidence.
        </p>
        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <Link
            href="/login"
            className="inline-flex items-center justify-center rounded-full bg-zinc-900 text-white px-6 py-3 text-sm font-medium hover:bg-zinc-700 dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-200 transition-colors"
          >
            Get Started
          </Link>
          <Link
            href="/dashboard"
            className="inline-flex items-center justify-center rounded-full border border-zinc-200 dark:border-zinc-700 px-6 py-3 text-sm font-medium text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          >
            Dashboard
          </Link>
        </div>
      </div>
    </div>
  )
}
