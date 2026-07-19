#!/usr/bin/env python3
import argparse
import asyncio
import io
import json
import os
import re
import sys
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import sherpa_onnx

try:
    import edge_tts
except ImportError:  # pragma: no cover - optional online engine
    edge_tts = None


ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL_DIR = os.path.join(ROOT, "models", "sherpa-onnx-vits-zh-ll")
EDGE_TIMEOUT_SECONDS = float(os.getenv("EDGE_TTS_TIMEOUT", "12"))

VOICES = [
    {
        "id": 0,
        "key": "xiaoxiao",
        "label": "晓晓｜自然女声",
        "edge_voice": "zh-CN-XiaoxiaoNeural",
        "fallback_sid": 0,
    },
    {
        "id": 1,
        "key": "yunyang",
        "label": "云扬｜新闻男声",
        "edge_voice": "zh-CN-YunyangNeural",
        "fallback_sid": 4,
    },
    {
        "id": 2,
        "key": "xiaoyi",
        "label": "晓伊｜温和女声",
        "edge_voice": "zh-CN-XiaoyiNeural",
        "fallback_sid": 2,
    },
    {
        "id": 3,
        "key": "yunjian",
        "label": "云健｜专业男声",
        "edge_voice": "zh-CN-YunjianNeural",
        "fallback_sid": 4,
    },
    {
        "id": 4,
        "key": "yunxi",
        "label": "云希｜清亮男声",
        "edge_voice": "zh-CN-YunxiNeural",
        "fallback_sid": 1,
    },
]


def normalize_text(text: str) -> str:
    replacements = [
        (r"\bAI\s*PMO\b", "人工智能项目管理助手"),
        (r"\bAI\b", "人工智能"),
        (r"\bPMO\b", "项目管理办公室"),
        (r"\bERP\b", "企业资源计划系统"),
        (r"\bCRM\b", "客户关系管理系统"),
        (r"\bSOP\b", "标准作业流程"),
        (r"\bPPT\b", "演示文稿"),
        (r"\bRPT\b", "汇报材料"),
        (r"\bCTRL\b", "控件材料"),
        (r"\bHTML\b", "网页"),
        (r"\bByte\b", "字节"),
        (r"\bFeishu\b", "飞书"),
        (r"\bSlack\b", "斯拉克"),
        (r"\bFacebook\b", "脸书"),
        (r"\bNetflix\b", "奈飞"),
        (r"150\s*多个", "一百五十多个"),
        (r"75\s*种", "七十五种"),
        (r"19\s*\+\s*亿", "十九亿"),
    ]
    normalized = text
    for pattern, value in replacements:
        normalized = re.sub(pattern, value, normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(?<=\d)[xX](?=\d)", "乘", normalized)
    punctuation = str.maketrans({
        ":": "，",
        "：": "，",
        ";": "。",
        "；": "。",
        "|": "，",
        "/": "，",
        "\\": "，",
        "·": "，",
        "•": "，",
        "&": "和",
        "×": "乘",
        "(": "，",
        ")": "，",
        "（": "，",
        "）": "，",
        "[": "，",
        "]": "，",
        "【": "，",
        "】": "，",
        '"': "",
        "'": "",
        "“": "",
        "”": "",
        "‘": "",
        "’": "",
    })
    normalized = normalized.translate(punctuation)
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"\s*([，。！？、—…])\s*", r"\1", normalized)
    normalized = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9%+\-，。！？、—… ]+", "，", normalized)
    normalized = re.sub(r"[，、]{2,}", "，", normalized)
    normalized = re.sub(r"[。]{2,}", "。", normalized)
    return normalized.strip(" ，。")


def build_tts(model_dir: str, num_threads: int) -> sherpa_onnx.OfflineTts:
    config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=os.path.join(model_dir, "model.onnx"),
                lexicon=os.path.join(model_dir, "lexicon.txt"),
                tokens=os.path.join(model_dir, "tokens.txt"),
                data_dir=model_dir,
            ),
            num_threads=num_threads,
            debug=False,
            provider="cpu",
        ),
        max_num_sentences=1,
        silence_scale=0.2,
    )
    return sherpa_onnx.OfflineTts(config)


def wav_bytes(samples, sample_rate: int) -> bytes:
    frames = bytearray()
    for sample in samples:
        value = max(-1.0, min(1.0, float(sample)))
        frames.extend(int(value * 32767).to_bytes(2, byteorder="little", signed=True))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)
    return buffer.getvalue()


def public_voices():
    return [{key: voice[key] for key in ("id", "key", "label")} for voice in VOICES]


async def _edge_tts_bytes(text: str, voice: str, speed: float) -> bytes:
    if edge_tts is None:
        raise RuntimeError("edge-tts-not-installed")
    rate_percent = int(round((speed - 1.0) * 100))
    communicate = edge_tts.Communicate(text, voice=voice, rate=f"{rate_percent:+d}%")
    chunks = []
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio" and chunk.get("data"):
            chunks.append(chunk["data"])
    if not chunks:
        raise RuntimeError("edge-tts-empty-audio")
    return b"".join(chunks)


def render_edge_tts(text: str, voice: str, speed: float) -> bytes:
    return asyncio.run(asyncio.wait_for(_edge_tts_bytes(text, voice, speed), timeout=EDGE_TIMEOUT_SECONDS))


class TtsHandler(BaseHTTPRequestHandler):
    server_version = "JielingLocalTTS/1.0"

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/health"):
            self._json({
                "ok": True,
                "engine": self.server.engine,
                "edge_available": edge_tts is not None,
                "fallback_engine": "sherpa-onnx-vits-zh-ll",
                "voices": public_voices(),
            })
            return
        if self.path.startswith("/voices"):
            self._json({"voices": public_voices()})
            return
        self.send_error(404)

    def do_POST(self):
        if not self.path.startswith("/tts"):
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            text = normalize_text(str(body.get("text", ""))).strip()
            if not text:
                raise ValueError("empty text")
            sid = int(body.get("voice", 0))
            speed = float(body.get("speed", 1.0))
            sid = min(max(sid, 0), len(VOICES) - 1)
            speed = min(max(speed, 0.8), 1.25)
            voice = VOICES[sid]
            data = None
            content_type = "audio/wav"
            engine = "sherpa-onnx"
            if self.server.prefer_edge and edge_tts is not None:
                try:
                    data = render_edge_tts(text, voice["edge_voice"], speed)
                    content_type = "audio/mpeg"
                    engine = "edge-tts"
                except Exception as error:
                    print(f"edge-tts failed, falling back to sherpa-onnx: {error}", file=sys.stderr)
            if data is None:
                audio = self.server.tts.generate(text, sid=voice["fallback_sid"], speed=speed)
                data = wav_bytes(audio.samples, audio.sample_rate)
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("X-TTS-Engine", engine)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as error:
            self._json({"ok": False, "error": str(error)}, status=500)

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), file=sys.stderr)

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    parser.add_argument("--threads", default=2, type=int)
    parser.add_argument("--engine", default=os.getenv("TTS_ENGINE", "edge"), choices=["edge", "sherpa"])
    args = parser.parse_args()

    print(f"Loading local TTS model from {args.model_dir}")
    server = ThreadingHTTPServer((args.host, args.port), TtsHandler)
    server.tts = build_tts(args.model_dir, args.threads)
    server.prefer_edge = args.engine == "edge"
    server.engine = "edge-tts+sherpa-onnx-fallback" if server.prefer_edge else "sherpa-onnx-vits-zh-ll"
    if server.prefer_edge and edge_tts is None:
        print("edge-tts is not installed; sherpa-onnx fallback will be used.", file=sys.stderr)
    print(f"Local TTS server listening on http://{args.host}:{args.port} ({server.engine})")
    server.serve_forever()


if __name__ == "__main__":
    main()
