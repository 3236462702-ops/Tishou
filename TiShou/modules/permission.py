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
        "name": "存储权限",
        "android_permission": "android.permission.READ_EXTERNAL_STORAGE",
        "android_permission2": "android.permission.WRITE_EXTERNAL_STORAGE",
        "description": "用于读取配置、保存日志和缓存数据",
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
          - 普通权限：使用 android.permissions 或 Context.checkSelfPermission()

        :param perm_key: 权限键名
        :return: PermissionState
        """
        try:
            # ---- 特殊权限：悬浮窗（SYSTEM_ALERT_WINDOW） ----
            if perm_key == "float_window":
                try:
                    from jnius import autoclass
                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    Settings = autoclass("android.provider.Settings")

                    activity = PythonActivity.mActivity
                    if not activity:
                        return PermissionState.UNKNOWN

                    # Settings.canDrawOverlays() 是 API 23+ 唯一正确判断方式
                    # checkSelfPermission() 对 SYSTEM_ALERT_WINDOW 无效
                    can_draw = Settings.canDrawOverlays(activity)
                    return PermissionState.GRANTED if can_draw else PermissionState.DENIED
                except Exception as e:
                    self._logger.warning(f"悬浮窗权限检查异常: {e}")
                    # 回退：传统方式（API < 23 有效）
                    try:
                        from jnius import autoclass
                        PythonActivity = autoclass("org.kivy.android.PythonActivity")
                        PackageManager = autoclass("android.content.pm.PackageManager")
                        activity = PythonActivity.mActivity
                        if activity:
                            result = activity.checkSelfPermission(
                                "android.permission.SYSTEM_ALERT_WINDOW"
                            )
                            if result == PackageManager.PERMISSION_GRANTED:
                                return PermissionState.GRANTED
                    except Exception:
                        pass
                    return PermissionState.DENIED

            # ---- 普通权限 ----
            try:
                from android.permissions import check_permission
                android_perm = self._get_android_perm_name(perm_key)
                if not android_perm:
                    return PermissionState.GRANTED

                if check_permission(android_perm):
                    return PermissionState.GRANTED
                else:
                    return PermissionState.DENIED
            except ImportError:
                # 回退：通过 pyjnius 桥接 Android Context.checkSelfPermission
                try:
                    from jnius import autoclass
                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    Context = autoclass("android.content.Context")
                    PackageManager = autoclass("android.content.pm.PackageManager")

                    activity = PythonActivity.mActivity
                    if not activity:
                        return PermissionState.UNKNOWN

                    android_perm = self._get_android_perm_name(perm_key)
                    if not android_perm:
                        return PermissionState.GRANTED

                    result = activity.checkSelfPermission(android_perm)
                    if result == PackageManager.PERMISSION_GRANTED:
                        return PermissionState.GRANTED
                    else:
                        return PermissionState.DENIED
                except Exception:
                    self._logger.debug("无法通过安卓 API 检查权限（非安卓环境）")
                    return PermissionState.GRANTED  # 非安卓环境模拟通过

        except Exception as e:
            self._logger.warning(f"安卓 API 权限检查失败: {e}")
            return PermissionState.UNKNOWN

    def _get_android_perm_name(self, perm_key: str) -> str:
        """根据权限键名获取安卓权限字符串"""
        mapping = {
            "storage": "android.permission.READ_EXTERNAL_STORAGE",
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

    def start_permission_flow(self, on_stage_change: Callable[[str, dict], None] = None):
        """
        启动分步权限申请流程

        特点：
          - 不批量弹窗，每个阶段单独申请
          - 前一个阶段完成后自动进入下一个
          - 可注册回调监听阶段变更

        :param on_stage_change: 回调函数(stage_enum_value, result_dict)
        """
        try:
            if on_stage_change:
                self._stage_callbacks.append(on_stage_change)

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
                    # 申请权限
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

        注意：
          普通权限 → request_permissions() 弹窗申请
          特殊权限（float_window / SYSTEM_ALERT_WINDOW）→ Intent 跳转系统设置页
        """
        try:
            if not is_android():
                self._logger.debug(f"[模拟] 申请权限: {perm_key} → 已同意")
                self._permission_cache[perm_key] = PermissionState.GRANTED
                return True

            android_perm = self._get_android_perm_name(perm_key)
            if not android_perm:
                return True

            # ============================================================
            # 特殊权限：悬浮窗（SYSTEM_ALERT_WINDOW）
            # 不能用普通权限 API 申请，需 Intent 跳转系统设置页手动开启
            # ============================================================
            if perm_key == "float_window":
                try:
                    from jnius import autoclass
                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    Intent = autoclass("android.content.Intent")
                    Uri = autoclass("android.net.Uri")

                    activity = PythonActivity.mActivity
                    if not activity:
                        self._logger.warning("无法获取 Activity 实例，无法跳转悬浮窗设置")
                        return False

                    # 构建 Intent：跳转到悬浮窗管理页（API 23+）
                    # action: android.settings.action.MANAGE_OVERLAY_PERMISSION
                    # data: package:<package_name>
                    intent = Intent(
                        "android.settings.action.MANAGE_OVERLAY_PERMISSION",
                        Uri.parse("package:" + activity.getPackageName())
                    )
                    intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    activity.startActivity(intent)
                    self._logger.info("已跳转悬浮窗权限设置页，请在系统中手动开启")
                    return True
                except Exception as e:
                    self._logger.error(f"跳转悬浮窗设置页失败: {e}")
                    # 兜底：尝试用通用应用设置页
                    try:
                        from jnius import autoclass
                        PythonActivity = autoclass("org.kivy.android.PythonActivity")
                        Intent = autoclass("android.content.Intent")

                        activity = PythonActivity.mActivity
                        if activity:
                            intent = Intent("android.settings.APPLICATION_DETAILS_SETTINGS")
                            Uri = autoclass("android.net.Uri")
                            intent.setData(Uri.parse("package:" + activity.getPackageName()))
                            intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            activity.startActivity(intent)
                            self._logger.info("已跳转应用设置页，请手动开启悬浮窗权限")
                            return True
                    except Exception:
                        pass
                    return False

            # ============================================================
            # 普通权限：使用 android.permissions.request_permissions()
            # ============================================================
            try:
                from android.permissions import request_permissions, Permission
                request_permissions([Permission(android_perm)])
                self._logger.info(f"权限申请已发送: {perm_key}")
                return True
            except ImportError:
                self._logger.warning("android.permissions 模块不可用，无法申请权限")
                return False

        except Exception as e:
            self._logger.error(f"申请权限异常 '{perm_key}': {e}")
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
    on_stage_callback: Callable[[str, dict], None] = None
):
    """
    启动分步权限申请流程（供 UI 层调用）

    :param on_stage_callback: 阶段回调(stage, result)
    """
    try:
        mgr = get_permission_manager()
        mgr.start_permission_flow(on_stage_callback)
    except Exception as e:
        LogManager.get_logger("app").error(f"启动权限流程异常: {e}")


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