#!/usr/bin/env pwsh
# 运行后端测试（pytest）
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root 'backend')
uv run pytest
