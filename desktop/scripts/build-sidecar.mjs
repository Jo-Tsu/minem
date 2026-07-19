import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join, delimiter } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const desktopDir = join(scriptDir, "..");
const projectRoot = join(desktopDir, "..");
const buildRoot = join(desktopDir, ".build");
const binariesDir = join(desktopDir, "src-tauri", "binaries");
const target = process.env.TAURI_ENV_TARGET_TRIPLE
  || (process.arch === "arm64" ? "aarch64-apple-darwin" : "x86_64-apple-darwin");
const output = join(binariesDir, `minem-server-${target}`);
const python = process.env.MINEM_DESKTOP_PYTHON || "python3";

rmSync(buildRoot, { recursive: true, force: true });
mkdirSync(buildRoot, { recursive: true });
mkdirSync(binariesDir, { recursive: true });

const addData = (source, destination) => `${join(projectRoot, source)}${delimiter}${destination}`;
const result = spawnSync(python, [
  "-m", "PyInstaller",
  "--noconfirm",
  "--clean",
  "--onefile",
  "--name", "minem-server",
  "--distpath", buildRoot,
  "--workpath", join(buildRoot, "work"),
  "--specpath", join(buildRoot, "spec"),
  "--collect-all", "minem",
  "--add-data", addData("product-version.json", "product-version.json"),
  "--add-data", addData("public", "public"),
  "--add-data", addData("templates", "templates"),
  join(projectRoot, "server.py")
], { cwd: projectRoot, stdio: "inherit" });

if (result.status !== 0) {
  process.exit(result.status || 1);
}

const binary = join(buildRoot, "minem-server");
if (!existsSync(binary)) {
  throw new Error(`MineM sidecar was not produced: ${binary}`);
}
cpSync(binary, output);
console.log(`MineM sidecar ready: ${output}`);
