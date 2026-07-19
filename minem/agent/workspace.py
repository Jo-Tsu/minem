from pathlib import Path


EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "data",
    "uploads",
    "extracted",
    "thumbnails",
    "backups",
    "local-tts/models",
    "frontend/dist",
    "public",
    "work",
    "realdoc",
    "local-tts",
}

EXCLUDED_FILES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
}

SOURCE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".css",
    ".html",
    ".json",
    ".md",
    ".yml",
    ".yaml",
}


def relative_path(root, path):
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def is_excluded(rel_path):
    rel = rel_path.replace("\\", "/").strip("/")
    if not rel:
        return False
    if Path(rel).name in EXCLUDED_FILES:
        return True
    parts = rel.split("/")
    prefixes = {parts[0]}
    if len(parts) >= 2:
        prefixes.add("/".join(parts[:2]))
    return bool(prefixes & EXCLUDED_DIRS)


def is_source_file(path):
    return Path(path).suffix.lower() in SOURCE_SUFFIXES


def classify_file(rel_path):
    rel = rel_path.replace("\\", "/")
    suffix = Path(rel).suffix.lower()
    if rel.startswith("frontend/"):
        return "frontend"
    if rel == "server.py" or rel.startswith(("minem/", "scripts/", "templates/")):
        return "backend"
    if rel.startswith(("docs/", "README")) or suffix == ".md":
        return "docs"
    if suffix in {".json", ".yml", ".yaml"}:
        return "config"
    return "other"


def iter_source_files(root, *, max_files=2000):
    root = Path(root)
    count = 0
    for path in sorted(root.rglob("*")):
        if count >= max_files:
            break
        if not path.is_file():
            continue
        rel = relative_path(root, path)
        if is_excluded(rel) or not is_source_file(path):
            continue
        count += 1
        yield path


def read_text_sample(path, limit=12000):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return text[:limit]


def line_count(path):
    try:
        with Path(path).open("r", encoding="utf-8", errors="ignore") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0
