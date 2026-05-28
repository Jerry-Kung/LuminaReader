#!/usr/bin/env bash
# 运行后端测试（pytest）
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root/backend"
uv run pytest
