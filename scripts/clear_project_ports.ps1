param(
    [int[]]$Ports = @(3000, 8003),
    [switch]$IncludePidFiles,
    [switch]$ForceAnyOwner,
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $RepoRoot = (Resolve-Path $RepoRoot).Path
}

$OutputDir = Join-Path $RepoRoot "output"
$RuntimeDir = Join-Path $OutputDir "runtime"

function Remove-LegacyLogFiles {
    if (-not (Test-Path $OutputDir)) {
        return
    }

    $legacyFiles = @(
        Get-ChildItem -Path $OutputDir -File -Filter "uvicorn-*.pid" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $OutputDir -File -Filter "uvicorn-*.out.log" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $OutputDir -File -Filter "uvicorn-*.err.log" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $OutputDir -File -Filter "verify-*.out.log" -ErrorAction SilentlyContinue
        Get-ChildItem -Path $OutputDir -File -Filter "verify-*.err.log" -ErrorAction SilentlyContinue
    )

    foreach ($file in $legacyFiles) {
        Remove-Item -LiteralPath $file.FullName -Force -ErrorAction SilentlyContinue
    }
}

if (-not $ForceAnyOwner) {
    $projectStack = Join-Path $PSScriptRoot "project_stack.ps1"
    if (Test-Path $projectStack) {
        $child = Start-Process `
            -FilePath "powershell.exe" `
            -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $projectStack, "-Action", "stop" `
            -WorkingDirectory $RepoRoot `
            -WindowStyle Hidden `
            -Wait `
            -PassThru
        if ($child.ExitCode -ne 0) {
            exit $child.ExitCode
        }
    }
}

function Stop-ProcessByPort {
    param([int]$Port)

    $stopped = @()
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    $established = @(Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue)
    $connections = @($listeners + $established | Sort-Object OwningProcess -Unique)

    foreach ($connection in $connections) {
        $pidValue = if ($null -ne $connection -and $null -ne $connection.OwningProcess) { $connection.OwningProcess } else { 0 }
        $pid = [int]$pidValue
        if ($pid -le 0) { continue }

        $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($null -eq $process) { continue }

        try {
            Stop-Process -Id $pid -Force -ErrorAction Stop
            $stopped += [pscustomobject]@{
                port = $Port
                pid = $pid
                process_name = $process.ProcessName
                via = "tcp_port"
            }
        } catch {
        }
    }

    return $stopped
}

function Stop-ProcessByPidFile {
    param(
        [string]$PidFile,
        [int]$PortHint
    )

    $stopped = @()
    if (-not (Test-Path $PidFile)) {
        return $stopped
    }

    $storedPid = (Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ($storedPid -match '^\d+$') {
        $pid = [int]$storedPid
        $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            try {
                Stop-Process -Id $pid -Force -ErrorAction Stop
                $stopped += [pscustomobject]@{
                    port = $PortHint
                    pid = $pid
                    process_name = $process.ProcessName
                    via = "pid_file"
                }
            } catch {
            }
        }
    }

    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    return $stopped
}

$results = @()

foreach ($port in $Ports) {
    $results += Stop-ProcessByPort -Port $port
}

if ($IncludePidFiles -and (Test-Path $OutputDir)) {
    foreach ($port in $Ports) {
        $pidFiles = @(
            Join-Path $OutputDir ("uvicorn-{0}.pid" -f $port),
            Join-Path $OutputDir ("uvicorn-fixed-{0}.pid" -f $port),
            Join-Path $RuntimeDir ("backend-fixed-{0}.pid" -f $port),
            Join-Path $RuntimeDir ("frontend-fixed-{0}.pid" -f $port)
        )
        foreach ($pidFile in $pidFiles) {
            $results += Stop-ProcessByPidFile -PidFile $pidFile -PortHint $port
        }
    }
}

Remove-LegacyLogFiles

Start-Sleep -Milliseconds 500

$status = foreach ($port in $Ports) {
    $remaining = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    [pscustomobject]@{
        port = $port
        cleared = ($remaining.Count -eq 0)
        remaining_pids = @($remaining | ForEach-Object { [int]$_.OwningProcess } | Sort-Object -Unique)
    }
}

[pscustomobject]@{
    authority = "scripts.clear_project_ports"
    repo_root = $RepoRoot
    requested_ports = $Ports
    stopped = $results
    status = $status
} | ConvertTo-Json -Depth 6
