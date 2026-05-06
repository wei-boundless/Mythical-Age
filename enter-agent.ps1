$envRoot = "C:\Users\admin\.conda\envs\agent"

if (-not (Test-Path "$envRoot\python.exe")) {
    Write-Error "Python environment not found: $envRoot"
    exit 1
}

$env:CONDA_PREFIX = $envRoot
$env:CONDA_DEFAULT_ENV = "agent"
$env:PYTHONPATH = Join-Path $PSScriptRoot "backend"
$env:PATH = "$envRoot;$envRoot\Scripts;$envRoot\Library\bin;$envRoot\Library\usr\bin;$envRoot\Library\mingw-w64\bin;$env:PATH"

Write-Host "Activated agent environment"
Write-Host "Python: $envRoot\python.exe"
