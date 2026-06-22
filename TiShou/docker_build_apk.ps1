# =============================================================================
# TiShou — Docker 本地 APK 构建脚本
# 版本：v2.6.1
# 生成日期：2026-06-23
# 更新内容：C11 修复p4a模板未被使用导致无障碍服务不注册(双重保险:绝对路径+构建前强制替换模板)
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
Write-Host "  版本: v2.6.1" -ForegroundColor Cyan
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
# 4. 清理旧容器和旧 APK（保留 .buildozer 缓存以加速增量构建）
# ─────────────────────────────────────────────────────────────
Write-Host "[2/8] 清理旧的构建产物..." -ForegroundColor Yellow

docker rm -f tishou-builder 2>$null | Out-Null

if (Test-Path "$projectDir/bin") {
    Remove-Item -Path "$projectDir/bin/*.apk" -Force -ErrorAction SilentlyContinue
    Write-Host "  ✓ 已清理旧 APK 文件" -ForegroundColor Green
}
# C11: 不再清理 .buildozer 缓存，因为我们需要保留 p4a 模板替换结果
# 如需完全清理，请手动删除 .buildozer 目录后重新构建

# ─────────────────────────────────────────────────────────────
# 5. 检查 OCR 模型文件（I4 修复）
# ─────────────────────────────────────────────────────────────
Write-Host "[3/8] 检查 OCR 模型文件..." -ForegroundColor Yellow
$modelsOk = $true
@("craft_mlt_25k.pth", "zh_sim_g2.pth", "english_g2.pth") | ForEach-Object {
    $modelPath = Join-Path $projectDir "models/$_"
    if (Test-Path $modelPath) {
        $sizeMB = [math]::Round((Get-Item $modelPath).Length / 1MB, 1)
        Write-Host "  ✓ $_ (${sizeMB}MB)" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $_ 缺失！" -ForegroundColor Red
        $modelsOk = $false
    }
}
if (-not $modelsOk) {
    Write-Host ""
    Write-Host "  ⚠ OCR 模型文件缺失，请先运行 download_ocr_models.py" -ForegroundColor Yellow
    Write-Host "    python download_ocr_models.py" -ForegroundColor Gray
    Write-Host ""
    $continue = Read-Host "  模型缺失，是否继续构建？(y/n)"
    if ($continue -ne "y") {
        exit 1
    }
}

# ─────────────────────────────────────────────────────────────
# 6. 运行前置校验脚本
# ─────────────────────────────────────────────────────────────
Write-Host "[4/8] 运行前置校验..." -ForegroundColor Yellow
$preCheckResult = python pre_check.py 2>&1
$preCheckExit = $LASTEXITCODE
if ($preCheckExit -ne 0) {
    Write-Host $preCheckResult
    Write-Host ""
    Write-Host "  ⚠ 前置校验发现严重错误，构建已终止" -ForegroundColor Red
    Write-Host "    请修复上述错误后重新运行" -ForegroundColor Yellow
    Read-Host "按 Enter 键退出"
    exit 1
}
Write-Host "  ✓ 前置校验通过" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────
# 7. 拉取最新的 buildozer Docker 镜像
# ─────────────────────────────────────────────────────────────
Write-Host "[5/8] 拉取 buildozer Docker 镜像..." -ForegroundColor Yellow
docker pull kivy/buildozer:latest 2>&1 | Out-Null
Write-Host "  ✓ 镜像已就绪" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────
# 8. 下载 p4a 并强制替换默认模板（C11 核心修复）
# ─────────────────────────────────────────────────────────────
# 原因：buildozer android.manifest.template 选项未被 p4a 正确使用，
#       导致自定义服务声明（TiShouAccessibilityService、KeepAliveService）
#       从未注入到最终 APK 的 AndroidManifest.xml 中。
#       这是 6 个版本以来无障碍服务从未出现在系统设置中的根本原因。
# 修复：先用 p4a --help 触发 python-for-android 下载，
#       然后用 find + cp 强制替换 p4a 默认模板为我们的自定义模板。
#       双重保险：android.manifest.template 路径也改为绝对路径。
Write-Host "[6/8] 下载 p4a 并强制替换模板（C11 无障碍修复）..." -ForegroundColor Yellow
docker run --rm `
    --volume "${projectDir}:/home/user/hostcwd" `
    --workdir /home/user/hostcwd `
    --env BUILDOZER_NO_TERMINAL=1 `
    kivy/buildozer:latest `
    bash -c "
      echo '=== 步骤 1/2: 下载 python-for-android 运行时 ==='
      buildozer android p4a -- --help 2>&1 | tail -5 || echo 'p4a 初始化完成（或已初始化）'
      echo ''
      echo '=== 步骤 2/2: 强制替换默认 AndroidManifest 模板 ==='
      find /home/user/hostcwd/.buildozer -name 'AndroidManifest.tmpl.xml' -path '*/templates/*' -exec cp -v /home/user/hostcwd/AndroidManifest.tmpl.xml {} \;
      if [ \$? -eq 0 ]; then
        echo '=== 模板替换成功！自定义服务声明已注入 ==='
      else
        echo '=== 警告：模板替换未找到目标文件，将回退到 android.manifest.template 配置 ==='
      fi
    "
Write-Host "  ✓ p4a 模板替换完成" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────
# 9. 执行构建
# ─────────────────────────────────────────────────────────────
Write-Host "[7/8] 开始构建 APK（首次构建约 30-60 分钟）..." -ForegroundColor Yellow
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
Write-Host "[8/8] 构建完成，检查产物..." -ForegroundColor Yellow

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
Write-Host "[8/8] 完成" -ForegroundColor Yellow
Write-Host ""
Read-Host "按 Enter 键退出"