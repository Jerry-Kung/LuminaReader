#!/usr/bin/env pwsh
# 启动后端开发服务器（uvicorn）
# 首次使用前请在 backend/ 目录执行 uv sync，并复制 .env.example 为 .env。
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$hostAddr = if ($env:HOST) { $env:HOST } else { '127.0.0.1' }
$port = if ($env:PORT) { $env:PORT } else { '18086' }
Set-Location (Join-Path $root 'backend')
uv run uvicorn lumina.main:app --host $hostAddr --port $port --reload
