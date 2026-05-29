#!/usr/bin/env bash
# 一键启动前后端开发服务器（合流输出）
# 首次使用前请按 scripts/README.md 完成 backend (uv sync) 与 frontend (npm install) 准备。
set -uo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
backend_pid=
frontend_pid=

cleanup() {
    printf "\nStopping backend and frontend...\n" >&2
    trap - INT TERM EXIT
    if [[ -n "${backend_pid:-}" ]] && kill -0 "$backend_pid" 2>/dev/null; then
        kill -TERM "$backend_pid" 2>/dev/null || true
    fi
    if [[ -n "${frontend_pid:-}" ]] && kill -0 "$frontend_pid" 2>/dev/null; then
        kill -TERM "$frontend_pid" 2>/dev/null || true
    fi
    # Best-effort: nuke any descendant that escaped the direct kills.
    kill 0 2>/dev/null || true
}
trap cleanup INT TERM EXIT

# Use process substitution so $! captures the backend/frontend bash PID,
# not the awk PID at the tail of a pipeline.
bash "$root/scripts/dev-backend.sh" > >(awk '{ print "[backend ] " $0; fflush() }') 2>&1 &
backend_pid=$!

bash "$root/scripts/dev-frontend.sh" > >(awk '{ print "[frontend] " $0; fflush() }') 2>&1 &
frontend_pid=$!

wait "$backend_pid" "$frontend_pid"
