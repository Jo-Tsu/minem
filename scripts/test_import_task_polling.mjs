import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../frontend/src/import-task-polling.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } });
const { startImportTaskPolling } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputText).toString("base64")}`);
const flush = () => new Promise((resolve) => setImmediate(resolve));

test("active tasks produce one polling loop and stop after cancellation", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  let requests = 0;
  const received = [];
  const stop = startImportTaskPolling(async () => {
    requests += 1;
    return [{ id: "task", status: "queued" }];
  }, (tasks) => received.push(tasks), assert.fail);
  context.after(stop);
  await flush();
  context.mock.timers.tick(1200);
  await flush();
  context.mock.timers.tick(1200);
  await flush();
  assert.equal(requests, 3);
  assert.equal(received.length, 3);
  stop();
  context.mock.timers.tick(10000);
  await flush();
  assert.equal(requests, 3);
});

test("cancellation aborts pending requests and discards late results", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  let complete;
  let signal;
  const received = [];
  const stop = startImportTaskPolling((current) => {
    signal = current;
    return new Promise((resolve) => { complete = resolve; });
  }, (tasks) => received.push(tasks), assert.fail);
  stop();
  complete([{ id: "task", status: "queued" }]);
  await flush();
  context.mock.timers.tick(10000);
  assert.equal(signal.aborted, true);
  assert.deepEqual(received, []);
});

test("temporary errors retry without overlapping requests", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  let requests = 0;
  const errors = [];
  const received = [];
  const stop = startImportTaskPolling(async () => {
    requests += 1;
    if (requests === 1) throw new Error("offline");
    return [];
  }, (tasks) => received.push(tasks), (error) => errors.push(error));
  context.after(stop);
  await flush();
  context.mock.timers.tick(4999);
  await flush();
  assert.equal(requests, 1);
  context.mock.timers.tick(1);
  await flush();
  assert.equal(requests, 2);
  assert.equal(errors.length, 1);
  assert.deepEqual(received, [[]]);
});
