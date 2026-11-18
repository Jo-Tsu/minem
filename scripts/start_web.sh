#!/bin/bash
# Open the existing Docker web deployment from Finder or Terminal.
set -euo pipefail

project=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$project"
export PATH="${PATH:-/usr/bin:/bin}:$HOME/.docker/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/Applications/Docker.app/Contents/Resources/bin"
url=http://127.0.0.1:8790/
log="$project/runtime/start-web.log"

if [[ $# -gt 1 || ( $# -eq 1 && $1 != --no-browser ) ]]; then
    printf '用法: %s [--no-browser]\n' "$0" >&2
    exit 2
fi

fail() {
    printf '%s\n启动日志：%s\n' "$1" "$log" >&2
    exit 1
}

web_ready() {
    curl --noproxy '*' -fsS --max-time 1 "${url}api/version" 2>/dev/null |
        grep -Eq '"product"[[:space:]]*:[[:space:]]*"MineM"'
}

docker_ready() {
    docker info --format '{{.ServerVersion}}' >/dev/null 2>&1
}

if ! web_ready; then
    mkdir -p "$project/runtime"
    date '+%Y-%m-%d %H:%M:%S MineM' >"$log"
    command -v docker >/dev/null || fail "找不到 Docker。请先打开 Docker Desktop。"
    if ! docker_ready; then
        printf '正在启动 Docker Desktop\n' >>"$log"
        open -g -a Docker >>"$log" 2>&1 || fail "无法打开 Docker Desktop。"
        for ((attempt=0; attempt<120; attempt++)); do
            docker_ready && break
            sleep 1
        done
        docker_ready || fail "Docker Desktop 尚未就绪，请打开 Docker 查看状态后再试。"
    fi
    docker compose up -d --no-build --pull never minem-platform >>"$log" 2>&1 ||
        fail "MineM 容器启动失败。"
    for ((attempt=0; attempt<45; attempt++)); do
        web_ready && break
        sleep 1
    done
    web_ready || fail "MineM 网页服务尚未就绪。"

fi

if [[ $# -eq 0 ]]; then
    open "$url" || { printf 'MineM 已就绪，无法打开默认浏览器。可访问 %s\n' "$url" >&2; exit 1; }
fi

# Recover the Drive worker independently when the web container survived a restart.
if command -v lark-cli >/dev/null; then
    (
        mkdir -p "$project/runtime"
        if [[ -x "$project/.venv/bin/python3" ]]; then
            export PATH="$project/.venv/bin:$PATH"
        fi
        "$project/scripts/start_drive_import_worker.sh" >>"$log" 2>&1
    ) </dev/null >/dev/null 2>&1 &
fi
