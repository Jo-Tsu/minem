import { execFileSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const projectRoot = resolve(desktopRoot, "..");
const targetRoot = process.env.CARGO_TARGET_DIR
  ? resolve(desktopRoot, process.env.CARGO_TARGET_DIR)
  : resolve(desktopRoot, "src-tauri/target");
const app = resolve(targetRoot, "release/bundle/macos/MineM.app");
const version = JSON.parse(readFileSync(resolve(projectRoot, "product-version.json"), "utf8")).version;
const dmg = resolve(targetRoot, `release/bundle/dmg/MineM_${version}_aarch64.dmg`);
const releaseDmg = resolve(desktopRoot, "dist", `MineM_${version}_aarch64.dmg`);

if (!existsSync(app)) {
  throw new Error(`MineM app bundle not found: ${app}`);
}

mkdirSync(dirname(dmg), { recursive: true });
rmSync(dmg, { force: true });
execFileSync("xattr", ["-cr", app], { stdio: "inherit" });
execFileSync("codesign", ["--force", "--deep", "--sign", "-", app], { stdio: "inherit" });
execFileSync("codesign", ["--verify", "--deep", "--strict", app], { stdio: "inherit" });
const stagingDir = mkdtempSync(join(tmpdir(), "minem-dmg-"));
const stagedDmg = join(stagingDir, "MineM.dmg");
try {
  execFileSync(
    "hdiutil",
    ["create", "-volname", "MineM", "-srcfolder", app, "-ov", "-format", "UDZO", stagedDmg],
    { stdio: "inherit" },
  );
  mkdirSync(dirname(releaseDmg), { recursive: true });
  copyFileSync(stagedDmg, dmg);
  copyFileSync(stagedDmg, releaseDmg);
} finally {
  rmSync(stagingDir, { recursive: true, force: true });
}

console.log(`MineM macOS installer ready: ${dmg}`);
console.log(`MineM macOS release copy: ${releaseDmg}`);
