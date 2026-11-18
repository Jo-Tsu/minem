import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const temporary = mkdtempSync(path.join(tmpdir(), "minem-frontend-test-"));
const result = await build({
  stdin: {
    contents: `
      import React from 'react';
      import { renderToStaticMarkup } from 'react-dom/server';
      import App from './frontend/src/App';
      import { Workbench } from './frontend/src/components/Workbench';
      export { api } from './frontend/src/api';
      export function appMarkup() { return renderToStaticMarkup(<App />); }
      export function workbenchMarkup() {
        return renderToStaticMarkup(<Workbench stats={null} pipeline={null}
          workbench={{reports: [], controls: [], resources: []}}
          setAssetType={() => {}} setView={() => {}} openAsset={async () => {}} />);
      }
    `,
    resolveDir: root,
    loader: "tsx",
  },
  bundle: true,
  write: false,
  platform: "node",
  format: "cjs",
  jsx: "automatic",
});
const bundle = path.join(temporary, "frontend.cjs");
writeFileSync(bundle, result.outputFiles[0].text);
const { api, appMarkup, workbenchMarkup } = createRequire(import.meta.url)(bundle);
process.on("exit", () => rmSync(temporary, { recursive: true, force: true }));

test("navigation exposes working report creation", () => {
  assert.match(appMarkup(), /新建汇报/);
});

test("navigation omits the retired storyline view", () => {
  assert.doesNotMatch(appMarkup(), /故事线|>故事</);
});

test("workbench keeps resources encapsulated inside pages", () => {
  assert.doesNotMatch(workbenchMarkup(), /最近资源/);
  assert.match(workbenchMarkup(), /最近页面/);
});

test("report creation sends ordered page IDs to the current API", async (context) => {
  const requests = [];
  context.mock.method(globalThis, "fetch", async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify({ ok: true, asset: { id: "report" } }));
  });
  const result = await api.createReport({ title: "Report", pageIds: ["b", "a"], note: "note" });
  assert.equal(result.asset.id, "report");
  assert.equal(requests[0].url, "/api/reports");
  assert.equal(requests[0].options.method, "POST");
  assert.deepEqual(JSON.parse(requests[0].options.body), { title: "Report", pageIds: ["b", "a"], note: "note" });
});

test("frontend only retains supported API operations", () => {
  for (const name of ["storylines", "createStorylineCollection", "createStorylineReport", "reportPresenterScript", "aiTag", "createTagAnalysisTask", "saveAssetTags", "adoptCandidate"]) {
    assert.equal(name in api, false, `${name} has been retired`);
  }
});

test("HTTP errors cannot be presented as successful operations", async (context) => {
  context.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({ ok: true, error: "Failed" }), { status: 500 }));
  const response = await api.createReport({ title: "Report", pageIds: ["page"] });
  assert.equal(response.ok, false);
  assert.equal(response.error, "Failed");
});

test("non-JSON service failures return a readable error", async (context) => {
  context.mock.method(globalThis, "fetch", async () => new Response("Service unavailable", { status: 503 }));
  const response = await api.assets({ type: "control" });
  assert.equal(response.ok, false);
  assert.match(response.error, /503/);
});

test("connection failures return an error instead of rejecting UI actions", async (context) => {
  context.mock.method(globalThis, "fetch", async () => { throw new TypeError("Failed to fetch"); });
  const response = await api.asset("page");
  assert.equal(response.ok, false);
  assert.match(response.error, /连接/);
});
