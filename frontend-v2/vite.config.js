import { defineConfig } from "vite";

// Vite + Vitest shared config. The test block is picked up by Vitest
// (happy-dom simulates DOM APIs fast — ~3× faster than jsdom for our
// component-render tests, and `window`/`document` Just Work).
export default defineConfig({
  root: ".",
  publicDir: "assets",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5175,
    // Proxy API calls to oh-sheet backend in dev so we don't fight CORS.
    // WebSocket upgrade support (`ws: true`) is REQUIRED on the /v1
    // block because the job-events stream lives at /v1/jobs/:id/ws —
    // without this, the proxy intercepts the HTTP request but silently
    // drops the Upgrade handshake, so the frontend's WebSocket never
    // reaches the backend and stays in a CONNECTING or CLOSED state.
    proxy: {
      "/v1": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  test: {
    environment: "happy-dom",
    globals: true,
    include: ["src/**/*.test.js"],
  },
});
