param(
    [string]$BindHost = "127.0.0.1",
    [int]$BindPort = 8003,
    [string]$PythonExe = "C:\Users\admin\.conda\envs\agent\python.exe",
    [switch]$SkipBackendRestart,
    [switch]$ForceBackendRestart,
    [switch]$SkipRunStart,
    [string]$GraphId = "graph.writing.modular_novel.master",
    [string]$TaskId = "task.writing.modular_novel.master",
    [string]$SessionId = "",
    [string]$WorkspaceView = "task_environment",
    [string]$TaskEnvironmentId = "env.creation.writing",
    [string]$ProjectId = "project.creation.writing.honghuang",
    [string]$ProjectTitle = "洪荒时代",
    [string]$ProjectBriefFile = "output/novel_artifacts/modular_novel/runs/project-honghuang-times-memoryscope-20260523-001/project_brief.md",
    [int]$TargetGroupCount = 2,
    [int]$UnitsPerGroup = 100,
    [int]$TargetMeasureUnits = 700000,
    [int]$UnitTargetMeasure = 3500,
    [int]$UnitsPerBatch = 10,
    [string]$ArtifactRoot = "",
    [int]$StartupTimeoutSeconds = 45
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$HealthUrl = "http://$BindHost`:$BindPort/health"
$ApiBaseUrl = "http://$BindHost`:$BindPort/api"
$ProjectStackScript = Join-Path $PSScriptRoot "project_stack.ps1"

function Invoke-ProjectStack {
    param([ValidateSet("start", "stop", "check")][string]$Action)
    if (-not (Test-Path $ProjectStackScript)) {
        throw "Project stack script not found: $ProjectStackScript"
    }
    $json = & $ProjectStackScript `
        -Action $Action `
        -HostName $BindHost `
        -BackendPort $BindPort `
        -PythonExe $PythonExe `
        -StartupTimeoutSeconds $StartupTimeoutSeconds
    return $json | ConvertFrom-Json
}

if ($SkipBackendRestart -and $ForceBackendRestart) {
    throw "Use either -SkipBackendRestart or -ForceBackendRestart, not both."
}

$stackAction = "check"
if ($ForceBackendRestart) {
    Invoke-ProjectStack -Action "stop" | Out-Null
    $stackAction = "start"
} elseif (-not $SkipBackendRestart) {
    $stackAction = "start"
}

$stack = Invoke-ProjectStack -Action $stackAction
$stackStatus = if ($null -ne $stack.status) { $stack.status } else { $stack }
$backendStatus = $stackStatus.health.backend
if (-not $backendStatus.ok) {
    throw "Backend is not healthy at $HealthUrl after project_stack action '$stackAction'. $($backendStatus.error)"
}

$result = [ordered]@{
    backend = [ordered]@{
        health_url = $HealthUrl
        api_base_url = $ApiBaseUrl
        pid_file = $stackStatus.pid_files.backend
        stdout_log = $stackStatus.logs.backend_stdout
        stderr_log = $stackStatus.logs.backend_stderr
        authority = "scripts.project_stack"
        stack_action = $stackAction
    }
}

if (-not $SkipRunStart) {
    $runOutput = & (Join-Path $PSScriptRoot "start_writing_project_run.ps1") `
        -BaseUrl $ApiBaseUrl `
        -GraphId $GraphId `
        -TaskId $TaskId `
        -SessionId $SessionId `
        -WorkspaceView $WorkspaceView `
        -TaskEnvironmentId $TaskEnvironmentId `
        -ProjectId $ProjectId `
        -ProjectTitle $ProjectTitle `
        -ProjectBriefFile $ProjectBriefFile `
        -TargetMeasureUnits $TargetMeasureUnits `
        -UnitTargetMeasure $UnitTargetMeasure `
        -TargetGroupCount $TargetGroupCount `
        -UnitsPerGroup $UnitsPerGroup `
        -UnitsPerBatch $UnitsPerBatch `
        -ArtifactRoot $ArtifactRoot
    $result.run = $runOutput | ConvertFrom-Json
}

$result | ConvertTo-Json -Depth 8
