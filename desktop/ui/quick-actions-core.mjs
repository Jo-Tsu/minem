export const MODE_META = {
  report: { label: "汇报", shortcut: "⌘1" },
  page: { label: "页面", shortcut: "⌘2" },
};

export const ACTION_META = {
  import_report: {
    mode: "report",
    label: "导入",
    icon: "upload",
    sourceLabel: "外部汇报",
    sourcePlaceholder: "文件路径、HTML/PPT/PDF 或外部链接",
    instruction: "导入外部多页材料，整体生成一个汇报素材，并将每一页分别生成页面素材。",
    needsSource: true,
  },
  create_report: {
    mode: "report",
    label: "新建",
    icon: "report",
    sourceLabel: "汇报主题",
    sourcePlaceholder: "标题、目标或已有内容说明",
    instruction: "创建新的汇报素材；如提供页面引用，严格按引用顺序组装。",
    needsSource: true,
  },
  insert_page: {
    mode: "report",
    label: "插入",
    icon: "insert",
    sourceLabel: "插入说明",
    sourcePlaceholder: "说明插入位置与页面衔接要求",
    instruction: "把引用页面插入指定汇报；只新增汇报页面槽位，不复制或删除页面素材。",
    needsReport: true,
    needsTarget: true,
    needsPageRefs: true,
  },
  replace_page: {
    mode: "report",
    label: "替换",
    icon: "replace",
    sourceLabel: "替换说明",
    sourcePlaceholder: "说明替换后的表达目标",
    instruction: "用引用页面替换指定汇报页；保留被替换页面素材，只更新当前汇报的页面槽位。",
    needsReport: true,
    needsTarget: true,
    needsPageRefs: true,
  },
  modify_report_page: {
    mode: "report",
    label: "修改",
    icon: "edit",
    sourceLabel: "修改说明",
    sourcePlaceholder: "说明要调整的内容、布局或表达",
    instruction: "基于指定汇报页创建页面新版本，并仅在当前汇报中引用新版本。",
    needsReport: true,
    needsTarget: true,
  },
  extract_case: {
    mode: "report",
    label: "案例",
    icon: "case",
    sourceLabel: "外部文档",
    sourcePlaceholder: "飞书文档、Markdown、PDF 或其他来源",
    instruction: "从外部文档提炼案例组和多张单页案例素材，再按要求插入指定汇报。",
    needsSource: true,
  },
  import_page: {
    mode: "page",
    label: "导入",
    icon: "upload",
    sourceLabel: "外部单页",
    sourcePlaceholder: "单页 HTML、图片、PDF 页或外部链接",
    instruction: "导入一个单页并生成页面素材；检测到多页时停止并提示改用汇报导入。",
    needsSource: true,
  },
  create_page: {
    mode: "page",
    label: "新建",
    icon: "page",
    sourceLabel: "页面主题",
    sourcePlaceholder: "页面目标、关键信息与表达要求",
    instruction: "从零创建一个 16:9 单页页面素材，并返回新页面编号和真实链接。",
    needsSource: true,
  },
  duplicate_page: {
    mode: "page",
    label: "复制",
    icon: "copy",
    sourceLabel: "复制要求",
    sourcePlaceholder: "说明需要保留和修改的内容",
    instruction: "复制引用页面并创建独立的新版本，不覆盖来源页面。",
    needsPageRefs: true,
  },
  modify_page: {
    mode: "page",
    label: "修改",
    icon: "edit",
    sourceLabel: "修改要求",
    sourcePlaceholder: "说明内容、布局、尺寸或资源修改",
    instruction: "基于引用页面创建新版本，保留旧版本和全部既有引用。",
    needsPageRefs: true,
  },
  custom_prompt: {
    mode: "both",
    label: "指令",
    icon: "command",
    sourceLabel: "上下文",
    sourcePlaceholder: "补充需要带给 AI 的上下文",
    instruction: "使用当前上下文生成自定义指令。",
    custom: true,
  },
};

export function actionsForMode(mode) {
  return Object.entries(ACTION_META)
    .filter(([, meta]) => meta.mode === mode || meta.mode === "both")
    .map(([value, meta]) => ({ value, ...meta }));
}

function cleanUrl(raw) {
  return raw.replace(/[),，。；;\]}>]+$/g, "");
}

export function parseMineMReferences(value) {
  const text = String(value || "").trim();
  if (!text) return [];

  const refs = [];
  const add = (ref) => {
    const key = `${ref.type}:${ref.code || ref.url}`;
    const index = refs.findIndex((item) => item.key === key);
    if (index < 0) refs.push({ ...ref, key });
    else refs[index] = { ...refs[index], code: refs[index].code || ref.code, url: refs[index].url || ref.url };
  };

  for (const match of text.matchAll(/CTRL-PAGE-[A-Z0-9-]+/gi)) {
    add({ type: "page", code: match[0].toUpperCase(), url: "" });
  }
  for (const match of text.matchAll(/RPT-[A-Z0-9-]+/gi)) {
    add({ type: "report", code: match[0].toUpperCase(), url: "" });
  }
  for (const match of text.matchAll(/https?:\/\/[^\s]+/gi)) {
    const url = cleanUrl(match[0]);
    let parsed;
    try {
      parsed = new URL(url);
    } catch (_) {
      continue;
    }
    const pageMatch = parsed.pathname.match(/\/pages\/([^/?#]+)(?:\/index\.html)?/i);
    const reportMatch = parsed.pathname.match(/\/reports\/([^/?#]+)(?:\/index\.html)?/i);
    if (pageMatch) {
      add({ type: "page", code: pageMatch[1].toUpperCase(), url });
    } else if (reportMatch) {
      add({ type: "report", code: reportMatch[1].toUpperCase(), url });
    } else {
      add({ type: "source", code: "", url });
    }
  }
  return refs.map(({ key, ...ref }) => ref);
}

export function mergeReference(target, incoming) {
  if (!incoming) return target;
  const existingIndex = target.findIndex(
    (item) => item.type === incoming.type && ((item.code && item.code === incoming.code) || (item.url && item.url === incoming.url)),
  );
  if (existingIndex < 0) return [...target, incoming];
  const next = [...target];
  next[existingIndex] = {
    ...next[existingIndex],
    code: next[existingIndex].code || incoming.code,
    url: next[existingIndex].url || incoming.url,
  };
  return next;
}

export function validateOperation(state) {
  const meta = ACTION_META[state.action];
  if (!meta) return "请选择操作。";
  if (meta.needsSource && !state.source?.trim()) return `请填写${meta.sourceLabel}。`;
  if (meta.needsReport && !state.reportRef?.trim()) return "请填写汇报链接或编号。";
  if (meta.needsTarget && !String(state.targetPage || "").trim()) return "请填写目标页码。";
  if (meta.needsPageRefs && !state.pageRefs?.length) return "请添加页面链接或 CTRL-PAGE 编号。";
  if (state.pageRefs?.some((item) => item.type !== "page")) return "页面引用中只能包含页面链接或 CTRL-PAGE 编号。";
  return "";
}

function renderRef(ref) {
  if (ref.code && ref.url) return `${ref.code} | ${ref.url}`;
  return ref.code || ref.url;
}

export function buildOperationPackage(state) {
  const meta = ACTION_META[state.action];
  const error = validateOperation(state);
  if (error) throw new Error(error);

  if (meta.custom) {
    const body = state.customBody?.trim();
    if (!body) throw new Error("请输入自定义指令。" );
    const values = {
      mode: MODE_META[state.mode]?.label || state.mode,
      action: meta.label,
      page_refs: (state.pageRefs || []).map(renderRef).join("\n"),
      report_ref: state.reportRef?.trim() || "",
      target_page: String(state.targetPage || ""),
      source_ref: state.source?.trim() || "",
      requirements: state.requirements?.trim() || "",
    };
    return body.replace(/\{\{(mode|action|page_refs|report_ref|target_page|source_ref|requirements)\}\}/g, (_, key) => values[key]);
  }

  const payload = {
    schema: "minem.codex-operation.v1",
    mode: state.mode,
    action: state.action,
    report_ref: state.reportRef?.trim() || null,
    target_page: Number(state.targetPage) || null,
    page_refs: (state.pageRefs || []).map(({ type, code, url }) => ({ type, code: code || null, url: url || null })),
    source_ref: state.source?.trim() || null,
    requirements: state.requirements?.trim() || null,
  };
  const context = [
    payload.report_ref ? `- 当前汇报：${payload.report_ref}` : "",
    payload.target_page ? `- 目标页：第 ${payload.target_page} 页` : "",
    ...payload.page_refs.map((ref) => `- 页面引用：${renderRef(ref)}`),
    payload.source_ref ? `- 来源/主题：${payload.source_ref}` : "",
    payload.requirements ? `- 补充要求：${payload.requirements}` : "",
  ].filter(Boolean);

  return [
    "MineM / Codex 操作包 v1",
    `模式：${MODE_META[state.mode]?.label || state.mode}`,
    `任务：${meta.label}`,
    "",
    meta.instruction,
    ...(context.length ? ["", "上下文：", ...context] : []),
    "",
    "执行约束：",
    "1. 只操作 MineM 平台，不改写 superclub 原始素材、既有生成方式或无关数据。",
    "2. 页面素材必须是单页；多页内容只能创建汇报素材或案例素材，并为每页建立页面素材。",
    "3. 修改或复制页面必须创建新版本，保留旧版本及其引用；插入或移出汇报不得删除页面素材。",
    "4. 预览统一按 16:9 画布适配，校验资源闭包、真实链接、编号、页数和页面顺序。",
    "5. 完成后返回最终编号、真实页面链接、变更清单和验证结果。",
    "",
    "结构化参数：",
    JSON.stringify(payload, null, 2),
  ].join("\n");
}
