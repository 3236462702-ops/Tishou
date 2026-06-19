# =============================================================================
# TiShou — Buildozer 打包配置文件
# 版本：v2.1.0
# 更新日期：2026-06-19
# 更新内容：自建 Java AccessibilityService + KeepAliveService + 权限重构
# =============================================================================
# 打包目标：Android APK（仅适配安卓真机）
# 项目框架：Kivy 2.3.0+ / Python 3.11
# 打包工具：buildozer（基于 python-for-android）
#
# 使用说明：
#   首次打包：buildozer android debug
#   调试+安装+运行：buildozer android debug deploy run
#   清理缓存：buildozer android distclean
#   发布包（需keystore）：buildozer android release
#
# ═══════════════════════════════════════════════════════════════
# Windows 系统无法安装的安卓专属依赖（由 buildozer/p4a 在编译时注入）：
#   pyjnius — Android Java 桥接（悬浮窗、通知、AudioTrack、权限检测）
#   jnius   — 随 pyjnius 附带，访问 Android 系统 API
#   p4a      — python-for-android 运行时，提供 android 模块
# 这些依赖在 Windows 开发环境通过 try-except ImportError 保护，
# 在 APK 编译时由 p4a 从源码构建并注入。
# ═══════════════════════════════════════════════════════════════
#
# 注意事项：
#   1. easyocr 模型文件（~100MB）默认首次启动联网下载
#   2. APK 最低支持 API 26（Android 8.0），目标 API 33
#   3. 不要写 pygame（依赖 longintrepr.h，Python 3.12+ 已移除）
#   4. 不要写 android（p4a 自动包含）
#   5. 不要锁定版本号（p4a 配方有自己的版本管理）
# =============================================================================

[app]

# (str) 应用标题
title = TiShou

# (str) 包名
package.name = tishou

# (str) 包域名
package.domain = org.tishou

# (str) 源代码目录（main.py 所在位置）
source.dir = .

# (list) 包含的源文件扩展名
source.include_exts = py,png,jpg,kv,atlas,ttf,conf,json,ini

# (list) 排除的源文件/目录
source.exclude_dirs = __pycache__,.git,.idea,.trae,logs,venv,tests
source.exclude_patterns = *.log,*.pyc,*.pyo

# (str) 应用版本号
version = 1.0.0

# ═══════════════════════════════════════════════════════════════
# 依赖清单（由 python-for-android 编译）
# 所有包均通过 p4a recipe 从源码构建，不依赖 pip/PyPI
# ═══════════════════════════════════════════════════════════════
requirements = python3,kivy,pyjnius,requests,easyocr,pillow,numpy,schedule

# (str) 启动画面图片
# presplash.filename = %(source.dir)s/data/presplash.png

# (str) 应用图标
# icon.filename = %(source.dir)s/data/icon.png

# (str) 屏幕方向：竖屏
orientation = portrait

# (bool) 全屏模式
fullscreen = 0

#
# ─────────────────────────────────────────────────────────────
# Android 专属配置
# ─────────────────────────────────────────────────────────────
#

# (int) 目标 Android API 级别
android.api = 33

# (int) 最低 Android API 级别（Android 8.0）
android.minapi = 26

# (str) NDK 版本
android.ndk = 26d

# (bool) 自动接受 SDK 许可证
android.accept_sdk_license = True

# (list) 目标 CPU 架构（仅 arm64-v8a，现代手机均为 64 位）
android.archs = arm64-v8a

# (bool) 使用 Gradle 构建系统
android.gradle = True

# (bool) 启用 AndroidX 支持库
android.use_androidx = True

# (str) 自定义 Java 源码目录（无障碍服务 + 前台保活服务）
android.add_src = src/main/java

# (str) 自定义 Android 资源目录（无障碍服务 XML 配置）
android.add_resources = res/xml:xml

# ═══════════════════════════════════════════════════════════════
# Android 权限清单
# 这些权限在 Windows 上无法声明或测试，仅在 APK 编译时生效
# ═══════════════════════════════════════════════════════════════
# 注意：Buildozer ConfigParser 不支持反斜杠续行，必须逗号分隔写在同一行
android.permissions = BIND_ACCESSIBILITY_SERVICE, INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE, ACCESS_FINE_LOCATION, ACCESS_COARSE_LOCATION, SYSTEM_ALERT_WINDOW, FOREGROUND_SERVICE, FOREGROUND_SERVICE_SPECIAL_USE, POST_NOTIFICATIONS, REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, RECEIVE_BOOT_COMPLETED, WAKE_LOCK, VIBRATE

# (int) 调试日志级别（20=verbose, 21=debug, 22=info, 23=warning, 24=error）
android.log_level = 22

# (int) 发布包日志级别
android.release_log_level = 24

# (bool) 保持屏幕常亮（WakeLock）
android.wakelock = True

# (bool) 启用振动
android.vibrate = True

# (str) Android 入口 Activity
# android.entrypoint = org.kivy.android.PythonActivity

# (str) p4a 引导模式
# android.bootstrap = sdl2

# (str) 自定义 AndroidManifest 模板（将 service 声明注入 <application> 内部）
android.manifest.template = AndroidManifest.tmpl.xml

#
# ─────────────────────────────────────────────────────────────
# 以下为其他平台配置（本项目仅适配安卓，保留默认值）
# ─────────────────────────────────────────────────────────────
#

# iOS
# ios.appstore_url =
# ios.kitchen =

# Windows
# windows.dependencies =
# windows.entry_point = main.py

# macOS
# macos.dependencies =
# macos.entry_point = main.py

# Linux
# linux.dependencies =
# linux.entry_point = main.py