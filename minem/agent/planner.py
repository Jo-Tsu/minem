from pathlib import Path

from .repo_map import build_repo_map


TASK_RULES = [
    {
        "name": "preview_pipeline",
        "keywords": ["preview", "thumbnail", "html", "预览", "缩略图", "图片", "卡片"],
        "files": ["minem/thumbnails.py", "minem/html_splitter.py", "server.py", "frontend/src/App.tsx", "frontend/src/styles.css"],
        "validations": ["python_compile", "frontend_build", "api_contract"],
        "risk": "medium",
    },
    {
        "name": "import_pipeline",
        "keywords": ["import", "upload", "导入", "入库", "外部资源", "页面素材"],
        "files": ["minem/imports.py", "minem/report_package_importer.py", "minem/resource_importer.py", "server.py", "frontend/src/App.tsx"],
        "validations": ["python_compile", "api_contract"],
        "risk": "high",
    },
    {
        "name": "report_storyline",
        "keywords": ["storyline", "collection", "version", "故事线", "收藏", "版本"],
        "files": ["minem/reports.py", "minem/lineage.py", "server.py", "frontend/src/App.tsx", "frontend/src/types.ts"],
        "validations": ["python_compile", "frontend_build", "api_contract"],
        "risk": "high",
    },
    {
        "name": "presenter_script",
        "keywords": ["presenter", "speech", "script", "演讲", "讲稿", "妙记", "时间戳"],
        "files": ["server.py", "templates/ai-presenter.html", "frontend/src/App.tsx", "frontend/src/styles.css"],
        "validations": ["python_compile", "frontend_build"],
        "risk": "medium",
    },
    {
        "name": "design_frontend",
        "keywords": ["style", "css", "ui", "design", "样式", "弹窗", "尺寸", "设计规范"],
        "files": ["frontend/src/App.tsx", "frontend/src/styles.css", "docs/DESIGN_SYSTEM.md"],
        "validations": ["frontend_build"],
        "risk": "medium",
    },
    {
        "name": "backend_core",
        "keywords": ["api", "server", "后端", "接口", "数据", "删除", "重命名"],
        "files": ["server.py", "minem/db.py", "minem/assets.py", "scripts/check_api_contract.py"],
        "validations": ["python_compile", "api_contract"],
        "risk": "medium",
    },
]


def _score_rule(task_text, rule):
    text = task_text.lower()
    return sum(1 for keyword in rule["keywords"] if keyword.lower() in text)


def analyze_task(root, task_text, *, focus=""):
    task_text = (task_text or "").strip()
    repo_map = build_repo_map(root, focus=focus or task_text)
    scored = []
    for rule in TASK_RULES:
        score = _score_rule(task_text, rule)
        if score:
            scored.append((score, rule))

    if not scored:
        scored = [(0, {
            "name": "general_engineering",
            "files": ["server.py", "frontend/src/App.tsx", "frontend/src/styles.css", "minem/"],
            "validations": ["python_compile", "frontend_build"],
            "risk": "medium",
        })]

    scored.sort(key=lambda item: item[0], reverse=True)
    selected_rules = [rule for _, rule in scored[:3]]
    impacted = []
    validations = []
    risk_rank = {"low": 1, "medium": 2, "high": 3}
    risk = "low"
    for rule in selected_rules:
        for file_path in rule.get("files", []):
            if file_path not in impacted:
                impacted.append(file_path)
        for check in rule.get("validations", []):
            if check not in validations:
                validations.append(check)
        if risk_rank[rule.get("risk", "medium")] > risk_rank[risk]:
            risk = rule.get("risk", "medium")

    existing_impacted = []
    missing_impacted = []
    for file_path in impacted:
        path = Path(root) / file_path
        if file_path.endswith("/") or path.exists():
            existing_impacted.append(file_path)
        else:
            missing_impacted.append(file_path)

    return {
        "ok": True,
        "task": task_text,
        "matchedCapabilities": [rule["name"] for rule in selected_rules],
        "risk": risk,
        "impactedFiles": existing_impacted,
        "missingReferences": missing_impacted,
        "recommendedValidations": validations,
        "method": [
            "Create a checkpoint before editing.",
            "Read impacted files and derive a narrow patch plan.",
            "Apply controlled patches only.",
            "Run recommended validations.",
            "Write an audit record with changed files and validation output.",
        ],
        "repoMapSummary": repo_map["summary"],
        "repoMapFocus": repo_map["importantFiles"][:12],
    }
