#!/usr/bin/env pwsh
# 一键启动前后端开发服务器（合流输出）
# 首次使用前请按 scripts/README.md 完成 backend (uv sync) 与 frontend (npm install) 准备。
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$backendScript  = Join-Path $root 'scripts\dev-backend.ps1'
$frontendScript = Join-Path $root 'scripts\dev-frontend.ps1'

$pwshCmd = Get-Command pwsh -ErrorAction SilentlyContinue
if (-not $pwshCmd) { $pwshCmd = Get-Command powershell -ErrorAction SilentlyContinue }
if (-not $pwshCmd) { throw 'PowerShell executable not found on PATH (pwsh.exe / powershell.exe).' }
$pwshExe = $pwshCmd.Source

function Start-LabeledProcess {
    param(
        [Parameter(Mandatory)] [string]$Label,
        [Parameter(Mandatory)] [string]$ScriptPath,
        [Parameter(Mandatory)] [ConsoleColor]$Color
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName               = $pwshExe
    $psi.Arguments              = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $psi.UseShellExecute        = $false
    $psi.CreateNoWindow         = $true
    $psi.WorkingDirectory       = $root

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi

    $sink = {
        if ($null -ne $EventArgs.Data) {
            $tag = $Event.MessageData
            Write-Host "[$($tag.Label)] " -NoNewline -ForegroundColor $tag.Color
            Write-Host $EventArgs.Data
        }
    }
    $tag = [pscustomobject]@{ Label = $Label; Color = $Color }
    Register-ObjectEvent -InputObject $proc -EventName OutputDataReceived -Action $sink -MessageData $tag | Out-Null
    Register-ObjectEvent -InputObject $proc -EventName ErrorDataReceived  -Action $sink -MessageData $tag | Out-Null

    [void]$proc.Start()
    $proc.BeginOutputReadLine()
    $proc.BeginErrorReadLine()
    return $proc
}

$backend  = Start-LabeledProcess -Label 'backend ' -ScriptPath $backendScript  -Color Cyan
$frontend = Start-LabeledProcess -Label 'frontend' -ScriptPath $frontendScript -Color Magenta

Write-Host ("Started backend (PID {0}) and frontend (PID {1}). Press Ctrl+C to stop both." -f $backend.Id, $frontend.Id) -ForegroundColor Yellow

try {
    while ($true) {
        if ($backend.HasExited -or $frontend.HasExited) { break }
        Start-Sleep -Milliseconds 250
    }
} finally {
    Write-Host "`nStopping backend and frontend..." -ForegroundColor Yellow
    foreach ($p in @($backend, $frontend)) {
        if ($null -ne $p -and -not $p.HasExited) {
            try {
                & taskkill.exe /PID $p.Id /T /F 2>&1 | Out-Null
            } catch { }
        }
    }
    Get-EventSubscriber | Where-Object {
        $_.SourceObject -eq $backend -or $_.SourceObject -eq $frontend
    } | ForEach-Object { Unregister-Event -SubscriptionId $_.SubscriptionId }
}
