# =============================================================================
# TiShou — Buildozer 打包配置文件
# =============================================================================
# 打包目标：Android APK（仅适配安卓真机）
# 项目框架：Kivy 2.3.0+ / Python 3.11+
# 打包工具：buildozer（基于 python-for-android）
#
# 使用说明：
#   首次打包：buildozer android debug
#   调试+安装+运行：buildozer android debug deploy run
#   清理缓存：buildozer android distclean
#   发布包（需keystore）：buildozer android release
#
# 注意事项：
#   1. 三个安卓专属库（accessible-android, android-permissions, android-apps）
#      由 python-for-android 从源码编译加入 APK，不是 pip 包
#   2. easyocr 模型文件（~100MB）默认首次启动联网下载
#   3. APK 最低支持 API 26（Android 8.0），目标 API 33
# =============================================================================

[app]

# (str) Title of your application
title = TiShou

# (str) Package name
package.name = tishou

# (str) Package domain (needed for android/ios packaging)
package.domain = org.tishou

# (str) Source code where the main.py live
source.dir = .

# (list) Source files to include (patterns)
source.include_exts = py,png,jpg,kv,atlas,ttf,conf,json,ini

# (list) List of inclusions using packagename=filelist format
# source.include_exts = py,png,jpg,kv,atlas,ttf,json

# (list) List of inclusions
# source.includes = *.json, *.ini

# (list) Exclude source files
# source.excludes = tests/*, venv/*, __pycache__/*, .git/*, .idea/*, *.log

# (str) Application versioning
version = 1.0.0

# (str) Application versioning (method)
# version.regex = __version__ = ['"](.*)['"]
# version.filename = %(source.dir)s/main.py

# (list) Application requirements
# 兼容 pip 的包（可从 PyPI 安装）+ 三个安卓专属库（由 p4a 源码编译）
requirements = python3,Kivy==2.3.0,pyjnius,requests,easyocr,pillow,pygame,numpy,schedule,accessible-android,android-permissions,android-apps

# (str) Custom source folders for requirements
# requirements.source.pyyaml = ext_libs/pyyaml

# (list) Garden requirements
# garden_requirements =

# (str) Presplash of the application
# presplash.filename = %(source.dir)s/data/presplash.png

# (str) Icon of the application
# icon.filename = %(source.dir)s/data/icon.png

# (str) Supported orientation (one of landscape, sensorLandscape, portrait or all)
orientation = portrait

# (list) List of service to declare
# services = NAME:ENTRYPOINT_TO_PY,NAME2:ENTRYPOINT2_TO_PY

#
# OS-specific Settings
#

#
# Android specific
#

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (int) Android API to use
android.api = 33

# (int) Minimum API required
android.minapi = 26

# (int) Android SDK version to use
# android.sdk = 24

# (str) Android NDK version to use
android.ndk = 25b

# (bool) Use --private data storage (True) or --dir public storage (False)
# android.private_storage = True

# (str) Android NDK directory (if not using the bundled NDK)
# android.ndk_path =

# (str) Android SDK directory (if not using the bundled SDK)
# android.sdk_path =

# (str) Android Ant directory (if not using the bundled Ant)
# android.ant_path =

# (bool) If True, then skip trying to update the Android SDK
# This can be useful to avoid excess Internet downloads
# android.skip_update = False

# (bool) If True, then automatically accept SDK license
# agreements. This is intended for automation only. If set to False,
# the default, you will be shown the license when first running
# buildozer.
android.accept_sdk_license = True

# (str) Android entry point, default is 'org.kivy.android.PythonActivity'
# android.entrypoint = org.robovm.apple.runtime.AppleRuntime

# (list) List of Java .jar files to add to the libs so that pyjnius can access
# their classes. Don't add jars that you do not need, since extra jars can slow
# down the build
# android.add_jars = foo.jar,bar.jar

# (list) List of Python .py source files to compile to .pyc
# android.add_pyx = src/main.py, src/some_script.py

# (str) python-for-android (p4a) branch to use, defaults to 'master'
# android.p4a_branch = master

# (list) List of Java classes to add as activities to the manifest.
# android.add_activities = com.example.FooActivity

# (list) List of Java classes to add as services to the manifest.
# android.add_services = com.example.FooService

# (list) List of Java classes to add as receivers to the manifest.
# android.add_receivers = com.example.FooReceiver

# (str) Python for android (p4a) bootstrap to use
# android.bootstrap = sdl2

# (str) Python for android (p4a) distribution type (appsource, internal)
# android.distribution = internal

#
# Permissions
#
# (list) Android permissions to use
android.permissions = \
    BIND_ACCESSIBILITY_SERVICE, \
    INTERNET, \
    ACCESS_NETWORK_STATE, \
    READ_EXTERNAL_STORAGE, \
    WRITE_EXTERNAL_STORAGE, \
    ACCESS_FINE_LOCATION, \
    ACCESS_COARSE_LOCATION, \
    SYSTEM_ALERT_WINDOW, \
    FOREGROUND_SERVICE, \
    POST_NOTIFICATIONS, \
    REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, \
    MEDIA_PROJECTION

# (list) Android libraries to use as dependencies (e.g. for pyjnius access to JARs)
# android.libs =

# (int) Android logging level (20 = verbose, 21 = debug, 22 = info, 23 = warning, 24 = error)
android.log_level = 22

# (int) Android release log level (used for release builds)
android.release_log_level = 24

# (str) Meta-data to add to AndroidManifest.xml
# android.meta_data =

# (str) Extra XML to add to AndroidManifest.xml (e.g., for accessibility service)
# android.extra_manifest_xml = <service android:name=".AccessibilityService" android:permission="android.permission.BIND_ACCESSIBILITY_SERVICE" android:exported="true"><intent-filter><action android:name="android.accessibilityservice.AccessibilityService"/></intent-filter></service>

# (list) Android extra Java libs to add to the APK
# android.extra_libs =

# (str) The Android theme to use
# android.theme = @android:style/Theme.NoTitleBar

# (str) The Android accent color (supports HEX, RGB, ARGB)
# android.accent_color = FF0000

# (str) The Android primary color
# android.primary_color = 00FF00

# (str) The Android resource string for app_name
# android.string.app_name = TiShou

# (bool) Indicate if the application needs to stay turned on (e.g., for screen wake lock)
android.wakelock = True

# (bool) Indicate if the application should use the device's hardware keyboard
# android.hardware_keyboard = False

# (bool) Indicate if the application uses the camera
# android.camera = False

# (bool) Indicate if the application uses the device's flash
# android.flash = False

# (bool) Indicate if the application uses the device's vibrator
# android.vibrate = True

# (bool) Indicate if the application uses the device's compass
# android.compass = False

# (bool) Indicate if the application uses the device's accelerometer
# android.accelerometer = False

# (list) List of extra system permissions (Android only)
# android.system_permissions =

# (str) The Android intent to add (e.g., for deep linking)
# android.intent =

# (str) The Android intent scheme to add
# android.intent_scheme =

#
# iOS specific
#

# (str) URL to your application's App Store page (used for title bar)
# ios.appstore_url = http://itunes.apple.com/...

# (str) Path to a custom kitchen to use
# ios.kitchen =

#
# Windows specific
#

# (list) List of Windows dependencies to include
# windows.dependencies =

# (str) Windows application entry point
# windows.entry_point = main.py

# (list) List of DLL files to include for Windows
# windows.include_dlls =

#
# macOS specific
#

# (list) List of macOS dependencies to include
# macos.dependencies =

# (str) macOS application entry point
# macos.entry_point = main.py

# (list) List of frameworks to include for macOS
# macos.frameworks =

#
# Linux specific
#

# (list) List of Linux dependencies to include
# linux.dependencies =

# (str) Linux application entry point
# linux.entry_point = main.py

#
# Common
#

# (list) List of custom external dependencies for the project
# dependencies =

# (list) Custom or extra Java/Kotlin/Android dependencies
# android.gradle_dependencies =

# (list) Custom AAR or JAR files to add to the APK
# android.add_aars =

# (list) Custom AAR or JAR files to add to the APK
# android.add_jars =

# (bool) Use the Gradle build system instead of the deprecated Ant
android.gradle = True

# (str) Path to the gradle executable (auto-detected if not specified)
# android.gradle_path =

# (list) Android product flavors
# android.product_flavors =

# (bool) Enable the use of AndroidX libraries
android.use_androidx = True