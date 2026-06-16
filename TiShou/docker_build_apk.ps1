# =============================================================================
# TiShou — buildozer Docker 打包脚本
# =============================================================================
# 用途：在 Windows 上通过 Docker 构建 Android APK
# 前提：已安装 Docker Desktop for Windows
#       并在 Docker Settings → Resources → File Sharing 中添加本项目目录
#
# 使用方法（PowerShell 执行）：
#   cd TiShou
#   .\docker_build_apk.ps1
#
# 首次构建约 30-60 分钟（下载 SDK/NDK）
# 后续增量构建约 5-15 分钟
# APK 输出位置：TiShou/bin/*.apk
# =============================================================================

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  TiShou APK 构建脚本 (Docker)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ---- 检查 Docker 是否安装 ----
try {
    $dockerVersion = docker --version
    Write-Host "✓ Docker 已安装: $dockerVersion" -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "✗ Docker 未安装或不在 PATH 中" -ForegroundColor Red
    Write-Host ""
    Write-Host "请先安装 Docker Desktop for Windows：" -ForegroundColor Yellow
    Write-Host "  https://docs.docker.com/desktop/install/windows-install/" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "安装完成后，在 Docker Settings → Resources → File Sharing 中" -ForegroundColor Yellow
    Write-Host "添加本项目所在目录（例如 C:\Users\admin\PyCharmMiscProject）" -ForegroundColor Yellow
    exit 1
}

# ---- 检查 Docker 是否运行 ----
try {
    $dockerInfo = docker info 2>$null
    if (-not $dockerInfo) {
        throw "Docker daemon not running"
    }
    Write-Host "✓ Docker 守护进程运行中" -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "✗ Docker 守护进程未运行" -ForegroundColor Red
    Write-Host "请启动 Docker Desktop" -ForegroundColor Yellow
    exit 1
}

# ---- 获取当前目录（应为 TiShou 项目根目录） ----
$projectDir = Get-Location
$parentDir = Split-Path $projectDir -Parent

Write-Host "项目目录: $projectDir" -ForegroundColor White
Write-Host ""

# ---- 清理旧容器 ----
Write-Host "[1/4] 清理旧容器..." -ForegroundColor Yellow
docker rm tishou-builder 2>$null | Out-Null
Write-Host "  ✓ 完成" -ForegroundColor Green

# ---- 拉取 buildozer 镜像（如果本地没有） ----
Write-Host "[2/4] 拉取 buildozer Docker 镜像..." -ForegroundColor Yellow
docker pull kivy/buildozer:latest 2>&1 | Out-Null
Write-Host "  ✓ 完成" -ForegroundColor Green

# ---- 执行构建 ----
Write-Host "[3/4] 开始构建 APK（首次构建约 30-60 分钟）..." -ForegroundColor Yellow
Write-Host "      日志将实时输出到下方：" -ForegroundColor Gray
Write-Host ""

$buildStart = Get-Date

docker run --name tishou-builder `
    --interactive --tty --rm `
    --volume "${projectDir}:/home/user/hostcwd" `
    --workdir /home/user/hostcwd `
    --env BUILDOZER_NO_TERMINAL=1 `
    kivy/buildozer:latest `
    buildozer android debug 2>&1

$buildExitCode = $LASTEXITCODE

$buildEnd = Get-Date
$buildDuration = ($buildEnd - $buildStart).TotalMinutes

Write-Host ""
if ($buildExitCode -eq 0) {
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  构建成功！耗时: $([math]::Round($buildDuration, 1)) 分钟" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""

    # 查找生成的 APK
    $apkFiles = Get-ChildItem -Path "$projectDir/bin" -Filter "*.apk" 2>$null
    if ($apkFiles) {
        foreach ($apk in $apkFiles) {
            $sizeInMB = [math]::Round($apk.Length / 1MB, 2)
            Write-Host "  APK 文件: $($apk.FullName)" -ForegroundColor Cyan
            Write-Host "  文件大小: ${sizeInMB} MB" -ForegroundColor Cyan
            Write-Host ""
        }
        Write-Host "安装方法: 将 APK 传到手机，点击安装即可" -ForegroundColor White
        Write-Host "  adb install bin\$($apkFiles[0].Name)" -ForegroundColor Gray
    } else {
        Write-Host "  APK 文件未找到，请检查构建日志" -ForegroundColor Yellow
    }
} else {
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  构建失败（退出码: $buildExitCode）" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "请检查上方日志中的错误信息" -ForegroundColor Yellow
    Write-Host "常见问题：" -ForegroundColor Yellow
    Write-Host "  1. Docker 文件共享权限未设置" -ForegroundColor Yellow
    Write-Host "  2. 网络问题导致 SDK/NDK 下载失败" -ForegroundColor Yellow
    Write-Host "  3. 磁盘空间不足（至少需要 10GB 空闲）" -ForegroundColor Yellow
}

Write-Host ""
Read-Host "按 Enter 键退出"