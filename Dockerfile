ARG MINEM_RUNTIME_BASE=python:3.12-slim
FROM node:22-alpine AS frontend-build

WORKDIR /build
COPY package.json package-lock.json tsconfig.json vite.config.ts ./
COPY frontend ./frontend
RUN npm ci && npm run build

FROM ${MINEM_RUNTIME_BASE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8790 \
    MINEM_DATA_DIR=/app \
    AUTO_IMPORT_ON_START=0 \
    MINEM_AGENT_INTERNAL_API=0

WORKDIR /app

RUN if ! command -v chromium >/dev/null; then \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        fonts-dejavu-core \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*; fi \
    && rm -rf /app/minem /app/scripts /app/templates /app/public

COPY requirements.txt pyproject.toml README.md LICENSE ./
RUN pip install --no-cache-dir -r requirements.txt

ARG MINEM_VERSION=0.0.0-dev
LABEL org.opencontainers.image.title="MineM" \
      org.opencontainers.image.description="Local-first presentation material platform" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${MINEM_VERSION}"

COPY server.py product-version.json LICENSE NOTICE ./
COPY minem ./minem
COPY scripts ./scripts
COPY templates ./templates
COPY --from=frontend-build /build/public ./public

RUN pip install --no-cache-dir --no-deps . \
    && minem --help >/dev/null

RUN mkdir -p data uploads extracted thumbnails report-exports

EXPOSE 8790

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8790/api/version', timeout=3)"

CMD ["python", "server.py"]
