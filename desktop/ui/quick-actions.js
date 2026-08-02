import {
  MODE_META,
  buildScenarioInstruction,
  scenariosForMode,
} from "./quick-actions-core.mjs";

const invoke = window.__TAURI__?.core?.invoke;
const iconPaths = {
  upload: '<path d="M12 3v12"/><path d="m7 8 5-5 5 5"/><path d="M5 21h14"/>',
  report: '<path d="M6 2h9l4 4v16H6z"/><path d="M14 2v5h5"/><path d="M9 13h6"/><path d="M9 17h6"/>',
  insert: '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
  replace: '<path d="m7 7-4 4 4 4"/><path d="M3 11h14"/><path d="m17 3 4 4-4 4"/><path d="M21 7H7"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4z"/>',
  case: '<path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M3 12h18"/>',
  page: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  command: '<path d="M18 9a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6a3 3 0 1 0-3 3z"/>',
  collapse: '<path d="m15 18-6-6 6-6"/>',
  close: '<path d="M18 6 6 18M6 6l12 12"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
};

const icon = (name) =>
  `<svg class="icon" aria-hidden="true" viewBox="0 0 24 24">${iconPaths[name] || iconPaths.command}</svg>`;
const $ = (id) => document.getElementById(id);
const status = $("status");
const state = {
  mode: "report",
  cliExecutable: "",
  cliChecking: false,
  cliInstalling: false,
  copying: "",
  copied: "",
  collapsed: false,
};
let toastTimer = 0;
let copiedTimer = 0;

function setIcon(id, name) {
  const element = $(id);
  if (element) element.innerHTML = icon(name);
}

function setStatus(message = "", error = false) {
  status.textContent = message;
  status.className = `status${error ? " error" : ""}`;
}

function showToast(message, error = false) {
  window.clearTimeout(toastTimer);
  const toast = $("toast");
  toast.textContent = message;
  toast.className = `toast visible${error ? " error" : ""}`;
  toastTimer = window.setTimeout(() => toast.classList.remove("visible"), error ? 3000 : 1800);
}

function withTimeout(promise, milliseconds, message) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      timer = window.setTimeout(() => reject(new Error(message)), milliseconds);
    }),
  ]).finally(() => window.clearTimeout(timer));
}

async function writeBrowserClipboard(text) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // WebView clipboard permissions vary; the selection fallback still works on a user gesture.
    }
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.cssText = "position:fixed;inset:0;opacity:0;pointer-events:none";
  document.body.append(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) throw new Error("浏览器未允许访问剪贴板");
}

function normalizeClipboardText(text) {
  return String(text ?? "").replace(/\r\n?/g, "\n");
}

async function verifySystemClipboard(text) {
  if (!invoke) return;
  const written = await withTimeout(invoke("clipboard_read"), 1500, "剪贴板校验超时");
  if (normalizeClipboardText(written) !== normalizeClipboardText(text)) {
    throw new Error("系统剪贴板没有保存指令");
  }
}

async function writeClipboard(text) {
  let nativeError;
  if (invoke) {
    try {
      await withTimeout(invoke("clipboard_write", { text }), 3000, "原生复制超时");
      await verifySystemClipboard(text);
      return;
    } catch (error) {
      nativeError = error;
    }
  }
  try {
    await withTimeout(writeBrowserClipboard(text), 1500, "备用复制超时");
    await verifySystemClipboard(text);
  } catch (error) {
    const reason = nativeError || error;
    throw new Error(reason?.message || String(reason) || "系统剪贴板不可用");
  }
}

function renderScenarios() {
  $("scenarios").replaceChildren(
    ...scenariosForMode(state.mode).map((scenario) => {
      const row = document.createElement("article");
      const copied = state.copied === scenario.value;
      row.className = `scenario${copied ? " copied" : ""}`;
      row.dataset.scenario = scenario.value;

      const leading = document.createElement("span");
      leading.className = "scenario-icon";
      leading.innerHTML = icon(scenario.icon);

      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "copy-button";
      copy.dataset.copyScenario = scenario.value;
      copy.title = `复制“${scenario.label}”指令`;
      copy.setAttribute("aria-label", `复制“${scenario.label}”指令`);
      copy.innerHTML = icon(copied ? "check" : "copy");
      copy.disabled = state.copying === scenario.value;

      const content = document.createElement("button");
      content.type = "button";
      content.className = "scenario-content";
      content.dataset.copyScenario = scenario.value;
      content.title = `复制“${scenario.label}”指令`;
      content.innerHTML = `<strong>${scenario.label}</strong><span>${scenario.description}</span>`;
      content.disabled = state.copying === scenario.value;

      row.append(leading, content, copy);
      return row;
    }),
  );
}

function renderMode() {
  document.querySelectorAll("[data-mode]").forEach((button) => {
    const active = button.dataset.mode === state.mode;
    const meta = MODE_META[button.dataset.mode];
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.innerHTML = icon(button.dataset.mode);
    button.title = meta?.label || "";
    button.setAttribute("aria-label", meta?.label || button.dataset.mode);
  });
  renderScenarios();
  setStatus("复制后粘贴到 AI 对话");
}

function setMode(mode) {
  if (!MODE_META[mode] || mode === state.mode) return;
  state.mode = mode;
  renderMode();
}

function renderCliState(path, message = "") {
  state.cliExecutable = path || "";
  const ready = Boolean(path);
  $("workspace").hidden = !ready;
  $("cli-gate").hidden = ready;
  $("native-state").className = `native-state ${ready ? "ready" : "error"}`;
  $("native-state").innerHTML = `<i></i>${ready ? "平台已连接" : "需要修复"}`;
  $("cli-gate-title").textContent = ready ? "MineM 已连接" : "需要修复 CLI";
  $("cli-gate-copy").textContent = ready
    ? ""
    : "本地命令入口不可用，修复后才能复制可执行指令。";
  $("cli-gate-status").textContent = message || "";
  $("cli-gate-status").classList.toggle("error", !ready && Boolean(message));
  $("cli-gate-install").disabled = ready || state.cliChecking || state.cliInstalling;
}

async function refreshCliState() {
  if (state.cliChecking || state.cliInstalling) return Boolean(state.cliExecutable);
  state.cliChecking = true;
  $("workspace").hidden = true;
  $("cli-gate").hidden = false;
  $("native-state").className = "native-state";
  $("native-state").innerHTML = "<i></i>正在连接";
  $("cli-gate-title").textContent = "正在准备 CLI";
  $("cli-gate-status").textContent = "正在检查本地入口";
  $("cli-gate-install").disabled = true;
  try {
    const path = invoke ? await invoke("cli_tool_path") : "minem";
    renderCliState(path, invoke ? "" : "浏览器预览模式");
    return Boolean(path);
  } catch (error) {
    renderCliState("", "无法检查 CLI，请重试");
    return false;
  } finally {
    state.cliChecking = false;
  }
}

async function installCli() {
  if (!invoke || state.cliInstalling) return;
  state.cliInstalling = true;
  $("cli-gate-install").disabled = true;
  $("cli-gate-title").textContent = "正在修复 CLI";
  $("cli-gate-status").textContent = "正在写入用户命令目录";
  try {
    const path = await withTimeout(invoke("install_cli_tool"), 6000, "CLI 修复超时");
    renderCliState(path);
    showToast("MineM 已连接");
  } catch (error) {
    renderCliState("", error.message || String(error));
  } finally {
    state.cliInstalling = false;
  }
}

async function copyScenarioInstruction(scenarioId) {
  if (state.copying) return;
  let instruction;
  try {
    instruction = buildScenarioInstruction(scenarioId);
  } catch (error) {
    const message = error.message || String(error);
    showToast(message, true);
    setStatus(message, true);
    return;
  }

  state.copying = scenarioId;
  renderScenarios();
  setStatus("正在写入剪贴板");
  try {
    await writeClipboard(instruction);
    window.clearTimeout(copiedTimer);
    state.copied = scenarioId;
    showToast("已复制");
    setStatus("已复制，可粘贴到 AI 对话");
    copiedTimer = window.setTimeout(() => {
      state.copied = "";
      renderScenarios();
    }, 1800);
  } catch (error) {
    const message = error.message || String(error) || "系统剪贴板不可用";
    showToast("复制失败", true);
    setStatus(message, true);
  } finally {
    state.copying = "";
    renderScenarios();
  }
}

async function hideQuickActions() {
  try {
    if (invoke) await invoke("hide");
    else window.close();
  } catch (error) {
    setStatus("无法关闭创作助手", true);
  }
}

function applyDrawerState(collapsed) {
  state.collapsed = collapsed;
  document.body.classList.toggle("collapsed", collapsed);
}

async function setCollapsed(collapsed) {
  applyDrawerState(collapsed);
  try {
    if (invoke) await invoke("set_collapsed", { collapsed });
    if (!collapsed) refreshCliState();
  } catch (error) {
    applyDrawerState(false);
    setStatus(`窗口状态调整失败：${error}`, true);
  }
}

window.setMineMDrawerCollapsed = (collapsed) => applyDrawerState(Boolean(collapsed));

document.querySelector(".mode-switch").addEventListener("click", (event) => {
  const button = event.target.closest("[data-mode]");
  if (button) setMode(button.dataset.mode);
});
$("scenarios").addEventListener("click", (event) => {
  const button = event.target.closest("[data-copy-scenario]");
  if (button) copyScenarioInstruction(button.dataset.copyScenario);
});
$("cli-gate-install").addEventListener("click", installCli);
$("collapse").addEventListener("click", () => setCollapsed(true));
$("close").addEventListener("click", hideQuickActions);

document.querySelector(".topbar").addEventListener("pointerdown", (event) => {
  if (event.button !== 0 || event.target.closest("button")) return;
  invoke?.("start_dragging").catch(() => {});
});

const launcher = $("drawer-launcher");
let launcherPointer = null;
launcher.addEventListener("pointerdown", (event) => {
  if (event.button !== 0) return;
  launcherPointer = { x: event.clientX, y: event.clientY, moved: false };
  launcher.setPointerCapture?.(event.pointerId);
});
launcher.addEventListener("pointermove", (event) => {
  if (!launcherPointer || launcherPointer.moved) return;
  if (Math.hypot(event.clientX - launcherPointer.x, event.clientY - launcherPointer.y) < 4) return;
  launcherPointer.moved = true;
  invoke?.("start_dragging").catch(() => {});
});
launcher.addEventListener("click", (event) => {
  const moved = launcherPointer?.moved;
  launcherPointer = null;
  if (moved) {
    event.preventDefault();
    return;
  }
  setCollapsed(false);
});

document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && ["1", "2", "3"].includes(event.key)) {
    event.preventDefault();
    setMode(["report", "page", "case"][Number(event.key) - 1]);
  } else if (event.key === "Escape") {
    event.preventDefault();
    hideQuickActions();
  }
});

setIcon("collapse", "collapse");
setIcon("close", "close");
setIcon("gate-icon", "command");
setIcon("footer-mark", "command");
renderMode();
refreshCliState();
