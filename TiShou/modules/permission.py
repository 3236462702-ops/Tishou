# -*- coding: utf-8 -*-
"""
安卓权限模块
===========
适配高版本安卓 + 小米澎湃OS（HyperOS）。

功能：
  1. 分步申请权限（不批量弹窗）：
     基础（存储/通知/定位/网络）→ 悬浮窗 → 屏幕录制 → 无障碍&后台
  2. 识别澎湃OS，自动跳转省电/自启动设置页，附带图文引导
  3. 全局权限检测，缺失引导跳转系统设置，一键跳转全部权限入口
  4. 权限降级机制：
     - 拒绝录屏 → 纯无障碍模式
     - 拒绝定位 → 手动选地区
     - 禁用网络 → 关闭素材自动更新
  5. 权限拒绝不闪退、不终止核心功能，全异常捕获

注意：实际权限操作依赖安卓环境（pyjnius / android-permissions），
Windows 开发环境只记录日志并模拟流程。
"""

import sys
import os
import json
import time
import threading
from typing import Optional, Callable, Dict, List
from enum import Enum

# 将父目录加入路径以便导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.utils import LogManager, ConfigManager, ExceptionUtil, is_android, safe_bool


# ============================================================
# 权限阶段定义
# ============================================================

class PermissionStage(Enum):
    """权限申请阶段（按顺序分步申请）"""

    STAGE_1_BASIC = "stage_1_basic"               # 基础：存储/通知/定位/网络
    STAGE_2_FLOAT = "stage_2_float"               # 悬浮窗
    STAGE_3_SCREEN_RECORD = "stage_3_screen_record"  # 屏幕录制
    STAGE_4_ACCESSIBILITY = "stage_4_accessibility"   # 无障碍&后台


class PermissionState(Enum):
    """权限状态"""

    UNKNOWN = "unknown"               # 未知
    GRANTED = "granted"               # 已授予
    DENIED = "denied"                 # 已拒绝
    NOT_REQUESTED = "not_requested"   # 未申请
    PERMANENTLY_DENIED = "permanently_denied"  # 永久拒绝（不再询问）


# ============================================================
# 权限清单（按阶段分组）
# ============================================================

# 阶段一：基础权限
STAGE_1_PERMISSIONS = [
    {
        "key": "storage",
        "name": "全部存储权限",
        "android_permission": "android.permission.READ_EXTERNAL_STORAGE",
        "android_permission2": "android.permission.WRITE_EXTERNAL_STORAGE",
        "android_permission3": "android.permission.MANAGE_EXTERNAL_STORAGE",
        "description": "用于读取配置、保存日志、截图缓存和素材下载",
        "required": True,
    },
    {
        "key": "notifications",
        "name": "通知权限",
        "android_permission": "android.permission.POST_NOTIFICATIONS",
        "description": "用于抢单成功时发送通知提醒",
        "required": False,
    },
    {
        "key": "location",
        "name": "定位权限",
        "android_permission": "android.permission.ACCESS_FINE_LOCATION",
        "android_permission2": "android.permission.ACCESS_COARSE_LOCATION",
        "description": "用于获取接单区域（拒绝后可手动选地区）",
        "required": False,
    },
    {
        "key": "network",
        "name": "网络权限",
        "android_permission": "android.permission.INTERNET",
        "android_permission2": "android.permission.ACCESS_NETWORK_STATE",
        "description": "用于网络请求和素材更新检查",
        "required": True,
    },
]

# 阶段二：悬浮窗权限
STAGE_2_PERMISSIONS = [
    {
        "key": "float_window",
        "name": "悬浮窗权限",
        "android_permission": "android.permission.SYSTEM_ALERT_WINDOW",
        "description": "用于在游戏/应用上层显示抢单悬浮窗",
        "required": False,
    },
]

# 阶段三：屏幕录制权限
STAGE_3_PERMISSIONS = [
    {
        "key": "screen_record",
        "name": "屏幕录制权限",
        "android_permission": "android.permission.MEDIA_PROJECTION",
        "description": "用于自动截屏识别订单（拒绝后切换纯无障碍模式）",
        "required": False,
    },
]

# 阶段四：无障碍&后台权限
STAGE_4_PERMISSIONS = [
    {
        "key": "accessibility",
        "name": "无障碍服务权限",
        "android_permission": "android.permission.BIND_ACCESSIBILITY_SERVICE",
        "description": "用于自动抢单操作（核心权限，建议开启）",
        "required": True,
    },
    {
        "key": "background",
        "name": "后台运行权限",
        "android_permission": "android.permission.FOREGROUND_SERVICE",
        "description": "用于应用在后台持续运行",
        "required": True,
    },
    {
        "key": "battery",
        "name": "省电白名单",
        "android_permission": "ignore_battery_optimizations",
        "description": "防止系统休眠时杀掉进程",
        "required": False,
    },
]

# 所有权限阶段
ALL_STAGES = [
    (PermissionStage.STAGE_1_BASIC, "基础权限", STAGE_1_PERMISSIONS),
    (PermissionStage.STAGE_2_FLOAT, "悬浮窗权限", STAGE_2_PERMISSIONS),
    (PermissionStage.STAGE_3_SCREEN_RECORD, "屏幕录制权限", STAGE_3_PERMISSIONS),
    (PermissionStage.STAGE_4_ACCESSIBILITY, "无障碍&后台权限", STAGE_4_PERMISSIONS),
]


# ============================================================
# 系统识别
# ============================================================

class SystemInfo:
    """
    安卓系统信息识别
    识别澎湃OS（HyperOS）及其他国产ROM
    """

    # 澎湃OS 特征
    HYPEROS_INDICATORS = ["hyperos", "xiaomi", "miui"]

    @staticmethod
    def detect_rom() -> str:
        """
        检测当前安卓 ROM 类型
        :return: "hyperos" / "miui" / "other" / "unknown"
        """
        try:
            if not is_android():
                return "unknown"

            # 方法1：读取 build.prop 属性
            props = SystemInfo._read_build_props()

            # 检查 HyperOS
            if props.get("ro.miui.ui.version.name", "").startswith("OS"):
                return "hyperos"

            # 检查 MIUI
            miui_version = props.get("ro.miui.ui.version.name", "")
            if miui_version:
                return "miui"

            # 检查品牌
            brand = props.get("ro.product.brand", "").lower()
            if "xiaomi" in brand:
                miui_ver = props.get("ro.miui.ui.version.name", "")
                return "hyperos" if miui_ver else "miui"

            return "other"

        except Exception:
            return "unknown"

    @staticmethod
    def is_hyperos() -> bool:
        """判断是否为澎湃OS"""
        return SystemInfo.detect_rom() == "hyperos"

    @staticmethod
    def is_xiaomi_family() -> bool:
        """判断是否为小米系列（HyperOS/MIUI）"""
        rom = SystemInfo.detect_rom()
        return rom in ("hyperos", "miui")

    @staticmethod
    def _read_build_props() -> dict:
        """
        读取系统 build.prop 属性（安卓环境）
        :return: 属性字典
        """
        props = {}
        try:
            # 方法1：通过 getprop 命令
            import subprocess
            result = subprocess.run(
                ["getprop"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    line = line.strip()
                    if ":" in line:
                        key, value = line.split(":", 1)
                        props[key.strip().strip("[]")] = value.strip().strip("[]")
        except Exception:
            pass

        # 方法2：环境变量补充
        try:
            props["ro.product.brand"] = os.environ.get("ANDROID_BRAND", "")
        except Exception:
            pass

        return props

    @staticmethod
    def get_hyperos_settings_intents() -> dict:
        """
        获取澎湃OS 省电/自启动设置页的 Intent 映射

        :return: {
            "battery_saver": "intent://...",
            "auto_start": "intent://...",
            "guide_text": "引导文案",
        }
        """
        return {
            "battery_saver": {
                "title": "省电策略",
                "package": "com.android.settings",
                "action": "android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS",
                "description": "将 TiShou 设置为「无限制」，防止系统休眠时被杀",
                "steps": [
                    "① 找到并点击「TiShou」应用",
                    "② 选择「省电策略」→「无限制」",
                    "③ 允许「后台运行」",
                ],
            },
            "auto_start": {
                "title": "自启动管理",
                "package": "com.miui.securitycenter",
                "action": "miui.intent.action.APP_PERM_EDITOR",
                "description": "允许 TiShou 开机自启和后台运行",
                "steps": [
                    "① 在列表中找到「TiShou」",
                    "② 打开「自启动」开关",
                    "③ 允许「关联启动」和「后台活动」",
                ],
            },
            "float_window_hyperos": {
                "title": "悬浮窗权限",
                "package": "com.android.settings",
                "action": "android.settings.action.MANAGE_OVERLAY_PERMISSION",
                "description": "允许 TiShou 显示悬浮窗",
                "steps": [
                    "① 找到「TiShou」应用",
                    "② 打开「显示悬浮窗」开关",
                ],
            },
        }

    @staticmethod
    def get_guide_html(rom: str) -> str:
        """
        获取图文引导 HTML（供 UI 层 WebView 或 Label 展示）

        :param rom: ROM 类型
        :return: HTML 格式的引导文案
        """
        if rom not in ("hyperos", "miui"):
            return "<p>请在系统设置中为 TiShou 授予所需权限</p>"

        intents = SystemInfo.get_hyperos_settings_intents()

        html = """
        <style>
            body { font-family: -apple-system, sans-serif; padding: 16px; color: #333; }
            h2 { color: #1A1A1A; font-size: 18px; }
            .card {
                background: #FFFFFF; border-radius: 12px;
                padding: 14px; margin: 10px 0;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            }
            .step { color: #666; font-size: 14px; line-height: 1.8; }
            .icon { font-size: 20px; margin-right: 6px; }
        </style>
        <h2>📱 澎湃OS 权限设置引导</h2>
        """

        for section_key in ["battery_saver", "auto_start", "float_window_hyperos"]:
            section = intents.get(section_key, {})
            html += f"""
            <div class="card">
                <strong>{section.get('title', '')}</strong>
                <p class="step">{section.get('description', '')}</p>
                <p class="step">{'<br>'.join(section.get('steps', []))}</p>
            </div>
            """

        return html


# ============================================================
# 权限降级管理
# ============================================================

class PermissionDegradation:
    """
    权限降级管理
    ===========
    当用户拒绝权限时，自动切换到对应的降级方案，
    保证核心功能不受影响。

    降级映射：
      - 拒绝录屏 → 纯无障碍模式（手动授权无障碍点击）
      - 拒绝定位 → 手动选地区
      - 禁用网络 → 关闭素材自动更新
    """

    def __init__(self):
        self._logger = LogManager.get_logger("app")
        self._config = ConfigManager()

        # 降级状态
        self._degradations = {
            "screen_record": False,   # True=已降级（无录屏）
            "location": False,        # True=已降级（手动选地区）
            "network": False,         # True=已降级（无网络）
        }

        # 用户手动选择的地区（定位降级时使用）
        self._manual_region = self._config.get("manual_region", "")

    def apply_screen_record_degradation(self) -> dict:
        """
        屏幕录制权限降级
        降级方案：切换到纯无障碍模式

        :return: {
            "mode": str,            # "accessibility_only"
            "description": str,     # 降级说明
            "capture_method": str,  # "accessibility"（通过无障碍获取截图）
        }
        """
        try:
            self._degradations["screen_record"] = True
            self._logger.warning("屏幕录制权限被拒绝，降级为纯无障碍模式")

            # 保存降级状态到配置
            self._config.set("capture_mode", "accessibility_only")

            return {
                "mode": "accessibility_only",
                "description": "已切换为纯无障碍模式（通过无障碍服务捕获界面）",
                "capture_method": "accessibility",
                "notice": "部分需要截屏的功能将受限，但抢单核心流程不受影响",
            }
        except Exception as e:
            self._logger.error(f"屏幕录制降级异常: {e}")
            return {"mode": "accessibility_only", "error": str(e)}

    def apply_location_degradation(self) -> dict:
        """
        定位权限降级
        降级方案：使用配置文件中的手动地区设定

        :return: {
            "mode": str,            # "manual_region"
            "current_region": str,  # 当前设定的地区
            "description": str,     # 降级说明
        }
        """
        try:
            self._degradations["location"] = True
            region = self._manual_region or "未设置（请在设置中手动选择地区）"
            self._logger.warning(f"定位权限被拒绝，降级为手动选地区: {region}")

            self._config.set("location_mode", "manual")
            self._config.set("location_degraded", True)

            return {
                "mode": "manual_region",
                "current_region": region,
                "description": "已切换为手动地区模式",
                "hint": "请前往「设置-地区设置」手动选择接单区域",
            }
        except Exception as e:
            self._logger.error(f"定位降级异常: {e}")
            return {"mode": "manual_region", "error": str(e)}

    def apply_network_degradation(self) -> dict:
        """
        网络权限降级
        降级方案：关闭素材自动更新，进入离线模式

        :return: {
            "mode": str,            # "offline"
            "description": str,     # 降级说明
        }
        """
        try:
            self._degradations["network"] = True
            self._logger.warning("网络权限被拒绝/无网络，关闭素材自动更新")

            # 关闭素材自动更新
            self._config.set("material_auto_update", False)

            return {
                "mode": "offline",
                "description": "网络不可用，已关闭素材自动更新，进入离线模式",
                "notice": "部分在线功能不可用，基础抢单功能不受影响",
            }
        except Exception as e:
            self._logger.error(f"网络降级异常: {e}")
            return {"mode": "offline", "error": str(e)}

    def is_degraded(self, permission_key: str) -> bool:
        """
        检查指定权限是否已降级

        :param permission_key: 权限键名: screen_record / location / network
        :return: True=已降级
        """
        return self._degradations.get(permission_key, False)

    def get_degradation_summary(self) -> dict:
        """
        获取所有降级状态摘要（供 UI 展示）
        :return: 降级状态字典
        """
        return {
            "screen_record": {
                "degraded": self._degradations["screen_record"],
                "hint": "当前使用纯无障碍模式",
            },
            "location": {
                "degraded": self._degradations["location"],
                "hint": "当前使用手动地区模式",
            },
            "network": {
                "degraded": self._degradations["network"],
                "hint": "当前为离线模式",
            },
        }

    def set_manual_region(self, region: str):
        """
        手动设置地区（定位降级时使用）
        :param region: 地区名称
        """
        try:
            self._manual_region = region
            self._config.set("manual_region", region)
            self._logger.info(f"手动地区已设置为: {region}")
        except Exception as e:
            self._logger.error(f"设置手动地区异常: {e}")


# ============================================================
# 权限管理器
# ============================================================

class PermissionManager:
    """
    权限管理器
    =========
    分步权限申请、全局检测、降级处理。

    权限申请流程：
      Stage 1: 基础权限（存储/通知/定位/网络）
      Stage 2: 悬浮窗权限
      Stage 3: 屏幕录制权限
      Stage 4: 无障碍&后台权限
    """

    def __init__(self):
        """初始化权限管理器"""
        self._logger = LogManager.get_logger("app")
        self._config = ConfigManager()

        # 权限状态缓存
        self._permission_cache = {}
        # 已申请过的权限集合（防止重复跳转系统设置页）
        self._requested = set()

        # 当前申请阶段
        self._current_stage = PermissionStage.STAGE_1_BASIC
        self._stage_index = 0

        # 权限申请回调（供 UI 层注册）
        self._stage_callbacks = []

        # 降级管理
        self._degradation = PermissionDegradation()

        # 各阶段申请状态
        self._stage_results = {
            PermissionStage.STAGE_1_BASIC: PermissionState.NOT_REQUESTED,
            PermissionStage.STAGE_2_FLOAT: PermissionState.NOT_REQUESTED,
            PermissionStage.STAGE_3_SCREEN_RECORD: PermissionState.NOT_REQUESTED,
            PermissionStage.STAGE_4_ACCESSIBILITY: PermissionState.NOT_REQUESTED,
        }

        # 系统信息
        self._rom = "unknown"
        self._is_hyperos = False

        self._logger.info("权限管理器初始化完成")

    # ============================================================
    # 系统识别
    # ============================================================

    def detect_system(self) -> dict:
        """
        检测安卓系统信息

        :return: {
            "is_android": bool,
            "rom": str,
            "is_hyperos": bool,
            "is_xiaomi": bool,
            "sdk": int,
        }
        """
        try:
            self._rom = SystemInfo.detect_rom()
            self._is_hyperos = SystemInfo.is_hyperos()

            info = {
                "is_android": is_android(),
                "rom": self._rom,
                "is_hyperos": self._is_hyperos,
                "is_xiaomi": SystemInfo.is_xiaomi_family(),
                "sdk": 0,
            }

            # 获取 SDK 版本
            try:
                if is_android():
                    import subprocess
                    result = subprocess.run(
                        ["getprop", "ro.build.version.sdk"],
                        capture_output=True, text=True, timeout=2,
                    )
                    if result.returncode == 0:
                        info["sdk"] = int(result.stdout.strip())
            except Exception:
                pass

            self._logger.info(f"系统检测: {info}")
            return info

        except Exception as e:
            self._logger.error(f"系统检测异常: {e}")
            return {"is_android": False, "rom": "unknown", "is_hyperos": False}

    # ============================================================
    # 全局权限检测
    # ============================================================

    def check_all_permissions(self) -> dict:
        """
        全局权限检测

        :return: {
            "all_granted": bool,
            "stages": {
                "stage_1_basic": { state, permissions: [...] },
                ...
            },
            "missing_count": int,
            "missing_keys": [str],
            "degradations": dict,
        }
        """
        result = {
            "all_granted": True,
            "stages": {},
            "missing_count": 0,
            "missing_keys": [],
            "degradations": self._degradation.get_degradation_summary(),
        }

        try:
            for stage_enum, stage_name, permissions in ALL_STAGES:
                stage_perms = []
                stage_all_granted = True

                for perm_info in permissions:
                    state = self._check_single_permission(perm_info["key"])
                    perm_result = {
                        "key": perm_info["key"],
                        "name": perm_info["name"],
                        "state": state.value,
                        "required": perm_info.get("required", False),
                    }
                    stage_perms.append(perm_result)

                    if state != PermissionState.GRANTED and perm_info.get("required", False):
                        stage_all_granted = False
                        result["all_granted"] = False
                        result["missing_count"] += 1
                        result["missing_keys"].append(perm_info["key"])

                result["stages"][stage_enum.value] = {
                    "name": stage_name,
                    "all_granted": stage_all_granted,
                    "permissions": stage_perms,
                }

        except Exception as e:
            self._logger.error(f"全局权限检测异常: {e}")
            result["all_granted"] = False

        return result

    def _check_single_permission(self, perm_key: str) -> PermissionState:
        """
        检查单个权限状态

        :param perm_key: 权限键名
        :return: PermissionState
        """
        try:
            # 检查缓存
            if perm_key in self._permission_cache:
                return self._permission_cache[perm_key]

            if not is_android():
                # 非安卓环境：模拟授予
                self._permission_cache[perm_key] = PermissionState.GRANTED
                return PermissionState.GRANTED

            # 安卓环境：调用系统 API 检查
            state = self._check_via_android_api(perm_key)
            self._permission_cache[perm_key] = state
            return state

        except Exception as e:
            self._logger.warning(f"检查权限 '{perm_key}' 异常: {e}")
            return PermissionState.UNKNOWN

    def _check_via_android_api(self, perm_key: str) -> PermissionState:
        """
        通过安卓 API 检查权限
        非安卓环境或库缺失时返回 GRANTED 模拟

        特殊处理：
          - float_window（SYSTEM_ALERT_WINDOW）：使用 Settings.canDrawOverlays()
          - accessibility（BIND_ACCESSIBILITY_SERVICE）：检查自定义 Java 服务是否运行
          - battery（REQUEST_IGNORE_BATTERY_OPTIMIZATIONS）：使用 PowerManager
          - notifications（POST_NOTIFICATIONS）：API 33+ 才需要动态申请
          - 普通权限：使用 Context.checkSelfPermission()

        :param perm_key: 权限键名
        :return: PermissionState
        """
        try:
            # ---- 特殊权限：悬浮窗（SYSTEM_ALERT_WINDOW） ----
            if perm_key == "float_window":
                return self._check_float_window_permission()

            # ---- 存储权限：Android 11+ 需要 MANAGE_EXTERNAL_STORAGE ----
            # Android 10 及以下：READ/WRITE_EXTERNAL_STORAGE 弹窗即可
            # Android 11+：必须跳转系统设置开启"所有文件访问权限"
            if perm_key == "storage":
                return self._check_storage_permission()

            # ---- 特殊权限：无障碍服务（BIND_ACCESSIBILITY_SERVICE） ----
            # BIND_ACCESSIBILITY_SERVICE 是签名级权限，checkSelfPermission 永远返回 DENIED。
            # 正确做法：检查我们的自定义 Java AccessibilityService 是否正在运行。
            if perm_key == "accessibility":
                return self._check_accessibility_service()

            # ---- 特殊权限：省电白名单（REQUEST_IGNORE_BATTERY_OPTIMIZATIONS） ----
            # 不能用 checkSelfPermission，必须用 PowerManager.isIgnoringBatteryOptimizations()
            if perm_key == "battery":
                return self._check_battery_optimization()

            # ---- 特殊权限：屏幕录制（MEDIA_PROJECTION） ----
            # MEDIA_PROJECTION 需要通过 MediaProjectionManager.createScreenCaptureIntent()
            # 以 startActivityForResult 方式获取授权，无法用 checkSelfPermission 判断
            if perm_key == "screen_record":
                return PermissionState.DENIED

            # ---- 通知权限（POST_NOTIFICATIONS）：仅 Android 13（API 33）+ 需要动态申请 ----
            if perm_key == "notifications":
                return self._check_notification_permission()

            # ---- 后台运行（FOREGROUND_SERVICE）：normal 权限，安装时自动授予 ----
            if perm_key == "background":
                return PermissionState.GRANTED

            # ---- 普通权限（存储 / 定位 / 网络） ----
            return self._check_normal_permission(perm_key)

        except Exception as e:
            self._logger.warning(f"安卓 API 权限检查失败: {e}")
            return PermissionState.UNKNOWN

    # ---------- 悬浮窗权限检查 ----------
    def _check_float_window_permission(self) -> PermissionState:
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Settings = autoclass("android.provider.Settings")
            activity = PythonActivity.mActivity
            if not activity:
                return PermissionState.UNKNOWN
            can_draw = Settings.canDrawOverlays(activity)
            return PermissionState.GRANTED if can_draw else PermissionState.DENIED
        except Exception as e:
            self._logger.warning(f"悬浮窗权限检查异常: {e}")
            return PermissionState.DENIED

    # ---------- 存储权限检查（Android 11+ 全部存储） ----------
    def _check_storage_permission(self) -> PermissionState:
        try:
            from jnius import autoclass
            Build = autoclass("android.os.Build")
            sdk = Build.VERSION.SDK_INT

            if sdk < 30:
                # Android 10 及以下：检查 READ_EXTERNAL_STORAGE
                return self._check_normal_permission("storage")

            # Android 11+：使用 Environment.isExternalStorageManager()
            Environment = autoclass("android.os.Environment")
            if Environment.isExternalStorageManager():
                return PermissionState.GRANTED
            return PermissionState.DENIED
        except Exception as e:
            self._logger.warning(f"存储权限检查异常: {e}")
            return PermissionState.DENIED

    # ---------- 无障碍服务检查 ----------
    def _check_accessibility_service(self) -> PermissionState:
        try:
            from jnius import autoclass
            svc = autoclass("org.tishou.accessibility.TiShouAccessibilityService")
            if svc.isAvailable():
                return PermissionState.GRANTED
            return PermissionState.DENIED
        except Exception as e:
            self._logger.debug(f"无障碍服务检查异常（可能未安装或未开启）: {e}")
            return PermissionState.DENIED

    # ---------- 省电白名单检查 ----------
    def _check_battery_optimization(self) -> PermissionState:
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            PowerManager = autoclass("android.os.PowerManager")
            activity = PythonActivity.mActivity
            if not activity:
                return PermissionState.UNKNOWN
            pm = activity.getSystemService(PowerManager)
            if pm and pm.isIgnoringBatteryOptimizations(activity.getPackageName()):
                return PermissionState.GRANTED
            return PermissionState.DENIED
        except Exception as e:
            self._logger.debug(f"省电白名单检查异常: {e}")
            return PermissionState.DENIED

    # ---------- 通知权限检查（API 33+） ----------
    def _check_notification_permission(self) -> PermissionState:
        try:
            from jnius import autoclass
            Build = autoclass("android.os.Build")
            if Build.VERSION.SDK_INT < 33:
                return PermissionState.GRANTED
            return self._check_normal_permission("notifications")
        except Exception:
            return PermissionState.GRANTED

    # ---------- 普通权限检查 ----------
    def _check_normal_permission(self, perm_key: str) -> PermissionState:
        android_perm = self._get_android_perm_name(perm_key)
        if not android_perm:
            return PermissionState.GRANTED

        # 方法1：android.permissions 模块
        try:
            from android.permissions import check_permission
            if check_permission(android_perm):
                return PermissionState.GRANTED
            return PermissionState.DENIED
        except ImportError:
            pass

        # 方法2：pyjnius 桥接 checkSelfPermission
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            PackageManager = autoclass("android.content.pm.PackageManager")
            activity = PythonActivity.mActivity
            if not activity:
                return PermissionState.UNKNOWN
            result = activity.checkSelfPermission(android_perm)
            if result == PackageManager.PERMISSION_GRANTED:
                return PermissionState.GRANTED
            return PermissionState.DENIED
        except Exception:
            return PermissionState.GRANTED

    def _get_android_perm_name(self, perm_key: str) -> str:
        """根据权限键名获取安卓权限字符串"""
        mapping = {
            "storage": "android.permission.MANAGE_EXTERNAL_STORAGE",
            "notifications": "android.permission.POST_NOTIFICATIONS",
            "location": "android.permission.ACCESS_FINE_LOCATION",
            "network": "android.permission.INTERNET",
            "float_window": "android.permission.SYSTEM_ALERT_WINDOW",
            "screen_record": "android.permission.MEDIA_PROJECTION",
            "accessibility": "android.permission.BIND_ACCESSIBILITY_SERVICE",
            "background": "android.permission.FOREGROUND_SERVICE",
            "battery": "android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS",
        }
        return mapping.get(perm_key, "")

    # ============================================================
    # 分步权限申请
    # ============================================================

    def start_permission_flow(self, on_stage_change: Callable[[str, dict], None] = None,
                              skip_settings: bool = False):
        """
        启动分步权限申请流程

        特点：
          - 不批量弹窗，每个阶段单独申请
          - 前一个阶段完成后自动进入下一个
          - 可注册回调监听阶段变更

        :param on_stage_change: 回调函数(stage_enum_value, result_dict)
        :param skip_settings: True=仅静默检测不跳转系统设置，False=完整流程
        """
        try:
            if on_stage_change:
                self._stage_callbacks.append(on_stage_change)

            # 设置是否跳过系统设置跳转（非首次启动时静默检测）
            self._skip_settings = skip_settings

            # 先检测系统
            self.detect_system()

            # 从第一阶段开始
            self._stage_index = 0
            self._request_next_stage()

        except Exception as e:
            self._logger.error(f"启动权限申请流程异常: {e}")

    def _request_next_stage(self):
        """申请下一阶段权限"""
        try:
            if self._stage_index >= len(ALL_STAGES):
                self._logger.info("所有权限阶段已完成")
                self._notify_stage("all_completed", {"message": "所有权限申请完成"})
                return

            stage_enum, stage_name, permissions = ALL_STAGES[self._stage_index]
            self._current_stage = stage_enum

            self._logger.info(f"开始权限阶段: {stage_name}")

            # 检查该阶段所有权限状态
            stage_result = {
                "stage": stage_enum.value,
                "name": stage_name,
                "permissions": [],
                "all_granted": True,
                "degradations": [],
            }

            for perm_info in permissions:
                perm_key = perm_info["key"]
                state = self._check_single_permission(perm_key)

                perm_result = {
                    "key": perm_key,
                    "name": perm_info["name"],
                    "state": state.value,
                    "required": perm_info.get("required", False),
                }

                if state != PermissionState.GRANTED:
                    # 非首次启动：跳过系统设置跳转，仅静默记录
                    if getattr(self, '_skip_settings', False):
                        perm_result["request_result"] = False
                        perm_result["skip_reason"] = "非首次启动，跳过系统设置跳转"
                        stage_result["all_granted"] = False
                        self._logger.warning(
                            f"权限 '{perm_info['name']}' 未授予（静默跳过，不跳转设置）"
                        )
                    else:
                        # 首次启动：申请权限（可能跳转系统设置）
                        perm_result["request_result"] = self._request_permission(perm_key)

                        # 申请后重新检查
                        new_state = self._check_single_permission(perm_key)
                        perm_result["state"] = new_state.value

                        if new_state != PermissionState.GRANTED:
                            stage_result["all_granted"] = False
                            # 执行降级策略
                            degradation = self._apply_degradation(perm_key)
                            if degradation:
                                perm_result["degradation"] = degradation
                                stage_result["degradations"].append(degradation)

                stage_result["permissions"].append(perm_result)

            # 记录阶段结果
            self._stage_results[stage_enum] = (
                PermissionState.GRANTED if stage_result["all_granted"]
                else PermissionState.DENIED
            )

            # 通知回调
            self._notify_stage(stage_enum.value, stage_result)

            # 进入下一阶段（短暂延迟避免连续弹窗）
            self._stage_index += 1
            if self._stage_index < len(ALL_STAGES):
                threading.Timer(0.5, self._request_next_stage).start()

        except Exception as e:
            self._logger.error(f"权限申请阶段异常: {e}")
            self._notify_stage("error", {"error": str(e)})

    def _request_permission(self, perm_key: str) -> bool:
        """
        申请单个权限

        :param perm_key: 权限键名
        :return: True=申请成功, False=申请失败或用户拒绝

        分类处理：
          普通权限（存储/定位/通知/网络）→ request_permissions() 弹窗
          特殊权限（悬浮窗）             → Intent 跳转系统设置页
          特殊权限（无障碍服务）         → Intent 跳转无障碍设置页
          特殊权限（屏幕录制）           → MediaProjection Intent 弹窗
          特殊权限（省电白名单）         → ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS
        """
        try:
            # 特殊权限防重复申请：已申请过则不再跳转系统设置页
            if perm_key in SPECIAL_PERMISSIONS and perm_key in self._requested:
                self._logger.debug(f"权限 '{perm_key}' 已申请过，跳过重复跳转")
                return True

            self._requested.add(perm_key)

            if not is_android():
                self._logger.debug(f"[模拟] 申请权限: {perm_key} → 已同意")
                self._permission_cache[perm_key] = PermissionState.GRANTED
                return True

            android_perm = self._get_android_perm_name(perm_key)
            if not android_perm:
                return True

            # ---- 特殊权限：悬浮窗 → 跳转悬浮窗管理页 ----
            if perm_key == "float_window":
                return self._request_float_window()

            # ---- 存储权限：Android 11+ 跳转全部文件访问设置 ----
            if perm_key == "storage":
                return self._request_storage_permission()

            # ---- 特殊权限：无障碍服务 → 跳转无障碍设置页 ----
            if perm_key == "accessibility":
                return self._request_accessibility_service()

            # ---- 特殊权限：屏幕录制 → 启动 MediaProjection Intent ----
            if perm_key == "screen_record":
                return self._request_screen_record()

            # ---- 特殊权限：省电白名单 → 跳转电池优化设置 ----
            if perm_key == "battery":
                return self._request_battery_optimization()

            # ---- 后台运行：normal 权限，无需动态申请 ----
            if perm_key == "background":
                return True

            # ---- 通知权限：仅 Android 13+ 需要动态申请 ----
            if perm_key == "notifications":
                try:
                    from jnius import autoclass
                    Build = autoclass("android.os.Build")
                    if Build.VERSION.SDK_INT < 33:
                        self._permission_cache[perm_key] = PermissionState.GRANTED
                        return True
                except Exception:
                    pass

            # ---- 普通权限：request_permissions() 弹窗 ----
            return self._request_normal_permission(android_perm, perm_key)

        except Exception as e:
            self._logger.error(f"申请权限异常 '{perm_key}': {e}")
            return False

    # ---------- 悬浮窗权限申请 ----------
    def _request_float_window(self) -> bool:
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            activity = PythonActivity.mActivity
            if not activity:
                self._logger.warning("无法获取 Activity 实例，无法跳转悬浮窗设置")
                return False
            intent = Intent(
                "android.settings.action.MANAGE_OVERLAY_PERMISSION",
                Uri.parse("package:" + activity.getPackageName())
            )
            intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(intent)
            self._logger.info("已跳转悬浮窗权限设置页")
            return True
        except Exception as e:
            self._logger.error(f"跳转悬浮窗设置页失败: {e}")
            return self._open_app_settings_fallback()

    # ---------- 存储权限申请（Android 11+ 全部存储） ----------
    def _request_storage_permission(self) -> bool:
        try:
            from jnius import autoclass
            Build = autoclass("android.os.Build")
            sdk = Build.VERSION.SDK_INT

            if sdk < 30:
                # Android 10 及以下：普通弹窗申请
                return self._request_normal_permission(
                    "android.permission.READ_EXTERNAL_STORAGE", "storage"
                )

            # Android 11+：跳转"所有文件访问权限"设置页
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            Settings = autoclass("android.provider.Settings")
            Uri = autoclass("android.net.Uri")
            activity = PythonActivity.mActivity
            if not activity:
                return False

            pkg = activity.getPackageName()
            intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
            intent.setData(Uri.parse("package:" + pkg))
            intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(intent)
            self._logger.info(f"已跳转全部存储权限设置页（包名: {pkg}）")
            return True
        except Exception as e:
            self._logger.error(f"跳转全部存储权限设置页失败: {e}")
            return self._open_app_settings_fallback()

    # ---------- 无障碍服务申请 ----------
    def _request_accessibility_service(self) -> bool:
        """
        申请无障碍服务权限
        使用 ACTION_ACCESSIBILITY_DETAILS_SETTINGS 直接跳转到本应用无障碍设置详情页，
        避免用户需要在一长串列表中手动查找应用。
        """
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            Settings = autoclass("android.provider.Settings")
            Uri = autoclass("android.net.Uri")
            activity = PythonActivity.mActivity
            if not activity:
                return False

            pkg = activity.getPackageName()
            intent = Intent(Settings.ACTION_ACCESSIBILITY_DETAILS_SETTINGS)
            intent.setData(Uri.parse("package:" + pkg))
            intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(intent)
            self._logger.info(f"已跳转无障碍详情设置页（包名: {pkg}）")
            return True
        except Exception as e:
            self._logger.error(f"跳转无障碍详情页失败: {e}")
            return self._open_app_settings_fallback()

    # ---------- 屏幕录制权限申请 ----------
    def _request_screen_record(self) -> bool:
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            activity = PythonActivity.mActivity
            if not activity:
                return False
            MediaProjectionManager = autoclass(
                "android.media.projection.MediaProjectionManager"
            )
            mp_manager = activity.getSystemService(
                autoclass("android.content.Context").MEDIA_PROJECTION_SERVICE
            )
            if not mp_manager:
                self._logger.warning("MediaProjectionManager 不可用")
                return False
            intent = mp_manager.createScreenCaptureIntent()
            intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(intent)
            self._logger.info("已弹出屏幕录制授权弹窗，请点击「立即开始」")
            return True
        except Exception as e:
            self._logger.error(f"启动屏幕录制授权失败: {e}")
            return False

    # ---------- 省电白名单申请 ----------
    def _request_battery_optimization(self) -> bool:
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            activity = PythonActivity.mActivity
            if not activity:
                return False
            intent = Intent(
                "android.settings.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS",
                Uri.parse("package:" + activity.getPackageName())
            )
            intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(intent)
            self._logger.info("已跳转省电白名单设置页，请选择「允许」")
            return True
        except Exception as e:
            self._logger.error(f"跳转省电白名单设置失败: {e}")
            return self._open_app_settings_fallback()

    # ---------- 普通权限申请 ----------
    def _request_normal_permission(self, android_perm: str, perm_key: str) -> bool:
        try:
            from android.permissions import request_permissions, Permission
            request_permissions([Permission(android_perm)])
            self._logger.info(f"权限申请已发送: {perm_key}")
            return True
        except ImportError:
            self._logger.warning("android.permissions 模块不可用，无法申请权限")
            return False

    # ---------- 兜底：跳转应用设置页 ----------
    def _open_app_settings_fallback(self) -> bool:
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            activity = PythonActivity.mActivity
            if not activity:
                return False
            intent = Intent("android.settings.APPLICATION_DETAILS_SETTINGS")
            intent.setData(Uri.parse("package:" + activity.getPackageName()))
            intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(intent)
            self._logger.info("已跳转应用设置页（兜底）")
            return True
        except Exception:
            return False

    def _apply_degradation(self, perm_key: str) -> Optional[dict]:
        """
        执行权限降级策略

        :param perm_key: 被拒绝的权限键名
        :return: 降级结果字典，或 None
        """
        degradation_map = {
            "screen_record": self._degradation.apply_screen_record_degradation,
            "location": self._degradation.apply_location_degradation,
            "network": self._degradation.apply_network_degradation,
        }

        strategy = degradation_map.get(perm_key)
        if strategy:
            result = strategy()
            self._logger.info(f"权限降级已执行: {perm_key} → {result.get('mode', '')}")
            return result

        return None

    def _notify_stage(self, stage_value: str, result: dict):
        """通知所有注册的回调阶段变更"""
        for cb in self._stage_callbacks:
            try:
                cb(stage_value, result)
            except Exception:
                pass

    # ============================================================
    # 一键跳转系统设置
    # ============================================================

    def open_settings_page(self, page_key: str) -> bool:
        """
        跳转到系统设置页面

        :param page_key: 页面键名:
            "app_settings"  - 应用设置
            "float_window"  - 悬浮窗权限
            "battery"       - 省电优化
            "auto_start"    - 自启动管理
            "accessibility" - 无障碍服务
        :return: True=跳转成功, False=跳转失败
        """
        try:
            if not is_android():
                self._logger.warning("非安卓环境，无法跳转系统设置")
                return False

            # Intent 映射
            intent_map = {
                "app_settings": {
                    "action": "android.settings.APPLICATION_DETAILS_SETTINGS",
                },
                "float_window": {
                    "action": "android.settings.action.MANAGE_OVERLAY_PERMISSION",
                },
                "battery": {
                    "action": "android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS",
                },
                "auto_start": {
                    "action": "miui.intent.action.APP_PERM_EDITOR",
                    "package": "com.miui.securitycenter",
                },
                "accessibility": {
                    "action": "android.settings.ACCESSIBILITY_SETTINGS",
                },
            }

            intent_info = intent_map.get(page_key)
            if not intent_info:
                self._logger.warning(f"未知的设置页面: {page_key}")
                return False

            # 通过 pyjnius 或 subprocess 启动 Intent
            try:
                from jnius import autoclass, cast
                Intent = autoclass("android.content.Intent")
                Uri = autoclass("android.net.Uri")
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                activity = PythonActivity.mActivity
                if not activity:
                    raise RuntimeError("PythonActivity 不可用")

                intent = Intent(intent_info.get("action", ""))
                package = intent_info.get("package", "")
                if package:
                    intent.setPackage(package)
                if page_key == "app_settings":
                    intent.setData(Uri.parse("package:" + activity.getPackageName()))
                activity.startActivity(intent)
                self._logger.info(f"跳转设置页面: {page_key}")
                return True
            except ImportError:
                self._logger.warning("pyjnius 未安装，尝试 am start 命令...")

                # 备用：通过 am start 命令
                import subprocess
                action = intent_info.get("action", "")
                cmd = ["am", "start", "-a", action]
                if "package" in intent_info:
                    cmd.extend(["-p", intent_info["package"]])
                if page_key == "app_settings":
                    from jnius import autoclass
                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    activity = PythonActivity.mActivity
                    if activity:
                        cmd.extend(["-d", f"package:{activity.getPackageName()}"])
                subprocess.run(cmd, timeout=3)
                return True

        except Exception as e:
            self._logger.error(f"跳转设置页面异常 '{page_key}': {e}")
            return False

    def open_all_settings_page(self) -> bool:
        """
        一键跳转全部权限入口（应用详情设置页）
        用户可在该页面集中授予所有权限

        :return: True=跳转成功
        """
        self._logger.info("一键跳转全部权限设置页")
        return self.open_settings_page("app_settings")

    def open_hyperos_battery_page(self) -> bool:
        """跳转澎湃OS 省电设置页"""
        if self._is_hyperos or SystemInfo.is_xiaomi_family():
            return self.open_settings_page("battery")
        else:
            self._logger.info("非澎湃OS/MIUI，跳转系统电池优化设置")
            return self.open_settings_page("battery")

    def open_hyperos_auto_start_page(self) -> bool:
        """跳转澎湃OS 自启动管理页"""
        if self._is_hyperos or SystemInfo.is_xiaomi_family():
            return self.open_settings_page("auto_start")
        else:
            self._logger.info("非澎湃OS/MIUI，不提供自启动引导")
            return False

    # ============================================================
    # 获取状态与引导
    # ============================================================

    def get_permission_summary(self) -> dict:
        """
        获取权限状态摘要（供 UI 展示）

        :return: {
            "stages": [...],
            "all_granted": bool,
            "missing_count": int,
            "degradations": dict,
            "system": dict,
            "rom": str,
            "guide_html": str,
        }
        """
        try:
            system_info = self.detect_system()
            perm_check = self.check_all_permissions()

            # 生成 ROM 引导 HTML
            guide_html = SystemInfo.get_guide_html(self._rom)

            return {
                "stages": perm_check.get("stages", {}),
                "all_granted": perm_check.get("all_granted", False),
                "missing_count": perm_check.get("missing_count", 0),
                "missing_keys": perm_check.get("missing_keys", []),
                "degradations": perm_check.get("degradations", {}),
                "system": system_info,
                "rom": self._rom,
                "is_hyperos": self._is_hyperos,
                "guide_html": guide_html,
            }
        except Exception as e:
            self._logger.error(f"获取权限摘要异常: {e}")
            return {"all_granted": False, "error": str(e)}

    def is_all_permission_granted(self) -> bool:
        """简易判断：所有必需权限是否已授予"""
        try:
            check = self.check_all_permissions()
            return check.get("all_granted", False)
        except Exception:
            return False

    # ============================================================
    # 资源清理
    # ============================================================

    def cleanup(self):
        """清理资源"""
        try:
            self._stage_callbacks.clear()
            self._permission_cache.clear()
            self._logger.info("权限管理器资源已清理")
        except Exception as e:
            self._logger.error(f"权限管理器清理异常: {e}")


# ============================================================
# 单例快捷访问
# ============================================================

_instance = None
_instance_lock = threading.Lock()


def get_permission_manager() -> PermissionManager:
    """
    获取权限管理器单例
    :return: PermissionManager 实例
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = PermissionManager()
    return _instance


# ============================================================
# 对外便捷接口（供 main.py / UI 层调用）
# ============================================================

def init_permissions() -> dict:
    """
    初始化权限系统（程序入口调用）

    检测系统、检查权限、构建摘要

    :return: 权限状态摘要字典
    """
    try:
        mgr = get_permission_manager()
        summary = mgr.get_permission_summary()
        return summary
    except Exception as e:
        LogManager.get_logger("app").error(f"初始化权限系统异常: {e}")
        return {"all_granted": False, "error": str(e)}


def start_permission_flow(
    on_stage_callback: Callable[[str, dict], None] = None,
    skip_settings: bool = False,
):
    """
    启动分步权限申请流程（供 UI 层调用）

    :param on_stage_callback: 阶段回调(stage, result)
    :param skip_settings: True=仅静默检测不跳转系统设置
    """
    try:
        mgr = get_permission_manager()
        mgr.start_permission_flow(on_stage_callback, skip_settings=skip_settings)
    except Exception as e:
        LogManager.get_logger("app").error(f"启动权限流程异常: {e}")


def is_first_launch() -> bool:
    """
    判断是否为首次启动（权限流程是否已完成）

    首次启动：需要完整权限申请流程（含跳转系统设置）
    非首次启动：仅静默检测，不跳转设置页

    :return: True=首次启动, False=已完成过权限流程
    """
    try:
        from modules.utils import ConfigManager
        config = ConfigManager()
        return not config.get("permission_flow_completed", False)
    except Exception:
        return True  # 配置读取失败，视为首次启动


def mark_permission_flow_completed() -> bool:
    """
    标记权限申请流程已完成（后续启动不再跳转系统设置）

    :return: True=标记成功
    """
    try:
        from modules.utils import ConfigManager
        config = ConfigManager()
        config.set("permission_flow_completed", True)  # set() 内部已调用 _save()
        LogManager.get_logger("app").info("权限申请流程已完成标记，后续启动不再跳转系统设置")
        return True
    except Exception as e:
        LogManager.get_logger("app").error(f"标记权限流程完成失败: {e}")
        return False


def get_permission_status_ui() -> dict:
    """
    UI 层获取权限状态
    :return: 权限摘要字典
    """
    try:
        mgr = get_permission_manager()
        return mgr.get_permission_summary()
    except Exception as e:
        LogManager.get_logger("app").error(f"UI 获取权限状态异常: {e}")
        return {"all_granted": False, "error": str(e)}


def open_settings_page_ui(page_key: str) -> bool:
    """
    UI 层跳转系统设置页面

    :param page_key: 页面键名
    :return: True=跳转成功
    """
    try:
        mgr = get_permission_manager()
        return mgr.open_settings_page(page_key)
    except Exception as e:
        LogManager.get_logger("app").error(f"UI 跳转设置页异常: {e}")
        return False


def open_all_settings_ui() -> bool:
    """
    UI 层一键跳转全部权限入口
    :return: True=跳转成功
    """
    try:
        mgr = get_permission_manager()
        return mgr.open_all_settings_page()
    except Exception as e:
        LogManager.get_logger("app").error(f"UI 一键跳转设置异常: {e}")
        return False


def set_manual_region_ui(region: str):
    """
    UI 层设置手动地区（定位降级时使用）
    :param region: 地区名称
    """
    try:
        mgr = get_permission_manager()
        mgr._degradation.set_manual_region(region)
    except Exception as e:
        LogManager.get_logger("app").error(f"UI 设置手动地区异常: {e}")


# ============================================================
# 模块 → 必需权限 映射表
# ============================================================
# 每个模块加载/初始化时，检查其依赖的权限是否已授予；
# 缺失则立即申请，避免模块因权限不足而功能异常或卡住。

MODULE_REQUIRED_PERMISSIONS = {
    "float_win": ["float_window", "notifications", "battery"],
    "capture":    ["accessibility", "storage"],
    "order_filter":   [],
    "statistics":     [],
    "material_update":["storage"],
    "app_list":       [],
    "activate_code":  [],
    "network":        [],
    "permission":     [],
}

# 必须跳转系统设置页的权限（无法通过弹窗申请的"特殊权限"）
# 这些权限申请后用户需手动操作，加载流程不应等待
SPECIAL_PERMISSIONS = {"float_window", "accessibility", "battery", "screen_record", "storage"}


def get_module_permissions(module_name: str) -> list:
    """
    获取模块加载所需的权限列表

    :param module_name: 模块名称（如 "float_win", "capture"）
    :return: 权限键名列表
    """
    return MODULE_REQUIRED_PERMISSIONS.get(module_name, [])


def request_module_permissions(
    module_name: str,
    on_progress: Callable[[str, str], None] = None
) -> dict:
    """
    检查模块必需权限，缺失则立即申请
    供 main.py 加载模块时调用，确保权限在模块使用前就绪。

    返回值：
      {
        "granted": [...],     # 已授予的权限
        "missing": [...],     # 缺失的权限（已触发申请）
        "special": [...],     # 需要跳转系统设置的特殊权限
        "all_ok": bool,       # 是否全部就绪
      }

    :param module_name: 模块名称
    :param on_progress: 进度回调(perm_key, status)
    :return: 权限状态字典
    """
    required = get_module_permissions(module_name)
    if not required:
        return {"granted": [], "missing": [], "special": [], "all_ok": True}

    try:
        mgr = get_permission_manager()
        granted = []
        missing = []
        special = []

        for perm_key in required:
            # 检查当前状态
            state = mgr._check_single_permission(perm_key)

            if state == PermissionState.GRANTED:
                granted.append(perm_key)
                if on_progress:
                    on_progress(perm_key, "granted")
            else:
                missing.append(perm_key)
                if perm_key in SPECIAL_PERMISSIONS:
                    special.append(perm_key)

                # 立即申请权限
                if on_progress:
                    on_progress(perm_key, "requesting")
                mgr._request_permission(perm_key)

        result = {
            "granted": granted,
            "missing": missing,
            "special": special,
            "all_ok": len(missing) == 0,
        }

        if missing:
            LogManager.get_logger("app").info(
                f"[{module_name}] 缺失权限: {missing}"
                + (f" (特殊权限需手动开启: {special})" if special else "")
            )

        return result

    except Exception as e:
        LogManager.get_logger("app").error(
            f"[{module_name}] 权限检查异常: {e}"
        )
        return {"granted": [], "missing": [], "special": [], "all_ok": False}