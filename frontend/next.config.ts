import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactCompiler: true,
  // Explicitly surface NEXT_PUBLIC_API_URL at build time.
  // Must be set in Vercel project settings (Environment Variables) BEFORE building.
  // Value is baked into the JS bundle — changing it in Vercel requires a redeploy.
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "",
  },
};

export default nextConfig;
