import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  root: "frontend",
  base: "/",
  plugins: [react()],
  publicDir: false,
  build: {
    outDir: "../public",
    emptyOutDir: true
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8790",
      "/extracted": "http://127.0.0.1:8790",
      "/thumbnails": "http://127.0.0.1:8790"
    }
  }
});
