export const MODE_META = {
  report: { label: "汇报", shortcut: "⌘1" },
  page: { label: "页面", shortcut: "⌘2" },
  case: { label: "案例", shortcut: "⌘3" },
};

export const SCENARIO_META = {
  import_report: {
    mode: "report",
    label: "导入汇报",
    description: "外部多页材料入库，每页同步为页面素材",
    icon: "upload",
    skill: "minem-report-workflow",
    inputs: [
      "外部材料（文件、文件夹或链接）",
      "汇报名称（可选）",
      "补充要求（可选）",
    ],
    constraint: "多页材料生成一个汇报，每页同步为一个页面素材。",
  },
  create_report: {
    mode: "report",
    label: "新建汇报",
    description: "按主题或已有页面组装新的完整汇报",
    icon: "report",
    skill: "minem-report-workflow",
    inputs: [
      "汇报主题与目标",
      "已有页面编号或链接（可选）",
      "顺序、受众或表达要求（可选）",
    ],
    constraint: "优先复用已有页面，缺少的页面再创建。",
  },
  insert_page: {
    mode: "report",
    label: "插入页面",
    description: "把一个或多个页面插入指定汇报位置",
    icon: "insert",
    skill: "minem-report-workflow",
    inputs: [
      "目标汇报编号或链接",
      "页面编号或链接（可多项）",
      "插入位置",
    ],
    constraint: "只修改目标汇报的编排，不复制或删除页面素材。",
  },
  replace_page: {
    mode: "report",
    label: "替换页面",
    description: "用已有或新页面替换当前汇报某一页",
    icon: "replace",
    skill: "minem-report-workflow",
    inputs: [
      "目标汇报编号或链接",
      "被替换的页码或页面编号",
      "替换页面编号、链接或新内容要求",
    ],
    constraint: "只替换汇报中的页面引用，保留原页面。",
  },
  modify_report_page: {
    mode: "report",
    label: "修改页面",
    description: "修改汇报中的一页并保留原页面版本",
    icon: "edit",
    skill: "minem-report-workflow",
    inputs: [
      "目标汇报编号或链接",
      "目标页码或页面编号",
      "修改要求",
    ],
    constraint: "创建页面新版本，只更新当前汇报引用，保留旧版本。",
  },
  import_page: {
    mode: "page",
    label: "导入页面",
    description: "导入一个外部单页并登记为页面素材",
    icon: "upload",
    skill: "minem-html-page",
    inputs: [
      "单页文件或链接",
      "页面名称（可选）",
      "保真要求（可选）",
    ],
    constraint: "页面素材只能是一页；多页材料请改用导入汇报或提炼案例。",
  },
  create_page: {
    mode: "page",
    label: "新建页面",
    description: "从零生成一个可复用的 HTML 页面素材",
    icon: "page",
    skill: "minem-html-page",
    inputs: [
      "页面主题与关键信息",
      "目标受众",
      "版式或可用素材（可选）",
    ],
    constraint: "生成一个 1920×1080 单页，页面内不添加平台工具栏。",
  },
  duplicate_page: {
    mode: "page",
    label: "复制页面",
    description: "复制已有页面并创建独立的新版本",
    icon: "copy",
    skill: "minem-html-page",
    inputs: [
      "来源页面编号或链接",
      "需要保留的内容",
      "需要变化的内容",
    ],
    constraint: "创建独立的新版本，保留来源页面和既有引用。",
  },
  modify_page: {
    mode: "page",
    label: "修改页面",
    description: "基于已有页面生成一个修改后的新版本",
    icon: "edit",
    skill: "minem-html-page",
    inputs: [
      "来源页面编号或链接",
      "内容修改要求",
      "布局、尺寸或素材要求（可选）",
    ],
    constraint: "生成页面新版本，不覆盖旧页面或既有引用。",
  },
  extract_case: {
    mode: "case",
    label: "提炼案例",
    description: "把外部文档整理为案例组和多张案例页",
    icon: "case",
    skill: "minem-case-material",
    inputs: [
      "外部文档或链接",
      "目标受众",
      "案例数量与重点（可选）",
    ],
    constraint: "通过 minem case brief 默认 3 个案例，每个案例 1–4 页；创建案例组和独立案例页，不登记为汇报素材，不按章节全量生成，不编造事实；视频点击播放，优质客户素材完整纳入。",
  },
  insert_case: {
    mode: "case",
    label: "插入汇报",
    description: "将已有案例页批量插入指定汇报",
    icon: "insert",
    skill: "minem-case-material",
    inputs: [
      "案例组或案例页面编号、链接",
      "目标汇报编号或链接",
      "插入位置与顺序",
    ],
    constraint: "只插入选中的案例页，不删除案例素材。",
  },
};

export function scenariosForMode(mode) {
  return Object.entries(SCENARIO_META)
    .filter(([, meta]) => meta.mode === mode)
    .map(([value, meta]) => ({ value, ...meta }));
}

export function buildScenarioInstruction(scenarioId) {
  const scenario = SCENARIO_META[scenarioId];
  if (!scenario) throw new Error("未知的创作场景。");

  return [
    `请使用已安装的 MineM 客户端完成「${scenario.label}」。`,
    `调用 Skill：\`${scenario.skill}\`，通过 \`minem\` CLI 实际执行。`,
    "",
    "请把信息贴到下面后发送：",
    ...scenario.inputs.map((label) => `- ${label}：`),
    "",
    `注意：${scenario.constraint}`,
    "信息不足时只追问缺失项；完成后返回素材编号、可打开链接和验证结果。",
  ].join("\n");
}
