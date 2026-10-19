import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  return {
    base: env.VITE_BASE_PATH || "/",
    plugins: [react(), tailwindcss()],
    build: {
      sourcemap: false,
      rollupOptions: { output: { manualChunks: { graph: ["cytoscape"] } } },
    },
    server: {
      proxy: {
        "/api": "http://127.0.0.1:8000",
        "/ui-config.json": "http://127.0.0.1:8000",
      },
    },
  };
});
