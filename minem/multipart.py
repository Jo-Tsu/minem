"""Multipart form-data parser replacing deprecated cgi.FieldStorage."""

import io
import re
from pathlib import Path


class UploadedFile:
    __slots__ = ("filename", "file", "content_type")

    def __init__(self, filename, file, content_type="application/octet-stream"):
        self.filename = filename
        self.file = file
        self.content_type = content_type


def parse_content_disposition(header):
    params = {}
    parts = header.split(";")
    for part in parts[1:]:
        part = part.strip()
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1].replace('\\"', '"')
        params[key] = value
    return params


def parse_multipart(rfile, content_type, content_length=0):
    match = re.search(r'boundary=([^\s;]+)', content_type or "")
    if not match:
        return {}
    boundary = match.group(1).encode("ascii")
    if boundary.startswith(b'"') and boundary.endswith(b'"'):
        boundary = boundary[1:-1]

    raw = rfile.read(int(content_length)) if content_length else rfile.read()
    delimiter = b"--" + boundary
    end_delimiter = delimiter + b"--"

    parts = raw.split(delimiter)
    fields = {}

    for part in parts:
        if not part or part.strip() == b"--" or part == b"\r\n":
            continue
        if part.startswith(end_delimiter):
            break

        if b"\r\n\r\n" in part:
            header_block, body = part.split(b"\r\n\r\n", 1)
        elif b"\n\n" in part:
            header_block, body = part.split(b"\n\n", 1)
        else:
            continue

        if body.endswith(b"\r\n"):
            body = body[:-2]
        elif body.endswith(b"\n"):
            body = body[:-1]

        headers = {}
        for line in header_block.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if ":" in line:
                hname, hval = line.split(":", 1)
                headers[hname.strip().lower()] = hval.strip()

        disposition = headers.get("content-disposition", "")
        params = parse_content_disposition(disposition)
        name = params.get("name", "")
        filename = params.get("filename")

        if not name:
            continue

        if filename:
            file_obj = io.BytesIO(body)
            ct = headers.get("content-type", "application/octet-stream")
            fields[name] = UploadedFile(filename, file_obj, ct)
        else:
            fields[name] = body.decode("utf-8", errors="replace")

    return fields
