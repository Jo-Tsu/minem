FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir sherpa-onnx soundfile edge-tts

COPY server.py /app/server.py

EXPOSE 8765

CMD ["python", "/app/server.py", "--host", "0.0.0.0", "--port", "8765", "--model-dir", "/app/models/sherpa-onnx-vits-zh-ll"]
