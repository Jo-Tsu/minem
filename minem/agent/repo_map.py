import re
from collections import Counter, defaultdict
from pathlib import Path

from .workspace import classify_file, iter_source_files, line_count, read_text_sample, relative_path


IMPORTANT_NAMES = {
    "server.py",
    "Dockerfile",
    "docker-compose.yml",
    "requirements.txt",
    "package.json",
    "vite.config.ts",
    "tsconfig.json",
    "README.md",
}


SYMBOL_PATTERNS = [
    re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE),
    re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\s*[:(]", re.MULTILINE),
    re.compile(r"^\s*export\s+(?:default\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE),
    re.compile(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?(?:const|let)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", re.MULTILINE),
]


def extract_symbols(path, *, limit=24):
    text = read_text_sample(path, 80000)
    symbols = []
    seen = set()
    for pattern in SYMBOL_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group(1)
            if name in seen:
                continue
            seen.add(name)
            symbols.append(name)
            if len(symbols) >= limit:
                return symbols
    return symbols


def build_repo_map(root, *, focus="", max_files=600):
    root = Path(root)
    focus_words = {word.lower() for word in re.split(r"\W+", focus or "") if len(word) >= 3}
    files = []
    buckets = defaultdict(lambda: {"files": 0, "lines": 0})
    suffixes = Counter()

    for path in iter_source_files(root, max_files=max_files):
        rel = relative_path(root, path)
        bucket = classify_file(rel)
        lines = line_count(path)
        symbols = extract_symbols(path) if path.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".jsx"} else []
        text_for_focus = f"{rel} {' '.join(symbols)}".lower()
        focus_score = sum(1 for word in focus_words if word in text_for_focus)
        important = rel in IMPORTANT_NAMES or rel.startswith(("minem/", "frontend/src/", "docs/"))
        files.append(
            {
                "path": rel,
                "bucket": bucket,
                "suffix": path.suffix.lower() or "none",
                "lines": lines,
                "symbols": symbols[:16],
                "important": important,
                "focusScore": focus_score,
            }
        )
        buckets[bucket]["files"] += 1
        buckets[bucket]["lines"] += lines
        suffixes[path.suffix.lower() or "none"] += 1

    ranked = sorted(
        files,
        key=lambda item: (item["focusScore"], item["important"], item["lines"]),
        reverse=True,
    )
    return {
        "root": str(root),
        "summary": {
            "fileCount": len(files),
            "lineCount": sum(item["lines"] for item in files),
            "buckets": dict(sorted(buckets.items())),
            "suffixes": dict(suffixes.most_common()),
        },
        "focus": focus,
        "importantFiles": ranked[:40],
    }
