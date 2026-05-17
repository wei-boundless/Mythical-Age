param(
    [Parameter(Mandatory = $true)]
    [string]$SessionId
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$LogRoot = Join-Path $RepoRoot "output/novel_artifacts/simple_novel/supervision/$SessionId"
$SupervisionRoot = Join-Path $RepoRoot "output/novel_artifacts/simple_novel/supervision"
$PidPath = Join-Path $LogRoot "supervisor.pid"
$StopFlag = Join-Path $SupervisionRoot "STOP_SUPERVISION.flag"
New-Item -ItemType Directory -Force -Path $SupervisionRoot | Out-Null
"manual stop requested for $SessionId at $(Get-Date -Format o)" | Set-Content -Encoding UTF8 -Path $StopFlag

if (-not (Test-Path $PidPath)) {
    [pscustomobject]@{
        session_id = $SessionId
        stopped = $false
        reason = "pid_file_missing"
        pid_file = $PidPath
        stop_flag = $StopFlag
    } | ConvertTo-Json -Depth 4
    exit 0
}

$PidValue = (Get-Content $PidPath | Select-Object -First 1).Trim()
if ([string]::IsNullOrWhiteSpace($PidValue)) {
    [pscustomobject]@{
        session_id = $SessionId
        stopped = $false
        reason = "pid_file_empty"
        pid_file = $PidPath
        stop_flag = $StopFlag
    } | ConvertTo-Json -Depth 4
    exit 0
}

$Stopped = $false
try {
    $Process = Get-Process -Id ([int]$PidValue) -ErrorAction Stop
    Stop-Process -Id $Process.Id -Force
    $Stopped = $true
} catch {
    $Stopped = $false
}

[pscustomobject]@{
    session_id = $SessionId
    pid = $PidValue
    stopped = $Stopped
    pid_file = $PidPath
    stop_flag = $StopFlag
} | ConvertTo-Json -Depth 4
