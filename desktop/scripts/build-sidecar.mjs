import {
  cpSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  realpathSync,
  rmSync,
  writeFileSync
} from "node:fs";
import { dirname, join, delimiter } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const desktopDir = join(scriptDir, "..");
const projectRoot = join(desktopDir, "..");
const buildRoot = join(desktopDir, ".build");
const binariesDir = join(desktopDir, "src-tauri", "binaries");
const python = process.env.MINEM_DESKTOP_PYTHON || "python3";

rmSync(buildRoot, { recursive: true, force: true });
mkdirSync(buildRoot, { recursive: true });
mkdirSync(binariesDir, { recursive: true });
rmSync(join(binariesDir, "minem-server-aarch64-apple-darwin"), { force: true });
rmSync(join(binariesDir, "minem-server-x86_64-apple-darwin"), { force: true });

const addData = (source, destination) => `${join(projectRoot, source)}${delimiter}${destination}`;

const materializeSymlinks = (directory) => {
  for (const entry of readdirSync(directory)) {
    const path = join(directory, entry);
    const stat = lstatSync(path);
    if (stat.isSymbolicLink()) {
      const source = realpathSync(path);
      rmSync(path, { recursive: true, force: true });
      cpSync(source, path, {
        recursive: true,
        dereference: true,
        preserveTimestamps: true
      });
    }
    if (lstatSync(path).isDirectory()) {
      materializeSymlinks(path);
    }
  }
};

const buildBinary = ({ name, entry, extra = [] }) => {
  const distPath = join(buildRoot, "dist", name);
  const result = spawnSync(python, [
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onedir",
    "--name", name,
    "--distpath", distPath,
    "--workpath", join(buildRoot, "work", name),
    "--specpath", join(buildRoot, "spec", name),
    "--paths", projectRoot,
    "--collect-all", "minem",
    ...extra,
    join(projectRoot, entry)
  ], { cwd: projectRoot, stdio: "inherit" });

  if (result.status !== 0) {
    process.exit(result.status || 1);
  }

  const bundle = join(distPath, name);
  const binary = join(bundle, name);
  if (!existsSync(binary)) {
    throw new Error(`MineM sidecar was not produced: ${binary}`);
  }
  const output = join(binariesDir, "sidecar");
  rmSync(output, { recursive: true, force: true });
  cpSync(bundle, output, { recursive: true, dereference: true });
  materializeSymlinks(output);
  writeFileSync(join(output, ".gitkeep"), "");
  console.log(`MineM sidecar directory ready: ${output}`);
};

buildBinary({
  name: "minem-server",
  entry: "server.py",
  extra: [
    "--add-data", addData("product-version.json", "."),
    "--add-data", addData("public", "public"),
    "--add-data", addData("templates", "templates"),
    "--add-data", addData("scripts/minem_cli.py", "scripts")
  ]
});
