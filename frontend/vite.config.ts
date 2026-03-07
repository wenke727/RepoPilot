import basicSsl from "@vitejs/plugin-basic-ssl"
import { defineConfig } from "vite"

// 默认启用 HTTPS；设 REPOPILOT_FRONTEND_HTTPS=0 可关闭
const useHttps = process.env.REPOPILOT_FRONTEND_HTTPS !== "0"

export default defineConfig({
  plugins: useHttps ? [basicSsl()] : [],
  server: {
    host: true,
    port: Number(process.env.REPOPILOT_APP_PORT) || 5173,
    https: useHttps ? true : undefined,
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${process.env.REPOPILOT_BACKEND_PORT || "8000"}`,
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: true,
    port: Number(process.env.REPOPILOT_APP_PORT) || 5173,
  },
})
