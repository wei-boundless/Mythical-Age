param(
    [ValidateSet("dev", "prod")]
    [string]$Mode = "dev",
    [int]$Port = 3000,
    [switch]$CleanNext
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$FrontendRoot = Join-Path $RepoRoot "frontend"

function Get-ProcessInfoById {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return $null }
    return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
}

function Test-IsProjectFrontendProcess {
    param($Process)
    if ($null -eq $Process) { return $false }
    $commandLine = [string]$Process.CommandLine
    if ($commandLine.Contains($FrontendRoot)) { return $true }
    if ($commandLine.Contains($RepoRoot) -and $commandLine -match "next(.cmd)?\s+(dev|start)") { return $true }
    if ($commandLine -match "next(.cmd)?\s+(dev|start)" -and $commandLine -match "$Port") { return $true }
    return $false
}

function Get-AncestorProjectProcesses {
    param([int]$ProcessId)
    $ancestors = @()
    $current = Get-ProcessInfoById -ProcessId $ProcessId
    while ($current) {
        if (Test-IsProjectFrontendProcess -Process $current) {
            $ancestors += $current
        }
        $parentId = [int]$current.ParentProcessId
        if ($parentId -le 0 -or $parentId -eq $current.ProcessId) { break }
        $current = Get-ProcessInfoById -ProcessId $parentId
    }
    return $ancestors
}

function Stop-ProjectFrontendListener {
    param([int]$ListenerPid)

    $targets = @()
    $targets += Get-AncestorProjectProcesses -ProcessId $ListenerPid
    $targets += Get-ProcessInfoById -ProcessId $ListenerPid
    $targets = @($targets | Where-Object { $null -ne $_ -and (Test-IsProjectFrontendProcess -Process $_) } | Sort-Object ProcessId -Unique)

    foreach ($target in @($targets | Sort-Object ProcessId -Descending)) {
        Stop-Process -Id ([int]$target.ProcessId) -Force -ErrorAction SilentlyContinue
    }
}

function Clear-ProjectOwnedPort {
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        $processId = [int]$listener.OwningProcess
        $process = Get-ProcessInfoById -ProcessId $processId
        if (-not (Test-IsProjectFrontendProcess -Process $process)) {
            $details = if ($process) { $process.CommandLine } else { "unknown process" }
            throw "Frontend port $Port is occupied by a non-project process. Close it manually before starting.`nPID: $processId`n$details"
        }
        Stop-ProjectFrontendListener -ListenerPid $processId
    }

    Start-Sleep -Milliseconds 700
    $remaining = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($remaining.Count -gt 0) {
        $details = $remaining | ForEach-Object {
            $process = Get-ProcessInfoById -ProcessId ([int]$_.OwningProcess)
            [pscustomobject]@{
                pid = [int]$_.OwningProcess
                command_line = if ($process) { $process.CommandLine } else { "" }
            }
        }
        throw "Frontend port $Port is still occupied after cleanup.`n$($details | ConvertTo-Json -Depth 4)"
    }
}

Set-Location -LiteralPath $FrontendRoot
Clear-ProjectOwnedPort
$env:API_PROXY_TARGET = "http://127.0.0.1:8003"
$env:NEXT_PUBLIC_API_BASE = "http://127.0.0.1:8003/api"

$shouldCleanNext = $CleanNext -or $Mode -eq "dev"
if ($shouldCleanNext) {
    $nextCache = Join-Path $FrontendRoot ".next"
    if (Test-Path $nextCache) {
        Remove-Item -LiteralPath $nextCache -Recurse -Force
    }
}

if ($Mode -eq "prod") {
    & npm run start:next
} else {
    & npm run dev:next -- -p $Port
}
