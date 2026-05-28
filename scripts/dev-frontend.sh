#!/usr/bin/env bash
# 启动前端开发服务器（Vite）
# 首次使用前请先在 frontend/ 目录执行 npm install。
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root/frontend"
npm run dev
