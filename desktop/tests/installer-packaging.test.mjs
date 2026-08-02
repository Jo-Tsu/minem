import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [packager, backgroundGenerator] = await Promise.all([
  readFile(new URL("../scripts/package-macos-dmg.mjs", import.meta.url), "utf8"),
  readFile(new URL("../scripts/create-dmg-background.py", import.meta.url), "utf8"),
]);

test("installer provides a drag-to-Applications disk image", () => {
  assert.match(packager, /symlinkSync\("\/Applications", join\(stagingDir, "Applications"\)\)/);
  assert.match(packager, /cpSync\(app, join\(stagingDir, "MineM\.app"\)/);
  assert.match(packager, /"MineM\.app" of container window to \{172, 220\}/);
  assert.match(packager, /"Applications" of container window to \{468, 220\}/);
});

test("installer uses a Retina background with a headless fallback", () => {
  assert.match(packager, /create-dmg-background\.py/);
  assert.match(packager, /"-cathidpicheck"/);
  assert.match(packager, /set background picture of opts to file "\.background:bg\.tiff"/);
  assert.match(packager, /Finder styling unavailable; creating an unstyled drag-to-Applications DMG/);
  assert.match(backgroundGenerator, /CANVAS_WIDTH = 640/);
  assert.match(backgroundGenerator, /CANVAS_HEIGHT = 423/);
  assert.match(backgroundGenerator, /Drag MineM to Applications/);
  assert.match(backgroundGenerator, /render_background\(2/);
});
