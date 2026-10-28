import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies the API and the session WebSocket to the FastAPI backend,
// so the browser only ever talks to one origin (no CORS setup needed).
const backend = process.env.NISHAAN_BACKEND || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
});
