# 组装免安装的 Windows 桌面程序目录。
#
# 结构：
#   MythicalAge/
#     MythicalAge.exe        Electron 外壳（已改名的主程序）
#     其余 Electron 运行时
#     resources/app/         运行器（main.cjs / preload.cjs）
#     resources/backend/     打包后的后端单文件
#     resources/frontend/    Next standalone 服务
#     resources/runtime/     随包的 node.exe
#
# Electron 运行时直接复用本机已安装的 electron 发行包（版本与 desktop/package.json 一致），
# 避免每次构建都从网络重新下载整包。

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DesktopRoot = Join-Path $RepoRoot "desktop"
$DistRoot = Join-Path $RepoRoot "dist"
$OutRoot = Join-Path $DistRoot "MythicalAge"
$ElectronDist = Join-Path $RepoRoot "frontend/node_modules/electron/dist"
$NodeExe = Join-Path $env:USERPROFILE ".workbuddy\binaries\node\versions\22.22.2-3\node.exe"

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

foreach ($required in @(
    (Join-Path $ElectronDist "electron.exe"),
    (Join-Path $DistRoot "backend/mythical-backend.exe"),
    (Join-Path $DistRoot "frontend/server.js"),
    $NodeExe
)) {
    if (-not (Test-Path $required)) { throw "缺少构建产物：$required" }
}

Write-Step "复制 Electron 运行时"
if (Test-Path $OutRoot) { Remove-Item -Recurse -Force $OutRoot }
New-Item -ItemType Directory -Force -Path $OutRoot | Out-Null
Copy-Item -Recurse (Join-Path $ElectronDist "*") $OutRoot

Write-Step "放置主程序"
Move-Item (Join-Path $OutRoot "electron.exe") (Join-Path $OutRoot "MythicalAge.exe") -Force

Write-Step "放置运行器"
$appDir = Join-Path $OutRoot "resources/app"
New-Item -ItemType Directory -Force -Path $appDir | Out-Null
Copy-Item (Join-Path $DesktopRoot "main.cjs") $appDir
Copy-Item (Join-Path $DesktopRoot "preload.cjs") $appDir
Copy-Item (Join-Path $DesktopRoot "app/package.json") $appDir

# Electron 内置的默认应用只在没有 app 目录时生效，留着会让启动错误地落到欢迎页。
Remove-Item (Join-Path $OutRoot "resources/default_app.asar") -Force -ErrorAction SilentlyContinue

Write-Step "放置后端与前端"
New-Item -ItemType Directory -Force -Path (Join-Path $OutRoot "resources/backend") | Out-Null
Copy-Item (Join-Path $DistRoot "backend/mythical-backend.exe") (Join-Path $OutRoot "resources/backend")
New-Item -ItemType Directory -Force -Path (Join-Path $OutRoot "resources/runtime") | Out-Null
Copy-Item $NodeExe (Join-Path $OutRoot "resources/runtime/node.exe")
Copy-Item -Recurse (Join-Path $DistRoot "frontend") (Join-Path $OutRoot "resources/frontend")

Write-Step "完成"
$size = (Get-ChildItem -Recurse -File $OutRoot | Measure-Object -Property Length -Sum).Sum
Write-Host ("输出目录：{0}" -f $OutRoot) -ForegroundColor Green
Write-Host ("总体积：{0} MB" -f [math]::Round($size / 1MB, 1)) -ForegroundColor Green
