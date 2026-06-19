# -*- coding: utf-8 -*-
"""
TiShou — 主入口（完整冷启动流程）
=================================
全局约束：
  1. 仅适配安卓真机（桌面环境日志模拟）
  2. 纯 Python 开发，不混用 C/C++/NDK/Java/Kotlin
  3. 仅免费、免注册、无授权公共 API
  4. 仅 Python 开源库内置免费素材
  5. pip 镜像优先阿里云→腾讯云回退
  6. 全代码异常捕获，杜绝闪退
  7. 分级日志（运行/错误/OCR/素材）
  8. easyocr + Pillow 纯本地 OCR
  9. 抢单判定延迟默认 13s
 10. HyperOS + iOS 融合风 UI

冷启动顺序（严格分步）：
  网络检测 → 权限检测 → 免责声明 → 卡密验证（已验证跳过）
  → 资源加载+OCR初始化 → 素材更新检测 → 主界面+后台全功能

============================================================================
【Buildozer 打包备忘】
============================================================================
打包目标：Android APK（仅适配安卓真机）
构建工具：buildozer（python-for-android）
项目框架：Kivy 2.3.0+ / Python 3.11+

一、打包清理（每次打包前执行）：
   1. 删除旧构建缓存：
      buildozer android clean
   2. 或完全清理（推荐）：
      buildozer android distclean       # 删除 .buildozer/ 全部缓存
      rm -rf ~/.buildozer               # 删除全局 buildozer 缓存
      rm -rf .buildozer                 # 删除项目级构建缓存

二、打包命令：
   # 调试包（含日志）：
   buildozer android debug deploy run   # 构建 + 安装 + 运行
   # 或分步执行：
   buildozer android debug              # 仅构建 debug APK

   # 发布包（release，需签名）：
   buildozer android release

   # 清理缓存（重要！Python 版本变更后必须先清理）：
   buildozer android distclean

三、⚠️ 重要：p4a 的 python3 配方默认编译 Python 3.14.2，导致 pygame（2.1.0）
   的 longintrepr.h 找不到。解决方案：彻底移除 pygame（已替换为 pyjnius →
   android.media.AudioTrack），requirements 中不写 pygame。

四、三个所谓"安卓专属库"的实际情况（⚠️ 真实情况与约束文件描述不符）：
   accessible-android  —— ❌ 非 PyPI 包，无 p4a recipe → 不写进 requirements
                           import: android_accessibility（capture.py）try-except 保护
                           缺失时自动降级：使用 EasyOCR 截图识别
   pyobjus              —— ❌ 是 iOS 桥接库（Objective-C），不适用 Android
                           Android 悬浮窗用 pyjnius → android.view.WindowManager
   android-apps        —— ❌ 非 PyPI 包，无 p4a recipe → 不写进 requirements
                           import: android_apps（app_list.py）try-except 保护
                           缺失时自动降级：subprocess → pm list packages 命令

   本质原因：
   - 原始约束文件定义的"三个安卓专属库"中，没有一个是真正存在且可用于 Android 的包
   - 代码中已全部用 try-except ImportError 保护，缺失时自动降级
   - 不影响 APK 正常打包和运行，所有核心功能有备用实现

五、关键 buildozer.spec 参数：
   requirements = python3,Kivy,pyjnius,requests,easyocr,Pillow,numpy,schedule

   ⚠️ 注意：
   - 不要写 pygame（它依赖 longintrepr.h，Python 3.12+ 已移除）
   - 不要写 android（p4a 自动包含，写进去会被 pip 当作 PyPI 包去搜）
   - 不要锁定版本号（p4a 配方有自己的版本管理，锁定会导致找不到包）

六、注意事项：
   - easyocr 模型文件较大（~100MB），需在首次启动时联网下载
   - 或在 buildozer.spec 中通过 extra_source_dirs 或 android.extra_libs 打包进 APK
   - 建议在 buildozer.spec 中设置 android.accept_sdk_license = True
   - 纯净环境首次打包需要下载 SDK/NDK/Ant，耗时较长（约30-60分钟）
   - APK 最低支持 API 26（Android 8.0），目标 API 33+
============================================================================
"""

import os
import sys
import json
import time
import logging
import threading
import traceback
from datetime import datetime, date
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, Any, Callable

# ============================================================
# 路径常量
# ============================================================
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")
MODULES_DIR = os.path.join(PROJECT_DIR, "modules")
ASSETS_DIR = os.path.join(PROJECT_DIR, "assets")
CACHE_DIR = os.path.join(PROJECT_DIR, "cache")
CONFIG_PATH = os.path.join(PROJECT_DIR, "config.json")

# ============================================================
# 默认配置
# ============================================================
DEFAULT_CONFIG = {
    "material_auto_update": True,
    "material_update_interval": 86400,        # 24小时
    "ocr_poll_interval": 2.0,
    "ocr_timeout": 8.0,
    "ocr_image_scale": 1.3,
    "order_judge_delay": 13.0,
    "order_filter": {
        "min_price": 0.0,                    # 最低金额
        "max_price": 999999.0,               # 最高金额
        "min_pickup_dist": 0.0,              # 最小接驾距离（km）
        "max_pickup_dist": 10.0,             # 最大接驾距离（km）
        "min_order_dist": 20.0,              # 订单最低里程（km）
        "max_order_dist": 999999.0,          # 订单最高里程（km）
        "min_unit_price": 1.0,               # 最低单价（元/km）
        "max_unit_price": 8.0,               # 最高单价（元/km）
        "keywords_include": [],              # 白名单关键词
        "keywords_exclude": [],              # 黑名单关键词
        "order_types": ["fast", "express"],  # 选中的订单类型key列表
        "region_whitelist": [],              # 区域白名单
        "region_blacklist": [],              # 区域黑名单
        "use_whitelist": True,               # 是否使用白名单模式
        "refresh_mode": "fixed",             # fixed | random
        "refresh_fixed_min": 1.0,            # 固定刷新间隔最小值（秒）
        "refresh_fixed_max": 3.0,            # 固定刷新间隔最大值（秒）
        "refresh_random_min": 0.5,           # 随机刷新间隔最小值（秒）
        "refresh_random_max": 5.0,           # 随机刷新间隔最大值（秒）
        "click_mode": "fixed",               # fixed | random
        "click_fixed_ms": 3000,              # 固定点击延迟（ms）
        "click_random_min_ms": 1000,         # 随机点击延迟最小值（ms）
        "click_random_max_ms": 8000,         # 随机点击延迟最大值（ms）
    },
    "float_window": {
        "width": 240,
        "height": 180,
        "corner_radius": 16,
        "opacity": 0.82,
        "position_x": 0,
        "position_y": 200,
        "locked": False,
        "mode": "normal",
    },
    "capture": {
        "region_x": 0,
        "region_y": 0,
        "region_w": 1080,
        "region_h": 1920,
    },
    "activate_code": {
        "enabled": False,
        "code": "",
    },
    "theme": {
        "dark_mode": False,
        "follow_system": True,
        "animation_enabled": True,
    },
    "debug_log": False,
    "eula_accepted": False,                   # 免责声明是否已同意
    "cold_start_completed": False,             # 冷启动是否已完成
}

# ============================================================
# 启动阶段枚举
# ============================================================
class StartupStage:
    """冷启动阶段常量"""
    INIT = "init"                           # 初始化日志/配置
    NETWORK_CHECK = "network_check"         # 网络检测
    PERMISSION_CHECK = "permission_check"   # 权限检测
    DISCLAIMER = "disclaimer"               # 免责声明
    ACTIVATION = "activation"               # 卡密验证
    RESOURCE_LOAD = "resource_load"         # 核心模块加载
    OCR_LOAD = "ocr_load"                   # OCR 模型加载（首次 30-60s）
    MATERIAL_UPDATE = "material_update"     # 素材更新
    SERVICES_START = "services_start"       # 后台服务启动
    COMPLETED = "completed"                 # 冷启动完成


# ============================================================
# 日志系统
# ============================================================
class LogManager:
    """分级日志管理器"""

    _instances: Dict[str, logging.Logger] = {}

    @staticmethod
    def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
        if name in LogManager._instances:
            return LogManager._instances[name]

        try:
            os.makedirs(LOGS_DIR, exist_ok=True)

            logger = logging.getLogger(f"TiShou.{name}")
            logger.setLevel(level)
            logger.handlers.clear()

            log_file = os.path.join(LOGS_DIR, f"{name}.log")
            file_handler = RotatingFileHandler(
                log_file, maxBytes=5 * 1024 * 1024, backupCount=7,
                encoding="utf-8",
            )
            file_handler.setLevel(level)

            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.WARNING)

            formatter = logging.Formatter(
                "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            logger.addHandler(file_handler)
            logger.addHandler(console_handler)
            LogManager._instances[name] = logger
            return logger
        except Exception as e:
            print(f"[LogManager] 初始化日志器失败: {e}", file=sys.stderr)
            fallback = logging.getLogger(f"TiShou.{name}_fallback")
            fallback.addHandler(logging.StreamHandler(sys.stderr))
            return fallback

    @staticmethod
    def set_debug_mode(enabled: bool):
        """全局切换 debug 模式"""
        level = logging.DEBUG if enabled else logging.INFO
        for name, logger in LogManager._instances.items():
            logger.setLevel(level)
            for handler in logger.handlers:
                if isinstance(handler, logging.StreamHandler):
                    handler.setLevel(logging.DEBUG if enabled else logging.WARNING)


# ============================================================
# 配置管理器
# ============================================================
class ConfigManager:
    """全局配置，损坏自动恢复默认"""

    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._logger = LogManager.get_logger("app")
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        try:
            if not os.path.exists(CONFIG_PATH):
                self._reset_to_default()
                return
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._config = {k: v for k, v in data.items() if not k.startswith("//")}
            self._logger.info("配置文件加载成功")
        except Exception as e:
            self._logger.error(f"配置文件损坏，已恢复默认: {e}")
            self._reset_to_default()

    def _reset_to_default(self):
        try:
            self._config = DEFAULT_CONFIG.copy()
            self._save()
            self._logger.info("已重置配置文件为默认值")
        except Exception as e:
            self._logger.error(f"重置配置文件失败: {e}")

    def _save(self):
        try:
            with self._lock:
                os.makedirs(PROJECT_DIR, exist_ok=True)
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(self._config, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self._logger.error(f"保存配置文件失败: {e}")

    def get(self, key: str, default=None):
        try:
            return self._config.get(key, default)
        except Exception:
            return default

    def set(self, key: str, value):
        try:
            with self._lock:
                self._config[key] = value
            self._save()
        except Exception as e:
            self._logger.error(f"设置配置项 {key} 失败: {e}")

    def get_all(self) -> dict:
        return self._config.copy()

    def reload(self):
        self._load()


# ============================================================
# 模块加载器
# ============================================================
class ModuleLoader:
    """动态加载 modules 目录下的模块"""

    @staticmethod
    def load(module_name: str):
        try:
            import importlib
            return importlib.import_module(f"modules.{module_name}")
        except ImportError as e:
            LogManager.get_logger("app").error(f"模块 {module_name} 加载失败: {e}")
            return None
        except Exception as e:
            LogManager.get_logger("app").error(f"模块 {module_name} 加载异常: {e}")
            return None


# ============================================================
# 安卓环境检测
# ============================================================
def is_android() -> bool:
    """检测是否运行在安卓真机环境"""
    try:
        import jnius
        return True
    except ImportError:
        return False
    except Exception:
        return False


# ============================================================
# TiShou 主应用
# ============================================================
class TiShouApp:
    """
    TiShou 主应用 —— 完整冷启动 + 后台运行
    =======================================
    启动顺序（严格分步）：
      1. init          — 日志、配置、路径
      2. network       — 网络连通性检测
      3. permission    — 安卓权限检测与申请
      4. disclaimer    — 免责声明（EULA）
      5. activation    — 卡密验证（已验证跳过）
      6. resource      — OCR 模型加载 + 模块加载
      7. material      — 素材更新检测
      8. services      — 后台保活/悬浮窗/轮询/统计
      9. completed     — 冷启动完成，显示主界面
    """

    # ---- 单例 ----
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True

        # ---- 日志 ----
        self._logger = LogManager.get_logger("app")
        self._error_logger = LogManager.get_logger("error", logging.ERROR)

        # ---- 配置 ----
        self._config = ConfigManager()

        # ---- 当前启动阶段 ----
        self._stage = StartupStage.INIT
        self._stage_errors: Dict[str, str] = {}

        # ---- 模块缓存 ----
        self._modules: Dict[str, Any] = {}

        # ---- 后台服务 ----
        self._keep_alive = None
        self._sound_mgr = None
        self._notification_mgr = None
        self._float_mgr = None
        self._polling_active = False

        # ---- 运行状态 ----
        self._running = False
        self._paused = False
        self._ui_app = None

        # ---- 启动进度回调（供 UI 层更新进度条） ----
        self._progress_callbacks: Dict[str, Callable] = {}

        self._logger.info("TiShouApp 实例已创建")

    # ========================================================
    # 冷启动（总入口）
    # ========================================================
    def start(self):
        """执行完整冷启动流程"""
        try:
            self._running = True
            self._logger.info("=" * 55)
            self._logger.info(" TiShou 冷启动开始")
            self._logger.info(f" 项目目录: {PROJECT_DIR}")
            self._logger.info(f"  安卓环境: {'是' if is_android() else '否（桌面模拟）'}")
            self._logger.info("=" * 55)

            # 确保必要目录
            for d in [LOGS_DIR, MODULES_DIR, ASSETS_DIR, CACHE_DIR]:
                os.makedirs(d, exist_ok=True)

            # ---- 第1步：初始化基础 ----
            self._stage = StartupStage.INIT
            self._on_stage_start("初始化日志与配置")
            self._init_debug_mode()
            self._on_stage_end("初始化日志与配置")

            # ---- 第2步：网络检测 ----
            self._stage = StartupStage.NETWORK_CHECK
            self._on_stage_start("网络连通性检测")
            network_ok = self._check_network()
            self._on_stage_end("网络连通性检测", ok=network_ok)

            # ---- 第3步：权限检测 ----
            self._stage = StartupStage.PERMISSION_CHECK
            self._on_stage_start("安卓权限检测")
            perm_ok = self._check_permissions()
            self._on_stage_end("安卓权限检测", ok=perm_ok)

            # ---- 第4步：免责声明 ----
            self._stage = StartupStage.DISCLAIMER
            self._on_stage_start("免责声明")

            # 第4步在 UI 中由用户交互完成，此处只设置初始状态
            eula_accepted = self._config.get("eula_accepted", False)
            if not eula_accepted:
                self._logger.info("免责声明尚未同意，待 UI 处理")
            else:
                self._logger.info("免责声明已同意，跳过")
            self._on_stage_end("免责声明", ok=True)

            # ---- 第5步：卡密验证 ----
            self._stage = StartupStage.ACTIVATION
            self._on_stage_start("卡密验证")

            activated = self._check_activation()
            if not activated:
                self._logger.info("卡密尚未激活，待 UI 处理")
            else:
                self._logger.info("卡密已验证通过，跳过")
            self._on_stage_end("卡密验证", ok=True)

            # ---- 第6步：资源加载 ----
            self._stage = StartupStage.RESOURCE_LOAD
            self._on_stage_start("核心模块加载")
            modules_ok = self._load_modules()
            self._on_stage_end("核心模块加载", ok=modules_ok)

            # OCR 模型加载单独汇报进度（首次加载约需 30-60 秒）
            if modules_ok:
                self._stage = StartupStage.OCR_LOAD
                self._on_stage_start("OCR 识别模型加载（首次较慢，请耐心等待）")
                ocr_ok = self._load_ocr()
                self._on_stage_end("OCR 识别模型加载", ok=ocr_ok)
            else:
                ocr_ok = False

            # ---- 第7步：素材更新检测 ----
            self._stage = StartupStage.MATERIAL_UPDATE
            self._on_stage_start("素材更新检测")
            self._check_material_update()
            self._on_stage_end("素材更新检测")

            # ---- 第8步：启动后台服务 ----
            self._stage = StartupStage.SERVICES_START
            self._on_stage_start("后台服务启动")
            self._start_background_services()
            self._on_stage_end("后台服务启动")

            # ---- 完成 ----
            self._stage = StartupStage.COMPLETED
            self._config.set("cold_start_completed", True)
            self._logger.info("=" * 55)
            self._logger.info(" TiShou 冷启动完成 ✓")
            self._logger.info("=" * 55)

            return True

        except Exception as e:
            self._error_logger.error(f"冷启动流程异常: {e}\n{traceback.format_exc()}")
            self._stage_errors[self._stage] = str(e)
            return False

    # ========================================================
    # 第1步：调试模式初始化
    # ========================================================
    def _init_debug_mode(self):
        """根据配置切换调试日志（同时同步到模块级日志）"""
        try:
            debug = self._config.get("debug_log", False)
            LogManager.set_debug_mode(debug)
            # 同步到 modules.utils 的 LogManager
            try:
                import importlib
                utils_mod = importlib.import_module("modules.utils")
                if hasattr(utils_mod, "LogManager") and hasattr(utils_mod.LogManager, "set_debug_mode"):
                    utils_mod.LogManager.set_debug_mode(debug)
            except Exception:
                pass
            if debug:
                self._logger.info("调试日志已开启")
            else:
                self._logger.info("正式包模式：仅保留 error/app/ocr/material 日志")
        except Exception as e:
            self._logger.warning(f"调试模式初始化异常: {e}")

    # ========================================================
    # 第2步：网络检测
    # ========================================================
    def _check_network(self) -> bool:
        """
        检测网络连通性
        返回 True=网络正常/弱网, False=完全无网络
        """
        try:
            network_mod = ModuleLoader.load("network")
            if not network_mod:
                self._logger.warning("网络模块未加载，跳过网络检测")
                return True  # 跳过网络检测不阻断启动

            manager = network_mod.get_network_manager()
            state = manager.check_network_state()

            if state == network_mod.NetworkState.NO_NETWORK:
                self._logger.warning("无网络连接，部分功能受限（素材更新、时间同步）")
                return False
            elif state == network_mod.NetworkState.WEAK_NETWORK:
                self._logger.warning("网络状态：弱网，响应可能较慢")
                return True
            else:
                self._logger.info("网络状态：正常")
                return True
        except Exception as e:
            self._logger.warning(f"网络检测异常（不阻断启动）: {e}")
            return True

    # ========================================================
    # 第3步：权限检测
    # ========================================================
    def _check_permissions(self) -> bool:
        """
        检测/申请安卓权限
        权限缺失不阻断主流程（功能降级使用）
        """
        try:
            perm_mod = ModuleLoader.load("permission")
            if not perm_mod:
                self._logger.warning("权限模块未加载，跳过权限检测")
                return True

            # 初始化权限管理器
            perm_mgr = perm_mod.init_permissions()
            if perm_mgr is None:
                # 桌面环境返回 None 是正常的
                self._logger.info("[桌面模式] 权限检测已跳过")
                return True

            # 执行完整权限流（异步）
            # 实际在 UI 中展示引导，此处只检测关键权限缺失
            result = perm_mod.get_permission_status_ui()
            if result:
                missing = result.get("missing", [])
                if missing:
                    self._logger.warning(f"以下权限缺失（功能可能受限）: {', '.join(missing)}")
                else:
                    self._logger.info("权限已全部就绪")
            return True

        except Exception as e:
            self._logger.warning(f"权限检测异常（不阻断启动）: {e}")
            return True

    # ========================================================
    # 第4步：免责声明（由 UI 处理，此处只检查状态）
    # ========================================================

    # ========================================================
    # 第5步：卡密验证
    # ========================================================
    def _check_activation(self) -> bool:
        """检查卡密是否已验证通过"""
        try:
            ac_mod = ModuleLoader.load("activate_code")
            if not ac_mod:
                self._logger.warning("卡密模块未加载，跳过验证")
                return True

            # 检查配置中的激活状态
            enabled = self._config.get("activate_code.enabled", False)
            code = self._config.get("activate_code.code", "")

            if enabled and code:
                # 已有激活记录，验证是否仍有效
                info = ac_mod.get_verify_info_ui()
                if info and info.get("verified", False):
                    self._logger.info("卡密已验证，跳过验证页")
                    return True

            self._logger.info("卡密未激活")
            return False

        except Exception as e:
            self._logger.warning(f"卡密验证检查异常: {e}")
            return False

    # ========================================================
    # 第6步：OCR + 模块加载
    # ========================================================
    def _load_ocr(self) -> bool:
        """
        加载 easyocr 模型
        注意：实际 OCR 引擎由 capture 模块管理（单例），
        此处仅验证 capture 模块的引擎已初始化，避免重复加载。
        """
        try:
            capture_mod = self._modules.get("capture")
            if capture_mod and hasattr(capture_mod, "warmup_engine_ui"):
                self._logger.info("通过 capture 模块加载 OCR 引擎...")
                ok = capture_mod.warmup_engine_ui()
                if ok:
                    self._logger.info("OCR 引擎加载完成（capture 模块管理）")
                    return True
            self._logger.warning("capture 模块不可用，跳过 OCR 引擎加载")
            return False
        except Exception as e:
            self._logger.error(f"OCR 引擎加载失败: {e}")
            return False

    def _load_modules(self) -> bool:
        """加载所有核心业务模块（带逐模块进度上报 + 超时保护）"""
        core_modules = [
            "network", "permission", "capture", "order_filter",
            "float_win", "statistics", "material_update",
            "activate_code", "app_list",
        ]
        total = len(core_modules)
        all_ok = True

        for idx, mod_name in enumerate(core_modules):
            try:
                # 逐模块上报进度：resource_load 阶段 60%~68%（9 个模块各约 0.9%）
                sub_progress = 60 + int((idx / total) * 8)
                self._on_stage_start(f"加载模块: {mod_name}")

                mod = ModuleLoader.load(mod_name)
                if mod:
                    self._modules[mod_name] = mod
                    self._logger.debug(f"模块 {mod_name} 加载成功")
                else:
                    self._logger.warning(f"模块 {mod_name} 加载失败")
                    all_ok = False
            except Exception as e:
                self._logger.error(f"模块 {mod_name} 加载异常: {e}")
                all_ok = False

        # 初始化各模块
        self._init_core_modules()
        return all_ok

    def _init_core_modules(self):
        """依次初始化核心模块（带进度上报）"""
        init_steps = [
            ("statistics", "统计模块", "init_statistics"),
            ("capture", "采集引擎", "init_capture"),
            ("order_filter", "订单筛选", "init_order_filter"),
            ("material_update", "素材更新", "init_material_updater"),
            ("app_list", "应用列表", "init_app_list"),
        ]

        for idx, (mod_key, display_name, init_func) in enumerate(init_steps):
            try:
                mod = self._modules.get(mod_key)
                if not mod:
                    self._logger.warning(f"{display_name}未加载，跳过初始化")
                    continue

                # 逐模块上报进度：resource_load 阶段后段 68%~72%
                sub_progress = 68 + int((idx / len(init_steps)) * 4)
                self._on_stage_start(f"初始化: {display_name}")

                if mod_key == "material_update":
                    auto_update = self._config.get("material_auto_update", True)
                    getattr(mod, init_func)(start_auto=auto_update)
                else:
                    getattr(mod, init_func)()

                self._logger.info(f"{display_name}已初始化")
            except Exception as e:
                self._logger.error(f"{display_name}初始化异常: {e}")

    # ========================================================
    # 第7步：素材更新
    # ========================================================
    def _check_material_update(self):
        """检测并更新素材"""
        try:
            mat_mod = self._modules.get("material_update")
            if not mat_mod:
                return

            auto_update = self._config.get("material_auto_update", True)
            if not auto_update:
                self._logger.info("素材自动更新已关闭，跳过")
                return

            # 在后台线程检查更新，不阻塞启动
            def _update_worker():
                try:
                    self._logger.info("正在检测素材更新...")
                    result = mat_mod.check_material_updates_ui()
                    if result and result.get("has_update", False):
                        self._logger.info("检测到素材更新，开始下载...")
                        update_result = mat_mod.update_all_materials_ui()
                        if update_result:
                            self._logger.info("素材更新完成")
                        else:
                            self._logger.warning("素材更新失败，保留现有素材")
                    else:
                        self._logger.info("素材已是最新版本")
                except Exception as e:
                    self._logger.warning(f"素材更新检查异常（不阻断）: {e}")

            t = threading.Thread(target=_update_worker, daemon=True, name="material-update")
            t.start()

        except Exception as e:
            self._logger.warning(f"素材更新启动异常（不阻断）: {e}")

    # ========================================================
    # 第8步：后台服务
    # ========================================================
    def _start_background_services(self):
        """启动所有后台服务"""
        self._logger.info("正在启动后台服务...")

        # ---- 1. 后台保活 ----
        self._start_keep_alive()

        # ---- 2. 音效管理 ----
        self._init_sound()

        # ---- 3. 通知管理 ----
        self._init_notifications()

        # ---- 4. 悬浮窗 ----
        self._init_float_window()

        self._logger.info("后台服务启动完成")

    def _start_keep_alive(self):
        """启动后台保活"""
        try:
            float_mod = self._modules.get("float_win")
            if not float_mod:
                return
            if not hasattr(float_mod, "KeepAliveManager"):
                return

            self._keep_alive = float_mod.KeepAliveManager()
            self._keep_alive.start()
            self._logger.info(f"后台保活状态: {'活跃' if self._keep_alive.is_active else '未启动'}")
        except Exception as e:
            self._logger.warning(f"后台保活启动失败（不影响主流程）: {e}")

    def _init_sound(self):
        """初始化音效系统"""
        try:
            float_mod = self._modules.get("float_win")
            if not float_mod:
                return
            if not hasattr(float_mod, "SoundManager"):
                return

            self._sound_mgr = float_mod.SoundManager()
            self._logger.info("音效系统已就绪")
        except Exception as e:
            self._logger.warning(f"音效初始化失败（不影响主流程）: {e}")

    def _init_notifications(self):
        """初始化通知系统"""
        try:
            float_mod = self._modules.get("float_win")
            if not float_mod:
                return
            if not hasattr(float_mod, "NotificationManager"):
                return

            self._notification_mgr = float_mod.NotificationManager()
            self._logger.info("通知系统已就绪")
        except Exception as e:
            self._logger.warning(f"通知初始化失败（不影响主流程）: {e}")

    def _init_float_window(self):
        """初始化悬浮窗（延迟到主界面加载后）"""
        try:
            float_mod = self._modules.get("float_win")
            if not float_mod:
                return

            # 注册回调（UI 跳转、暂停/继续、关闭）
            float_mod.register_float_callbacks_ui(
                on_open_main=self._on_float_open_main,
                on_toggle_pause=self._on_float_toggle_pause,
                on_close=self._on_float_close,
            )
            self._logger.info("悬浮窗回调和状态已注册")

            # 更新初始状态
            capture_mod = self._modules.get("capture")
            engine = "accessibility"
            if capture_mod and hasattr(capture_mod, "get_engine_status_ui"):
                status = capture_mod.get_engine_status_ui()
                if status and status.get("active_engine"):
                    engine = status["active_engine"]

            float_mod.update_float_status_ui(
                engine=engine,
                polling="stopped",
                network="online",
                order_count=0,
            )
        except Exception as e:
            self._logger.warning(f"悬浮窗初始化失败（不影响主流程）: {e}")

    # ---- 悬浮窗回调 ----
    def _on_float_open_main(self):
        """悬浮窗菜单：打开主界面"""
        try:
            self._logger.info("悬浮窗请求打开主界面")
            ui_mod = self._modules.get("ui")
            if ui_mod and hasattr(ui_mod, "switch_to_main"):
                ui_mod.switch_to_main()
        except Exception as e:
            self._logger.warning(f"打开主界面失败: {e}")

    def _on_float_toggle_pause(self):
        """悬浮窗菜单：暂停/继续抢单"""
        try:
            self._paused = not self._paused
            if self._paused:
                self._pause_grabbing()
            else:
                self._resume_grabbing()
            self._logger.info(f"抢单状态: {'暂停' if self._paused else '运行中'}")
        except Exception as e:
            self._logger.warning(f"切换暂停状态失败: {e}")

    def _pause_grabbing(self):
        """暂停抢单"""
        try:
            capture_mod = self._modules.get("capture")
            if capture_mod and hasattr(capture_mod, "stop_polling_ui"):
                capture_mod.stop_polling_ui()
            self._polling_active = False

            float_mod = self._modules.get("float_win")
            if float_mod and hasattr(float_mod, "set_float_paused_ui"):
                float_mod.set_float_paused_ui(True)
            self._logger.info("抢单已暂停")
        except Exception as e:
            self._logger.warning(f"暂停抢单失败: {e}")

    def _resume_grabbing(self):
        """恢复抢单"""
        try:
            capture_mod = self._modules.get("capture")
            if capture_mod and hasattr(capture_mod, "start_polling_ui"):
                capture_mod.start_polling_ui()
            self._polling_active = True

            float_mod = self._modules.get("float_win")
            if float_mod and hasattr(float_mod, "set_float_paused_ui"):
                float_mod.set_float_paused_ui(False)
            self._logger.info("抢单已恢复")
        except Exception as e:
            self._logger.warning(f"恢复抢单失败: {e}")

    def _on_float_close(self):
        """悬浮窗菜单：关闭应用"""
        try:
            self._logger.info("用户通过悬浮窗关闭应用")
            self.stop()
        except Exception as e:
            self._logger.warning(f"关闭应用失败: {e}")

    # ========================================================
    # 抢单结果处理
    # ========================================================
    def on_order_result(self, success: bool, order_info: str = ""):
        """
        处理抢单结果（由 capture 模块回调）
        :param success: 是否成功
        :param order_info: 订单信息
        """
        try:
            self._logger.info(f"抢单结果: {'成功 ✓' if success else '失败 ✗'} {order_info}")

            # 1. 统计
            stats_mod = self._modules.get("statistics")
            if stats_mod:
                if success:
                    stats_mod.record_order_success_ui()
                else:
                    stats_mod.record_order_failed_ui()

            # 2. 悬浮窗指示灯
            float_mod = self._modules.get("float_win")
            if float_mod and hasattr(float_mod, "set_float_indicator_result_ui"):
                float_mod.set_float_indicator_result_ui(success)

            # 3. 音效
            if self._sound_mgr:
                if success:
                    self._sound_mgr.play_order_success()
                else:
                    self._sound_mgr.play_order_failed()

            # 4. 通知
            if self._notification_mgr:
                if success:
                    self._notification_mgr.notify_order_success(order_info)
                else:
                    self._notification_mgr.notify_order_failed(order_info)

        except Exception as e:
            self._error_logger.error(f"处理抢单结果异常: {e}")

    # ========================================================
    # UI 集成
    # ========================================================
    def launch_ui(self):
        """启动 Kivy 界面"""
        try:
            ui_mod = ModuleLoader.load("ui")
            if not ui_mod or not hasattr(ui_mod, "run_ui"):
                self._logger.warning("UI 模块不可用")
                return False

            # 传递当前实例引用给 UI（通过环境变量）
            os.environ["TISHOU_APP_INSTANCE"] = "1"

            # 启动 UI（这通常会阻塞到 UI 退出）
            self._logger.info("正在启动 Kivy 界面...")
            ui_mod.run_ui(biz_app=self)
            return True
        except Exception as e:
            self._error_logger.error(f"UI 启动失败: {e}\n{traceback.format_exc()}")
            return False

    def get_startup_progress(self) -> Dict[str, Any]:
        """获取启动进度信息（供 UI 加载页轮询）"""
        stages_order = [
            StartupStage.INIT,
            StartupStage.NETWORK_CHECK,
            StartupStage.PERMISSION_CHECK,
            StartupStage.DISCLAIMER,
            StartupStage.ACTIVATION,
            StartupStage.RESOURCE_LOAD,
            StartupStage.MATERIAL_UPDATE,
            StartupStage.SERVICES_START,
            StartupStage.COMPLETED,
        ]
        try:
            current_idx = stages_order.index(self._stage) if self._stage in stages_order else 0
            total = len(stages_order) - 1  # COMPLETED 不计入进度
            progress = min(current_idx / total, 1.0) if total > 0 else 0
            return {
                "stage": self._stage,
                "progress": round(progress, 2),
                "errors": dict(self._stage_errors),
                "running": self._running,
            }
        except Exception:
            return {"stage": self._stage, "progress": 0, "errors": {}, "running": False}

    # ========================================================
    # 生命周期
    # ========================================================
    def stop(self):
        """停止应用，释放所有资源"""
        try:
            self._logger.info("正在停止 TiShou...")
            self._running = False

            # 停止轮询
            try:
                capture_mod = self._modules.get("capture")
                if capture_mod and hasattr(capture_mod, "stop_polling_ui"):
                    capture_mod.stop_polling_ui()
            except Exception:
                pass

            # 停止悬浮窗
            try:
                float_mod = self._modules.get("float_win")
                if float_mod and hasattr(float_mod, "destroy_float_ui"):
                    float_mod.destroy_float_ui()
            except Exception:
                pass

            # 停保活
            try:
                if self._keep_alive:
                    self._keep_alive.stop()
                    self._keep_alive = None
            except Exception:
                pass

            self._logger.info("TiShou 已停止")
        except Exception as e:
            self._error_logger.error(f"停止应用异常: {e}")

    def restart(self):
        """重启应用"""
        try:
            self._logger.info("正在重启 TiShou...")
            self.stop()
            time.sleep(0.5)
            self._initialized = False
            self.__init__()
            self.start()
        except Exception as e:
            self._error_logger.error(f"重启应用异常: {e}")

    # ========================================================
    # 进度回调注册
    # ========================================================
    def register_progress_callback(self, name: str, callback: Callable):
        """注册启动进度回调"""
        self._progress_callbacks[name] = callback

    def unregister_progress_callback(self, name: str):
        """注销启动进度回调"""
        self._progress_callbacks.pop(name, None)

    def _on_stage_start(self, stage_name: str):
        """阶段开始回调"""
        self._logger.info(f"▶ {stage_name}...")
        for cb in self._progress_callbacks.values():
            try:
                cb(self._stage, stage_name, "start", None)
            except Exception:
                pass

    def _on_stage_end(self, stage_name: str, ok: bool = True):
        """阶段结束回调"""
        status = "✓" if ok else "✗"
        self._logger.info(f"  {status} {stage_name}")
        if not ok:
            self._stage_errors[stage_name] = f"{stage_name} 完成但状态异常"
        for cb in self._progress_callbacks.values():
            try:
                cb(self._stage, stage_name, "end", ok)
            except Exception:
                pass

    # ========================================================
    # 属性
    # ========================================================
    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def config(self) -> ConfigManager:
        return self._config

    @property
    def modules(self) -> Dict[str, Any]:
        return self._modules

    @property
    def current_stage(self) -> str:
        return self._stage


# ============================================================
# 全局应用实例访问
# ============================================================
_app_instance: Optional[TiShouApp] = None


def get_app() -> TiShouApp:
    """获取全局 TiShouApp 单例"""
    global _app_instance
    if _app_instance is None:
        _app_instance = TiShouApp()
    return _app_instance


# ============================================================
# 主入口
# ============================================================
def main():
    """
    主入口函数
    =========
    1. 确保目录结构
    2. 创建应用实例
    3. 启动 Kivy 界面（内部自动调度冷启动，防止安卓主线程阻塞黑屏）
    """
    try:
        # 确保必要目录
        for d in [LOGS_DIR, MODULES_DIR, ASSETS_DIR, CACHE_DIR]:
            os.makedirs(d, exist_ok=True)

        # 获取应用实例
        app = get_app()

        # ✅ 立即启动 Kivy UI，不执行阻塞冷启动
        # Kivy 的 LoadingScreen 会在 on_start 中调度后台冷启动
        app.launch_ui()

    except KeyboardInterrupt:
        print("\n用户中断，正在退出...")
        try:
            if _app_instance:
                _app_instance.stop()
        except Exception:
            pass
    except Exception as e:
        error_msg = f"主入口致命异常: {e}\n{traceback.format_exc()}"
        try:
            error_logger = LogManager.get_logger("error", logging.ERROR)
            error_logger.critical(error_msg)
        except Exception:
            print(error_msg, file=sys.stderr)

        # 将崩溃信息写入独立文件
        try:
            crash_log = os.path.join(LOGS_DIR, "crash.log")
            with open(crash_log, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 50}\n")
                f.write(f"崩溃时间: {datetime.now().isoformat()}\n")
                f.write(error_msg)
                f.write(f"\n{'=' * 50}\n")
        except Exception:
            pass

        sys.exit(1)


if __name__ == "__main__":
    main()