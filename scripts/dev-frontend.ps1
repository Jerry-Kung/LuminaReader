#!/usr/bin/env pwsh
# 启动前端开发服务器（Vite）
# 首次使用前请先在 frontend/ 目录执行 npm install。
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root 'frontend')
npm run dev
