import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const projectRoot = resolve(desktopRoot, "..");
const targetRoot = process.env.CARGO_TARGET_DIR
  ? resolve(desktopRoot, process.env.CARGO_TARGET_DIR)
  : resolve(desktopRoot, "src-tauri/target");
const app = resolve(targetRoot, "release/bundle/macos/MineM.app");
const version = JSON.parse(readFileSync(resolve(projectRoot, "product-version.json"), "utf8")).version;
const dmg = resolve(targetRoot, `release/bundle/dmg/MineM_${version}_aarch64.dmg`);

if (!existsSync(app)) {
  throw new Error(`MineM app bundle not found: ${app}`);
}

mkdirSync(dirname(dmg), { recursive: true });
rmSync(dmg, { force: true });
execFileSync("xattr", ["-cr", app], { stdio: "inherit" });
execFileSync("codesign", ["--force", "--deep", "--sign", "-", app], { stdio: "inherit" });
execFileSync("codesign", ["--verify", "--deep", "--strict", app], { stdio: "inherit" });
execFileSync(
  "hdiutil",
  ["create", "-volname", "MineM", "-srcfolder", app, "-ov", "-format", "UDZO", dmg],
  { stdio: "inherit" },
);

console.log(`MineM macOS installer ready: ${dmg}`);
