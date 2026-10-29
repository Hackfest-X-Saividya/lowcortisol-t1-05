import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import nishaan3d from "./nishaan3d.js";

// The dev server proxies the API and the session WebSocket to the FastAPI backend,
// so the browser only ever talks to one origin (no CORS setup needed).
// It also serves the 3D face builder ("3D MODEL" folder) under /nishaan3d/ (see nishaan3d.js).
const backend = process.env.NISHAAN_BACKEND || "http://localhost:8000";

export default defineConfig({
  plugins: [react(), nishaan3d()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
});
