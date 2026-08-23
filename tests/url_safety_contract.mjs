import assert from "node:assert/strict";
import { safeAbsoluteUrl, safePreviewUrl } from "../frontend/src/urlSafety.ts";

const base = "http://127.0.0.1:8790/library";

assert.equal(safeAbsoluteUrl("/reports/demo/index.html", base), "http://127.0.0.1:8790/reports/demo/index.html");
assert.equal(safeAbsoluteUrl("https://example.com/report", base), "https://example.com/report");
assert.equal(safeAbsoluteUrl("http://example.com/report", base), "");
assert.equal(safeAbsoluteUrl("javascript:alert(1)", base), "");
assert.equal(safeAbsoluteUrl("file:///tmp/report.html", base), "");
assert.equal(safeAbsoluteUrl("https://user:pass@example.com/", base), "");
assert.equal(safePreviewUrl("data:image/png;base64,AAAA", base), "data:image/png;base64,AAAA");
assert.equal(safePreviewUrl("data:text/html,<script>alert(1)</script>", base), "");

console.log("url safety contract passed");
