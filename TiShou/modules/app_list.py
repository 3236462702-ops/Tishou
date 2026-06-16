# -*- coding: utf-8 -*-
"""
应用列表管理模块（双模式：安卓真机 + 桌面开发）
========================================

安卓真机：通过 Android pm 命令读取已安装应用
桌面开发：Mock 数据，不依赖 Android 环境

功能：
  1. 读取设备已安装应用列表，默认过滤系统应用
  2. 搜索框按应用名/包名筛选
  3. 多选、全选、反选、清空
  4. 勾选状态持久化，重启自动还原
  5. 读取异常弹窗提示，不影响其他功能

遵守全局约束：
  - 纯 Python，免注册免费公共接口
  - 全异常捕获，日志记录
  - 不下载第三方独立资源包
"""

import sys
import os
import re
import subprocess
import threading
import time
from typing import Optional, Callable, List, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.utils import (
    LogManager, ConfigManager, ExceptionUtil,
    is_android, safe_int, safe_bool, safe_str,
    PROJECT_DIR,
)


# ============================================================
# 常量
# ============================================================

# 系统应用包名前缀（用于启发式判断系统应用）
SYSTEM_PACKAGE_PREFIXES = (
    "android.",
    "com.android.",
    "com.google.android.",
    "com.qualcomm.",
    "com.mediatek.",
    "com.samsung.",
    "com.xiaomi.",
    "com.miui.",
    "com.huawei.",
    "com.vivo.",
    "com.oppo.",
    "com.oneplus.",
    "com.realme.",
    "com.asus.",
    "com.lenovo.",
    "com.sony.",
    "com.lge.",
    "com.htc.",
    "com.zte.",
    "com.meizu.",
    "com.nubia.",
    "com.android.phone",
    "com.android.systemui",
    "com.android.settings",
    "com.android.launcher",
    "com.android.providers",
    "com.android.server",
    "com.android.calendar",
    "com.android.contacts",
    "com.android.deskclock",
    "com.android.email",
    "com.android.mms",
    "com.android.music",
    "com.android.browser",
    "com.android.calculator2",
    "com.android.camera2",
    "com.android.dialer",
    "com.android.documentsui",
    "com.android.dreams",
    "com.android.egg",
    "com.android.fmradio",
    "com.android.gallery",
    "com.android.hotwordenrollment",
    "com.android.inputdevices",
    "com.android.inputmethod",
    "com.android.keyguard",
    "com.android.mediacenter",
    "com.android.midrive",
    "com.android.mipush",
    "com.android.packageinstaller",
    "com.android.phone",
    "com.android.printspooler",
    "com.android.safetycenter",
    "com.android.soundrecorder",
    "com.android.stk",
    "com.android.thememanager",
    "com.android.vending",
    "com.android.wallpaper",
    "com.android.wifi",
)

# 已知系统应用包名集合（精准匹配）
KNOWN_SYSTEM_PACKAGES = {
    "com.miui.securitycenter",
    "com.miui.securityadd",
    "com.miui.cleanmaster",
    "com.miui.powerkeeper",
    "com.miui.notes",
    "com.miui.gallery",
    "com.miui.video",
    "com.miui.player",
    "com.miui.weather2",
    "com.miui.screensearch",
    "com.miui.voiceassist",
    "com.miui.compass",
    "com.miui.miservice",
    "com.miui.micloudsync",
    "com.miui.backup",
    "com.miui.yellowpage",
    "com.miui.bugreport",
    "com.miui.virtualsim",
    "com.miui.notification",
    "com.miui.system",
    "com.miui.tsmclient",
    "com.miui.wmsvc",
    "com.miui.rom",
    "com.miui.core",
    "com.miui.hybrid",
    "com.miui.systemui",
    "com.miui.securitycore",
    "com.miui.analytics",
    "com.miui.freeform",
    "com.miui.daemon",
    "com.miui.contentcatcher",
    "com.miui.cit",
    "com.miui.wallpaper",
    "com.miui.misound",
    "com.miui.calculator",
    "com.miui.calendar",
    "com.miui.voiceassist",
    "com.miui.screenshot",
    "com.miui.screenrecorder",
    "com.miui.monitor",
    "com.miui.personalassistant",
    "com.miui.touchassistant",
    "com.miui.aod",
    "com.miui.dandelion",
    "com.miui.voicetrigger",
    "com.miui.translation",
    "com.miui.cloudservice",
    "com.miui.cloudbackup",
    "com.miui.finddevice",
}

# 配置键
CONFIG_KEY_SELECTED = "app_list.selected_packages"
CONFIG_KEY_SHOW_SYSTEM = "app_list.show_system_apps"

# 默认桌面环境 Mock 应用列表
MOCK_APPS = [
    {"package": "com.taobao.tb", "name": "手机淘宝", "system": False, "icon": ""},
    {"package": "com.taobao.trip", "name": "飞猪旅行", "system": False, "icon": ""},
    {"package": "com.tencent.mm", "name": "微信", "system": False, "icon": ""},
    {"package": "com.tencent.mobileqq", "name": "QQ", "system": False, "icon": ""},
    {"package": "com.tencent.qqmusic", "name": "QQ音乐", "system": False, "icon": ""},
    {"package": "com.tencent.qqlive", "name": "腾讯视频", "system": False, "icon": ""},
    {"package": "com.tencent.news", "name": "腾讯新闻", "system": False, "icon": ""},
    {"package": "com.sina.weibo", "name": "微博", "system": False, "icon": ""},
    {"package": "com.baidu.searchbox", "name": "百度", "system": False, "icon": ""},
    {"package": "com.baidu.BaiduMap", "name": "百度地图", "system": False, "icon": ""},
    {"package": "com.baidu.netdisk", "name": "百度网盘", "system": False, "icon": ""},
    {"package": "com.alibaba.android.rimet", "name": "钉钉", "system": False, "icon": ""},
    {"package": "com.alibaba.wireless", "name": "阿里巴巴", "system": False, "icon": ""},
    {"package": "com.jingdong.app.mall", "name": "京东", "system": False, "icon": ""},
    {"package": "com.pinduoduo", "name": "拼多多", "system": False, "icon": ""},
    {"package": "com.douyin", "name": "抖音", "system": False, "icon": ""},
    {"package": "com.ss.android.ugc.aweme", "name": "抖音", "system": False, "icon": ""},
    {"package": "com.kuaishou", "name": "快手", "system": False, "icon": ""},
    {"package": "com.ximalaya.ting.android", "name": "喜马拉雅", "system": False, "icon": ""},
    {"package": "com.meituan", "name": "美团", "system": False, "icon": ""},
    {"package": "com.dianping.v1", "name": "大众点评", "system": False, "icon": ""},
    {"package": "com.ctrip.tripplan", "name": "携程旅行", "system": False, "icon": ""},
    {"package": "com.didi.soda", "name": "滴滴", "system": False, "icon": ""},
    {"package": "com.sf.express", "name": "顺丰速运", "system": False, "icon": ""},
    {"package": "com.achievo.vipshop", "name": "唯品会", "system": False, "icon": ""},
    {"package": "com.sunii.android", "name": "苏宁易购", "system": False, "icon": ""},
    {"package": "com.yhd", "name": "1号店", "system": False, "icon": ""},
    {"package": "com.wandoujia.phoenix2", "name": "豌豆荚", "system": False, "icon": ""},
    {"package": "com.qihoo360.mobilesafe", "name": "360手机卫士", "system": False, "icon": ""},
    {"package": "com.ijinshan.mobguard", "name": "金山手机卫士", "system": False, "icon": ""},
    {"package": "com.netease.cloudmusic", "name": "网易云音乐", "system": False, "icon": ""},
    {"package": "com.netease.news", "name": "网易新闻", "system": False, "icon": ""},
    {"package": "com.netease.mail", "name": "网易邮箱", "system": False, "icon": ""},
    {"package": "com.UCMobile", "name": "UC浏览器", "system": False, "icon": ""},
    {"package": "com.zhihu.android", "name": "知乎", "system": False, "icon": ""},
    {"package": "com.bilibili.app", "name": "哔哩哔哩", "system": False, "icon": ""},
    {"package": "com.autonavi.minimap", "name": "高德地图", "system": False, "icon": ""},
    {"package": "com.xunmeng.pinduoduo", "name": "拼多多", "system": False, "icon": ""},
    {"package": "com.eg.android.AlipayGphone", "name": "支付宝", "system": False, "icon": ""},
    {"package": "com.xiaomi.shop", "name": "小米商城", "system": False, "icon": ""},
    {"package": "com.xiaomi.market", "name": "小米应用商店", "system": False, "icon": ""},
    {"package": "com.miui.notes", "name": "小米便签", "system": True, "icon": ""},
    {"package": "com.miui.gallery", "name": "小米相册", "system": True, "icon": ""},
    {"package": "com.android.settings", "name": "设置", "system": True, "icon": ""},
    {"package": "com.android.systemui", "name": "系统界面", "system": True, "icon": ""},
    {"package": "com.android.chrome", "name": "Chrome浏览器", "system": True, "icon": ""},
    {"package": "com.google.android.gms", "name": "Google Play服务", "system": True, "icon": ""},
    {"package": "com.google.android.gsf", "name": "Google服务框架", "system": True, "icon": ""},
]


# ============================================================
# 安卓设备应用读取器
# ============================================================

class AndroidAppReader:
    """
    安卓设备应用读取器
    ================
    通过 Android pm 命令读取已安装应用列表。
    桌面环境使用 Mock 数据。
    """

    def __init__(self):
        """初始化应用读取器"""
        self._logger = LogManager.get_logger("app")
        self._cache: List[dict] = []
        self._cache_time: float = 0.0
        self._cache_lock = threading.Lock()
        self._cache_ttl = 30.0  # 缓存有效期（秒）

    @ExceptionUtil.safe_call(default_return=[], log_level="error")
    def get_installed_apps(self, force_refresh: bool = False) -> List[dict]:
        """
        获取设备已安装应用列表

        :param force_refresh: 是否强制刷新（忽略缓存）
        :return: 应用列表 [{"package": str, "name": str, "system": bool}, ...]
        """
        # 检查缓存
        now = time.time()
        with self._cache_lock:
            if not force_refresh and self._cache and (now - self._cache_time) < self._cache_ttl:
                return list(self._cache)

        # 安卓真机 vs 桌面环境
        if is_android():
            apps = self._read_from_device()
        else:
            apps = self._read_mock()

        # 更新缓存
        with self._cache_lock:
            self._cache = list(apps)
            self._cache_time = time.time()

        self._logger.debug(f"读取应用列表: {len(apps)} 个应用")
        return list(apps)

    def _read_from_device(self) -> List[dict]:
        """
        通过 Android pm 命令读取设备应用

        :return: 应用列表
        """
        apps = []
        try:
            # ---- 第1步：获取所有应用的包名和APK路径 ----
            # pm list packages -f 输出格式：
            #   package:/data/app/com.example.app-xxx/base.apk=com.example.app
            output = subprocess.check_output(
                ["pm", "list", "packages", "-f"],
                timeout=10,
                stderr=subprocess.DEVNULL,
            ).decode("utf-8", errors="replace")

            lines = output.strip().split("\n")
            package_paths = {}  # {package_name: apk_path}

            for line in lines:
                line = line.strip()
                if not line or not line.startswith("package:"):
                    continue

                # 解析 "package:/path/to/apk=com.example.app"
                content = line[8:]  # 去掉 "package:"
                if "=" in content:
                    apk_path, package_name = content.rsplit("=", 1)
                    package_name = package_name.strip()
                    apk_path = apk_path.strip()
                    if package_name:
                        package_paths[package_name] = apk_path

            # ---- 第2步：获取系统/第三方标记 ----
            # pm list packages -s → 系统应用
            # pm list packages -3 → 第三方应用
            system_packages = set()
            try:
                sys_output = subprocess.check_output(
                    ["pm", "list", "packages", "-s"],
                    timeout=5, stderr=subprocess.DEVNULL,
                ).decode("utf-8", errors="replace")
                for line in sys_output.strip().split("\n"):
                    line = line.strip()
                    if line.startswith("package:"):
                        pkg = line[8:].strip()
                        if pkg:
                            system_packages.add(pkg)
            except Exception:
                pass  # 获取系统应用标记失败，改用启发式判断

            # ---- 第3步：获取应用名称（label） ----
            # 使用 aapt dump badging 或 cmd package resolve-activity
            app_labels = {}
            try:
                # 方法1：使用 cmd package list packages 获取更多信息
                # （Android 11+ 支持 --show-versioncode）
                pass
            except Exception:
                pass

            # 尝试使用 aapt 获取应用名称（仅读取前几行加速）
            for pkg, apk_path in package_paths.items():
                app_name = self._get_app_label_via_aapt(apk_path)
                if not app_name:
                    app_name = self._get_app_label_via_dumpsys(pkg)
                if not app_name:
                    app_name = self._package_to_friendly_name(pkg)
                app_labels[pkg] = app_name

            # ---- 第4步：组装结果 ----
            for package_name, apk_path in package_paths.items():
                is_system = (
                    package_name in system_packages
                    or self._is_system_package(package_name)
                )
                apps.append({
                    "package": package_name,
                    "name": app_labels.get(package_name, self._package_to_friendly_name(package_name)),
                    "system": is_system,
                    "apk_path": apk_path,
                })

            # 按名称排序
            apps.sort(key=lambda x: x["name"].lower())

        except subprocess.TimeoutExpired:
            self._logger.error("pm list packages 超时")
        except FileNotFoundError:
            self._logger.error("pm 命令不可用（非安卓环境）")
        except Exception as e:
            self._logger.error(f"读取设备应用异常: {e}")

        return apps

    def _get_app_label_via_aapt(self, apk_path: str) -> str:
        """
        使用 aapt 从 APK 中提取应用名称

        :param apk_path: APK 文件路径
        :return: 应用名称，失败返回空字符串
        """
        try:
            if not apk_path or not os.path.exists(apk_path):
                return ""

            # 使用 aapt dump badging 快速获取应用标签
            # 只取前几行，因为 application-label 通常在开头附近
            result = subprocess.run(
                ["aapt", "dump", "badging", apk_path],
                capture_output=True, timeout=10, text=True,
            )

            if result.returncode != 0:
                return ""

            # 匹配 application-label: '应用名称'
            for line in result.stdout.split("\n"):
                line = line.strip()
                if line.startswith("application-label:"):
                    # 提取引号内的内容
                    match = re.search(r"'(.*?)'", line)
                    if match:
                        return match.group(1)
                    # 也可能是 application-label-zh-CN: '中文名称'
                if line.startswith("application-label-zh"):
                    match = re.search(r"'(.*?)'", line)
                    if match:
                        return match.group(1)

            return ""

        except (FileNotFoundError, subprocess.TimeoutExpired):
            return ""
        except Exception:
            return ""

    def _get_app_label_via_dumpsys(self, package_name: str) -> str:
        """
        使用 dumpsys package 获取应用名称

        :param package_name: 包名
        :return: 应用名称，失败返回空字符串
        """
        try:
            result = subprocess.run(
                ["dumpsys", "package", package_name],
                capture_output=True, timeout=5, text=True,
            )

            if result.returncode != 0:
                return ""

            # 匹配 application-label 行
            for line in result.stdout.split("\n"):
                line = line.strip()
                if "application-label=" in line:
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        return parts[1].strip().strip("'\"")
                # 也可能是 application-label-zh_CN
                if "application-label-zh" in line:
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        return parts[1].strip().strip("'\"")

            return ""

        except (subprocess.TimeoutExpired, Exception):
            return ""

    def _is_system_package(self, package_name: str) -> bool:
        """
        启发式判断是否为系统应用

        :param package_name: 包名
        :return: True=系统应用
        """
        # 精准匹配已知系统包名
        if package_name in KNOWN_SYSTEM_PACKAGES:
            return True

        # 前缀匹配
        for prefix in SYSTEM_PACKAGE_PREFIXES:
            if package_name.startswith(prefix):
                return True

        return False

    @staticmethod
    def _package_to_friendly_name(package_name: str) -> str:
        """
        从包名推导可读的应用名称

        :param package_name: 包名，如 "com.tencent.mm"
        :return: 友好名称，如 "Tencent Mm"
        """
        try:
            # 取最后一段
            parts = package_name.split(".")
            last = parts[-1] if parts else package_name

            # 驼峰转空格
            friendly = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", last)
            friendly = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", friendly)

            # 首字母大写
            friendly = friendly.title().strip()

            # 如果为空或过长，返回包名最后一段
            if not friendly or len(friendly) > 30:
                return last

            return friendly
        except Exception:
            return package_name

    def _read_mock(self) -> List[dict]:
        """桌面环境：返回 Mock 应用列表"""
        return [dict(app) for app in MOCK_APPS]

    def clear_cache(self):
        """清除缓存（强制下次重新读取）"""
        with self._cache_lock:
            self._cache = []
            self._cache_time = 0.0
        self._logger.debug("应用列表缓存已清除")

    def refresh(self) -> List[dict]:
        """
        强制刷新应用列表（清除缓存 + 重新读取）
        :return: 最新应用列表
        """
        return self.get_installed_apps(force_refresh=True)


# ============================================================
# 应用列表管理器（含选择状态管理）
# ============================================================

class AppListManager:
    """
    应用列表管理器
    ============
    整合应用读取、搜索筛选、多选管理、状态持久化。

    功能：
      - 获取设备应用列表，默认过滤系统应用
      - 搜索框按应用名/包名实时筛选
      - 多选、全选、反选、清空
      - 选择状态持久化（config.json）
      - 读取异常弹窗提醒
    """

    def __init__(self):
        """初始化应用列表管理器"""
        self._logger = LogManager.get_logger("app")
        self._config = ConfigManager()
        self._reader = AndroidAppReader()

        # ---- 应用列表 ----
        self._all_apps: List[dict] = []          # 全量应用
        self._filtered_apps: List[dict] = []     # 当前筛选后的应用
        self._displayed_apps: List[dict] = []    # 显示给用户的应用（过滤系统后）

        # ---- 选择状态 ----
        self._selected: Dict[str, bool] = {}     # {package: True/False}
        self._search_query: str = ""
        self._show_system: bool = False

        # ---- 加载状态 ----
        self._loaded = False
        self._last_error: str = ""
        self._load_lock = threading.Lock()

        # ---- 回调 ----
        self._on_apps_changed: Optional[Callable] = None  # 列表/选择变更回调
        self._on_error: Optional[Callable[[str], None]] = None  # 错误通知回调

        # ---- 加载状态（后台加载，不阻塞） ----
        self._background_loading = False
        self._load_thread: Optional[threading.Thread] = None

    # ============================================================
    # 初始化与加载
    # ============================================================

    def load_apps(self, background: bool = True) -> bool:
        """
        加载应用列表

        :param background: 是否后台加载（不阻塞主线程）
        :return: True=加载成功或已启动后台加载
        """
        if background and not self._loaded:
            if not self._background_loading:
                self._background_loading = True
                self._load_thread = threading.Thread(
                    target=self._do_load, daemon=True
                )
                self._load_thread.start()
                self._logger.debug("后台加载应用列表已启动")
            return True

        return self._do_load()

    def _do_load(self) -> bool:
        """
        执行应用列表加载（内部方法）

        :return: True=成功
        """
        with self._load_lock:
            try:
                # 读取设备应用
                apps = self._reader.get_installed_apps()
                if not apps:
                    self._logger.warning("应用列表为空")
                    self._last_error = "未读取到任何应用"
                    self._notify_error("未读取到任何应用，请检查设备")
                    self._loaded = True
                    self._background_loading = False
                    return False

                self._all_apps = apps

                # 读取持久化的选择状态
                self._load_selected_state()

                # 恢复显示系统应用开关
                self._show_system = safe_bool(
                    self._config.get(CONFIG_KEY_SHOW_SYSTEM), False
                )

                # 应用筛选
                self._apply_filters()

                self._loaded = True
                self._last_error = ""
                self._background_loading = False

                self._logger.info(
                    f"应用列表加载完成: {len(apps)} 个应用, "
                    f"已选择 {self._get_selected_count()} 个"
                )

                # 通知变更
                self._notify_changed()
                return True

            except Exception as e:
                self._last_error = str(e)
                self._logger.error(f"加载应用列表异常: {e}")
                self._notify_error(f"读取应用列表失败: {e}")
                self._loaded = True
                self._background_loading = False
                return False

    @property
    def is_loaded(self) -> bool:
        """是否已加载完成"""
        return self._loaded

    @property
    def is_loading(self) -> bool:
        """是否正在后台加载"""
        return self._background_loading

    @property
    def last_error(self) -> str:
        """获取最后一次错误信息"""
        return self._last_error

    # ============================================================
    # 筛选
    # ============================================================

    def set_show_system(self, show: bool):
        """
        设置是否显示系统应用

        :param show: True=显示系统应用, False=隐藏
        """
        try:
            self._show_system = show
            self._config.set(CONFIG_KEY_SHOW_SYSTEM, show)
            self._apply_filters()
            self._notify_changed()
            self._logger.debug(f"系统应用显示: {'开' if show else '关'}")
        except Exception as e:
            self._logger.error(f"设置系统应用显示异常: {e}")

    def get_show_system(self) -> bool:
        """获取是否显示系统应用"""
        return self._show_system

    def search(self, query: str):
        """
        按应用名/包名搜索筛选

        :param query: 搜索关键词（空字符串=显示全部）
        """
        try:
            self._search_query = query.strip()
            self._apply_filters()
            self._notify_changed()
        except Exception as e:
            self._logger.error(f"搜索异常: {e}")

    def get_search_query(self) -> str:
        """获取当前搜索关键词"""
        return self._search_query

    def _apply_filters(self):
        """应用所有筛选条件（系统应用过滤 + 搜索）"""
        # 第1层：系统应用过滤
        if self._show_system:
            self._displayed_apps = list(self._all_apps)
        else:
            self._displayed_apps = [
                app for app in self._all_apps if not app["system"]
            ]

        # 第2层：搜索过滤
        if self._search_query:
            query = self._search_query.lower()
            self._filtered_apps = [
                app for app in self._displayed_apps
                if query in app["name"].lower()
                or query in app["package"].lower()
            ]
        else:
            self._filtered_apps = list(self._displayed_apps)

    # ============================================================
    # 获取应用列表
    # ============================================================

    def get_all_apps(self) -> List[dict]:
        """
        获取全量应用列表（不过滤系统应用）

        :return: 应用列表
        """
        return list(self._all_apps)

    def get_displayed_apps(self) -> List[dict]:
        """
        获取当前筛选后的应用列表

        :return: 应用列表 [{"package": str, "name": str, "system": bool}, ...]
        """
        if not self._loaded:
            self.load_apps(background=False)
        return list(self._filtered_apps)

    def get_displayed_count(self) -> int:
        """获取当前显示的应用数量"""
        return len(self._filtered_apps)

    def get_total_count(self) -> int:
        """获取总应用数量"""
        return len(self._all_apps)

    def _get_selected_count(self) -> int:
        """获取已选择的应用数量"""
        return sum(1 for v in self._selected.values() if v)

    # ============================================================
    # 选择管理（仅对当前筛选/显示列表生效）
    # ============================================================

    def is_selected(self, package: str) -> bool:
        """
        检查应用是否被选中

        :param package: 包名
        :return: True=已选中
        """
        return self._selected.get(package, False)

    def get_selected_packages(self) -> List[str]:
        """
        获取所有已选中的包名列表

        :return: 包名列表
        """
        return [pkg for pkg, sel in self._selected.items() if sel]

    def get_selected_apps(self) -> List[dict]:
        """
        获取所有已选中的应用详情（包含名称等）

        :return: 应用详情列表
        """
        selected_pkgs = set(self.get_selected_packages())
        return [
            app for app in self._all_apps
            if app["package"] in selected_pkgs
        ]

    def toggle_select(self, package: str) -> bool:
        """
        切换单个应用的选中状态

        :param package: 包名
        :return: 切换后的状态
        """
        try:
            current = self._selected.get(package, False)
            self._selected[package] = not current
            self._save_selected_state()
            self._notify_changed()
            return self._selected[package]
        except Exception as e:
            self._logger.error(f"切换选择异常: {e}")
            return False

    def select_all(self):
        """全选当前显示列表中的所有应用"""
        try:
            for app in self._filtered_apps:
                self._selected[app["package"]] = True
            self._save_selected_state()
            self._notify_changed()
            self._logger.debug(f"全选: {len(self._filtered_apps)} 个应用")
        except Exception as e:
            self._logger.error(f"全选异常: {e}")

    def deselect_all(self):
        """清空选择（取消选中所有应用）"""
        try:
            self._selected.clear()
            self._save_selected_state()
            self._notify_changed()
            self._logger.debug("已清空所有选择")
        except Exception as e:
            self._logger.error(f"清空选择异常: {e}")

    def invert_selection(self):
        """反选（翻转当前显示列表中所有应用的选中状态）"""
        try:
            for app in self._filtered_apps:
                pkg = app["package"]
                self._selected[pkg] = not self._selected.get(pkg, False)
            self._save_selected_state()
            self._notify_changed()
            self._logger.debug("已反选")
        except Exception as e:
            self._logger.error(f"反选异常: {e}")

    def select_packages(self, packages: List[str]):
        """
        批量选中指定包名

        :param packages: 包名列表
        """
        try:
            for pkg in packages:
                self._selected[pkg] = True
            self._save_selected_state()
            self._notify_changed()
        except Exception as e:
            self._logger.error(f"批量选中异常: {e}")

    # ============================================================
    # 状态持久化
    # ============================================================

    def _load_selected_state(self):
        """从配置加载持久化的选择状态"""
        try:
            saved = self._config.get(CONFIG_KEY_SELECTED, [])
            if isinstance(saved, list) and saved:
                self._selected = {pkg: True for pkg in saved}
                self._logger.debug(f"已恢复选择状态: {len(saved)} 个应用")
            else:
                self._selected = {}
        except Exception as e:
            self._logger.warning(f"恢复选择状态失败: {e}")
            self._selected = {}

    def _save_selected_state(self):
        """持久化当前选择状态到配置"""
        try:
            selected_list = self.get_selected_packages()
            self._config.set(CONFIG_KEY_SELECTED, selected_list)
        except Exception as e:
            self._logger.error(f"持久化选择状态异常: {e}")

    # ============================================================
    # 回调与通知
    # ============================================================

    def set_on_apps_changed(self, callback: Optional[Callable]):
        """
        设置应用列表/选择变更回调

        :param callback: 回调函数()
        """
        self._on_apps_changed = callback

    def set_on_error(self, callback: Optional[Callable[[str], None]]):
        """
        设置错误通知回调（供 UI 弹窗使用）

        :param callback: 回调函数(error_message)
        """
        self._on_error = callback

    def _notify_changed(self):
        """通知应用列表或选择状态变更"""
        try:
            if self._on_apps_changed:
                self._on_apps_changed()
        except Exception:
            pass

    def _notify_error(self, message: str):
        """
        通知错误（供 UI 弹窗）

        :param message: 错误消息
        """
        try:
            if self._on_error:
                self._on_error(message)
        except Exception:
            pass

    # ============================================================
    # 统计
    # ============================================================

    def get_stats(self) -> dict:
        """
        获取应用列表统计信息

        :return: {
            "total": int,           # 总应用数
            "displayed": int,       # 当前显示数
            "selected": int,        # 已选择数
            "system_count": int,    # 系统应用数
            "third_party_count": int, # 第三方应用数
            "show_system": bool,    # 是否显示系统应用
            "loaded": bool,         # 是否已加载
            "loading": bool,        # 是否正在加载
        }
        """
        system_count = sum(1 for app in self._all_apps if app["system"])
        return {
            "total": len(self._all_apps),
            "displayed": len(self._filtered_apps),
            "selected": self._get_selected_count(),
            "system_count": system_count,
            "third_party_count": len(self._all_apps) - system_count,
            "show_system": self._show_system,
            "loaded": self._loaded,
            "loading": self._background_loading,
        }

    # ============================================================
    # 刷新
    # ============================================================

    def refresh(self) -> bool:
        """
        强制刷新应用列表（清除缓存后重新读取）

        :return: True=成功
        """
        try:
            self._loaded = False
            self._reader.clear_cache()
            return self.load_apps(background=False)
        except Exception as e:
            self._logger.error(f"刷新应用列表异常: {e}")
            return False


# ============================================================
# 单例快捷访问
# ============================================================

_instance = None
_instance_lock = threading.Lock()


def get_app_list_manager() -> AppListManager:
    """
    获取应用列表管理器单例
    :return: AppListManager 实例
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AppListManager()
    return _instance


def get_app_reader() -> AndroidAppReader:
    """
    获取应用读取器实例
    :return: AndroidAppReader 实例
    """
    return AndroidAppReader()


# ============================================================
# 对外便捷接口（供 main.py / UI 层调用）
# ============================================================

def init_app_list(on_error: Optional[Callable[[str], None]] = None) -> dict:
    """
    初始化应用列表（程序入口调用）

    后台加载应用列表，同时还原上次选择状态。
    加载异常通过 on_error 回调通知 UI 弹窗。

    :param on_error: 错误回调（弹窗用）
    :return: 当前应用列表状态统计
    """
    try:
        mgr = get_app_list_manager()
        if on_error:
            mgr.set_on_error(on_error)
        mgr.load_apps(background=True)
        stats = mgr.get_stats()
        LogManager.get_logger("app").info(
            f"应用列表初始化完成: "
            f"total={stats['total']}, "
            f"selected={stats['selected']}"
        )
        return stats
    except Exception as e:
        LogManager.get_logger("error").error(f"初始化应用列表异常: {e}")
        if on_error:
            try:
                on_error(f"初始化应用列表失败: {e}")
            except Exception:
                pass
        return {"total": 0, "selected": 0, "error": str(e)}


def get_apps_ui() -> List[dict]:
    """
    UI 层获取当前筛选后的应用列表
    :return: 应用列表
    """
    try:
        mgr = get_app_list_manager()
        return mgr.get_displayed_apps()
    except Exception as e:
        LogManager.get_logger("app").error(f"获取应用列表异常: {e}")
        return []


def get_selected_apps_ui() -> List[dict]:
    """
    UI 层获取已选中的应用详情
    :return: 应用详情列表
    """
    try:
        mgr = get_app_list_manager()
        return mgr.get_selected_apps()
    except Exception as e:
        LogManager.get_logger("app").error(f"获取已选应用异常: {e}")
        return []


def toggle_select_ui(package: str) -> bool:
    """
    UI 层切换应用选中状态
    :param package: 包名
    :return: 切换后的状态
    """
    try:
        mgr = get_app_list_manager()
        return mgr.toggle_select(package)
    except Exception as e:
        LogManager.get_logger("app").error(f"切换选择异常: {e}")
        return False


def select_all_ui():
    """UI 层全选"""
    try:
        mgr = get_app_list_manager()
        mgr.select_all()
    except Exception as e:
        LogManager.get_logger("app").error(f"全选异常: {e}")


def deselect_all_ui():
    """UI 层清空选择"""
    try:
        mgr = get_app_list_manager()
        mgr.deselect_all()
    except Exception as e:
        LogManager.get_logger("app").error(f"清空选择异常: {e}")


def invert_selection_ui():
    """UI 层反选"""
    try:
        mgr = get_app_list_manager()
        mgr.invert_selection()
    except Exception as e:
        LogManager.get_logger("app").error(f"反选异常: {e}")


def search_apps_ui(query: str):
    """
    UI 层搜索应用
    :param query: 搜索关键词
    """
    try:
        mgr = get_app_list_manager()
        mgr.search(query)
    except Exception as e:
        LogManager.get_logger("app").error(f"搜索异常: {e}")


def set_show_system_ui(show: bool):
    """
    UI 层切换系统应用显示
    :param show: True=显示系统应用
    """
    try:
        mgr = get_app_list_manager()
        mgr.set_show_system(show)
    except Exception as e:
        LogManager.get_logger("app").error(f"切换系统应用显示异常: {e}")


def get_app_stats_ui() -> dict:
    """
    UI 层获取应用列表统计
    :return: 统计字典
    """
    try:
        mgr = get_app_list_manager()
        return mgr.get_stats()
    except Exception as e:
        LogManager.get_logger("app").error(f"获取统计异常: {e}")
        return {"total": 0, "selected": 0}


def refresh_apps_ui(on_error: Optional[Callable[[str], None]] = None) -> dict:
    """
    UI 层强制刷新应用列表
    :param on_error: 错误回调
    :return: 刷新后的统计
    """
    try:
        mgr = get_app_list_manager()
        success = mgr.refresh()
        stats = mgr.get_stats()
        if not success and on_error:
            on_error(mgr.last_error or "刷新应用列表失败")
        return stats
    except Exception as e:
        LogManager.get_logger("app").error(f"刷新应用列表异常: {e}")
        if on_error:
            try:
                on_error(f"刷新应用列表失败: {e}")
            except Exception:
                pass
        return {"total": 0, "selected": 0, "error": str(e)}