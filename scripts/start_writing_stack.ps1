param(
    [string]$BindHost = "127.0.0.1",
    [int]$BindPort = 8002,
    [string]$PythonExe = "C:\Users\admin\.conda\envs\agent\python.exe",
    [switch]$SkipBackendRestart,
    [switch]$SkipRunStart,
    [string]$GraphId = "graph.writing.modular_novel.master",
    [string]$TaskId = "task.writing.modular_novel.master",
    [string]$SessionId = "",
    [string]$ProjectId = "project:honghuang-times",
    [string]$ProjectTitle = "洪荒时代",
    [string]$ProjectBriefFile = "output/novel_artifacts/modular_novel/project_brief.md",
    [int]$TargetVolumes = 5,
    [int]$ChaptersPerVolume = 100,
    [int]$TargetWords = 1000000,
    [int]$ChapterTargetWords = 2000,
    [int]$ChaptersPerRound = 10,
    [string]$ArtifactRoot = "",
    [int]$StartupTimeoutSeconds = 45
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendRoot = Join-Path $RepoRoot "backend"
$HealthUrl = "http://$BindHost`:$BindPort/health"
$ApiBaseUrl = "http://$BindHost`:$BindPort/api"
$PidFile = Join-Path $RepoRoot "output/uvicorn-$BindPort.pid"
$OutLog = Join-Path $RepoRoot "output/uvicorn-$BindPort.out.log"
$ErrLog = Join-Path $RepoRoot "output/uvicorn-$BindPort.err.log"

function Test-BackendHealth {
    param([string]$Url)

    try {
        $response = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 3
        return $response.status -eq "ok"
    } catch {
        return $false
    }
}

function Stop-BackendProcesses {
    param([int]$BackendPort, [string]$StoredPidFile)

    if (Test-Path $StoredPidFile) {
        $storedPid = (Get-Content -Path $StoredPidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
        if ($storedPid -match '^\d+$') {
            Stop-Process -Id ([int]$storedPid) -Force -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $StoredPidFile -Force -ErrorAction SilentlyContinue
    }

    $listeners = @(Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        if ($listener.OwningProcess) {
            Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    }
}

function Start-BackendProcess {
    param(
        [string]$WorkingDirectory,
        [string]$PythonPath,
        [string]$StdOutLog,
        [string]$StdErrLog,
        [string]$StoredPidFile,
        [string]$BindHost,
        [int]$BindPort
    )

    if (-not (Test-Path $PythonPath)) {
        throw "Python executable not found: $PythonPath"
    }
    if (-not (Test-Path $WorkingDirectory)) {
        throw "Backend working directory not found: $WorkingDirectory"
    }

    $process = Start-Process `
        -FilePath $PythonPath `
        -ArgumentList "-m", "uvicorn", "app:app", "--host", $BindHost, "--port", "$BindPort" `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $StdOutLog `
        -RedirectStandardError $StdErrLog `
        -WindowStyle Hidden `
        -PassThru

    Set-Content -Path $StoredPidFile -Value $process.Id
    return $process
}

function Wait-BackendHealthy {
    param(
        [string]$Url,
        [int]$TimeoutSeconds,
        [string]$StdErrLog
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-BackendHealth -Url $Url) {
            return
        }
        Start-Sleep -Milliseconds 800
    }

    $tail = ""
    if (Test-Path $StdErrLog) {
        $tail = (Get-Content -Path $StdErrLog -Tail 40 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
    }
    throw "Backend did not become healthy within $TimeoutSeconds seconds.`n$tail"
}

if (-not $SkipBackendRestart) {
    Stop-BackendProcesses -BackendPort $BindPort -StoredPidFile $PidFile
    Start-Sleep -Seconds 1
    $backendProcess = Start-BackendProcess `
        -WorkingDirectory $BackendRoot `
        -PythonPath $PythonExe `
        -StdOutLog $OutLog `
        -StdErrLog $ErrLog `
        -StoredPidFile $PidFile `
        -BindHost $BindHost `
        -BindPort $BindPort
    Wait-BackendHealthy -Url $HealthUrl -TimeoutSeconds $StartupTimeoutSeconds -StdErrLog $ErrLog
} elseif (-not (Test-BackendHealth -Url $HealthUrl)) {
    throw "Backend is not healthy at $HealthUrl. Remove -SkipBackendRestart or restart the service first."
}

$result = [ordered]@{
    backend = [ordered]@{
        health_url = $HealthUrl
        api_base_url = $ApiBaseUrl
        pid_file = $PidFile
        stdout_log = $OutLog
        stderr_log = $ErrLog
        restarted = (-not $SkipBackendRestart)
    }
}

if (-not $SkipRunStart) {
    $runOutput = & (Join-Path $PSScriptRoot "start_writing_project_run.ps1") `
        -BaseUrl $ApiBaseUrl `
        -GraphId $GraphId `
        -TaskId $TaskId `
        -SessionId $SessionId `
        -ProjectId $ProjectId `
        -ProjectTitle $ProjectTitle `
        -ProjectBriefFile $ProjectBriefFile `
        -TargetWords $TargetWords `
        -ChapterTargetWords $ChapterTargetWords `
        -TargetVolumes $TargetVolumes `
        -ChaptersPerVolume $ChaptersPerVolume `
        -ChaptersPerRound $ChaptersPerRound `
        -ArtifactRoot $ArtifactRoot
    $result.run = $runOutput | ConvertFrom-Json
}

$result | ConvertTo-Json -Depth 8
