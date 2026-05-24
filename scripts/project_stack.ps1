param(
    [ValidateSet("start", "stop", "check")]
    [string]$Action = "check",
    [ValidateSet("dev", "prod")]
    [string]$FrontendMode = "dev",
    [string]$HostName = "127.0.0.1",
    [int]$FrontendPort = 3000,
    [int]$BackendPort = 8003,
    [string]$PythonExe = "C:\Users\admin\.conda\envs\agent\python.exe",
    [int]$StartupTimeoutSeconds = 45
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendRoot = Join-Path $RepoRoot "backend"
$FrontendRoot = Join-Path $RepoRoot "frontend"
$RuntimeDir = Join-Path $RepoRoot "output\runtime"
$BackendPidFile = Join-Path $RuntimeDir "backend-fixed-8003.pid"
$FrontendPidFile = Join-Path $RuntimeDir "frontend-fixed-3000.pid"
$BackendOutLog = Join-Path $RuntimeDir "backend-fixed-8003.out.log"
$BackendErrLog = Join-Path $RuntimeDir "backend-fixed-8003.err.log"
$FrontendOutLog = Join-Path $RuntimeDir "frontend-fixed-3000.out.log"
$FrontendErrLog = Join-Path $RuntimeDir "frontend-fixed-3000.err.log"
$BackendHealthUrl = "http://$HostName`:$BackendPort/health"
$CapabilityCatalogUrl = "http://$HostName`:$BackendPort/api/capability-system/catalog"
$FrontendUrl = "http://$HostName`:$FrontendPort/"

function Ensure-RuntimeDir {
    if (-not (Test-Path $RuntimeDir)) {
        New-Item -ItemType Directory -Path $RuntimeDir | Out-Null
    }
}

function Clear-LegacyRuntimeLogs {
    $legacyFiles = @(
        Get-ChildItem -Path $RuntimeDir -File -Filter "backend-*.pid" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $RuntimeDir -File -Filter "backend-*.out.log" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $RuntimeDir -File -Filter "backend-*.err.log" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $RuntimeDir -File -Filter "frontend-*.pid" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $RuntimeDir -File -Filter "frontend-*.out.log" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $RuntimeDir -File -Filter "frontend-*.err.log" -ErrorAction SilentlyContinue
    ) | Where-Object {
        $_.FullName -notin @(
            $BackendPidFile,
            $FrontendPidFile,
            $BackendOutLog,
            $BackendErrLog,
            $FrontendOutLog,
            $FrontendErrLog
        )
    }

    foreach ($file in $legacyFiles) {
        Remove-Item -LiteralPath $file.FullName -Force -ErrorAction SilentlyContinue
    }
}

function Clear-LegacyRootLogs {
    $outputDir = Join-Path $RepoRoot "output"
    if (-not (Test-Path $outputDir)) {
        return
    }

    $legacyFiles = @(
        Get-ChildItem -Path $outputDir -File -Filter "uvicorn-*.pid" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $outputDir -File -Filter "uvicorn-*.out.log" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $outputDir -File -Filter "uvicorn-*.err.log" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $outputDir -File -Filter "verify-*.out.log" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $outputDir -File -Filter "verify-*.err.log" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $outputDir -File -Filter "next-*.out.log" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $outputDir -File -Filter "next-*.err.log" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $outputDir -File -Filter "frontend-fixed-*.out.log" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $outputDir -File -Filter "frontend-fixed-*.err.log" -ErrorAction SilentlyContinue
    )

    foreach ($file in $legacyFiles) {
        Remove-Item -LiteralPath $file.FullName -Force -ErrorAction SilentlyContinue
    }
}

function Get-ProcessInfoById {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return $null }
    return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
}

function Get-ListeningProcesses {
    param([int]$Port)
    $connections = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    foreach ($connection in $connections) {
        $processId = [int]$connection.OwningProcess
        $process = Get-ProcessInfoById -ProcessId $processId
        [pscustomobject]@{
            port = $Port
            pid = $processId
            name = if ($process) { $process.Name } else { "" }
            command_line = if ($process) { $process.CommandLine } else { "" }
            project_owned = Test-IsProjectProcess -Process $process
        }
    }
}

function Test-IsProjectProcess {
    param($Process)
    if ($null -eq $Process) { return $false }
    $commandLine = [string]$Process.CommandLine
    if ($commandLine.Contains($RepoRoot)) { return $true }
    if ($commandLine -match "npm\s+run\s+(dev|start)") { return $true }
    if ($commandLine -match "next(.cmd)?\s+(dev|start)" -and $commandLine -match "$FrontendPort") { return $true }
    if ($commandLine -match "uvicorn" -and $commandLine -match "app:app" -and $commandLine -match "$BackendPort") { return $true }
    return $false
}

function Read-PidFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return 0 }
    $value = (Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ($value -match '^\d+$') { return [int]$value }
    return 0
}

function Test-HttpOk {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        return [pscustomobject]@{
            ok = ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400)
            status_code = [int]$response.StatusCode
            error = ""
        }
    } catch {
        $statusCode = 0
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }
        return [pscustomobject]@{
            ok = $false
            status_code = $statusCode
            error = $_.Exception.Message
        }
    }
}

function Stop-ManagedProcess {
    param(
        [string]$PidFile,
        [int]$Port,
        [string]$Role
    )

    $stopped = @()
    $managedProcessId = Read-PidFile -Path $PidFile
    if ($managedProcessId -gt 0) {
        $process = Get-ProcessInfoById -ProcessId $managedProcessId
        if ($process -and (Test-IsProjectProcess -Process $process)) {
            Stop-Process -Id $managedProcessId -Force -ErrorAction SilentlyContinue
            $stopped += [pscustomobject]@{ role = $Role; pid = $managedProcessId; via = "pid_file" }
        }
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    }

    foreach ($listener in @(Get-ListeningProcesses -Port $Port)) {
        if ($listener.project_owned) {
            Stop-Process -Id $listener.pid -Force -ErrorAction SilentlyContinue
            $stopped += [pscustomobject]@{ role = $Role; pid = $listener.pid; via = "port_project_match" }
        }
    }
    return $stopped
}

function Assert-PortAvailableOrOwned {
    param(
        [int]$Port,
        [string]$Role
    )
    $listeners = @(Get-ListeningProcesses -Port $Port)
    $foreign = @($listeners | Where-Object { -not $_.project_owned })
    if ($foreign.Count -gt 0) {
        $details = $foreign | ConvertTo-Json -Depth 4
        throw "$Role port $Port is occupied by a non-project process. Run check and close it manually if needed.`n$details"
    }
}

function Start-Backend {
    Ensure-RuntimeDir
    Clear-LegacyRuntimeLogs
    if (-not (Test-Path $PythonExe)) { throw "Python executable not found: $PythonExe" }
    Assert-PortAvailableOrOwned -Port $BackendPort -Role "backend"
    $health = Test-HttpOk -Url $BackendHealthUrl
    if ($health.ok) { return "already_healthy" }

    Stop-ManagedProcess -PidFile $BackendPidFile -Port $BackendPort -Role "backend" | Out-Null
    $env:PYTHONPATH = $BackendRoot
    $process = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList "-m", "uvicorn", "app:app", "--host", $HostName, "--port", "$BackendPort" `
        -WorkingDirectory $BackendRoot `
        -RedirectStandardOutput $BackendOutLog `
        -RedirectStandardError $BackendErrLog `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -LiteralPath $BackendPidFile -Value $process.Id
    return "started"
}

function Start-Frontend {
    Ensure-RuntimeDir
    Clear-LegacyRuntimeLogs
    Assert-PortAvailableOrOwned -Port $FrontendPort -Role "frontend"
    Stop-ManagedProcess -PidFile $FrontendPidFile -Port $FrontendPort -Role "frontend" | Out-Null
    $env:API_PROXY_TARGET = "http://127.0.0.1:$BackendPort"
    $env:NEXT_PUBLIC_API_BASE = "http://127.0.0.1:$BackendPort/api"
    $frontendScript = Join-Path $RepoRoot "scripts\frontend_dev.ps1"
    $frontendCommand = if ($FrontendMode -eq "prod") {
        "powershell -NoProfile -ExecutionPolicy Bypass -File `"$frontendScript`" -Mode prod -Port $FrontendPort"
    } else {
        "powershell -NoProfile -ExecutionPolicy Bypass -File `"$frontendScript`" -Mode dev -Port $FrontendPort"
    }
    $process = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList "/d", "/s", "/c", $frontendCommand `
        -WorkingDirectory $FrontendRoot `
        -RedirectStandardOutput $FrontendOutLog `
        -RedirectStandardError $FrontendErrLog `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -LiteralPath $FrontendPidFile -Value $process.Id
    return "started"
}

function Wait-ForUrl {
    param(
        [string]$Url,
        [int]$TimeoutSeconds,
        [string]$LogPath
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $result = Test-HttpOk -Url $Url
        if ($result.ok) { return $result }
        Start-Sleep -Milliseconds 900
    } while ((Get-Date) -lt $deadline)

    $tail = ""
    if (Test-Path $LogPath) {
        $tail = (Get-Content -LiteralPath $LogPath -Tail 30 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
    }
    throw "Timed out waiting for $Url.`n$tail"
}

function Get-StackStatus {
    $backendHealth = Test-HttpOk -Url $BackendHealthUrl
    $capabilityCatalog = Test-HttpOk -Url $CapabilityCatalogUrl
    $frontendHome = Test-HttpOk -Url $FrontendUrl
    return [pscustomobject]@{
        authority = "scripts.project_stack"
        repo_root = $RepoRoot
        ports = [pscustomobject]@{
            frontend = $FrontendPort
            backend = $BackendPort
        }
        urls = [pscustomobject]@{
            frontend = $FrontendUrl
            backend_health = $BackendHealthUrl
            capability_catalog = $CapabilityCatalogUrl
        }
        pid_files = [pscustomobject]@{
            frontend = $FrontendPidFile
            backend = $BackendPidFile
        }
        logs = [pscustomobject]@{
            frontend_stdout = $FrontendOutLog
            frontend_stderr = $FrontendErrLog
            backend_stdout = $BackendOutLog
            backend_stderr = $BackendErrLog
        }
        listeners = @(
            Get-ListeningProcesses -Port $FrontendPort
            Get-ListeningProcesses -Port $BackendPort
        )
        health = [pscustomobject]@{
            backend = $backendHealth
            capability_catalog = $capabilityCatalog
            frontend = $frontendHome
        }
    }
}

if ($Action -eq "stop") {
    Ensure-RuntimeDir
    Clear-LegacyRuntimeLogs
    $stopped = @()
    $stopped += Stop-ManagedProcess -PidFile $FrontendPidFile -Port $FrontendPort -Role "frontend"
    $stopped += Stop-ManagedProcess -PidFile $BackendPidFile -Port $BackendPort -Role "backend"
    Start-Sleep -Milliseconds 500
    Clear-LegacyRootLogs
    Clear-LegacyRuntimeLogs
    [pscustomobject]@{
        authority = "scripts.project_stack"
        action = "stop"
        stopped = $stopped
        status = Get-StackStatus
    } | ConvertTo-Json -Depth 8
    return
}

if ($Action -eq "start") {
    $backendAction = Start-Backend
    Wait-ForUrl -Url $BackendHealthUrl -TimeoutSeconds $StartupTimeoutSeconds -LogPath $BackendErrLog | Out-Null
    $frontendAction = Start-Frontend
    Wait-ForUrl -Url $FrontendUrl -TimeoutSeconds $StartupTimeoutSeconds -LogPath $FrontendErrLog | Out-Null
    [pscustomobject]@{
        authority = "scripts.project_stack"
        action = "start"
        backend = $backendAction
        frontend = $frontendAction
        status = Get-StackStatus
    } | ConvertTo-Json -Depth 8
    return
}

Get-StackStatus | ConvertTo-Json -Depth 8
