# 构建桌面分发包：前端 standalone → 后端单文件 → Electron 安装包。
#
# 全程使用项目约定的固定端口（前端 3000 / 后端 8003）。这两个值在 Next 构建期
# 会被内联进产物，因此必须在构建前就确定，运行时无法再改。

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$FrontendRoot = Join-Path $RepoRoot "frontend"
$DesktopRoot = Join-Path $RepoRoot "desktop"
$DistRoot = Join-Path $RepoRoot "dist"
$PythonExe = Join-Path $env:USERPROFILE ".workbuddy\binaries\python\envs\myage\Scripts\python.exe"
$NodeExe = Join-Path $env:USERPROFILE ".workbuddy\binaries\node\versions\22.22.2-3\node.exe"
$NpmCli = Join-Path $env:USERPROFILE ".workbuddy\binaries\node\versions\22.22.2-3\node_modules\npm\bin\npm-cli.js"

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

if (-not (Test-Path $PythonExe)) { throw "Python 环境缺失：$PythonExe" }
if (-not (Test-Path $NodeExe)) { throw "Node 缺失：$NodeExe" }

Write-Step "构建前端生产产物（Next standalone）"
Push-Location $FrontendRoot
$env:NEXT_PUBLIC_API_BASE = "http://127.0.0.1:8003/api"
$env:API_PROXY_TARGET = "http://127.0.0.1:8003"
& $NodeExe "node_modules/next/dist/bin/next" build
if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }
Pop-Location

Write-Step "整理前端发布目录"
if (Test-Path (Join-Path $DistRoot "frontend")) { Remove-Item -Recurse -Force (Join-Path $DistRoot "frontend") }
New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
Copy-Item -Recurse (Join-Path $FrontendRoot ".next/standalone") (Join-Path $DistRoot "frontend")
Copy-Item -Recurse (Join-Path $FrontendRoot ".next/static") (Join-Path $DistRoot "frontend/.next/static")
if (Test-Path (Join-Path $FrontendRoot "public")) {
    Copy-Item -Recurse (Join-Path $FrontendRoot "public") (Join-Path $DistRoot "frontend/public")
}

Write-Step "构建后端单文件可执行程序"
& $PythonExe -m PyInstaller --noconfirm --clean `
    --distpath (Join-Path $DistRoot "backend") `
    --workpath (Join-Path $DistRoot "build-backend") `
    (Join-Path $DesktopRoot "backend.spec")
if ($LASTEXITCODE -ne 0) { throw "后端构建失败" }

Write-Step "打包 Electron 安装程序"
Push-Location $DesktopRoot
$ElectronBuilder = Join-Path $DesktopRoot "node_modules/.bin/electron-builder.cmd"
if (-not (Test-Path $ElectronBuilder)) {
    Write-Step "安装桌面打包依赖"
    & $NodeExe $NpmCli install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "桌面依赖安装失败" }
}
if (-not (Test-Path $ElectronBuilder)) { throw "Electron Builder 缺失：$ElectronBuilder" }
$env:ELECTRON_BUILDER_BINARIES_MIRROR = "https://npmmirror.com/mirrors/electron-builder-binaries/"
& $ElectronBuilder --win --x64
if ($LASTEXITCODE -ne 0) { throw "Electron 打包失败" }
Pop-Location

Write-Step "完成"
Get-ChildItem (Join-Path $DistRoot "desktop") | Select-Object Name, @{Name = "MB"; Expression = { [math]::Round($_.Length / 1MB, 1) } }
