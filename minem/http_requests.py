"""Bound request bodies before parsing them at the HTTP boundary."""

import json
import re


MAX_JSON_REQUEST_BYTES = 128 * 1024


class RequestBodyError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def request_content_length(headers, max_bytes):
    if headers.get("Transfer-Encoding"):
        raise RequestBodyError("不支持 Transfer-Encoding 请求正文")
    values = headers.get_all("Content-Length", [])
    if len(values) > 1:
        raise RequestBodyError("Content-Length 不可重复")
    raw = values[0].strip() if values else "0"
    if not re.fullmatch(r"[0-9]{1,20}", raw):
        raise RequestBodyError("Content-Length 必须是非负整数")
    length = int(raw)
    if length > max_bytes:
        raise RequestBodyError("请求正文过大", 413)
    return length


def read_json_request(headers, stream, max_bytes=MAX_JSON_REQUEST_BYTES):
    length = request_content_length(headers, max_bytes)
    try:
        body = stream.read(length)
    except TimeoutError as error:
        raise RequestBodyError("读取请求正文超时", 408) from error
    if len(body) != length:
        raise RequestBodyError("请求正文不完整")
    try:
        payload = json.loads(body or b"{}")
    except (ValueError, RecursionError) as error:
        raise RequestBodyError("请求正文必须是有效的 JSON") from error
    if not isinstance(payload, dict):
        raise RequestBodyError("JSON 请求正文必须是对象")
    return payload
