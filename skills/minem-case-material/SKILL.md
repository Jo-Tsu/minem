---
name: minem-case-material
description: Turn external documents into MineM case groups and reusable single-page case materials, then optionally insert selected case pages into a report.
---

# MineM Case Material

Use this skill when the user wants to extract cases from a document, create a case group with multiple case pages, or insert existing case pages into a report.

## Boundary

- A case group is not a report material.
- Every case page is an independent single-page material.
- Use public MineM CLI capabilities; never write the database directly.
- Keep source traceability and do not invent unsupported facts.
- Reuse identical historical pages and resources instead of duplicating them.
- The CLI brief is the source of truth for selection and generation rules. Do not maintain a separate ad-hoc prompt.
- By default publish at most 3 high-value cases. Do not create one case per heading, and do not pad the result to the limit.

## Start

1. Run `minem doctor --output json --no-input`.
2. Run `minem agent capabilities --output json`.
3. Run `minem case brief <source> --audience <audience> --max-cases 3 --output json --no-input`.
4. Treat the returned `prompt`, `selectionPolicy`, `mediaPolicy`, `pagePolicy`, and `outputSchema` as mandatory.
5. Read the source document and identify audience, case boundaries, facts, outcomes, and evidence.
6. Ask only for information still required to execute.

## Extract

1. Clean navigation, boilerplate, duplicate passages, timestamps that do not carry meaning, and malformed text.
2. Preserve useful meeting timestamps and source anchors.
3. Merge headings that describe the same business object or result chain before scoring candidates.
4. Score candidates using the CLI contract. Publish only candidates above the threshold, up to the requested maximum; fewer is correct when evidence is weak.
5. Produce the exact structured output required by the CLI `outputSchema`, including excluded candidates and reasons.
6. Create one or more reusable page materials per selected case using `minem-html-page`, following the adaptive 1–4 page plan returned by the CLI contract.
7. Register directly related attachments as resource materials and map each one to background, pain, solution, result, or modal.
8. Register the case group and its ordered page references through MineM CLI.

## Media And Page Rules

- Use only source media that directly proves the selected case. Never mix assets across cases.
- Prefer original media; do not substitute a user screenshot when the source contains the original asset.
- Keep every strong customer asset that directly proves the selected case; do not discard useful media just to force a single-image page.
- Select one primary evidence asset per page. Place before/after media in the module it proves; use additional pages or expandable areas for other strong evidence.
- Video must be a real playable resource: click to play with controls, pause, seek and fullscreen; never autoplay; provide a fallback link to the original video.
- Preserve GIF animation and make images openable at original size.
- A case uses 1–4 pages according to evidence density. Use one page only when it remains clear; split overview, before/after, workflow/video and results when strong evidence would otherwise be compressed.
- Save the original source URL on every page. MineM viewer owns source-copy UI and its one-second success toast; do not add a duplicate viewer toolbar inside the page.
- If the document contains many eligible sections and the user did not set a count, keep only the top 3 cases by score.

## Insert

1. List the selected case pages.
2. Resolve the target report and insertion position.
3. Insert page references without copying or deleting page materials.
4. Verify report page count and order.

## Finish

Return the case-group code, selected case count, page count per case, excluded candidate count, page codes, resource codes, real preview links, target report changes when applicable, command summary, video/GIF verification, and validation results.
