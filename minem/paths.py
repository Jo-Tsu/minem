from pathlib import Path


def is_safe_filename_stem(value):
    if not isinstance(value, str) or not value or value != value.strip() or value in {".", ".."}:
        return False
    if any(character in value for character in ("/", "\\", ":")) or any(ord(character) < 32 for character in value):
        return False
    try:
        return len(value.encode("utf-8")) <= 240
    except UnicodeError:
        return False


def is_path_within(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, ValueError):
        return False
