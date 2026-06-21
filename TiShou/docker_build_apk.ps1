# =============================================================================
# TiShou — Docker 本地 APK 构建脚本
# 版本：v2.3.4
# 生成日期：2026-06-21
# 更新内容：accessibility_service_config.xml改用硬编码描述替代@string引用（p4a不支持values资源编译）
#          buildozer.spec的android.add_resources仅保留res/xml:xml
# =============================================================================
# 用途：在 Windows 开发机上通过 Docker 容器构建 Android APK
# 前提：已安装 Docker Desktop for Windows
#       并在 Docker Settings → Resources → File Sharing 中添加本项目目录
#
# 使用方法：
#   cd TiShou
#   .\docker_build_apk.ps1
#
# 构建时长：
#   首次构建：约 30-60 分钟（下载 SDK/NDK/依赖）
#   后续增量构建：约 5-15 分钟
#
# APK 输出位置：TiShou/bin/*.apk
#
# ═══════════════════════════════════════════════════════════════
# 安卓专属依赖说明（Windows 上无法安装，由 Docker 容器编译注入）：
#   pyjnius — Android Java 桥接（悬浮窗/通知/AudioTrack/权限检测）
#   jnius   — 访问 Android 系统 API
#   p4a      — python-for-android 运行时（提供 android 模块）
# 这些依赖在 buildozer.spec 的 requirements 中声明，
# 由 p4a 在容器内编译 APK 时从源码构建，不依赖 Windows 宿主环境。
# ═══════════════════════════════════════════════════════════════
# TiShou 安卓权限清单（共 17 项，Windows 无法处理，由 Docker p4a 编译注入）
# ═══════════════════════════════════════════════════════════════
# 核心功能: BIND_ACCESSIBILITY_SERVICE, SYSTEM_ALERT_WINDOW, FOREGROUND_SERVICE,
#           FOREGROUND_SERVICE_SPECIAL_USE, POST_NOTIFICATIONS, REQUEST_IGNORE_BATTERY_OPTIMIZATIONS
# 存储:    READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE, MANAGE_EXTERNAL_STORAGE
# 定位:    ACCESS_FINE_LOCATION, ACCESS_COARSE_LOCATION
# 网络:    INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE
# 系统:    RECEIVE_BOOT_COMPLETED, WAKE_LOCK, VIBRATE
# ═══════════════════════════════════════════════════════════════
# 无障碍服务注册链（3 文件联动，缺一不可，Android 15/16 严格校验）:
#   AndroidManifest.tmpl.xml → <service> + intent-filter + meta-data
#   res/xml/accessibility_service_config.xml → 服务能力声明
#   src/main/java/.../TiShouAccessibilityService.java → 服务实现
# buildozer.spec 必须配置:
#   android.add_src = src/main/java
#   android.add_resources = res/xml:xml
#   android.permissions 含 BIND_ACCESSIBILITY_SERVICE
# ═══════════════════════════════════════════════════════════════
# =============================================================================

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  TiShou APK 构建脚本 (Docker)" -ForegroundColor Cyan
Write-Host "  版本: v2.3.4" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ─────────────────────────────────────────────────────────────
# 1. 检查 Docker 是否安装
# ─────────────────────────────────────────────────────────────
Write-Host "[1/6] 检查 Docker 环境..." -ForegroundColor Yellow

try {
    $dockerVersion = docker --version 2>&1
    Write-Host "  ✓ Docker 已安装: $dockerVersion" -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "  ✗ Docker 未安装或不在 PATH 中" -ForegroundColor Red
    Write-Host ""
    Write-Host "  请先安装 Docker Desktop for Windows：" -ForegroundColor Yellow
    Write-Host "    https://docs.docker.com/desktop/install/windows-install/" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  安装完成后，在 Docker Settings → Resources → File Sharing 中" -ForegroundColor Yellow
    Write-Host "  添加本项目所在目录（例如 C:\Users\admin\PyCharmMiscProject）" -ForegroundColor Yellow
    exit 1
}

# ─────────────────────────────────────────────────────────────
# 2. 检查 Docker 守护进程是否运行
# ─────────────────────────────────────────────────────────────
try {
    $dockerInfo = docker info 2>&1
    Write-Host "  ✓ Docker 守护进程运行中" -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "  ✗ Docker 守护进程未运行" -ForegroundColor Red
    Write-Host "  请启动 Docker Desktop" -ForegroundColor Yellow
    exit 1
}

# ─────────────────────────────────────────────────────────────
# 3. 获取项目目录
# ─────────────────────────────────────────────────────────────
$projectDir = Get-Location
$parentDir = Split-Path $projectDir -Parent

Write-Host ""
Write-Host "  项目目录: $projectDir" -ForegroundColor White
Write-Host ""

# ─────────────────────────────────────────────────────────────
# 4. 清理旧容器和旧 APK
# ─────────────────────────────────────────────────────────────
Write-Host "[2/6] 清理旧的构建产物..." -ForegroundColor Yellow

docker rm -f tishou-builder 2>$null | Out-Null

if (Test-Path "$projectDir/bin") {
    Remove-Item -Path "$projectDir/bin/*.apk" -Force -ErrorAction SilentlyContinue
    Write-Host "  ✓ 已清理旧 APK 文件" -ForegroundColor Green
}
if (Test-Path "$projectDir/.buildozer") {
    Remove-Item -Path "$projectDir/.buildozer" -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  ✓ 已清理旧构建缓存" -ForegroundColor Green
}

# ─────────────────────────────────────────────────────────────
# 5. 拉取最新的 buildozer Docker 镜像
# ─────────────────────────────────────────────────────────────
Write-Host "[3/6] 拉取 buildozer Docker 镜像..." -ForegroundColor Yellow
docker pull kivy/buildozer:latest 2>&1 | Out-Null
Write-Host "  ✓ 镜像已就绪" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────
# 6. 执行构建
# ─────────────────────────────────────────────────────────────
Write-Host "[4/6] 开始构建 APK（首次构建约 30-60 分钟）..." -ForegroundColor Yellow
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
$buildDuration = [math]::Round(($buildEnd - $buildStart).TotalMinutes, 1)

# ─────────────────────────────────────────────────────────────
# 7. 输出结果
# ─────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[5/6] 构建完成，检查产物..." -ForegroundColor Yellow

if ($buildExitCode -eq 0) {
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  构建成功！耗时: ${buildDuration} 分钟" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""

    $apkFiles = Get-ChildItem -Path "$projectDir/bin" -Filter "*.apk" -ErrorAction SilentlyContinue
    if ($apkFiles) {
        foreach ($apk in $apkFiles) {
            $sizeInMB = [math]::Round($apk.Length / 1MB, 2)
            Write-Host "  APK 文件: $($apk.FullName)" -ForegroundColor Cyan
            Write-Host "  文件大小: ${sizeInMB} MB" -ForegroundColor Cyan
        }
        Write-Host ""
        Write-Host "  安装到手机：" -ForegroundColor White
        Write-Host "    adb install $($apkFiles[0].FullName)" -ForegroundColor Gray
        Write-Host "    或直接将 APK 传到手机点击安装" -ForegroundColor Gray
    } else {
        Write-Host "  ⚠ APK 文件未找到，请检查构建日志" -ForegroundColor Yellow
    }
} else {
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  构建失败（退出码: $buildExitCode）" -ForegroundColor Red
    Write-Host "  耗时: ${buildDuration} 分钟" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "  常见问题排查：" -ForegroundColor Yellow
    Write-Host "    1. Docker 文件共享权限未设置" -ForegroundColor Yellow
    Write-Host "       → Docker Settings → Resources → File Sharing → 添加项目目录" -ForegroundColor Yellow
    Write-Host "    2. 网络问题导致 SDK/NDK 下载失败" -ForegroundColor Yellow
    Write-Host "       → 检查网络连接，必要时使用代理" -ForegroundColor Yellow
    Write-Host "    3. 磁盘空间不足（至少需要 10GB 空闲）" -ForegroundColor Yellow
    Write-Host "       → 清理 Docker 缓存: docker system prune -a" -ForegroundColor Yellow
    Write-Host "    4. 内存不足（Docker 至少需要 4GB）" -ForegroundColor Yellow
    Write-Host "       → Docker Settings → Resources → Memory → 调整为 4GB+" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[6/6] 完成" -ForegroundColor Yellow
Write-Host ""
Read-Host "按 Enter 键退出"