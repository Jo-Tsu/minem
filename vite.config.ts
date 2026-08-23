import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const API_TARGET = "http://127.0.0.1:8790";

function processIsRunning(pid: unknown) {
  const parsed = Number(pid);
  if (!Number.isInteger(parsed) || parsed <= 0) return false;
  try {
    process.kill(parsed, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException)?.code === "EPERM";
  }
}

function runtimeToken(target: string) {
  const roots = [
    process.env.MINEM_DATA_DIR,
    path.join(os.homedir(), "Library/Application Support/MineM"),
    process.cwd()
  ].filter(Boolean) as string[];
  for (const root of roots) {
    try {
      const manifest = JSON.parse(fs.readFileSync(path.join(root, "runtime/session.json"), "utf8"));
      if (
        manifest?.status !== "running"
        || new URL(manifest.baseUrl).origin !== new URL(target).origin
        || !processIsRunning(manifest.pid)
      ) {
        continue;
      }
      const token = fs.readFileSync(path.join(root, "runtime/session-token"), "utf8").trim();
      if (token) return token;
    } catch {
      // Continue to the next supported local runtime location.
    }
  }
  return "";
}

function securedProxy() {
  return {
    target: API_TARGET,
    changeOrigin: true,
    configure(proxy: { on: (event: string, listener: (request: { setHeader: (name: string, value: string) => void }) => void) => void }) {
      proxy.on("proxyReq", (request) => {
        const token = runtimeToken(API_TARGET);
        if (token) request.setHeader("X-MineM-Session-Token", token);
        request.setHeader("Origin", API_TARGET);
        request.setHeader("Sec-Fetch-Site", "same-origin");
      });
    }
  };
}

export default defineConfig({
  root: "frontend",
  base: "/",
  plugins: [react()],
  publicDir: "public",
  build: {
    outDir: "../public",
    emptyOutDir: true
  },
  server: {
    proxy: {
      "/api": securedProxy(),
      "/extracted": API_TARGET,
      "/thumbnails": API_TARGET
    }
  }
});
