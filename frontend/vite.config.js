import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3012,
    proxy: {
      "/api": { target: "http://localhost:8012", changeOrigin: true },
      "/health": { target: "http://localhost:8012", changeOrigin: true },
    },
  },
});
