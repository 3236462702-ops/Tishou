# -*- coding: utf-8 -*-
"""
TiShou 前置校验脚本（pre_check.py）
====================================
用途：本地自测配置完整性，防止错误代码提交到仓库后 CI 构建失败。
运行：python pre_check.py
退出码：0=全部通过, 1=有严重错误

校验项：
  1. buildozer.spec 关键参数（api>=35, 权限, 资源路径, 依赖）
  2. AndroidManifest.tmpl.xml 模板语法和 service 声明
  3. accessibility_service_config.xml 语法和必需属性
  4. TiShouAccessibilityService.java 文件存在和包名匹配
  5. KeepAliveService.java 文件存在
  6. 目录结构完整性（src/main/java, res/xml, models）
  7. OCR 模型文件存在性
  8. requirements.txt 与 buildozer.spec 一致性
  9. 进程隔离检查（无障碍服务与 PythonActivity 同进程）
"""

import os
import re
import sys
import json
import fnmatch

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_DIR)

# ============================================================
# 结果收集
# ============================================================
ERRORS = []
WARNINGS = []
PASSES = []


def error(msg):
    ERRORS.append(msg)
    print(f"  ❌ [ERROR] {msg}")


def warn(msg):
    WARNINGS.append(msg)
    print(f"  ⚠ [WARN]  {msg}")


def ok(msg):
    PASSES.append(msg)
    print(f"  ✓ [OK]    {msg}")


def file_exists(path, required=True):
    full = os.path.join(PROJECT_DIR, path)
    if os.path.exists(full):
        if required:
            ok(f"文件存在: {path}")
        return True
    else:
        if required:
            error(f"文件不存在: {path}")
        else:
            warn(f"文件缺失（可选）: {path}")
        return False


def dir_exists(path, required=True):
    full = os.path.join(PROJECT_DIR, path)
    if os.path.isdir(full):
        if required:
            ok(f"目录存在: {path}")
        return True
    else:
        if required:
            error(f"目录不存在: {path}")
        else:
            warn(f"目录缺失（可选）: {path}")
        return False


# ============================================================
# 1. buildozer.spec 校验
# ============================================================
def check_buildozer_spec():
    print("\n━━━ [1/9] buildozer.spec 校验 ━━━")
    if not file_exists("buildozer.spec"):
        return

    with open("buildozer.spec", "r", encoding="utf-8") as f:
        content = f.read()

    # 1.1 API 版本
    m = re.search(r'android\.api\s*=\s*(\d+)', content)
    if m:
        api = int(m.group(1))
        if api >= 35:
            ok(f"android.api = {api} (>= 35, OK)")
        else:
            error(f"android.api = {api}，必须 >= 35（Android 15+）")
    else:
        error("android.api 未配置")

    # 1.2 minapi
    m = re.search(r'android\.minapi\s*=\s*(\d+)', content)
    if m:
        minapi = int(m.group(1))
        if minapi >= 26:
            ok(f"android.minapi = {minapi} (>= 26, OK)")
        else:
            warn(f"android.minapi = {minapi}，建议 >= 26")

    # 1.3 NDK
    m = re.search(r'android\.ndk\s*=\s*(\S+)', content)
    if m:
        ok(f"android.ndk = {m.group(1)}")
    else:
        warn("android.ndk 未配置")

    # 1.4 add_src
    m = re.search(r'android\.add_src\s*=\s*(.+)', content)
    if m:
        src_dir = m.group(1).strip()
        if dir_exists(src_dir):
            ok(f"android.add_src = {src_dir}")
        else:
            error(f"android.add_src = {src_dir}，但目录不存在")
    else:
        error("android.add_src 未配置（无障碍服务 Java 源码不会被编译）")

    # 1.5 add_resources
    m = re.search(r'android\.add_resources\s*=\s*(.+)', content)
    if m:
        res = m.group(1).strip()
        ok(f"android.add_resources = {res}")
        if "res/values" in res:
            warn("android.add_resources 包含 res/values，p4a 会覆盖自定义 strings.xml")
    else:
        warn("android.add_resources 未配置（无障碍服务 XML 不会被包含）")

    # 1.6 permissions
    m = re.search(r'android\.permissions\s*=\s*(.+)', content)
    if m:
        perms = m.group(1).strip()
        required_perms = ["BIND_ACCESSIBILITY_SERVICE", "SYSTEM_ALERT_WINDOW",
                          "FOREGROUND_SERVICE", "POST_NOTIFICATIONS"]
        for p in required_perms:
            if p in perms:
                ok(f"权限已声明: {p}")
            else:
                error(f"缺少必要权限: {p}")
        count = len([x for x in perms.split(",") if x.strip()])
        ok(f"权限总数: {count}")
    else:
        error("android.permissions 未配置")

    # 1.7 manifest template
    m = re.search(r'android\.manifest\.template\s*=\s*(.+)', content)
    if m and m.group(1).strip():
        ok(f"android.manifest.template = {m.group(1).strip()}")
    else:
        warn("android.manifest.template 未配置（使用默认模板）")

    # 1.8 requirements
    m = re.search(r'^requirements\s*=\s*(.+)', content, re.MULTILINE)
    if m:
        reqs = m.group(1).strip()
        required = ["pyjnius", "kivy", "easyocr", "pillow", "numpy"]
        for r in required:
            if r.lower() in reqs.lower():
                ok(f"requirements 包含: {r}")
            else:
                error(f"requirements 缺少: {r}")
    else:
        error("requirements 未配置")

    # 1.9 version
    m = re.search(r'^version\s*=\s*(.+)', content, re.MULTILINE)
    if m:
        ok(f"version = {m.group(1).strip()}")
    else:
        warn("version 未配置")

    # 1.10 arch
    m = re.search(r'android\.archs\s*=\s*(.+)', content)
    if m:
        archs = m.group(1).strip()
        if "arm64-v8a" in archs:
            ok("android.archs 包含 arm64-v8a")
        else:
            warn(f"android.archs = {archs}，建议包含 arm64-v8a")
    else:
        warn("android.archs 未配置")

    # 1.11 gradle
    if "android.gradle = True" in content or "android.gradle = true" in content:
        ok("android.gradle = True")
    else:
        warn("android.gradle 未启用，建议设为 True")

    # 1.12 androidx
    if "android.use_androidx = True" in content or "android.use_androidx = true" in content:
        ok("android.use_androidx = True")
    else:
        warn("android.use_androidx 未启用")


# ============================================================
# 2. AndroidManifest.tmpl.xml 校验
# ============================================================
def check_manifest():
    print("\n━━━ [2/9] AndroidManifest.tmpl.xml 校验 ━━━")
    if not file_exists("AndroidManifest.tmpl.xml"):
        return

    with open("AndroidManifest.tmpl.xml", "r", encoding="utf-8") as f:
        content = f.read()

    # 2.1 无障碍 service 声明
    if "TiShouAccessibilityService" in content:
        ok("TiShouAccessibilityService 已声明")
    else:
        error("AndroidManifest 中缺少 TiShouAccessibilityService 声明")

    # 2.2 BIND_ACCESSIBILITY_SERVICE permission
    if "BIND_ACCESSIBILITY_SERVICE" in content:
        ok("无障碍服务绑定权限已声明")
    else:
        error("缺少 BIND_ACCESSIBILITY_SERVICE 权限")

    # 2.3 intent-filter
    if "android.accessibilityservice.AccessibilityService" in content:
        ok("无障碍 intent-filter 已配置")
    else:
        error("缺少无障碍 intent-filter")

    # 2.4 meta-data 资源引用
    if "@xml/accessibility_service_config" in content:
        ok("无障碍 meta-data 资源引用正确")
    else:
        error("无障碍 meta-data 缺少 @xml/accessibility_service_config")

    # 2.5 KeepAliveService
    if "KeepAliveService" in content:
        ok("KeepAliveService 已声明")
    else:
        warn("KeepAliveService 未声明")

    # 2.6 foregroundServiceType
    if "foregroundServiceType" in content:
        ok("foregroundServiceType 已配置")
    else:
        warn("foregroundServiceType 未配置（Android 14+ 需要）")

    # 2.7 C10 进程统一检查（HyperOS/Android 15/16 兼容）
    # C10 修复：移除所有 android:process=":pythonservice"，全部组件回归默认进程
    # 原因：小米澎湃 HyperOS 对非默认进程的无障碍服务有严格过滤，不显示在系统设置中
    has_py_service = ':pythonservice' in content
    if has_py_service:
        # 如果还有 :pythonservice 残留，检查无障碍服务是否也在同一进程
        warn("C10: 检测到 :pythonservice 残留，HyperOS 可能不显示无障碍服务")
        a11y_section = content.split("TiShouAccessibilityService")[1].split("</service>")[0]
        if 'process=":pythonservice"' in a11y_section:
            warn("C10: 无障碍服务仍在 :pythonservice 进程，HyperOS 可能不显示")
        else:
            ok("C10: 无障碍服务已在默认进程")
    else:
        # 没有 :pythonservice 说明所有组件在主进程，HyperOS 兼容
        ok("C10: 所有组件在主进程（HyperOS 无障碍服务兼容）")


# ============================================================
# 3. accessibility_service_config.xml 校验
# ============================================================
def check_accessibility_config():
    print("\n━━━ [3/9] accessibility_service_config.xml 校验 ━━━")
    path = "res/xml/accessibility_service_config.xml"
    if not file_exists(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # 3.1 必需属性
    required_attrs = [
        "android:accessibilityEventTypes",
        "android:accessibilityFeedbackType",
        "android:accessibilityFlags",
        "android:notificationTimeout",
        "android:canRetrieveWindowContent",
        "android:canPerformGestures",
        "android:description",
    ]
    for attr in required_attrs:
        if attr in content:
            ok(f"属性已声明: {attr}")
        else:
            error(f"缺少必需属性: {attr}")

    # 3.2 description 必须是 @string 或 @android:string 引用
    if '@string/app_name' in content:
        ok("description 使用 @string/app_name（p4a 自动生成）")
    elif '@android:string/' in content:
        ok("description 使用 @android:string/xxx（系统资源，HyperOS 兼容兜底）")
    elif '@string/' in content:
        warn("description 使用自定义 @string，确保 strings.xml 能正确打包")
    elif 'android:description="' in content:
        error("description 使用硬编码字符串，AAPT2 会拒绝！必须用 @string/xxx")

    # 3.3 FLAG_REQUEST_2_PASS_PAINT (Android 15+，p4a 编译 SDK 暂不支持)
    if "flagRequest2PassPaint" in content:
        ok("flagRequest2PassPaint 已声明")
    else:
        pass  # p4a compile SDK doesn't support this flag yet, skip warning

    # 3.4 canRetrieveWindowContent
    if 'android:canRetrieveWindowContent="true"' in content:
        ok("canRetrieveWindowContent=true")
    else:
        error("canRetrieveWindowContent 必须为 true")

    # 3.5 notificationTimeout
    m = re.search(r'android:notificationTimeout="(\d+)"', content)
    if m:
        timeout = int(m.group(1))
        if timeout <= 200:
            ok(f"notificationTimeout={timeout}ms (合理)")
        else:
            warn(f"notificationTimeout={timeout}ms，建议 <= 200ms")


# ============================================================
# 4. Java 源码校验
# ============================================================
def check_java_sources():
    print("\n━━━ [4/9] Java 源码校验 ━━━")

    # 4.1 TiShouAccessibilityService.java
    a11y_path = "src/main/java/org/tishou/accessibility/TiShouAccessibilityService.java"
    if file_exists(a11y_path):
        with open(a11y_path, "r", encoding="utf-8") as f:
            content = f.read()

        checks = [
            ("extends AccessibilityService", "继承 AccessibilityService"),
            ("onServiceConnected", "onServiceConnected 方法"),
            ("onAccessibilityEvent", "onAccessibilityEvent 方法"),
            ("onInterrupt", "onInterrupt 方法"),
            ("getInstance", "getInstance 静态方法"),
            ("isAvailable", "isAvailable 静态方法"),
            ("extractAllTexts", "extractAllTexts 方法"),
            ("getRootInActiveWindow", "getRootInActiveWindow 调用"),
        ]
        for pattern, desc in checks:
            if pattern in content:
                ok(f"Java: {desc}")
            else:
                error(f"Java: 缺少 {desc}")

        # 包名检查
        if "package org.tishou.accessibility;" in content:
            ok("Java: 包名 org.tishou.accessibility 正确")
        else:
            error("Java: 包名不正确，应为 org.tishou.accessibility")

        # FLAG_REQUEST_2_PASS_PAINT (p4a 编译 SDK 暂不支持)
        if "FLAG_REQUEST_2_PASS_PAINT" in content:
            ok("Java: flagRequest2PassPaint 已添加（p4a SDK 暂不支持，运行时会忽略）")
        else:
            pass  # p4a compile SDK doesn't support this yet

    # 4.2 KeepAliveService.java
    keepalive_path = "src/main/java/org/tishou/service/KeepAliveService.java"
    if file_exists(keepalive_path):
        with open(keepalive_path, "r", encoding="utf-8") as f:
            content = f.read()

        if "extends Service" in content:
            ok("Java: KeepAliveService extends Service")
        else:
            error("Java: KeepAliveService 未继承 Service")

        if "startForeground" in content:
            ok("Java: KeepAliveService 有 startForeground")
        else:
            warn("Java: KeepAliveService 缺少 startForeground 调用")

        if "createNotificationChannel" in content:
            ok("Java: KeepAliveService 有通知渠道创建")
        else:
            warn("Java: KeepAliveService 缺少通知渠道")

    # 4.3 包名与目录结构一致性
    if dir_exists("src/main/java/org/tishou/accessibility"):
        ok("目录: src/main/java/org/tishou/accessibility")
    else:
        error("目录缺失: src/main/java/org/tishou/accessibility")

    if dir_exists("src/main/java/org/tishou/service"):
        ok("目录: src/main/java/org/tishou/service")
    else:
        warn("目录缺失: src/main/java/org/tishou/service")


# ============================================================
# 5. 目录结构校验
# ============================================================
def check_directory_structure():
    print("\n━━━ [5/9] 目录结构校验 ━━━")
    required_dirs = [
        "modules",
        "res/xml",
        "src/main/java/org/tishou/accessibility",
        "src/main/java/org/tishou/service",
        "logs",
        "assets",
    ]
    for d in required_dirs:
        dir_exists(d)

    optional_dirs = [
        "models",
        "captures",
        "cache",
        "bin",
    ]
    for d in optional_dirs:
        dir_exists(d, required=False)


# ============================================================
# 6. OCR 模型文件校验
# ============================================================
def check_ocr_models():
    print("\n━━━ [6/9] OCR 模型文件校验 ━━━")
    required_models = [
        "models/craft_mlt_25k.pth",
        "models/zh_sim_g2.pth",
        "models/english_g2.pth",
    ]
    for m in required_models:
        if file_exists(m):
            size_mb = os.path.getsize(os.path.join(PROJECT_DIR, m)) / (1024 * 1024)
            ok(f"模型存在: {m} ({size_mb:.1f} MB)")
        else:
            error(f"OCR 模型缺失: {m}（请运行 download_ocr_models.py）")


# ============================================================
# 7. requirements.txt 一致性
# ============================================================
def check_requirements_txt():
    print("\n━━━ [7/9] requirements.txt 一致性 ━━━")
    if not file_exists("requirements.txt", required=False):
        return

    with open("requirements.txt", "r", encoding="utf-8") as f:
        txt_reqs = set()
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                # 取包名（去掉版本号）
                pkg = re.split(r'[=<>!~]', line)[0].strip().lower()
                if pkg:
                    txt_reqs.add(pkg)

    with open("buildozer.spec", "r", encoding="utf-8") as f:
        content = f.read()

    m = re.search(r'^requirements\s*=\s*(.+)', content, re.MULTILINE)
    if m:
        spec_reqs = set(x.strip().lower() for x in m.group(1).split(","))

        only_in_txt = txt_reqs - spec_reqs
        only_in_spec = spec_reqs - txt_reqs

        if only_in_txt:
            warn(f"仅在 requirements.txt 中: {only_in_txt}")
        if only_in_spec:
            warn(f"仅在 buildozer.spec 中: {only_in_spec}")
        if not only_in_txt and not only_in_spec:
            ok("requirements.txt 与 buildozer.spec 一致")

    ok(f"requirements.txt 包含 {len(txt_reqs)} 个包")


# ============================================================
# 8. .gitignore 合理性检查
# ============================================================
def check_gitignore():
    print("\n━━━ [8/9] .gitignore 合理性 ━━━")
    if not file_exists(".gitignore"):
        return

    with open(".gitignore", "r", encoding="utf-8") as f:
        content = f.read()

    # 检查 models/ 是否被忽略
    if "models/" in content or "models" in content.split("\n"):
        # 但 buildozer.spec 的 source.include_patterns 又需要 models/*.pth
        with open("buildozer.spec", "r", encoding="utf-8") as f2:
            spec = f2.read()
        if "models/*.pth" in spec:
            warn("W2: models/ 被 .gitignore 排除，但 buildozer.spec 需要 models/*.pth。确保 CI 构建时模型文件存在")
        else:
            ok("models/ 被 .gitignore 排除，buildozer.spec 中无 models 引用")

    # 检查 docker_build_apk.ps1 是否被忽略
    if "docker_build_apk.ps1" in content:
        warn("W4: docker_build_apk.ps1 被 .gitignore 排除，其他开发者 clone 后无本地构建脚本")
    else:
        ok("docker_build_apk.ps1 未被忽略")


# ============================================================
# 9. 配置文件校验
# ============================================================
def check_config():
    print("\n━━━ [9/9] 配置文件校验 ━━━")
    if not file_exists("config.json"):
        warn("config.json 不存在（将使用默认配置）")
        return

    try:
        with open("config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
        ok("config.json 格式正确")

        # 检查关键配置项
        key_items = ["order_filter", "material_auto_update", "order_judge_delay"]
        for item in key_items:
            if item in cfg:
                ok(f"config.json 包含: {item}")
            else:
                warn(f"config.json 缺少: {item}")
    except json.JSONDecodeError as e:
        error(f"config.json 格式错误: {e}")


# ============================================================
# 主流程
# ============================================================
def main():
    print("=" * 60)
    print("  TiShou 前置校验脚本")
    print("=" * 60)

    check_buildozer_spec()
    check_manifest()
    check_accessibility_config()
    check_java_sources()
    check_directory_structure()
    check_ocr_models()
    check_requirements_txt()
    check_gitignore()
    check_config()

    # 汇总
    print("\n" + "=" * 60)
    print(f"  校验完成: {len(PASSES)} 通过, {len(WARNINGS)} 警告, {len(ERRORS)} 错误")
    print("=" * 60)

    if ERRORS:
        print("\n❌ 发现严重错误，请修复后再提交：")
        for e in ERRORS:
            print(f"   - {e}")
        print()
        return 1

    if WARNINGS:
        print("\n⚠ 发现警告，建议检查：")
        for w in WARNINGS:
            print(f"   - {w}")
        print()

    print("\n✅ 所有严重检查通过，可以提交代码！")
    return 0


if __name__ == "__main__":
    sys.exit(main())