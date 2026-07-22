import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built into webui/dist and served by FastAPI at the same origin, so API calls
// use relative /api paths. In dev (npm run dev) we proxy /api to uvicorn:8000.
export default defineConfig({
  plugins: [react()],
  base: "/",
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
