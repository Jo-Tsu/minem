---
name: minem-report-workflow
description: Create, import, arrange, insert, replace, modify, validate, and export MineM report materials through the public MineM CLI.
---

# MineM Report Workflow

Use this skill whenever the user wants to import or create a multi-page report, insert or replace pages, modify a page inside a report, or validate report ordering.

## Boundary

- Use the public `minem` CLI. Never write the SQLite database directly.
- A report is an ordered list of page-material references.
- A page material is always one page.
- Removing or replacing a report slot never deletes the referenced page material.
- Page modifications create a new version and preserve the old version.
- Reuse existing page and resource records when content is identical.

## Start

1. Run `minem doctor --output json --no-input`.
2. Run `minem agent capabilities --output json`.
3. Read the current report and page references before mutating anything.
4. Ask only for information that is still missing from the conversation.

## Workflows

### Import

- Confirm the source is multi-page.
- Import it as one report.
- Ensure every source page becomes exactly one page material.
- Verify page count, order, resource closure, preview links, and idempotency.

### Create

- Agree on a page outline.
- Reuse supplied page references.
- Create missing pages with `minem-html-page`.
- Create the report with ordered page references.

### Insert or replace

- Resolve the target report and the target slot from the current report page list.
- Insert reuses a page reference.
- Replace changes one report slot and preserves the old page.
- If new content is needed, build and import a new page version first.

### Modify a report page

- Resolve the source page material.
- Use `minem-html-page` to create a new version.
- Replace only the target report slot with the new page reference.
- Verify that other reports still reference their original versions.

## Finish

Return the report code, real report URL, affected page codes, version or reference changes, command summary, and validation results. Do not stop after writing a plan.
