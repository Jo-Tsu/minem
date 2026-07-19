import test from "node:test";
import assert from "node:assert/strict";

import {
  actionsForMode,
  buildOperationPackage,
  parseMineMReferences,
  validateOperation,
} from "../ui/quick-actions-core.mjs";

test("creator assistant only exposes report and page workflows", () => {
  assert.deepEqual(actionsForMode("report").map((item) => item.label), ["导入", "新建", "插入", "替换", "修改", "案例", "指令"]);
  assert.deepEqual(actionsForMode("page").map((item) => item.label), ["导入", "新建", "复制", "修改", "指令"]);
});

test("parser separates report ids, page ids and MineM links", () => {
  const refs = parseMineMReferences([
    "RPT-20260714-001",
    "CTRL-PAGE-031",
    "http://127.0.0.1:8790/reports/RPT-20260714-001/index.html",
    "http://127.0.0.1:8790/pages/CTRL-PAGE-031/index.html",
  ].join("\n"));
  assert.equal(refs.filter((item) => item.type === "report").length, 1);
  assert.equal(refs.filter((item) => item.type === "page").length, 1);
  assert.equal(refs.find((item) => item.type === "page").url, "http://127.0.0.1:8790/pages/CTRL-PAGE-031/index.html");
});

test("generic extracted links stay source references instead of being guessed as reports", () => {
  const [ref] = parseMineMReferences("http://127.0.0.1:8790/extracted/import-1/index.html");
  assert.equal(ref.type, "source");
});

test("replace requires report, target and a page reference", () => {
  const base = { mode: "report", action: "replace_page", reportRef: "", targetPage: "", pageRefs: [] };
  assert.equal(validateOperation(base), "请填写汇报链接或编号。");
  assert.equal(validateOperation({ ...base, reportRef: "RPT-1", targetPage: 2 }), "请添加页面链接或 CTRL-PAGE 编号。");
});

test("new report and page require a focused topic", () => {
  assert.equal(validateOperation({ mode: "report", action: "create_report", source: "", pageRefs: [] }), "请填写汇报主题。");
  assert.equal(validateOperation({ mode: "page", action: "create_page", source: "", pageRefs: [] }), "请填写页面主题。");
});

test("operation package carries version and non-destructive constraints", () => {
  const text = buildOperationPackage({
    mode: "report",
    action: "insert_page",
    reportRef: "RPT-20260714-001",
    targetPage: 3,
    pageRefs: [{ type: "page", code: "CTRL-PAGE-031", url: "http://127.0.0.1:8790/pages/CTRL-PAGE-031/index.html" }],
    source: "插入到第三页前",
    requirements: "保持 16:9",
  });
  assert.match(text, /minem\.codex-operation\.v1/);
  assert.match(text, /不得删除页面素材/);
  assert.match(text, /CTRL-PAGE-031/);
  assert.match(text, /RPT-20260714-001/);
});
