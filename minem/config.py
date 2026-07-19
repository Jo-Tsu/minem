import os


def env_int(name, default):
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


MAX_UPLOAD_BYTES = env_int("MAX_UPLOAD_BYTES", 512 * 1024 * 1024)
MAX_UPLOAD_REQUEST_BYTES = env_int("MAX_UPLOAD_REQUEST_BYTES", MAX_UPLOAD_BYTES + 16 * 1024 * 1024)
MAX_ZIP_FILES = env_int("MAX_ZIP_FILES", 5000)
MAX_ZIP_MEMBER_BYTES = env_int("MAX_ZIP_MEMBER_BYTES", 256 * 1024 * 1024)
MAX_ZIP_TOTAL_BYTES = env_int("MAX_ZIP_TOTAL_BYTES", 1024 * 1024 * 1024)
MAX_ZIP_COMPRESSION_RATIO = env_int("MAX_ZIP_COMPRESSION_RATIO", 120)
STREAM_CHUNK_BYTES = env_int("STREAM_CHUNK_BYTES", 1024 * 1024)
