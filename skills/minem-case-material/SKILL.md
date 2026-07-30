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

## Start

1. Run `minem doctor --output json --no-input`.
2. Run `minem agent capabilities --output json`.
3. Read the source document and identify audience, case boundaries, facts, outcomes, and evidence.
4. Ask only for information still required to execute.

## Extract

1. Clean navigation, boilerplate, duplicate passages, timestamps that do not carry meaning, and malformed text.
2. Preserve useful meeting timestamps and source anchors.
3. Produce a case-group outline.
4. Create one reusable page material per case using `minem-html-page`.
5. Register the case group and its ordered page references through MineM CLI.

## Insert

1. List the selected case pages.
2. Resolve the target report and insertion position.
3. Insert page references without copying or deleting page materials.
4. Verify report page count and order.

## Finish

Return the case-group code, page codes, real preview links, target report changes when applicable, command summary, and validation results.
