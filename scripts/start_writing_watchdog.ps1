param(
    [string]$BindHost = "127.0.0.1",
    [int]$BindPort = 8004,
    [string]$PythonExe = "C:\Users\admin\.conda\envs\agent\python.exe",
    [string]$ProjectId = "project:honghuang-times",
    [string]$ProjectTitle = "洪荒时代",
    [string]$ProjectBriefFile = "output/novel_artifacts/simple_novel/project_brief.md",
    [int]$TargetWords = 1000000,
    [int]$ChapterTargetWords = 2000,
    [int]$ChaptersPerRound = 10,
    [int]$IntervalSeconds = 120,
    [int]$StaleSeconds = 300,
    [switch]$StartNewIfMissing
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SupervisionRoot = Join-Path $RepoRoot "output/novel_artifacts/simple_novel/supervision"
New-Item -ItemType Directory -Force -Path $SupervisionRoot | Out-Null

$PidPath = Join-Path $SupervisionRoot "watchdog.pid"
$Stdout = Join-Path $SupervisionRoot "watchdog.out.log"
$Stderr = Join-Path $SupervisionRoot "watchdog.err.log"
$BaseUrl = "http://$BindHost`:$BindPort/api"
$HealthUrl = "http://$BindHost`:$BindPort/health"

function Get-RunningWatchdog {
    if (-not (Test-Path $PidPath)) {
        return $null
    }
    $pidValue = (Get-Content -Path $PidPath -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ([string]::IsNullOrWhiteSpace($pidValue) -or $pidValue -notmatch '^\d+$') {
        return $null
    }
    try {
        return Get-Process -Id ([int]$pidValue) -ErrorAction Stop
    } catch {
        return $null
    }
}

$Existing = Get-RunningWatchdog
if ($Existing) {
    [pscustomobject]@{
        already_running = $true
        pid = $Existing.Id
        pid_file = $PidPath
        stdout = $Stdout
        stderr = $Stderr
        interval_seconds = $IntervalSeconds
        stale_seconds = $StaleSeconds
        authority = "scripts.start_writing_watchdog"
    } | ConvertTo-Json -Depth 4
    return
}

if (-not (Test-Path $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}

$ArgsList = @(
    "scripts/watch_writing_supervision.py",
    "--bind-host", $BindHost,
    "--bind-port", [string]$BindPort,
    "--base-url", $BaseUrl,
    "--health-url", $HealthUrl,
    "--python-exe", $PythonExe,
    "--project-id", $ProjectId,
    "--project-title", $ProjectTitle,
    "--project-brief-file", $ProjectBriefFile,
    "--target-words", [string]$TargetWords,
    "--chapter-target-words", [string]$ChapterTargetWords,
    "--chapters-per-round", [string]$ChaptersPerRound,
    "--interval", [string]$IntervalSeconds,
    "--stale-seconds", [string]$StaleSeconds
)

if ($StartNewIfMissing) {
    $ArgsList += "--start-new-if-missing"
}

$Process = Start-Process `
    -FilePath $PythonExe `
    -ArgumentList $ArgsList `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $Stdout `
    -RedirectStandardError $Stderr `
    -WindowStyle Hidden `
    -PassThru

[string]$Process.Id | Set-Content -Encoding UTF8 -Path $PidPath

[pscustomobject]@{
    already_running = $false
    pid = $Process.Id
    pid_file = $PidPath
    stdout = $Stdout
    stderr = $Stderr
    interval_seconds = $IntervalSeconds
    stale_seconds = $StaleSeconds
    start_new_if_missing = [bool]$StartNewIfMissing
    authority = "scripts.start_writing_watchdog"
} | ConvertTo-Json -Depth 4
