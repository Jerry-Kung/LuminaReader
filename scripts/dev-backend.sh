#!/usr/bin/env bash
# 启动后端开发服务器（uvicorn）
# 首次使用前请在 backend/ 目录执行 uv sync，并复制 .env.example 为 .env。
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
host_addr="${HOST:-127.0.0.1}"
port="${PORT:-18086}"
cd "$root/backend"
uv run uvicorn lumina.main:app --host "$host_addr" --port "$port" --reload
