param(
    [string]$BaseUrl = "http://127.0.0.1:8004/api",
    [string]$SessionId = "",
    [string]$ProjectId = "project:honghuang-times",
    [string]$ProjectTitle = "洪荒时代",
    [string]$ProjectBriefFile = "output/novel_artifacts/simple_novel/project_brief.md",
    [int]$TargetWords = 1000000,
    [int]$ChapterTargetWords = 2000,
    [int]$ChaptersPerRound = 10,
    [int]$IntervalSeconds = 8,
    [switch]$AttachExisting,
    [string]$TaskRunId = "",
    [string]$CoordinationRunId = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if ([string]::IsNullOrWhiteSpace($SessionId)) {
    $SessionId = "writing-simple-novel-honghuang-supervised-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss")
}

$LogRoot = Join-Path $RepoRoot "output/novel_artifacts/simple_novel/supervision/$SessionId"
$SupervisionRoot = Join-Path $RepoRoot "output/novel_artifacts/simple_novel/supervision"
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
New-Item -ItemType Directory -Force -Path $SupervisionRoot | Out-Null
$StopFlag = Join-Path $SupervisionRoot "STOP_SUPERVISION.flag"
if (Test-Path $StopFlag) {
    Remove-Item -LiteralPath $StopFlag -Force
}

$Stdout = Join-Path $LogRoot "supervisor.out.log"
$Stderr = Join-Path $LogRoot "supervisor.err.log"
$PidPath = Join-Path $LogRoot "supervisor.pid"

function Get-ExistingActiveSupervision {
    $MarkerPath = Join-Path $SupervisionRoot "active_codex_supervision.json"
    if (-not (Test-Path $MarkerPath)) {
        return $null
    }
    try {
        $Active = Get-Content -Raw -Path $MarkerPath | ConvertFrom-Json
    } catch {
        return $null
    }
    if ([string]::IsNullOrWhiteSpace($Active.session_id) -or [string]::IsNullOrWhiteSpace($Active.status)) {
        return $null
    }
    if ($Active.status -ne "running") {
        return $null
    }
    $ExistingStatePath = [string]$Active.state_path
    if ([string]::IsNullOrWhiteSpace($ExistingStatePath)) {
        return $null
    }
    $ExistingPidPath = Join-Path (Split-Path -Parent $ExistingStatePath) "supervisor.pid"
    if (Test-Path $ExistingPidPath) {
        try {
            $ExistingPidValue = (Get-Content -Path $ExistingPidPath | Select-Object -First 1).Trim()
            if (-not [string]::IsNullOrWhiteSpace($ExistingPidValue)) {
                $ExistingProcess = Get-Process -Id ([int]$ExistingPidValue) -ErrorAction Stop
                if ($ExistingProcess) {
                    return $Active
                }
            }
        } catch {
        }
    }
    return $null
}

$ExistingActive = Get-ExistingActiveSupervision
if ($ExistingActive) {
    $ExistingStatePath = [string]$ExistingActive.state_path
    $ExistingLogPath = [string]$ExistingActive.log_path
    $ExistingPidPath = Split-Path -Parent $ExistingStatePath
    $ExistingPidFile = Join-Path $ExistingPidPath "supervisor.pid"
    $Result = [pscustomobject]@{
        session_id = [string]$ExistingActive.session_id
        pid = if (Test-Path $ExistingPidFile) { (Get-Content $ExistingPidFile | Select-Object -First 1).Trim() } else { "" }
        stdout = if (Test-Path (Join-Path $ExistingPidPath "supervisor.out.log")) { Join-Path $ExistingPidPath "supervisor.out.log" } else { "" }
        stderr = if (Test-Path (Join-Path $ExistingPidPath "supervisor.err.log")) { Join-Path $ExistingPidPath "supervisor.err.log" } else { "" }
        pid_file = $ExistingPidFile
        state_file = $ExistingStatePath
        event_log = $ExistingLogPath
        codex_supervision_marker = Join-Path $SupervisionRoot "active_codex_supervision.json"
        stop_flag = $StopFlag
        chapters_per_round = $ChaptersPerRound
        already_running = $true
        attached = $true
    }
    Write-Output ($Result | ConvertTo-Json -Depth 4)
    return
}

if ($AttachExisting -and [string]::IsNullOrWhiteSpace($TaskRunId) -and [string]::IsNullOrWhiteSpace($CoordinationRunId)) {
    $StatePath = Join-Path $LogRoot "state.json"
    if (Test-Path $StatePath) {
        try {
            $State = Get-Content -Raw -Path $StatePath | ConvertFrom-Json
            if ([string]::IsNullOrWhiteSpace($TaskRunId) -and $State.task_run_id) {
                $TaskRunId = [string]$State.task_run_id
            }
            if ([string]::IsNullOrWhiteSpace($CoordinationRunId) -and $State.coordination_run_id) {
                $CoordinationRunId = [string]$State.coordination_run_id
            }
        } catch {
        }
    }
}

function Get-RootTaskRunIdFromCoordinationRunId {
    param([string]$CoordinationRunId)

    if ([string]::IsNullOrWhiteSpace($CoordinationRunId)) {
        return ""
    }
    if (-not $CoordinationRunId.StartsWith("coordrun:")) {
        return ""
    }
    $RootTaskRunId = $CoordinationRunId.Substring("coordrun:".Length)
    if ($RootTaskRunId.EndsWith(":primary")) {
        $RootTaskRunId = $RootTaskRunId.Substring(0, $RootTaskRunId.Length - ":primary".Length)
    }
    return $RootTaskRunId
}

if ($AttachExisting) {
    $RootTaskRunId = Get-RootTaskRunIdFromCoordinationRunId -CoordinationRunId $CoordinationRunId
    if (-not [string]::IsNullOrWhiteSpace($RootTaskRunId) -and ($TaskRunId.Contains(":taskinst:") -or [string]::IsNullOrWhiteSpace($TaskRunId))) {
        $TaskRunId = $RootTaskRunId
    }
}

$ArgsList = @(
    "scripts/supervise_writing_campaign.py",
    "--base-url", $BaseUrl,
    "--session-id", $SessionId,
    "--project-id", $ProjectId,
    "--project-title", $ProjectTitle,
    "--project-brief-file", $ProjectBriefFile,
    "--target-words", [string]$TargetWords,
    "--chapter-target-words", [string]$ChapterTargetWords,
    "--chapters-per-round", [string]$ChaptersPerRound,
    "--interval", [string]$IntervalSeconds
)

if (-not $AttachExisting) {
    $ArgsList += "--start"
}
if (-not [string]::IsNullOrWhiteSpace($TaskRunId)) {
    $ArgsList += @("--task-run-id", $TaskRunId)
}
if (-not [string]::IsNullOrWhiteSpace($CoordinationRunId)) {
    $ArgsList += @("--coordination-run-id", $CoordinationRunId)
}

$Process = Start-Process -FilePath "python" `
    -ArgumentList $ArgsList `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $Stdout `
    -RedirectStandardError $Stderr `
    -WindowStyle Hidden `
    -PassThru

[string]$Process.Id | Set-Content -Encoding UTF8 -Path $PidPath

$ActiveSupervision = [pscustomobject]@{
    enabled = $true
    status = "starting"
    reason = "start_writing_supervisor"
    updated_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    session_id = $SessionId
    project_id = $ProjectId
    project_title = $ProjectTitle
    target_words = $TargetWords
    chapters_per_round = $ChaptersPerRound
    state_path = (Join-Path $LogRoot "state.json")
    log_path = (Join-Path $LogRoot "supervision.jsonl")
    stop_flag = $StopFlag
    authority = "scripts.start_writing_supervisor"
}
$ActiveSupervision | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 -Path (Join-Path $SupervisionRoot "active_codex_supervision.json")

$Result = [pscustomobject]@{
    session_id = $SessionId
    pid = $Process.Id
    stdout = $Stdout
    stderr = $Stderr
    pid_file = $PidPath
    state_file = (Join-Path $LogRoot "state.json")
    event_log = (Join-Path $LogRoot "supervision.jsonl")
    codex_supervision_marker = (Join-Path $SupervisionRoot "active_codex_supervision.json")
    stop_flag = $StopFlag
    chapters_per_round = $ChaptersPerRound
}

Write-Output ($Result | ConvertTo-Json -Depth 4)
