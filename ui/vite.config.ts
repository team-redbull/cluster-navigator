import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the UI runs on its own port and forwards API calls to the
// server, so the browser still sees a single origin and cookies just work.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 4100,
    proxy: { "/api": "http://localhost:8100" },
  },
});
