import { configDefaults, defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.replaceAll("\\", "/").endsWith("/src/contracts.ts"))
            return "api-capabilities";
        },
      },
    },
  },
  server: {
    proxy: {
      "/api": {
        target:
          loadEnv(mode, ".", "").API_PROXY_TARGET || "http://127.0.0.1:8800",
        changeOrigin: false,
      },
    },
  },
  test: {
    exclude: [...configDefaults.exclude, "qa-previews/**"],
    environment: "jsdom",
    setupFiles: "./src/test-setup.ts",
    clearMocks: true,
  },
}));
