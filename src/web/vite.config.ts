import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// Static SPA — built to src/web/dist, deployed to S3 + CloudFront by infra/console.py.
//
// In production CloudFront serves the SPA and `/api/*` (the invoke proxy) from the SAME origin, so
// the bundle only ever fetches relative `/api/...` paths. The dev server has no `/api/*`, so it
// proxies to the deployed HTTP API instead. VITE_API_ORIGIN is written by scripts/gen_web_env.py
// from the stack's StreamProxyUrl output; `dev` fails loudly rather than serving a broken /api.
export default defineConfig(({ mode, command }) => {
  const apiOrigin = loadEnv(mode, process.cwd(), "VITE_").VITE_API_ORIGIN;
  if (command === "serve" && !apiOrigin) {
    throw new Error(
      "VITE_API_ORIGIN is empty — run `npx projen dev:web` (it regenerates src/web/.env.local from the " +
        "deployed stack outputs) with AWS credentials for the account holding agentcore-x402-dev.",
    );
  }
  return {
    plugins: [react()],
    build: { outDir: "dist" },
    server: {
      proxy: apiOrigin ? { "/api": { target: apiOrigin, changeOrigin: true } } : undefined,
    },
  };
});
