import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the Vite server forwards API and event-stream calls to the Python server.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:7860", ws: true },
    },
  },
  build: { sourcemap: false, assetsInlineLimit: 0 },
});
