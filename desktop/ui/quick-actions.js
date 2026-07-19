import {
  ACTION_META,
  actionsForMode,
  buildOperationPackage,
  mergeReference,
  parseMineMReferences,
  validateOperation,
} from "./quick-actions-core.mjs";

const invoke = window.__TAURI__?.core?.invoke;
const templateStorageKey = "minem.creator-assistant.templates.v2";
const glyphs = {
  upload: "↥",
  report: "▤",
  insert: "⊕",
  replace: "⇄",
  edit: "✎",
  case: "◇",
  page: "▱",
  copy: "⧉",
  command: "⌘",
};
const state = {
  mode: "report",
  action: "import_report",
  pageRefs: [],
  currentUrl: "",
  templates: [],
  selectedTemplate: "",
};
const $ = (id) => document.getElementById(id);
const source = $("source");
const report = $("report");
const targetPage = $("target-page");
const requirements = $("requirements");
const status = $("status");

function setStatus(message = "", error = false) {
  status.textContent = message;
  status.className = `status${error ? " error" : ""}`;
}

function currentOperationState() {
  return {
    mode: state.mode,
    action: state.action,
    reportRef: report.value,
    targetPage: targetPage.value,
    pageRefs: state.pageRefs,
    source: source.value,
    requirements: requirements.value,
    customBody: $("template-body").value,
  };
}

function updateCopyState() {
  $("copy").disabled = Boolean(validateOperation(currentOperationState()));
}

function renderActions() {
  const container = $("actions");
  const actions = actionsForMode(state.mode);
  container.style.gridTemplateColumns = `repeat(${actions.length}, minmax(0, 1fr))`;
  container.replaceChildren(
    ...actions.map((meta) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `action${meta.value === state.action ? " active" : ""}`;
      button.dataset.action = meta.value;
      button.title = meta.instruction;
      button.innerHTML = `<span class="glyph" aria-hidden="true">${glyphs[meta.icon] || "·"}</span>${meta.label}`;
      return button;
    }),
  );
}

function renderRefs() {
  const container = $("refs");
  container.replaceChildren();
  if (!state.pageRefs.length) {
    const empty = document.createElement("span");
    empty.className = "empty";
    empty.textContent = "粘贴页面链接或 CTRL-PAGE 编号";
    container.append(empty);
    return;
  }
  state.pageRefs.forEach((ref, index) => {
    const chip = document.createElement("span");
    chip.className = "ref";
    const label = ref.code || ref.url;
    chip.innerHTML = `<span>${label}</span><button type="button" title="移除引用" aria-label="移除引用">×</button>`;
    chip.querySelector("button").onclick = () => {
      state.pageRefs.splice(index, 1);
      renderRefs();
      updateCopyState();
    };
    container.append(chip);
  });
}

function renderActionFields() {
  const meta = ACTION_META[state.action];
  $("source-label").textContent = meta.sourceLabel;
  source.placeholder = meta.sourcePlaceholder;
  $("report-field").hidden = !(meta.needsReport || state.action === "extract_case");
  $("target-field").hidden = !meta.needsTarget;
  $("reference-field").hidden = !(meta.needsPageRefs || state.action === "create_report");
  $("template-panel").hidden = !meta.custom;
  renderTemplates();
  updateCopyState();
}

function renderMode() {
  document.querySelectorAll("[data-mode]").forEach((button) => {
    const active = button.dataset.mode === state.mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  const available = actionsForMode(state.mode).map((item) => item.value);
  if (!available.includes(state.action)) state.action = available[0];
  renderActions();
  renderActionFields();
  renderRefs();
}

function setMode(mode) {
  if (!Object.hasOwn({ report: true, page: true }, mode)) return;
  state.mode = mode;
  renderMode();
}

function consumeContext(raw, origin) {
  const text = String(raw || "").trim();
  if (!text) {
    setStatus(`${origin}没有可识别内容。`, true);
    return;
  }
  const refs = parseMineMReferences(text);
  const reportRef = refs.find((item) => item.type === "report");
  const pageRefs = refs.filter((item) => item.type === "page");
  const sourceRef = refs.find((item) => item.type === "source");
  if (reportRef) report.value = reportRef.url || reportRef.code;
  for (const ref of pageRefs) state.pageRefs = mergeReference(state.pageRefs, ref);
  if (!source.value && sourceRef) source.value = sourceRef.url;
  if (!reportRef && !pageRefs.length && !sourceRef && !source.value) source.value = text;
  $("context-title").textContent = reportRef || pageRefs.length
    ? `${origin} · ${reportRef ? "汇报" : "页面"} · ${reportRef?.code || pageRefs[0]?.code || "已识别"}`
    : `${origin} · 已作为来源带入`;
  renderRefs();
  updateCopyState();
  setStatus("上下文已识别。" );
}

function loadTemplates() {
  try {
    const value = JSON.parse(localStorage.getItem(templateStorageKey) || "[]");
    state.templates = Array.isArray(value)
      ? value.filter((item) => item && typeof item.name === "string" && typeof item.body === "string").slice(0, 30)
      : [];
  } catch (_) {
    state.templates = [];
  }
}

function saveTemplates() {
  localStorage.setItem(templateStorageKey, JSON.stringify(state.templates.slice(0, 30)));
}

function renderTemplates() {
  const select = $("template-select");
  select.replaceChildren(new Option("新建指令", ""));
  state.templates.forEach((template) => select.add(new Option(template.name, template.id)));
  select.value = state.selectedTemplate;
}

async function copyOperationPackage() {
  try {
    const text = buildOperationPackage(currentOperationState());
    if (invoke) await invoke("quick_clipboard_write", { text });
    else await navigator.clipboard.writeText(text);
    setStatus("操作包已复制，可直接粘贴到 Codex。" );
  } catch (error) {
    setStatus(error.message || String(error), true);
  }
}

document.querySelector(".mode-switch").addEventListener("click", (event) => {
  const button = event.target.closest("[data-mode]");
  if (button) setMode(button.dataset.mode);
});

$("actions").addEventListener("click", (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  state.action = button.dataset.action;
  renderActions();
  renderActionFields();
  setStatus("");
});

$("read-current").onclick = async () => {
  try {
    const current = invoke ? await invoke("quick_current_url") : window.location.href;
    state.currentUrl = current || "";
    consumeContext(current, "当前页面");
  } catch (error) {
    setStatus(String(error), true);
  }
};

$("read-clipboard").onclick = async () => {
  try {
    const text = invoke ? await invoke("quick_clipboard_read") : await navigator.clipboard.readText();
    consumeContext(text, "剪贴板");
  } catch (error) {
    setStatus(String(error), true);
  }
};

$("add-reference").onclick = () => {
  const pageRefs = parseMineMReferences(source.value).filter((item) => item.type === "page");
  if (!pageRefs.length) {
    setStatus("未识别到页面链接或 CTRL-PAGE 编号。", true);
    return;
  }
  for (const ref of pageRefs) state.pageRefs = mergeReference(state.pageRefs, ref);
  renderRefs();
  updateCopyState();
  setStatus("页面引用已添加。" );
};

$("copy").onclick = copyOperationPackage;
$("preview").onclick = () => {
  const error = validateOperation(currentOperationState());
  setStatus(error || "上下文完整，可以生成操作包。", Boolean(error));
};
$("clear").onclick = () => {
  state.pageRefs = [];
  state.currentUrl = "";
  source.value = "";
  report.value = "";
  targetPage.value = "";
  requirements.value = "";
  $("context-title").textContent = "尚未识别页面上下文";
  setStatus("");
  renderRefs();
  updateCopyState();
};
$("close").onclick = () => invoke?.("hide_quick_actions");

$("template-select").onchange = (event) => {
  state.selectedTemplate = event.target.value;
  const template = state.templates.find((item) => item.id === state.selectedTemplate);
  $("template-name").value = template?.name || "";
  $("template-body").value = template?.body || "";
  updateCopyState();
};
$("save-template").onclick = () => {
  const name = $("template-name").value.trim();
  const body = $("template-body").value.trim();
  if (!name || !body) {
    setStatus("请填写指令名称和内容。", true);
    return;
  }
  const id = state.selectedTemplate || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const template = { id, name, body };
  const index = state.templates.findIndex((item) => item.id === id);
  if (index >= 0) state.templates[index] = template;
  else if (state.templates.length < 30) state.templates.push(template);
  else {
    setStatus("最多保留 30 条自定义指令。", true);
    return;
  }
  state.selectedTemplate = id;
  saveTemplates();
  renderTemplates();
  updateCopyState();
  setStatus("自定义指令已保存。" );
};
$("delete-template").onclick = () => {
  if (!state.selectedTemplate) return;
  state.templates = state.templates.filter((item) => item.id !== state.selectedTemplate);
  state.selectedTemplate = "";
  $("template-name").value = "";
  $("template-body").value = "";
  saveTemplates();
  renderTemplates();
  updateCopyState();
  setStatus("自定义指令已删除。" );
};

for (const element of [source, report, targetPage, requirements, $("template-body")]) {
  element.addEventListener("input", updateCopyState);
}

document.addEventListener("keydown", (event) => {
  if (event.metaKey && event.key === "1") {
    event.preventDefault();
    setMode("report");
  } else if (event.metaKey && event.key === "2") {
    event.preventDefault();
    setMode("page");
  } else if (event.metaKey && event.key.toLowerCase() === "k") {
    event.preventDefault();
    $("actions").querySelector(".active")?.focus();
  } else if (event.metaKey && event.key === "Enter") {
    event.preventDefault();
    copyOperationPackage();
  } else if (event.metaKey && event.shiftKey && event.key.toLowerCase() === "c") {
    event.preventDefault();
    copyOperationPackage();
  } else if (event.key === "Escape") {
    invoke?.("hide_quick_actions");
  }
});

loadTemplates();
renderMode();
