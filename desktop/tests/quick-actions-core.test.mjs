import test from "node:test";
import assert from "node:assert/strict";

import {
  MODE_META,
  SCENARIO_META,
  buildScenarioInstruction,
  scenariosForMode,
} from "../ui/quick-actions-core.mjs";

test("creator assistant exposes report, page and case scenario libraries", () => {
  assert.deepEqual(Object.keys(MODE_META), ["report", "page", "case"]);
  assert.deepEqual(
    scenariosForMode("report").map((item) => item.label),
    ["导入汇报", "新建汇报", "插入页面", "替换页面", "修改页面"],
  );
  assert.deepEqual(
    scenariosForMode("page").map((item) => item.label),
    ["导入页面", "新建页面", "复制页面", "修改页面"],
  );
  assert.deepEqual(
    scenariosForMode("case").map((item) => item.label),
    ["提炼案例", "插入汇报"],
  );
});

test("every scenario declares a real fixed skill and fill-in fields", () => {
  for (const scenario of Object.values(SCENARIO_META)) {
    assert.match(scenario.skill, /^minem-/);
    assert.ok(scenario.inputs.length >= 2);
    assert.ok(scenario.inputs.every((item) => item.length >= 4));
    assert.ok(scenario.constraint.length >= 10);
  }
});

test("scenario instruction is a short fill-in template for an installed client", () => {
  const text = buildScenarioInstruction("create_page");
  assert.match(text, /请使用已安装的 MineM 客户端完成「新建页面」/);
  assert.match(text, /调用 Skill：`minem-html-page`/);
  assert.match(text, /请把信息贴到下面后发送/);
  assert.match(text, /- 页面主题与关键信息：\n/);
  assert.match(text, /- 目标受众：\n/);
  assert.match(text, /通过 `minem` CLI 实际执行/);
  assert.match(text, /完成后返回素材编号、可打开链接和验证结果/);
  assert.ok(text.length < 360);
  assert.doesNotMatch(text, /执行协议|MineM 固定规则|minem doctor|agent capabilities/);
});

test("report modification instruction preserves versions and references", () => {
  const text = buildScenarioInstruction("modify_report_page");
  assert.match(text, /- 目标汇报编号或链接：/);
  assert.match(text, /- 目标页码或页面编号：/);
  assert.match(text, /创建页面新版本/);
  assert.match(text, /只更新当前汇报引用/);
  assert.match(text, /保留旧版本/);
});

test("imports keep page and report classifications distinct", () => {
  const report = buildScenarioInstruction("import_report");
  const page = buildScenarioInstruction("import_page");
  assert.match(report, /- 外部材料（文件、文件夹或链接）：/);
  assert.match(report, /多页材料生成一个汇报/);
  assert.match(report, /每页同步为一个页面素材/);
  assert.match(page, /- 单页文件或链接：/);
  assert.match(page, /页面素材只能是一页/);
});

test("case instructions create case groups instead of report records", () => {
  const text = buildScenarioInstruction("extract_case");
  assert.match(text, /调用 Skill：`minem-case-material`/);
  assert.match(text, /默认 3 个/);
  assert.match(text, /minem case brief/);
  assert.match(text, /不按章节全量生成/);
  assert.match(text, /1–4 页/);
  assert.match(text, /视频点击播放/);
  assert.match(text, /优质客户素材完整纳入/);
});

test("desktop instructions assume the installed client and avoid machine-specific paths", () => {
  const text = buildScenarioInstruction("insert_page");
  assert.match(text, /已安装的 MineM 客户端/);
  assert.match(text, /- 目标汇报编号或链接：/);
  assert.match(text, /- 插入位置：/);
  assert.doesNotMatch(text, /\/Users\/|cliExecutable/);
});

test("unknown scenarios fail explicitly", () => {
  assert.throws(
    () => buildScenarioInstruction("missing"),
    /未知的创作场景/,
  );
});
