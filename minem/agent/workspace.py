from pathlib import Path


EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "data",
    "runtime",
    "uploads",
    "extracted",
    "thumbnails",
    "report-exports",
    "backups",
    "frontend/dist",
    "desktop/node_modules",
    "desktop/src-tauri/target",
    "public",
    "work",
    "realdoc",
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
    prefixes = {"/".join(parts[:length]) for length in range(1, len(parts) + 1)}
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

    def visit(directory):
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return
        for path in entries:
            if is_excluded(relative_path(root, path)):
                continue
            if path.is_dir():
                if not path.is_symlink():
                    yield from visit(path)
            elif path.is_file() and is_source_file(path):
                yield path

    count = 0
    for path in visit(root):
        if count >= max_files:
            break
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
