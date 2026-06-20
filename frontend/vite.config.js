import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발 시 백엔드(FastAPI 8000) 로 /api 프록시
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
  },
});
