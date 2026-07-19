#!/usr/bin/env python3
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def fetch_json(base_url, path, query=None):
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = response.read().decode("utf-8")
            return response.status, json.loads(payload)
    except urllib.error.HTTPError as error:
        payload = error.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = {"error": payload}
        return error.code, data


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def require_keys(payload, keys, context):
    missing = [key for key in keys if key not in payload]
    require(not missing, f"{context} missing keys: {', '.join(missing)}")


def main():
    parser = argparse.ArgumentParser(description="Check MineM local API contract.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8790", help="MineM server base URL")
    args = parser.parse_args()
    base_url = args.base_url

    status, stats_before = fetch_json(base_url, "/api/stats")
    require(status == 200, f"/api/stats expected 200, got {status}: {stats_before}")
    require_keys(stats_before, ["assetCount", "visibleAssetCount", "rawAssetCount", "versionedAssetCount", "uploadCount", "types", "pipeline"], "/api/stats")
    require(isinstance(stats_before["assetCount"], int), "assetCount must be int")
    require(stats_before["visibleAssetCount"] + stats_before["versionedAssetCount"] == stats_before["rawAssetCount"], "asset visibility counts must reconcile")

    status, assets = fetch_json(
        base_url,
        "/api/assets",
        {"type": "resource", "category": "all", "resource_kind": "all", "page": 1, "page_size": 5},
    )
    require(status == 200, f"/api/assets expected 200, got {status}: {assets}")
    require_keys(assets, ["assets", "pagination", "types", "resourceKinds", "pipeline"], "/api/assets")
    require(isinstance(assets["assets"], list), "assets must be list")
    pagination = assets["pagination"]
    require_keys(pagination, ["page", "pageSize", "total", "totalPages", "hasPrev", "hasNext"], "pagination")
    require(pagination["page"] == 1, "pagination.page must echo requested page")
    require(pagination["pageSize"] <= 5, "pagination.pageSize must respect requested page size")
    require(len(assets["assets"]) <= 5, "paginated assets must not exceed page size")

    status, tasks = fetch_json(base_url, "/api/import-tasks")
    require(status == 200, f"/api/import-tasks expected 200, got {status}: {tasks}")
    require(tasks.get("ok") is True and isinstance(tasks.get("tasks"), list), "import tasks contract invalid")

    status, case_groups = fetch_json(base_url, "/api/case-groups")
    require(status == 200, f"/api/case-groups expected 200, got {status}: {case_groups}")
    require(case_groups.get("ok") is True and isinstance(case_groups.get("caseGroups"), list), "case groups contract invalid")
    require(case_groups.get("total") == len(case_groups["caseGroups"]), "case group total must match payload")
    for group in case_groups["caseGroups"]:
        require_keys(group, ["code", "title", "reportUrl", "controls"], "case group")
        require(group["controls"] and all(item.get("code") and item.get("controlUrl") for item in group["controls"]), "case group controls must be imported and previewable")

    status, retired_graph = fetch_json(base_url, "/api/graph")
    require(status == 404, f"retired /api/graph must return 404, got {status}: {retired_graph}")

    status, reports = fetch_json(
        base_url,
        "/api/assets",
        {"type": "report", "category": "all", "resource_kind": "all", "page": 1, "page_size": 1},
    )
    require(status == 200, f"/api/assets report expected 200, got {status}: {reports}")
    report_items = reports.get("assets") or []
    if report_items:
        report_id = report_items[0]["id"]
        status, lineage = fetch_json(base_url, f"/api/assets/{urllib.parse.quote(report_id)}/lineage")
        require(status == 200, f"/api/assets/{{id}}/lineage expected 200, got {status}: {lineage}")
        require(lineage.get("ok") is True, "lineage ok must be true")
        require_keys(lineage, ["assetId", "sourceBatch", "sections"], "lineage")
        require(isinstance(lineage["sections"], list), "lineage.sections must be list")

    status, stats_after = fetch_json(base_url, "/api/stats")
    require(status == 200, f"/api/stats second read expected 200, got {status}: {stats_after}")
    require(
        stats_before["assetCount"] == stats_after["assetCount"],
        "read-only contract failed: assetCount changed after read endpoints",
    )

    print("API contract ok")
    print(json.dumps({
        "baseUrl": base_url,
        "assetCount": stats_after["assetCount"],
        "resourcePageSize": pagination["pageSize"],
        "resourceTotal": pagination["total"],
        "caseGroups": case_groups["total"],
        "checkedLineage": bool(report_items),
        "retiredGraphApi": True,
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"API contract failed: {error}", file=sys.stderr)
        sys.exit(1)
