import { execFileSync } from "node:child_process";
import {
  copyFileSync,
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync
} from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const projectRoot = resolve(desktopRoot, "..");
const scriptRoot = resolve(desktopRoot, "scripts");
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

const sleep = (seconds) => {
  execFileSync("sleep", [String(seconds)]);
};

const appleScriptString = (value) => `"${value.replaceAll("\\", "\\\\").replaceAll("\"", "\\\"")}"`;

const createStyledDmg = (stagingDir, stagedDmg, workspace) => {
  const mountedVolume = "/Volumes/MineM";
  if (existsSync(mountedVolume)) {
    try {
      execFileSync("hdiutil", ["detach", mountedVolume, "-force"], { stdio: "ignore" });
    } catch {
      return false;
    }
  }

  const readWriteDmg = join(workspace, "MineM-rw.dmg");
  let device = "";
  try {
    execFileSync(
      "hdiutil",
      ["create", "-volname", "MineM", "-srcfolder", stagingDir, "-fs", "HFS+", "-format", "UDRW", "-ov", readWriteDmg],
      { stdio: "ignore" },
    );
    const attachOutput = execFileSync(
      "hdiutil",
      ["attach", "-readwrite", "-noverify", "-noautoopen", readWriteDmg],
      { encoding: "utf8" },
    );
    device = attachOutput.match(/^\/dev\/disk\d+/m)?.[0] || "";
    const mountPath = attachOutput.match(/\/Volumes\/.*$/m)?.[0]?.trim() || "";
    if (!device || !mountPath) return false;
    const volumeName = basename(mountPath);
    sleep(1);
    const finderScript = `
tell application "Finder"
  tell disk ${appleScriptString(volumeName)}
    open
    delay 1
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {200, 120, 840, 543}
    set opts to the icon view options of container window
    set arrangement of opts to not arranged
    set icon size of opts to 96
    set text size of opts to 12
    set background picture of opts to file ".background:bg.tiff"
    set position of item "MineM.app" of container window to {172, 220}
    set position of item "Applications" of container window to {468, 220}
    close
    open
    update without registering applications
    delay 3
  end tell
end tell`;
    execFileSync("osascript", ["-e", finderScript], { stdio: "ignore" });
    for (let attempt = 0; attempt < 15 && !existsSync(join(mountPath, ".DS_Store")); attempt += 1) {
      sleep(1);
    }
    if (!existsSync(join(mountPath, ".DS_Store"))) return false;
    execFileSync("sync");
    execFileSync("sync");
    execFileSync("hdiutil", ["detach", device, "-force"], { stdio: "ignore" });
    device = "";
    execFileSync(
      "hdiutil",
      ["convert", readWriteDmg, "-format", "UDZO", "-imagekey", "zlib-level=9", "-o", stagedDmg],
      { stdio: "inherit" },
    );
    return true;
  } catch {
    return false;
  } finally {
    if (device) {
      try {
        execFileSync("hdiutil", ["detach", device, "-force"], { stdio: "ignore" });
      } catch {
        // The volume may already be detached after a partial Finder operation.
      }
    }
  }
};

mkdirSync(dirname(dmg), { recursive: true });
rmSync(dmg, { force: true });
execFileSync("xattr", ["-cr", app], { stdio: "inherit" });
execFileSync("codesign", ["--force", "--deep", "--sign", "-", app], { stdio: "inherit" });
execFileSync("codesign", ["--verify", "--deep", "--strict", app], { stdio: "inherit" });
const workspace = mkdtempSync(join(tmpdir(), "minem-dmg-"));
const stagingDir = join(workspace, "staging");
const backgroundDir = join(workspace, "background");
const stagedDmg = join(workspace, "MineM.dmg");
try {
  mkdirSync(stagingDir, { recursive: true });
  cpSync(app, join(stagingDir, "MineM.app"), { recursive: true, dereference: false });
  symlinkSync("/Applications", join(stagingDir, "Applications"));
  mkdirSync(join(stagingDir, ".background"), { recursive: true });
  execFileSync(
    process.env.MINEM_DESKTOP_PYTHON || "python3",
    [join(scriptRoot, "create-dmg-background.py"), backgroundDir],
    { cwd: projectRoot, stdio: "inherit" },
  );
  execFileSync(
    "tiffutil",
    [
      "-cathidpicheck",
      join(backgroundDir, "bg_1x.tiff"),
      join(backgroundDir, "bg_2x.tiff"),
      "-out",
      join(stagingDir, ".background", "bg.tiff")
    ],
    { stdio: "inherit" },
  );
  if (!createStyledDmg(stagingDir, stagedDmg, workspace)) {
    console.warn("Finder styling unavailable; creating an unstyled drag-to-Applications DMG.");
    execFileSync(
      "hdiutil",
      ["create", "-volname", "MineM", "-srcfolder", stagingDir, "-ov", "-format", "UDZO", stagedDmg],
      { stdio: "inherit" },
    );
  }
  mkdirSync(dirname(releaseDmg), { recursive: true });
  copyFileSync(stagedDmg, dmg);
  copyFileSync(stagedDmg, releaseDmg);
} finally {
  rmSync(workspace, { recursive: true, force: true });
}

console.log(`MineM macOS installer ready: ${dmg}`);
console.log(`MineM macOS release copy: ${releaseDmg}`);
