param(
    [string]$BindHost = "127.0.0.1",
    [int]$BindPort = 8003,
    [string]$PythonExe = "C:\Users\admin\.conda\envs\agent\python.exe",
    [switch]$SkipBackendRestart,
    [switch]$SkipRunStart,
    [string]$GraphId = "graph.writing.modular_novel.master",
    [string]$TaskId = "task.writing.modular_novel.master",
    [string]$SessionId = "",
    [string]$ProjectId = "project:honghuang-times",
    [string]$ProjectTitle = "洪荒时代",
    [string]$ProjectBriefFile = "output/novel_artifacts/modular_novel/runs/project-honghuang-times-memoryscope-20260523-001/project_brief.md",
    [int]$TargetGroupCount = 5,
    [int]$UnitsPerGroup = 100,
    [int]$TargetMeasureUnits = 1000000,
    [int]$UnitTargetMeasure = 2000,
    [int]$UnitsPerBatch = 10,
    [string]$ArtifactRoot = "",
    [int]$StartupTimeoutSeconds = 45
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendRoot = Join-Path $RepoRoot "backend"
$HealthUrl = "http://$BindHost`:$BindPort/health"
$ApiBaseUrl = "http://$BindHost`:$BindPort/api"
$OutputDir = Join-Path $RepoRoot "output"
$PidFile = Join-Path $OutputDir "uvicorn-fixed-8003.pid"
$OutLog = Join-Path $OutputDir "uvicorn-fixed-8003.out.log"
$ErrLog = Join-Path $OutputDir "uvicorn-fixed-8003.err.log"

function Ensure-OutputDir {
    if (-not (Test-Path $OutputDir)) {
        New-Item -ItemType Directory -Path $OutputDir | Out-Null
    }
}

function Clear-LegacyBackendLogs {
    $legacyFiles = @(
        Get-ChildItem -Path $OutputDir -File -Filter "uvicorn-*.pid" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $OutputDir -File -Filter "uvicorn-*.out.log" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $OutputDir -File -Filter "uvicorn-*.err.log" -ErrorAction SilentlyContinue
    ) | Where-Object {
        $_.FullName -notin @($PidFile, $OutLog, $ErrLog)
    }

    foreach ($file in $legacyFiles) {
        Remove-Item -LiteralPath $file.FullName -Force -ErrorAction SilentlyContinue
    }
}

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
    param([int]$BackendPort, [string]$StoredPidFile, [string]$ExpectedBackendRoot)

    if (Test-Path $StoredPidFile) {
        $storedPid = (Get-Content -Path $StoredPidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
        if ($storedPid -match '^\d+$') {
            $storedProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$storedPid" -ErrorAction SilentlyContinue
            if ($storedProcess -and (Test-IsProjectBackendProcess -ProcessInfo $storedProcess -ExpectedBackendRoot $ExpectedBackendRoot -ExpectedBackendPort $BackendPort)) {
                Stop-Process -Id ([int]$storedPid) -Force -ErrorAction SilentlyContinue
            }
        }
        Remove-Item -LiteralPath $StoredPidFile -Force -ErrorAction SilentlyContinue
    }

    $listeners = @(Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        if ($listener.OwningProcess) {
            $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
            if ($processInfo -and (Test-IsProjectBackendProcess -ProcessInfo $processInfo -ExpectedBackendRoot $ExpectedBackendRoot -ExpectedBackendPort $BackendPort)) {
                Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
            } else {
                throw "Port $BackendPort is occupied by a non-project process: PID $($listener.OwningProcess). Stop it manually or free the fixed backend port."
            }
        }
    }
}

function Test-IsProjectBackendProcess {
    param([object]$ProcessInfo, [string]$ExpectedBackendRoot, [int]$ExpectedBackendPort)

    $commandLine = [string]($ProcessInfo.CommandLine)
    $normalizedCommand = $commandLine.Replace('/', '\').ToLowerInvariant()
    $normalizedRoot = ([string]$ExpectedBackendRoot).Replace('/', '\').ToLowerInvariant()
    $usesProjectRoot = $normalizedCommand.Contains($normalizedRoot) -and $normalizedCommand.Contains("run_uvicorn.py")
    $usesFixedBackendEntry = $normalizedCommand.Contains("run_uvicorn.py") -and $normalizedCommand.Contains("--port $ExpectedBackendPort")
    return $usesProjectRoot -or $usesFixedBackendEntry
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
        -ArgumentList "run_uvicorn.py", "--host", $BindHost, "--port", "$BindPort" `
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
    Ensure-OutputDir
    Clear-LegacyBackendLogs
    Stop-BackendProcesses -BackendPort $BindPort -StoredPidFile $PidFile -ExpectedBackendRoot $BackendRoot
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
        -TargetMeasureUnits $TargetMeasureUnits `
        -UnitTargetMeasure $UnitTargetMeasure `
        -TargetGroupCount $TargetGroupCount `
        -UnitsPerGroup $UnitsPerGroup `
        -UnitsPerBatch $UnitsPerBatch `
        -ArtifactRoot $ArtifactRoot
    $result.run = $runOutput | ConvertFrom-Json
}

$result | ConvertTo-Json -Depth 8
