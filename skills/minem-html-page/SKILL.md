---
name: minem-html-page
description: Create a polished, self-contained 1920x1080 HTML presentation page from structured content and publish it as a MineM page material. Use when a user asks to generate an HTML report page, create a reusable page material, turn a short outline into one page, or create a page and insert it into an existing MineM report.
---

# MineM HTML Page

Use MineM's deterministic page builder. Do not create a second database path or call internal APIs directly.

## Workflow

1. Run `minem doctor --output json`. Stop and report the connection error if MineM is unavailable.
2. Convert the user's content into a JSON specification. Read [references/page-spec.md](references/page-spec.md) for the schema.
3. Keep one page focused on one conclusion. Shorten content before reducing visual hierarchy.
4. Build and publish:

```bash
minem page build \
  --spec "${SPEC_PATH}" \
  --file "${HTML_PATH}" \
  --publish \
  --wait \
  --output json \
  --no-input
```

5. Verify the returned resource has `type: page`, a `CTRL-*` code, and a reachable `links.preview`.
6. Return the page code and preview link to the user.

## Report Operations

To insert the new page into an existing report, use the returned page code:

```bash
minem report page add "${REPORT_REFERENCE}" \
  --page "${PAGE_CODE}" \
  --after "${TARGET_PAGE_REFERENCE}" \
  --confirm \
  --output json \
  --no-input
```

Use `report page replace` for replacement. Never delete the source page when removing, hiding, or replacing a report slot.

## Guardrails

- Generate exactly one page per specification.
- Use local images only. The builder embeds them into the HTML; remote image URLs are rejected.
- Do not add page navigation, fullscreen, copy-link, refresh, zoom, or viewer controls inside the HTML. MineM owns those controls.
- Do not use absolute local asset paths in the generated HTML.
- Do not write directly to SQLite, `extracted/`, `pages/`, or `thumbnails/`.
- Do not claim AI content generation comes from MineM CLI. The agent creates the specification; MineM renders, validates, imports, and manages it.
- Keep the generated HTML file after publishing so the user can inspect or reuse it.

## Fallback

If the requested composition cannot fit the supported specification, create a self-contained HTML file manually using the same 1920x1080 canvas contract, then publish it with:

```bash
minem page import "${HTML_PATH}" --name "${PAGE_TITLE}" --wait --output json --no-input
```

Still follow every guardrail above.
