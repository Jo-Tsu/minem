import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [html, style, script, shell, bridge, boot, main, app, api, server, runtime, cargo, tauriConfig] = await Promise.all([
  readFile(new URL("../ui/quick-actions.html", import.meta.url), "utf8"),
  readFile(new URL("../ui/quick-actions.css", import.meta.url), "utf8"),
  readFile(new URL("../ui/quick-actions.js", import.meta.url), "utf8"),
  readFile(new URL("../src-tauri/src/quick_actions.rs", import.meta.url), "utf8"),
  readFile(new URL("../src-tauri/src/native_bridge.rs", import.meta.url), "utf8"),
  readFile(new URL("../ui/index.html", import.meta.url), "utf8"),
  readFile(new URL("../src-tauri/src/main.rs", import.meta.url), "utf8"),
  readFile(new URL("../../frontend/src/App.tsx", import.meta.url), "utf8"),
  readFile(new URL("../../frontend/src/api.ts", import.meta.url), "utf8"),
  readFile(new URL("../../server.py", import.meta.url), "utf8"),
  readFile(new URL("../src-tauri/src/desktop_runtime.rs", import.meta.url), "utf8"),
  readFile(new URL("../src-tauri/Cargo.toml", import.meta.url), "utf8"),
  readFile(new URL("../src-tauri/tauri.conf.json", import.meta.url), "utf8"),
]);

test("creator assistant can be moved without exposing a native white window", () => {
  assert.match(html, /data-tauri-drag-region/);
  assert.match(script, /invoke\?\.\("start_dragging"\)/);
  assert.match(script, /launcherPointer/);
  assert.match(shell, /\.transparent\(true\)/);
  assert.match(shell, /\.shadow\(false\)/);
  assert.match(cargo, /features = \["tray-icon", "macos-private-api"\]/);
  assert.equal(JSON.parse(tauriConfig).app.macOSPrivateApi, true);
  assert.match(shell, /pub fn start_dragging/);
  assert.match(style, /background:\s*transparent/);
  assert.match(style, /\.launcher:focus\s*\{\s*outline:\s*none/);
  assert.match(html, /id="collapse"/);
  assert.match(html, /id="close"/);
  assert.match(html, /id="drawer-launcher"/);
  assert.match(main, /Modifiers::CONTROL \| Modifiers::ALT/);
});

test("creator assistant uses the shared compact radius and control sizing", () => {
  assert.match(style, /--radius-panel:\s*8px/);
  assert.match(style, /--radius-control:\s*6px/);
  assert.match(style, /\.drawer[\s\S]*border-radius:\s*var\(--radius-panel\)/);
  assert.match(style, /\.icon-button[\s\S]*width:\s*32px[\s\S]*height:\s*32px/);
  assert.match(style, /\.mode-switch[\s\S]*border-radius:\s*var\(--radius-control\)/);
  assert.match(style, /\.mode-button[\s\S]*border-radius:\s*var\(--radius-control\)/);
  assert.match(style, /\.copy-button[\s\S]*border-radius:\s*var\(--radius-control\)/);
  assert.doesNotMatch(style, /border-radius:\s*(5|7|10|12|14)px/);
});

test("drawer collapse and close remain separate native actions", () => {
  assert.match(script, /invoke\("set_collapsed"/);
  assert.match(script, /invoke\("hide"\)/);
  assert.match(script, /window\.setMineMDrawerCollapsed/);
  assert.match(shell, /EXPANDED_WIDTH: f64 = 420\.0/);
  assert.match(shell, /COLLAPSED_SIZE: f64 = 48\.0/);
  assert.match(shell, /MIN_HEIGHT: f64 = 480\.0/);
  assert.match(shell, /MAX_HEIGHT: f64 = 520\.0/);
  assert.match(shell, /pub fn set_collapsed/);
  assert.match(shell, /resize_preserving_position/);
  assert.match(shell, /anchored_position/);
});

test("assistant has no user input form and exposes three scenario groups", () => {
  assert.match(html, /data-mode="report"/);
  assert.match(html, /data-mode="page"/);
  assert.match(html, /data-mode="case"/);
  assert.match(html, /id="scenarios"/);
  assert.doesNotMatch(html, /<input|<textarea|<select/);
  assert.doesNotMatch(html, /命令预览|补充要求|汇报链接或编号/);
  assert.doesNotMatch(script, /localStorage|draftStorageKey|templateStorageKey/);
});

test("each scenario copies a complete AI instruction instead of a raw CLI form", () => {
  assert.match(script, /buildScenarioInstruction/);
  assert.match(script, /dataset\.copyScenario/);
  assert.match(script, /已复制，可粘贴到 AI 对话/);
  assert.doesNotMatch(script, /buildCliCommand|buildOperationPackage|parseMineMReferences/);
  assert.doesNotMatch(html, /复制 CLI/);
});

test("instruction copy cannot deadlock and always reports a visible result", () => {
  assert.match(html, /id="toast"/);
  assert.match(script, /state\.copying/);
  assert.match(script, /async function writeClipboard/);
  assert.match(script, /invoke\("clipboard_write"/);
  assert.match(script, /invoke\("clipboard_read"\)/);
  assert.match(script, /verifySystemClipboard/);
  assert.match(script, /normalizeClipboardText/);
  assert.match(script, /writeBrowserClipboard/);
  assert.match(script, /state\.copied = scenarioId/);
  assert.match(script, /showToast\("复制失败", true\)/);
  assert.match(bridge, /NSPasteboard::generalPasteboard/);
  assert.match(bridge, /setString_forType/);
  assert.match(bridge, /stringForType/);
  assert.match(bridge, /normalize_clipboard_text/);
  assert.match(bridge, /spawn_blocking\(move \|\| write_clipboard/);
  assert.doesNotMatch(bridge, /Command::new\("\/usr\/bin\/pbcopy"\)/);
  assert.doesNotMatch(bridge, /Command::new\("\/usr\/bin\/pbpaste"\)/);
});

test("assistant keeps CLI readiness and absolute path discovery", () => {
  assert.match(script, /invoke\("cli_tool_path"\)/);
  assert.match(script, /invoke\("install_cli_tool"\)/);
  assert.match(script, /cliExecutable/);
  assert.match(html, /id="cli-gate"/);
});

test("failed desktop startup can retry in the same window", () => {
  assert.match(boot, /id="retry"/);
  assert.match(boot, /invoke\("retry_runtime"\)/);
  assert.match(boot, /window\.location\.assign\(url\)/);
});

test("the platform header can open the same native creator assistant", () => {
  assert.match(app, /creator-assistant-entry/);
  assert.match(app, /api\.openCreatorAssistant\(\)/);
  assert.match(api, /openCreatorAssistant.*\/api\/desktop\/creator-assistant/);
  assert.match(server, /parsed\.path == "\/api\/desktop\/creator-assistant"/);
  assert.match(server, /\[str\(executable\), "--assistant"\]/);
  assert.match(server, /MINEM_DESKTOP_EXECUTABLE/);
  assert.match(runtime, /command\.env\("MINEM_DESKTOP_EXECUTABLE", executable\)/);
});
