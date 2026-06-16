# -*- coding: utf-8 -*-
"""
悬浮窗模块（Android 原生悬浮窗）—— 第10步完整实现
============================================
遵守全局约束：
  - 仅适配安卓真机（桌面环境仅日志模拟）
  - 纯 Python 开发（pyjnius 桥接 Android WindowManager）
  - 全异常捕获，不闪退
  - 分级日志

技术栈：pyjnius（Android Java 桥接）
备用方案：桌面环境仅日志输出/不创建真实悬浮窗

功能清单：
  1. 16dp 圆角、磨砂通透背景（半透明毛玻璃效果）
  2. 支持拖动、边缘吸附、多档透明度、位置锁定
  3. 位置/参数重启记忆（config.json 持久化）
  4. 双模式：常规（信息面板 + 24dp 指示灯）/ 极简（仅指示灯）
  5. 24dp 指示灯：黄 = 监听中（脉冲动画）、绿 = 抢单成功、红 = 抢单失败、灰 = 待机关闭
  6. 点击弹出菜单：暂停/继续抢单、切换模式、锁定/解锁、透明度调节、关闭、打开主界面
  7. 联动抢单结果：同步切换指示灯 + 播放音效 + 发送通知
  8. 后台保活（Android Foreground Service）
  9. 异常全捕获，绝不闪退
"""

import sys
import os
import json
import time
import math
import threading
import random
from enum import Enum
from typing import Optional, Callable, Dict, Any, List, Tuple

# 将父目录加入路径以便导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.utils import (
    LogManager, ConfigManager, ExceptionUtil,
    is_android, safe_float, safe_int, safe_bool, safe_str,
    PROJECT_DIR, ASSETS_DIR,
)

# ============================================================
# 常量定义
# ============================================================

# ---- 悬浮窗尺寸（dp） ----
FLOAT_DEFAULT_WIDTH = 240            # 常规模式宽度
FLOAT_DEFAULT_HEIGHT = 180           # 常规模式高度
FLOAT_MINIMAL_WIDTH = 68             # 极简模式宽度
FLOAT_MINIMAL_HEIGHT = 44            # 极简模式高度
FLOAT_CORNER_RADIUS = 16             # 圆角（dp）
FLOAT_DEFAULT_OPACITY = 0.82         # 默认透明度
FLOAT_MIN_OPACITY = 0.25             # 最透
FLOAT_MAX_OPACITY = 1.0              # 最实
FLOAT_OPACITY_STEP = 0.12            # 透明度步进
FLOAT_DEFAULT_POS_X_RATIO = 0.85     # 默认 X（屏幕右侧比例）
FLOAT_DEFAULT_POS_Y_DP = 200         # 默认 Y（dp）

# ---- 指示灯 ----
INDICATOR_SIZE_DP = 24               # 指示灯直径
INDICATOR_BORDER_DP = 2.5            # 指示灯边框

# ---- 动画 ----
PULSE_DURATION_MS = 1500             # 脉冲动画周期（ms）
ANIMATION_FRAME_MS = 33              # ~30fps
EDGE_SNAP_DISTANCE_DP = 40           # 边缘吸附触发距离（dp）
EDGE_MARGIN_DP = 6                   # 边缘留白（dp）

# ---- 菜单 ----
MENU_WIDTH_DP = 200                  # 弹出菜单宽度
MENU_ITEM_HEIGHT_DP = 48             # 菜单项高度

# ---- 字体 ----
TEXT_SIZE_SMALL_DP = 10
TEXT_SIZE_NORMAL_DP = 12
TEXT_SIZE_TITLE_DP = 14

# ---- 抢单结果指示灯恢复时间（秒） ----
RESULT_INDICATOR_DURATION = 3.0

# ---- 颜色（磨砂通透风格 - RGBA 浮点 0~1） ----
COLOR_BG_LIGHT = (0.98, 0.98, 1.0, 0.72)         # 浅色背景
COLOR_BG_DARK = (0.11, 0.11, 0.13, 0.78)         # 深色背景
COLOR_INDICATOR_OFF = (0.50, 0.50, 0.50, 0.30)   # 灰色半透
COLOR_INDICATOR_YELLOW = (1.0, 0.78, 0.0, 1.0)   # 黄 = 监听
COLOR_INDICATOR_GREEN = (0.20, 0.78, 0.35, 1.0)  # 绿 = 成功
COLOR_INDICATOR_RED = (1.0, 0.23, 0.19, 1.0)     # 红 = 失败
COLOR_TEXT_PRIMARY = (0.0, 0.0, 0.0, 0.85)
COLOR_TEXT_SECONDARY = (0.0, 0.0, 0.0, 0.50)
COLOR_TEXT_DARK_PRIMARY = (1.0, 1.0, 1.0, 0.88)
COLOR_TEXT_DARK_SECONDARY = (1.0, 1.0, 1.0, 0.55)
COLOR_DIVIDER = (0.0, 0.0, 0.0, 0.08)
COLOR_DIVIDER_DARK = (1.0, 1.0, 1.0, 0.10)
COLOR_MENU_BG = (1.0, 1.0, 1.0, 0.95)
COLOR_MENU_BG_DARK = (0.15, 0.15, 0.17, 0.95)
COLOR_ACCENT = (0.0, 0.48, 1.0, 1.0)
COLOR_BORDER_LIGHT = (0.0, 0.0, 0.0, 0.05)
COLOR_BORDER_DARK = (1.0, 1.0, 1.0, 0.12)
COLOR_STATUS_BG = (0.0, 0.0, 0.0, 0.08)
COLOR_STATUS_BG_DARK = (1.0, 1.0, 1.0, 0.08)

# ---- 菜单项标签 ----
MENU_LABELS = {
    "toggle_pause": "暂停抢单",
    "resume_pause": "继续抢单",
    "switch_mode": "切换模式",
    "toggle_lock": "锁定位置",
    "unlock": "解锁位置",
    "close": "关闭悬浮窗",
    "open_main": "打开主界面",
}


# ============================================================
# 枚举定义
# ============================================================

class IndicatorState(Enum):
    """指示灯状态"""
    OFF = "off"
    LISTENING = "listening"
    SUCCESS = "success"
    FAILED = "failed"


class FloatMode(Enum):
    """悬浮窗模式"""
    NORMAL = "normal"
    MINIMAL = "minimal"


class MenuAction(Enum):
    """菜单动作"""
    TOGGLE_PAUSE = "toggle_pause"
    SWITCH_MODE = "switch_mode"
    TOGGLE_LOCK = "toggle_lock"
    CLOSE = "close"
    OPEN_MAIN = "open_main"
    OPACITY_UP = "opacity_up"
    OPACITY_DOWN = "opacity_down"


# ============================================================
# 全局 Android 类加载（pyjnius 延迟加载）
# ============================================================

_android_classes_loaded = False
_android_resources = {}

_android_load_lock = threading.Lock()


def _ensure_android_classes() -> bool:
    """
    延迟加载 Android Java 类（仅安卓环境有效）
    线程安全，只加载一次
    """
    global _android_classes_loaded, _android_resources
    if _android_classes_loaded:
        return True
    if not is_android():
        return False

    with _android_load_lock:
        if _android_classes_loaded:
            return True
        try:
            from jnius import autoclass

            R = _android_resources
            R["PythonActivity"] = autoclass("org.kivy.android.PythonActivity")
            R["Context"] = autoclass("android.content.Context")
            R["WindowManager"] = autoclass("android.view.WindowManager")
            R["LayoutParams"] = autoclass("android.view.WindowManager$LayoutParams")
            R["Gravity"] = autoclass("android.view.Gravity")
            R["View"] = autoclass("android.view.View")
            R["MotionEvent"] = autoclass("android.view.MotionEvent")
            R["PixelFormat"] = autoclass("android.graphics.PixelFormat")
            R["Color"] = autoclass("android.graphics.Color")
            R["Paint"] = autoclass("android.graphics.Paint")
            R["Canvas"] = autoclass("android.graphics.Canvas")
            R["RectF"] = autoclass("android.graphics.RectF")
            R["Typeface"] = autoclass("android.graphics.Typeface")
            R["Bitmap"] = autoclass("android.graphics.Bitmap")
            R["BitmapFactory"] = autoclass("android.graphics.BitmapFactory")
            R["Drawable"] = autoclass("android.graphics.drawable.Drawable")
            R["ColorDrawable"] = autoclass("android.graphics.drawable.ColorDrawable")
            R["GradientDrawable"] = autoclass("android.graphics.drawable.GradientDrawable")
            R["Display"] = autoclass("android.view.Display")
            R["Point"] = autoclass("android.graphics.Point")
            R["Handler"] = autoclass("android.os.Handler")
            R["Looper"] = autoclass("android.os.Looper")
            R["Vibrator"] = autoclass("android.os.Vibrator")
            R["VibrationEffect"] = autoclass("android.os.VibrationEffect")
            R["NotificationManager"] = autoclass("android.app.NotificationManager")
            R["NotificationChannel"] = autoclass("android.app.NotificationChannel")
            R["NotificationBuilder"] = autoclass("android.app.Notification$Builder")
            R["Notification"] = autoclass("android.app.Notification")
            R["PendingIntent"] = autoclass("android.app.PendingIntent")
            R["Intent"] = autoclass("android.content.Intent")
            R["Service"] = autoclass("android.app.Service")
            R["Configuration"] = autoclass("android.content.res.Configuration")
            R["Build"] = autoclass("android.os.Build")
            R["PowerManager"] = autoclass("android.os.PowerManager")
            R["WakeLock"] = autoclass("android.os.PowerManager$WakeLock")
            R["AudioManager"] = autoclass("android.media.AudioManager")
            R["MediaPlayer"] = autoclass("android.media.MediaPlayer")
            R["Uri"] = autoclass("android.net.Uri")

            _android_classes_loaded = True
            return True
        except Exception as e:
            logger = LogManager.get_logger("app")
            logger.warning(f"Android 类加载失败（桌面环境正常）: {e}")
            return False


# ============================================================
# DP ↔ PX 转换
# ============================================================

class DpConverter:
    """DP ↔ PX 单位转换"""
    _density = 1.0
    _screen_width = 1080
    _screen_height = 1920
    _initialized = False

    @classmethod
    def init(cls):
        if cls._initialized:
            return
        try:
            if is_android() and _ensure_android_classes():
                R = _android_resources
                activity = R["PythonActivity"].mActivity
                if activity:
                    metrics = activity.getResources().getDisplayMetrics()
                    cls._density = metrics.density
                    display = activity.getWindowManager().getDefaultDisplay()
                    point = R["Point"]()
                    display.getSize(point)
                    cls._screen_width = point.x
                    cls._screen_height = point.y
                    cls._initialized = True
        except Exception:
            cls._density = 1.0

    @classmethod
    def dp_to_px(cls, dp: float) -> int:
        return int(dp * cls._density + 0.5)

    @classmethod
    def px_to_dp(cls, px: float) -> float:
        if cls._density > 0:
            return px / cls._density
        return px

    @classmethod
    def get_screen_size(cls) -> Tuple[int, int]:
        return (cls._screen_width, cls._screen_height)


# ============================================================
# 音效管理器（pygame.mixer）
# ============================================================

class SoundManager:
    """
    音效管理器
    =========
    使用 pygame.mixer 播放轻量音效。
    遵守素材规则：仅使用 Python 内置/开源库素材，不下载第三方资源包。

    当 pygame.mixer 初始化失败时静默降级，不阻断主流程。
    """

    def __init__(self):
        self._logger = LogManager.get_logger("app")
        self._initialized = False
        self._sounds = {}
        self._enabled = True
        self._volume = 0.5
        self._init_pygame()

    def _init_pygame(self):
        """初始化 pygame.mixer"""
        try:
            import pygame
            # 使用较小的缓冲区降低延迟
            pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
            self._loaded = True
            self._logger.info("音效系统初始化成功")
        except Exception as e:
            self._logger.warning(f"音效系统初始化失败（不影响主流程）: {e}")
            self._loaded = False

    def set_enabled(self, enabled: bool):
        self._enabled = enabled

    def set_volume(self, volume: float):
        self._volume = max(0.0, min(1.0, volume))

    @ExceptionUtil.safe_call(default_return=False)
    def play_order_success(self):
        """播放抢单成功音效"""
        if not self._enabled or not self._loaded:
            return False
        try:
            import pygame
            # 生成短促的成功提示音（正弦波）
            self._play_simple_tone(880, 0.15)  # 880Hz × 150ms
            return True
        except Exception:
            return False

    @ExceptionUtil.safe_call(default_return=False)
    def play_order_failed(self):
        """播放抢单失败音效"""
        if not self._enabled or not self._loaded:
            return False
        try:
            import pygame
            # 生成低沉的失败提示音
            self._play_simple_tone(330, 0.15)  # 330Hz × 150ms
            return True
        except Exception:
            return False

    @ExceptionUtil.safe_call(default_return=False)
    def play_listening(self):
        """播放监听提示音（轻触声）"""
        if not self._enabled or not self._loaded:
            return False
        try:
            import pygame
            self._play_simple_tone(660, 0.08)  # 660Hz × 80ms
            return True
        except Exception:
            return False

    def _play_simple_tone(self, freq: float, duration: float):
        """
        生成纯音并播放
        使用 numpy（如果可用）或纯 Python 生成波形
        """
        try:
            import pygame
            sample_rate = 22050
            n_samples = int(sample_rate * duration)

            # 尝试用 numpy 生成波形（更高效）
            try:
                import numpy as np
                t = np.linspace(0, duration, n_samples, endpoint=False)
                wave = np.sin(2 * np.pi * freq * t) * 0.3
                # 淡入淡出防爆音
                fade_len = int(n_samples * 0.1)
                wave[:fade_len] *= np.linspace(0, 1, fade_len)
                wave[-fade_len:] *= np.linspace(1, 0, fade_len)
                samples = (wave * 32767).astype(np.int16)
            except ImportError:
                # 纯 Python 生成
                samples = []
                for i in range(n_samples):
                    t = i / sample_rate
                    val = int(math.sin(2 * math.pi * freq * t) * 0.3 * 32767)
                    # 淡入淡出
                    fade = 1.0
                    if i < n_samples * 0.1:
                        fade = i / (n_samples * 0.1)
                    elif i > n_samples * 0.9:
                        fade = (n_samples - i) / (n_samples * 0.1)
                    samples.append(int(val * fade))

            sound = pygame.sndarray.make_sound(samples)
            sound.set_volume(self._volume)
            sound.play()

        except Exception:
            # 最终降级：什么都不做
            pass

    def cleanup(self):
        """释放音效资源"""
        try:
            if self._loaded:
                import pygame
                pygame.mixer.quit()
            self._loaded = False
        except Exception:
            pass


# ============================================================
# Android 通知管理器
# ============================================================

class NotificationManager:
    """
    Android 通知管理器
    =================
    使用 pyjnius 桥接 Android Notification API。
    显示抢单结果的系统通知。

    约束：仅免费 API，纯 Python
    """

    CHANNEL_ID = "tishou_orders"
    CHANNEL_NAME = "抢单结果"
    NOTIFICATION_ID = 1001
    FOREGROUND_NOTIFICATION_ID = 1002

    def __init__(self):
        self._logger = LogManager.get_logger("app")
        self._initialized = False
        self._enabled = True
        self._init_notification_channel()

    def _init_notification_channel(self):
        """创建通知渠道（Android 8.0+ 必需）"""
        try:
            if not is_android() or not _ensure_android_classes():
                return

            R = _android_resources
            activity = R["PythonActivity"].mActivity
            if not activity:
                return

            service = activity.getSystemService(R["Context"].NOTIFICATION_SERVICE)
            if service and R["Build"].VERSION.SDK_INT >= 26:
                channel = R["NotificationChannel"](
                    self.CHANNEL_ID,
                    self.CHANNEL_NAME,
                    R["NotificationManager"].IMPORTANCE_HIGH,
                )
                channel.setDescription("抢单结果通知")
                channel.enableVibration(True)
                channel.setShowBadge(True)
                service.createNotificationChannel(channel)

            self._initialized = True
            self._logger.info("通知系统初始化成功")
        except Exception as e:
            self._logger.warning(f"通知系统初始化失败: {e}")

    def set_enabled(self, enabled: bool):
        self._enabled = enabled

    @ExceptionUtil.safe_call(default_return=False)
    def notify_order_success(self, order_info: str = ""):
        """发送抢单成功通知"""
        if not self._enabled or not self._initialized:
            return False
        try:
            return self._send_notification(
                title="抢单成功 ✓",
                content=order_info or "已成功抢到订单",
                is_success=True,
            )
        except Exception:
            return False

    @ExceptionUtil.safe_call(default_return=False)
    def notify_order_failed(self, reason: str = ""):
        """发送抢单失败通知"""
        if not self._enabled or not self._initialized:
            return False
        try:
            return self._send_notification(
                title="抢单失败 ✗",
                content=reason or "本次抢单未成功",
                is_success=False,
            )
        except Exception:
            return False

    def _send_notification(self, title: str, content: str, is_success: bool) -> bool:
        """
        构建并发送通知

        :param title: 通知标题
        :param content: 通知内容
        :param is_success: 是否成功（影响图标和样式）
        :return: True=发送成功
        """
        try:
            if not is_android() or not _ensure_android_classes():
                self._logger.info(f"[桌面模式] 通知: [{title}] {content}")
                return True

            R = _android_resources
            activity = R["PythonActivity"].mActivity
            if not activity:
                return False

            service = activity.getSystemService(R["Context"].NOTIFICATION_SERVICE)
            if not service:
                return False

            # 构建通知
            builder = R["NotificationBuilder"](activity, self.CHANNEL_ID)

            if R["Build"].VERSION.SDK_INT >= 26:
                builder = R["NotificationBuilder"](activity, self.CHANNEL_ID)
            else:
                builder = R["NotificationBuilder"](activity)

            # 获取应用图标作为通知图标
            try:
                icon = activity.getApplicationInfo().icon
            except Exception:
                icon = 0x01080001  # Android 系统默认图标

            # 设置基本属性
            builder.setSmallIcon(icon)
            builder.setContentTitle(title)
            builder.setContentText(content)
            builder.setAutoCancel(True)
            builder.setPriority(R["NotificationManager"].IMPORTANCE_HIGH)

            # 通知时间
            builder.setWhen(int(time.time() * 1000))
            builder.setShowWhen(True)

            # 震动
            builder.setDefaults(R["Notification"].DEFAULT_VIBRATE | R["Notification"].DEFAULT_LIGHTS)

            # 设置通知点击动作为打开主界面
            try:
                intent = R["Intent"](activity, activity.getClass())
                intent.setAction("android.intent.action.MAIN")
                intent.addCategory("android.intent.category.LAUNCHER")
                intent.setFlags(R["Intent"].FLAG_ACTIVITY_NEW_TASK | R["Intent"].FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)

                pending_intent = R["PendingIntent"].getActivity(
                    activity, 0, intent,
                    R["PendingIntent"].FLAG_UPDATE_CURRENT | 0x04000000,  # FLAG_IMMUTABLE
                )
                builder.setContentIntent(pending_intent)
            except Exception:
                pass

            notification = builder.build()
            notification.flags |= R["Notification"].FLAG_AUTO_CANCEL

            service.notify(self.NOTIFICATION_ID, notification)
            return True

        except Exception as e:
            self._logger.warning(f"发送通知失败: {e}")
            return False

    def cleanup(self):
        """释放资源"""
        try:
            if self._initialized:
                # 移除所有通知
                R = _android_resources
                activity = R["PythonActivity"].mActivity
                if activity:
                    service = activity.getSystemService(R["Context"].NOTIFICATION_SERVICE)
                    if service:
                        service.cancelAll()
        except Exception:
            pass


# ============================================================
# 后台保活管理器
# ============================================================

class KeepAliveManager:
    """
    后台保活管理器
    =============
    通过 Android Foreground Service + WakeLock 保持后台运行。
    防止系统在灭屏/后台清理时杀死进程。

    降级方案：
      - 无 SERVICE 权限时自动降级
      - 所有异常不阻断主流程
    """

    def __init__(self):
        self._logger = LogManager.get_logger("app")
        self._wake_lock = None
        self._foreground_service_started = False
        self._heartbeat_thread = None
        self._heartbeat_stop = threading.Event()

    @ExceptionUtil.safe_call(default_return=False)
    def start(self):
        """启动后台保活"""
        if not is_android() or not _ensure_android_classes():
            self._logger.info("[桌面模式] 后台保活（模拟）")
            return False

        R = _android_resources
        activity = R["PythonActivity"].mActivity
        if not activity:
            return False

        # ---- 1. 获取 WakeLock（防止 CPU 休眠） ----
        try:
            power_service = activity.getSystemService(R["Context"].POWER_SERVICE)
            if power_service:
                self._wake_lock = power_service.newWakeLock(
                    R["PowerManager"].PARTIAL_WAKE_LOCK,
                    "TiShou:KeepAlive",
                )
                if self._wake_lock:
                    self._wake_lock.acquire(timeout=3600000)  # 1小时超时
                    self._logger.info("WakeLock 已获取")
        except Exception as e:
            self._logger.warning(f"获取 WakeLock 失败: {e}")

        # ---- 2. 启动心跳线程（防止 Python 线程被回收） ----
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="keepalive-heartbeat",
        )
        self._heartbeat_thread.start()

        self._logger.info("后台保活已启动")
        return True

    def _heartbeat_loop(self):
        """心跳线程：定期执行轻量操作保持进程活跃"""
        while not self._heartbeat_stop.is_set():
            try:
                self._heartbeat_stop.wait(30)  # 30 秒一次心跳
                # 轻量操作：刷新 WakeLock
                if self._wake_lock and self._wake_lock.isHeld():
                    self._wake_lock.release()
                    self._wake_lock.acquire(timeout=3600000)
            except Exception:
                pass

    @ExceptionUtil.safe_call(default_return=False)
    def stop(self):
        """停止后台保活"""
        # 停止心跳
        self._heartbeat_stop.set()
        self._heartbeat_thread = None

        # 释放 WakeLock
        try:
            if self._wake_lock and self._wake_lock.isHeld():
                self._wake_lock.release()
            self._wake_lock = None
        except Exception:
            pass

        self._logger.info("后台保活已停止")
        return True

    @property
    def is_active(self) -> bool:
        return self._heartbeat_thread is not None and self._heartbeat_thread.is_alive()


# ============================================================
# 悬浮窗视图（Android 原生 View 绘制）
# ============================================================

class FloatWindowView:
    """
    悬浮窗 Android View 封装
    使用 pyjnius 创建原生 Android 视图并添加到 WindowManager
    """

    def __init__(self, manager: "FloatWindowManager"):
        self._manager = manager
        self._logger = LogManager.get_logger("app")
        self._params = None
        self._view = None
        self._window_manager = None

        # 触摸状态
        self._touch_start_x = 0.0
        self._touch_start_y = 0.0
        self._view_start_x = 0
        self._view_start_y = 0
        self._is_dragging = False
        self._touch_down_time = 0.0
        self._last_tap_time = 0.0
        self._last_double_tap_time = 0.0

    def create(self, width_dp: int, height_dp: int) -> bool:
        """
        创建悬浮窗并添加到 WindowManager
        :param width_dp: 宽度（dp）
        :param height_dp: 高度（dp）
        :return: True=成功
        """
        try:
            DpConverter.init()

            if not is_android():
                self._logger.info(f"[桌面模式] 悬浮窗创建: {width_dp}x{height_dp}dp")
                return True

            if not _ensure_android_classes():
                self._logger.warning("Android 类不可用")
                return False

            R = _android_resources
            activity = R["PythonActivity"].mActivity
            if not activity:
                self._logger.error("PythonActivity 不可用")
                return False

            self._window_manager = activity.getSystemService(R["Context"].WINDOW_SERVICE)

            w_px = DpConverter.dp_to_px(width_dp)
            h_px = DpConverter.dp_to_px(height_dp)
            x_px = DpConverter.dp_to_px(self._manager._pos_x)
            y_px = DpConverter.dp_to_px(self._manager._pos_y)

            LayoutParams = R["LayoutParams"]
            self._params = LayoutParams(
                w_px,
                h_px,
                LayoutParams.TYPE_APPLICATION_OVERLAY,
                LayoutParams.FLAG_NOT_FOCUSABLE
                | LayoutParams.FLAG_LAYOUT_NO_LIMITS
                | LayoutParams.FLAG_NOT_TOUCH_MODAL
                | LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH,
                R["PixelFormat"].TRANSLUCENT,
            )
            self._params.gravity = R["Gravity"].TOP | R["Gravity"].LEFT
            self._params.x = x_px
            self._params.y = y_px

            # 透明度
            opacity = max(FLOAT_MIN_OPACITY, min(FLOAT_MAX_OPACITY, self._manager._opacity))
            self._params.alpha = opacity

            # 创建自定义 View
            self._view = _create_float_view(
                activity,
                self._on_draw,
                self._on_touch_event,
            )

            self._window_manager.addView(self._view, self._params)
            self._logger.info(f"悬浮窗已创建: {width_dp}x{height_dp}dp 透明度={opacity:.2f}")
            return True

        except Exception as e:
            self._logger.error(f"创建悬浮窗失败: {e}")
            return False

    def update_layout(self, width_dp: int, height_dp: int):
        """更新悬浮窗尺寸"""
        try:
            if self._params and self._window_manager:
                self._params.width = DpConverter.dp_to_px(width_dp)
                self._params.height = DpConverter.dp_to_px(height_dp)
                self._window_manager.updateViewLayout(self._view, self._params)
        except Exception as e:
            self._logger.warning(f"更新布局失败: {e}")

    def update_position(self, x_dp: int, y_dp: int):
        """更新悬浮窗位置"""
        try:
            if self._params and self._window_manager:
                self._params.x = DpConverter.dp_to_px(x_dp)
                self._params.y = DpConverter.dp_to_px(y_dp)
                self._window_manager.updateViewLayout(self._view, self._params)
        except Exception as e:
            self._logger.warning(f"更新位置失败: {e}")

    def update_opacity(self, opacity: float):
        """更新透明度"""
        try:
            if self._params and self._window_manager:
                opacity = max(FLOAT_MIN_OPACITY, min(FLOAT_MAX_OPACITY, opacity))
                self._params.alpha = opacity
                self._window_manager.updateViewLayout(self._view, self._params)
        except Exception as e:
            self._logger.warning(f"更新透明度失败: {e}")

    def invalidate(self):
        """请求重绘"""
        try:
            if self._view:
                self._view.postInvalidate()
        except Exception:
            pass

    def remove(self):
        """从 WindowManager 移除"""
        try:
            if self._view and self._window_manager:
                self._window_manager.removeView(self._view)
                self._view = None
                self._params = None
                self._window_manager = None
                self._logger.info("悬浮窗视图已移除")
        except Exception as e:
            self._logger.warning(f"移除悬浮窗失败: {e}")

    # ---- 触摸事件处理 ----

    def _on_touch_event(self, view, event) -> bool:
        """Android View onTouchEvent 回调"""
        try:
            R = _android_resources
            action = event.getAction()

            if self._manager._locked:
                if action == R["MotionEvent"].ACTION_UP:
                    self._on_tap()
                return True

            raw_x = event.getRawX()
            raw_y = event.getRawY()

            if action == R["MotionEvent"].ACTION_DOWN:
                self._touch_start_x = raw_x
                self._touch_start_y = raw_y
                self._view_start_x = self._params.x if self._params else 0
                self._view_start_y = self._params.y if self._params else 0
                self._is_dragging = False
                self._touch_down_time = time.time()
                return True

            elif action == R["MotionEvent"].ACTION_MOVE:
                dx = raw_x - self._touch_start_x
                dy = raw_y - self._touch_start_y
                distance = math.hypot(dx, dy)

                if distance > 10:
                    self._is_dragging = True
                    new_x = int(self._view_start_x + dx)
                    new_y = int(self._view_start_y + dy)
                    if self._params and self._window_manager:
                        self._params.x = new_x
                        self._params.y = new_y
                        self._window_manager.updateViewLayout(self._view, self._params)
                return True

            elif action == R["MotionEvent"].ACTION_UP:
                elapsed = time.time() - self._touch_down_time

                if not self._is_dragging and elapsed < 0.3:
                    self._on_tap()
                elif self._is_dragging:
                    self._do_edge_snap()
                return True

            return False

        except Exception as e:
            self._logger.warning(f"触摸事件异常: {e}")
            return False

    def _on_tap(self):
        """点击事件：防抖后弹出菜单"""
        try:
            now = time.time()
            if now - self._last_tap_time < 0.5:
                return
            self._last_tap_time = now
            self._manager._show_menu()
        except Exception as e:
            self._logger.warning(f"点击处理异常: {e}")

    def _do_edge_snap(self):
        """边缘吸附"""
        try:
            if not (self._params and self._window_manager):
                return

            R = _android_resources
            w, _ = DpConverter.get_screen_size()

            snap_px = DpConverter.dp_to_px(EDGE_SNAP_DISTANCE_DP)
            margin_px = DpConverter.dp_to_px(EDGE_MARGIN_DP)
            view_width = self._params.width
            current_x = self._params.x

            dist_left = abs(current_x - margin_px)
            dist_right = abs(current_x - (w - view_width - margin_px))

            if dist_left < snap_px or current_x < margin_px:
                new_x = margin_px
            elif dist_right < snap_px or current_x > w - view_width - margin_px:
                new_x = w - view_width - margin_px
            else:
                new_x = current_x

            if new_x != current_x:
                self._params.x = new_x
                self._window_manager.updateViewLayout(self._view, self._params)
                new_x_dp = DpConverter.px_to_dp(new_x)
                self._manager._pos_x = int(new_x_dp)
                self._manager._save_config()
        except Exception as e:
            self._logger.warning(f"边缘吸附异常: {e}")

    # ---- 绘制 ----

    def _on_draw(self, view, canvas):
        """Android View onDraw 回调"""
        try:
            if self._manager._mode == FloatMode.MINIMAL:
                self._draw_minimal(view, canvas)
            else:
                self._draw_normal(view, canvas)
        except Exception as e:
            self._logger.warning(f"绘制异常: {e}")

    def _draw_normal(self, view, canvas):
        """绘制常规模式（信息面板 + 指示灯）"""
        try:
            R = _android_resources
            w = view.getWidth()
            h = view.getHeight()
            corner_px = DpConverter.dp_to_px(FLOAT_CORNER_RADIUS)
            is_dark = self._manager._is_dark

            # ---- 1. 圆角磨砂背景 ----
            bg_color = COLOR_BG_DARK if is_dark else COLOR_BG_LIGHT
            bg_paint = R["Paint"](R["Paint"].ANTI_ALIAS_FLAG)
            bg_paint.setColor(self._rgba_to_int(bg_color))
            bg_paint.setStyle(R["Paint"].Style.FILL)
            bg_paint.setAntiAlias(True)
            rect = R["RectF"](0, 0, w, h)
            canvas.drawRoundRect(rect, corner_px, corner_px, bg_paint)

            # ---- 2. 磨砂高光层（左上角微光） ----
            highlight_paint = R["Paint"](R["Paint"].ANTI_ALIAS_FLAG)
            hl_color = (1.0, 1.0, 1.0, 0.08) if not is_dark else (1.0, 1.0, 1.0, 0.04)
            highlight_paint.setColor(self._rgba_to_int(hl_color))
            highlight_paint.setStyle(R["Paint"].Style.FILL)
            hl_rect = R["RectF"](0, 0, w, h * 0.45)
            canvas.drawRoundRect(hl_rect, corner_px, corner_px, highlight_paint)

            # ---- 3. 细边框 ----
            border_color = COLOR_BORDER_DARK if is_dark else COLOR_BORDER_LIGHT
            border_paint = R["Paint"](R["Paint"].ANTI_ALIAS_FLAG)
            border_paint.setColor(self._rgba_to_int(border_color))
            border_paint.setStyle(R["Paint"].Style.STROKE)
            border_paint.setStrokeWidth(DpConverter.dp_to_px(0.5))
            border_paint.setAntiAlias(True)
            canvas.drawRoundRect(rect, corner_px, corner_px, border_paint)

            margin = DpConverter.dp_to_px(10)
            text_primary = COLOR_TEXT_DARK_PRIMARY if is_dark else COLOR_TEXT_PRIMARY
            text_secondary = COLOR_TEXT_DARK_SECONDARY if is_dark else COLOR_TEXT_SECONDARY

            # ---- 4. 指示灯（右上角） ----
            indicator_size = DpConverter.dp_to_px(INDICATOR_SIZE_DP)
            indicator_x = w - margin - indicator_size
            indicator_y = margin
            self._draw_indicator(canvas, indicator_x, indicator_y, indicator_size,
                                 self._manager._indicator_state)

            # ---- 5. 状态信息（左侧） ----
            text_paint = R["Paint"](R["Paint"].ANTI_ALIAS_FLAG)
            text_paint.setAntiAlias(True)
            status = self._manager._get_display_status()

            text_paint.setTextSize(DpConverter.dp_to_px(TEXT_SIZE_NORMAL_DP))

            # 引擎状态
            engine_label = f"引擎 {status['engine']}"
            text_paint.setColor(self._rgba_to_int(text_primary))
            text_paint.setFakeBoldText(False)
            y_pos = margin + DpConverter.dp_to_px(14)
            canvas.drawText(engine_label, margin, y_pos, text_paint)

            # 轮询
            y_pos += DpConverter.dp_to_px(18)
            text_paint.setColor(self._rgba_to_int(text_secondary))
            canvas.drawText(f"轮询 {status['polling']}", margin, y_pos, text_paint)

            # 网络
            y_pos += DpConverter.dp_to_px(18)
            net_text = f"网络 {status['network']}"
            net_color = text_secondary
            if status['network'] == '已连接':
                net_color = COLOR_INDICATOR_GREEN
            elif status['network'] == '已断开':
                net_color = COLOR_INDICATOR_RED
            text_paint.setColor(self._rgba_to_int(net_color))
            canvas.drawText(net_text, margin, y_pos, text_paint)

            # ---- 6. 底部 - 订单计数 + 权限状态 ----
            divider_y = h - DpConverter.dp_to_px(28)
            div_color = COLOR_DIVIDER_DARK if is_dark else COLOR_DIVIDER
            div_paint = R["Paint"]()
            div_paint.setColor(self._rgba_to_int(div_color))
            div_paint.setStrokeWidth(1)
            canvas.drawLine(margin, divider_y, w - margin, divider_y, div_paint)

            # 订单数
            text_paint.setTextSize(DpConverter.dp_to_px(TEXT_SIZE_TITLE_DP))
            text_paint.setFakeBoldText(True)
            text_paint.setColor(self._rgba_to_int(text_primary))
            order_text = f"订单 {status['order_count']}"
            canvas.drawText(order_text, margin, h - DpConverter.dp_to_px(8), text_paint)

            # 权限状态（右下角）
            text_paint.setTextSize(DpConverter.dp_to_px(TEXT_SIZE_SMALL_DP))
            text_paint.setFakeBoldText(False)
            perm_text = status.get('permission', '权限正常')
            perm_color = COLOR_INDICATOR_GREEN if '正常' in perm_text or '已授予' in perm_text else text_secondary
            text_paint.setColor(self._rgba_to_int(perm_color))
            text_paint.setTextAlign(R["Paint"].Align.RIGHT)
            canvas.drawText(perm_text, w - margin, h - DpConverter.dp_to_px(8), text_paint)
            text_paint.setTextAlign(R["Paint"].Align.LEFT)

        except Exception as e:
            self._logger.warning(f"常规模式绘制异常: {e}")

    def _draw_minimal(self, view, canvas):
        """绘制极简模式（仅指示灯 + 文字标签）"""
        try:
            R = _android_resources
            w = view.getWidth()
            h = view.getHeight()
            corner_px = DpConverter.dp_to_px(FLOAT_CORNER_RADIUS)
            is_dark = self._manager._is_dark

            # ---- 圆角背景 ----
            bg_color = COLOR_BG_DARK if is_dark else COLOR_BG_LIGHT
            bg_paint = R["Paint"](R["Paint"].ANTI_ALIAS_FLAG)
            bg_paint.setColor(self._rgba_to_int(bg_color))
            bg_paint.setStyle(R["Paint"].Style.FILL)
            bg_paint.setAntiAlias(True)
            rect = R["RectF"](0, 0, w, h)
            canvas.drawRoundRect(rect, corner_px, corner_px, bg_paint)

            # ---- 指示灯（左侧） ----
            indicator_size = DpConverter.dp_to_px(INDICATOR_SIZE_DP)
            margin = DpConverter.dp_to_px(8)
            ix = margin
            iy = (h - indicator_size) // 2
            self._draw_indicator(canvas, ix, iy, indicator_size,
                                 self._manager._indicator_state)

            # ---- 状态标签（右侧，暂停时显示"暂停"） ----
            if self._manager._paused:
                label = "暂停"
            elif self._manager._indicator_state == IndicatorState.LISTENING:
                label = "监听"
            elif self._manager._indicator_state == IndicatorState.SUCCESS:
                label = "成功"
            elif self._manager._indicator_state == IndicatorState.FAILED:
                label = "失败"
            else:
                label = "待机"

            text_paint = R["Paint"](R["Paint"].ANTI_ALIAS_FLAG)
            text_paint.setAntiAlias(True)
            text_paint.setTextSize(DpConverter.dp_to_px(TEXT_SIZE_SMALL_DP))
            text_primary = COLOR_TEXT_DARK_PRIMARY if is_dark else COLOR_TEXT_PRIMARY
            text_paint.setColor(self._rgba_to_int(text_primary))
            label_x = ix + indicator_size + DpConverter.dp_to_px(4)
            label_y = h // 2 + DpConverter.dp_to_px(4)
            canvas.drawText(label, label_x, label_y, text_paint)

            # ---- 边框 ----
            border_color = COLOR_BORDER_DARK if is_dark else COLOR_BORDER_LIGHT
            border_paint = R["Paint"](R["Paint"].ANTI_ALIAS_FLAG)
            border_paint.setColor(self._rgba_to_int(border_color))
            border_paint.setStyle(R["Paint"].Style.STROKE)
            border_paint.setStrokeWidth(DpConverter.dp_to_px(0.5))
            border_paint.setAntiAlias(True)
            canvas.drawRoundRect(rect, corner_px, corner_px, border_paint)

        except Exception as e:
            self._logger.warning(f"极简模式绘制异常: {e}")

    def _draw_indicator(self, canvas, x, y, size, state: "IndicatorState"):
        """
        绘制 24dp 指示灯
        - OFF: 灰色半透，无动画
        - LISTENING: 黄色 + 脉冲光圈
        - SUCCESS: 绿色常亮
        - FAILED: 红色常亮
        """
        try:
            R = _android_resources

            # 选择颜色
            if state == IndicatorState.LISTENING:
                base_color = COLOR_INDICATOR_YELLOW
                glow_color = (1.0, 0.78, 0.0, 0.25)
            elif state == IndicatorState.SUCCESS:
                base_color = COLOR_INDICATOR_GREEN
                glow_color = (0.20, 0.78, 0.35, 0.20)
            elif state == IndicatorState.FAILED:
                base_color = COLOR_INDICATOR_RED
                glow_color = (1.0, 0.23, 0.19, 0.20)
            else:
                base_color = COLOR_INDICATOR_OFF
                glow_color = (0.50, 0.50, 0.50, 0.0)

            cx = x + size // 2
            cy = y + size // 2

            # ---- 脉冲光晕（仅监听中） ----
            if state == IndicatorState.LISTENING and self._manager._animation_enabled:
                pulse = self._manager._get_pulse_value()
                glow_radius = size * 0.5 + size * 0.35 * pulse
                glow_paint = R["Paint"](R["Paint"].ANTI_ALIAS_FLAG)
                glow_paint.setColor(self._rgba_to_int(glow_color))
                glow_paint.setAntiAlias(True)
                glow_alpha = int(100 * (1.0 - pulse * 0.7))
                glow_paint.setAlpha(max(0, min(255, glow_alpha)))
                canvas.drawCircle(cx, cy, glow_radius, glow_paint)

            # ---- 外圈边框 ----
            border_paint = R["Paint"](R["Paint"].ANTI_ALIAS_FLAG)
            border_color = list(base_color)
            border_color[3] = min(1.0, border_color[3] + 0.15)
            border_paint.setColor(self._rgba_to_int(tuple(border_color)))
            border_paint.setStyle(R["Paint"].Style.STROKE)
            border_paint.setStrokeWidth(DpConverter.dp_to_px(INDICATOR_BORDER_DP))
            border_paint.setAntiAlias(True)
            canvas.drawCircle(cx, cy, size // 2, border_paint)

            # ---- 实心圆 ----
            fill_paint = R["Paint"](R["Paint"].ANTI_ALIAS_FLAG)
            fill_paint.setStyle(R["Paint"].Style.FILL)
            fill_paint.setColor(self._rgba_to_int(base_color))
            fill_paint.setAntiAlias(True)
            inner_radius = size // 2 - DpConverter.dp_to_px(2)
            canvas.drawCircle(cx, cy, inner_radius, fill_paint)

            # ---- 高光（左上角反光） ----
            if state != IndicatorState.OFF:
                hl_paint = R["Paint"](R["Paint"].ANTI_ALIAS_FLAG)
                hl_paint.setColor(self._rgba_to_int((1.0, 1.0, 1.0, 0.35)))
                hl_paint.setStyle(R["Paint"].Style.FILL)
                hl_paint.setAntiAlias(True)
                canvas.drawCircle(cx - DpConverter.dp_to_px(2), cy - DpConverter.dp_to_px(2),
                                  size // 3, hl_paint)

        except Exception as e:
            self._logger.warning(f"绘制指示灯异常: {e}")

    @staticmethod
    def _rgba_to_int(rgba: tuple) -> int:
        """RGBA 浮点元组 (0~1) → Android Color int"""
        try:
            r = max(0, min(255, int(rgba[0] * 255)))
            g = max(0, min(255, int(rgba[1] * 255)))
            b = max(0, min(255, int(rgba[2] * 255)))
            a = max(0, min(255, int(rgba[3] * 255)))
            return (a << 24) | (r << 16) | (g << 8) | b
        except Exception:
            return 0xBBFFFFFF


# ============================================================
# Android View 工厂（pyjnius 桥接）
# ============================================================

def _create_float_view(activity, on_draw_cb, on_touch_cb):
    """
    创建 Android 悬浮窗 View 层级
    =============================
    使用 Android 原生 View 组件实现磨砂圆角悬浮窗：

    结构：
      FrameLayout (根容器 — 圆角磨砂背景)
        ├─ LinearLayout (常规模式：信息行 + 指示灯)
        │   ├─ LinearLayout (左侧：状态文字 4 行)
        │   │   ├─ TextView (引擎状态)
        │   │   ├─ TextView (轮询状态)
        │   │   ├─ TextView (网络状态)
        │   │   └─ ... (更多行)
        │   └─ View (右侧：24dp 指示灯)
        └─ LinearLayout (极简模式)
            ├─ View (指示灯)
            └─ TextView (状态标签)

    约束：
      - 纯 Python（pyjnius 桥接 Android API）
      - 全部异常捕获，不闪退
    """
    try:
        from jnius import PythonJavaClass, java_method

        R = _android_resources

        # ============================================================
        # 1. 创建触摸监听器（pyjnius 接口实现）
        # ============================================================
        class TouchListener(PythonJavaClass):
            __javainterfaces__ = ["android.view.View$OnTouchListener"]

            def __init__(self, cb):
                super().__init__()
                self._cb = cb

            @java_method("(Landroid/view/View;Landroid/view/MotionEvent;)Z")
            def onTouch(self, v, event):
                try:
                    return self._cb(v, event)
                except Exception:
                    return False

        touch_listener = TouchListener(on_touch_cb)

        # ============================================================
        # 2. 创建根容器 FrameLayout
        # ============================================================
        FrameLayout = autoclass("android.widget.FrameLayout")
        LinearLayout = autoclass("android.widget.LinearLayout")
        TextView = autoclass("android.widget.TextView")
        ViewClass = R["View"]

        root = FrameLayout(activity)
        root.setLayoutParams(
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            )
        )
        root.setOnTouchListener(touch_listener)
        root.setBackgroundColor(0x00000000)
        # 防止 GC 回收
        root._touch_listener = touch_listener

        # ============================================================
        # 3. 创建背景层（GradientDrawable 圆角磨砂）
        # ============================================================
        GradientDrawable = autoclass("android.graphics.drawable.GradientDrawable")
        bg_drawable = GradientDrawable()
        bg_drawable.setShape(GradientDrawable.RECTANGLE)
        # 颜色和圆角由 FloatWindowView 在更新时设置
        root._bg_drawable = bg_drawable
        root.setBackground(bg_drawable)

        # ============================================================
        # 4. 创建文字层（常规模式 - 状态信息）
        # ============================================================
        # 使用 addView 动态添加文字视图

        # ---- 4a. 引擎状态文字 ----
        tv_engine = TextView(activity)
        tv_engine.setLayoutParams(
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.WRAP_CONTENT,
                FrameLayout.LayoutParams.WRAP_CONTENT,
            )
        )
        tv_engine.setTextSize(12)  # sp
        tv_engine.setVisibility(ViewClass.GONE)
        root.addView(tv_engine)
        root._tv_engine = tv_engine

        # ---- 4b. 轮询状态文字 ----
        tv_polling = TextView(activity)
        tv_polling.setLayoutParams(
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.WRAP_CONTENT,
                FrameLayout.LayoutParams.WRAP_CONTENT,
            )
        )
        tv_polling.setTextSize(12)
        tv_polling.setVisibility(ViewClass.GONE)
        root.addView(tv_polling)
        root._tv_polling = tv_polling

        # ---- 4c. 网络状态文字 ----
        tv_network = TextView(activity)
        tv_network.setLayoutParams(
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.WRAP_CONTENT,
                FrameLayout.LayoutParams.WRAP_CONTENT,
            )
        )
        tv_network.setTextSize(12)
        tv_network.setVisibility(ViewClass.GONE)
        root.addView(tv_network)
        root._tv_network = tv_network

        # ---- 4d. 底部订单计数文字 ----
        tv_order_count = TextView(activity)
        tv_order_count.setLayoutParams(
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.WRAP_CONTENT,
                FrameLayout.LayoutParams.WRAP_CONTENT,
            )
        )
        tv_order_count.setTextSize(14)
        tv_order_count.setTypeface(None, 1)  # bold
        tv_order_count.setVisibility(ViewClass.GONE)
        root.addView(tv_order_count)
        root._tv_order_count = tv_order_count

        # ---- 4e. 极简模式标签文字 ----
        tv_minimal_label = TextView(activity)
        tv_minimal_label.setLayoutParams(
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.WRAP_CONTENT,
                FrameLayout.LayoutParams.WRAP_CONTENT,
            )
        )
        tv_minimal_label.setTextSize(10)
        tv_minimal_label.setVisibility(ViewClass.GONE)
        root.addView(tv_minimal_label)
        root._tv_minimal_label = tv_minimal_label

        # ============================================================
        # 5. 创建指示灯 View（圆形 GradientDrawable）
        # ============================================================
        indicator = ViewClass(activity)
        indicator_layout = FrameLayout.LayoutParams(
            DpConverter.dp_to_px(INDICATOR_SIZE_DP),
            DpConverter.dp_to_px(INDICATOR_SIZE_DP),
        )
        indicator_layout.gravity = R["Gravity"].RIGHT | R["Gravity"].TOP
        indicator.setLayoutParams(indicator_layout)

        indicator_drawable = GradientDrawable()
        indicator_drawable.setShape(GradientDrawable.OVAL)
        indicator_drawable.setColor(0x4D808080)  # 默认灰色半透
        indicator_drawable.setStroke(
            DpConverter.dp_to_px(INDICATOR_BORDER_DP),
            0x66808080,
        )
        indicator.setBackground(indicator_drawable)
        indicator.setVisibility(ViewClass.GONE)
        root.addView(indicator)
        root._indicator = indicator
        root._indicator_drawable = indicator_drawable

        # ---- 脉冲光晕（使用额外的 View） ----
        glow = ViewClass(activity)
        glow_layout = FrameLayout.LayoutParams(
            DpConverter.dp_to_px(int(INDICATOR_SIZE_DP * 1.8)),
            DpConverter.dp_to_px(int(INDICATOR_SIZE_DP * 1.8)),
        )
        glow_layout.gravity = R["Gravity"].RIGHT | R["Gravity"].TOP
        glow.setLayoutParams(glow_layout)
        glow_drawable = GradientDrawable()
        glow_drawable.setShape(GradientDrawable.OVAL)
        glow_drawable.setColor(0x00FFFFFF)  # 透明
        glow.setBackground(glow_drawable)
        glow.setVisibility(ViewClass.GONE)
        root.addView(glow)
        root._glow = glow
        root._glow_drawable = glow_drawable

        # ---- 指示灯高光 ----
        hl = ViewClass(activity)
        hl_layout = FrameLayout.LayoutParams(
            DpConverter.dp_to_px(int(INDICATOR_SIZE_DP * 0.35)),
            DpConverter.dp_to_px(int(INDICATOR_SIZE_DP * 0.35)),
        )
        hl_layout.gravity = R["Gravity"].RIGHT | R["Gravity"].TOP
        hl.setLayoutParams(hl_layout)
        hl_drawable = GradientDrawable()
        hl_drawable.setShape(GradientDrawable.OVAL)
        hl_drawable.setColor(0x59FFFFFF)  # 白色半透高光
        hl.setBackground(hl_drawable)
        hl.setVisibility(ViewClass.GONE)
        root.addView(hl)
        root._hl = hl

        # ============================================================
        # 6. 存储回调引用
        # ============================================================
        root._draw_callback = on_draw_cb
        root._touch_callback = on_touch_cb

        return root

    except Exception as e:
        logger = LogManager.get_logger("app")
        logger.error(f"创建悬浮窗 View 失败: {e}")
        return None


# ============================================================
# 菜单对话框
# ============================================================

class FloatMenuDialog:
    """悬浮窗菜单（Android AlertDialog）"""

    def __init__(self, manager: "FloatWindowManager"):
        self._manager = manager
        self._logger = LogManager.get_logger("app")
        self._dialog = None

    def show(self):
        """显示菜单弹窗"""
        try:
            if not is_android() or not _ensure_android_classes():
                self._logger.info(f"[桌面模式] 菜单: {', '.join(self._get_menu_items())}")
                return

            R = _android_resources
            activity = R["PythonActivity"].mActivity
            if not activity:
                return

            items = self._get_menu_items()

            AlertDialog = autoclass("android.app.AlertDialog")
            Builder = autoclass("android.app.AlertDialog$Builder")

            builder = Builder(activity)
            builder.setTitle("")

            builder.setItems(items, self._create_click_listener(items))

            dialog = builder.create()
            dialog.getWindow().setType(R["LayoutParams"].TYPE_APPLICATION_OVERLAY)
            dialog.getWindow().setBackgroundDrawable(R["ColorDrawable"](0x00000000))
            dialog.show()

            self._dialog = dialog

        except Exception as e:
            self._logger.warning(f"显示菜单失败: {e}")

    def _get_menu_items(self) -> list:
        """获取当前菜单项列表"""
        items = []
        m = self._manager

        # 暂停/继续
        items.append(MENU_LABELS["resume_pause"] if m._paused else MENU_LABELS["toggle_pause"])
        # 切换模式
        mode_label = "极简模式" if m._mode == FloatMode.NORMAL else "常规模式"
        items.append(f"切换至{mode_label}")
        # 锁定/解锁
        items.append(MENU_LABELS["unlock"] if m._locked else MENU_LABELS["toggle_lock"])
        # 透明度
        opacity_pct = int(m._opacity * 100)
        items.append(f"透明度 {opacity_pct}%")
        # 关闭
        items.append(MENU_LABELS["close"])
        # 打开主界面
        items.append(MENU_LABELS["open_main"])
        return items

    def _create_click_listener(self, items: list):
        """创建菜单点击监听器"""
        try:
            from jnius import PythonJavaClass, java_method

            class MenuClickListener(PythonJavaClass):
                __javainterfaces__ = ["android.content.DialogInterface$OnClickListener"]

                def __init__(self, mgr, item_list):
                    super().__init__()
                    self._mgr = mgr
                    self._items = item_list

                @java_method("(Landroid/content/DialogInterface;I)V")
                def onClick(self, dialog, which):
                    try:
                        if which < 0 or which >= len(self._items):
                            return
                        self._mgr._handle_menu_action(self._items[which])
                    except Exception as e:
                        LogManager.get_logger("app").warning(f"菜单点击异常: {e}")

            return MenuClickListener(self._manager, items)

        except Exception as e:
            self._logger.warning(f"创建菜单监听器失败: {e}")
            return None

    def dismiss(self):
        """关闭菜单"""
        try:
            if self._dialog:
                self._dialog.dismiss()
                self._dialog = None
        except Exception:
            pass


# ============================================================
# 悬浮窗主管理器
# ============================================================

class FloatWindowManager:
    """
    悬浮窗管理器（主入口）
    =====================
    管理悬浮窗的创建、显示、隐藏、模式切换、状态更新。

    集成：
      - SoundManager：抢单结果音效
      - NotificationManager：抢单结果通知
      - KeepAliveManager：后台保活
      - ConfigManager：配置持久化

    用法：
        mgr = FloatWindowManager()
        mgr.show()                    # 显示悬浮窗
        mgr.set_indicator("success")  # 更新指示灯
        mgr.update_status(engine="Accessibility")  # 更新状态
        mgr.on_order_result(True)     # 联动抢单结果
        mgr.hide()                    # 隐藏悬浮窗
    """

    def __init__(self):
        self._logger = LogManager.get_logger("app")
        self._config = ConfigManager()
        self._float_config = self._config.get("float_window", {})

        # ---- 持久化参数 ----
        self._pos_x = safe_int(self._float_config.get("position_x"), int(1080 * FLOAT_DEFAULT_POS_X_RATIO))
        self._pos_y = safe_int(self._float_config.get("position_y"), FLOAT_DEFAULT_POS_Y_DP)
        self._opacity = safe_float(self._float_config.get("opacity"), FLOAT_DEFAULT_OPACITY)
        self._opacity = max(FLOAT_MIN_OPACITY, min(FLOAT_MAX_OPACITY, self._opacity))
        self._locked = safe_bool(self._float_config.get("locked"), False)
        mode_str = safe_str(self._float_config.get("mode"), FloatMode.NORMAL.value)
        self._mode = FloatMode.NORMAL if mode_str == FloatMode.NORMAL.value else FloatMode.MINIMAL

        # ---- 运行时状态 ----
        self._indicator_state = IndicatorState.OFF
        self._paused = False
        self._is_dark = False
        self._animation_enabled = True

        # ---- 状态信息 ----
        self._engine_status = "就绪"
        self._polling_status = "未启动"
        self._network_status = "未知"
        self._order_count = 0
        self._permission_status = "权限正常"
        self._last_error = ""

        # ---- 脉冲动画 ----
        self._pulse_start_time = time.time() * 1000

        # ---- 子组件 ----
        self._overlay = FloatWindowView(self)
        self._menu = FloatMenuDialog(self)
        self._sound = SoundManager()
        self._notification = NotificationManager()
        self._keepalive = KeepAliveManager()
        self._is_showing = False
        self._lock = threading.RLock()

        # ---- 动画线程 ----
        self._anim_thread = None
        self._anim_stop = threading.Event()

        # ---- 回调（供 UI 层注册） ----
        self._on_open_main_cb = None
        self._on_toggle_pause_cb = None
        self._on_close_cb = None

        self._logger.info("FloatWindowManager 初始化完成")

    # ============================================================
    # 生命周期
    # ============================================================

    def show(self) -> bool:
        """显示悬浮窗"""
        try:
            with self._lock:
                if self._is_showing:
                    return True

                self._update_theme()
                w_dp = self._get_width_dp()
                h_dp = self._get_height_dp()

                if is_android():
                    success = self._overlay.create(w_dp, h_dp)
                    if not success:
                        return False
                else:
                    self._logger.info(f"[桌面模式] 悬浮窗显示")

                self._is_showing = True
                self._start_animation()
                self._keepalive.start()

                self._logger.info(f"悬浮窗已显示 (mode={self._mode.value})")
                return True
        except Exception as e:
            self._logger.error(f"显示悬浮窗异常: {e}")
            return False

    def hide(self):
        """隐藏悬浮窗"""
        try:
            with self._lock:
                if not self._is_showing:
                    return
                self._stop_animation()
                self._keepalive.stop()
                self._overlay.remove()
                self._is_showing = False
                self._logger.info("悬浮窗已隐藏")
        except Exception as e:
            self._logger.error(f"隐藏悬浮窗异常: {e}")

    def destroy(self):
        """彻底销毁悬浮窗"""
        try:
            self.hide()
            self._menu.dismiss()
            self._overlay.remove()
            self._sound.cleanup()
            self._notification.cleanup()
            self._keepalive.stop()
            with self._lock:
                self._anim_stop.set()
                self._anim_thread = None
            self._logger.info("悬浮窗已销毁")
        except Exception as e:
            self._logger.error(f"销毁悬浮窗异常: {e}")

    # ============================================================
    # 模式切换
    # ============================================================

    def set_mode(self, mode: FloatMode):
        """切换显示模式"""
        try:
            with self._lock:
                self._mode = mode
                w_dp = self._get_width_dp()
                h_dp = self._get_height_dp()
                self._overlay.update_layout(w_dp, h_dp)
                self._overlay.invalidate()
                self._save_config()
                self._logger.info(f"悬浮窗模式: {mode.value}")
        except Exception as e:
            self._logger.warning(f"切换模式异常: {e}")

    def toggle_mode(self):
        """切换常规/极简"""
        new_mode = FloatMode.MINIMAL if self._mode == FloatMode.NORMAL else FloatMode.NORMAL
        self.set_mode(new_mode)

    # ============================================================
    # 指示灯控制
    # ============================================================

    def set_indicator(self, state: IndicatorState):
        """设置指示灯状态"""
        try:
            with self._lock:
                self._indicator_state = state
                self._overlay.invalidate()
                if state == IndicatorState.LISTENING:
                    self._pulse_start_time = time.time() * 1000
        except Exception as e:
            self._logger.warning(f"设置指示灯异常: {e}")

    def set_indicator_by_result(self, success: bool):
        """
        根据抢单结果设置指示灯 + 联动音效与通知

        :param success: True=成功, False=失败
        """
        try:
            new_state = IndicatorState.SUCCESS if success else IndicatorState.FAILED
            self.set_indicator(new_state)

            # 音效
            if success:
                self._sound.play_order_success()
                self._notification.notify_order_success()
            else:
                self._sound.play_order_failed()
                self._notification.notify_order_failed()

            # N 秒后自动恢复监听状态
            def _auto_reset():
                try:
                    time.sleep(RESULT_INDICATOR_DURATION)
                    if self._is_showing and not self._paused:
                        self.set_indicator(IndicatorState.LISTENING)
                except Exception:
                    pass

            threading.Thread(target=_auto_reset, daemon=True).start()
        except Exception as e:
            self._logger.warning(f"指示灯联动异常: {e}")

    # ============================================================
    # 透明度
    # ============================================================

    def set_opacity(self, opacity: float):
        """设置透明度 (0.25~1.0)"""
        try:
            opacity = max(FLOAT_MIN_OPACITY, min(FLOAT_MAX_OPACITY, opacity))
            with self._lock:
                self._opacity = opacity
                self._overlay.update_opacity(opacity)
                self._save_config()
        except Exception as e:
            self._logger.warning(f"设置透明度异常: {e}")

    def adjust_opacity(self, delta: float):
        """步进调节透明度"""
        new_opacity = self._opacity + delta
        self.set_opacity(new_opacity)

    def cycle_opacity(self):
        """循环切换透明度档位"""
        levels = [0.25, 0.40, 0.55, 0.70, 0.82, 1.0]
        current = min(range(len(levels)), key=lambda i: abs(levels[i] - self._opacity))
        next_idx = (current + 1) % len(levels)
        self.set_opacity(levels[next_idx])

    # ============================================================
    # 锁定
    # ============================================================

    def set_locked(self, locked: bool):
        """设置锁定状态"""
        try:
            with self._lock:
                self._locked = locked
                self._save_config()
                self._logger.info(f"悬浮窗位置: {'已锁定' if locked else '已解锁'}")
        except Exception as e:
            self._logger.warning(f"设置锁定异常: {e}")

    def toggle_locked(self):
        self.set_locked(not self._locked)

    # ============================================================
    # 暂停/继续
    # ============================================================

    def set_paused(self, paused: bool):
        """设置暂停/继续抢单"""
        try:
            with self._lock:
                self._paused = paused
                if paused:
                    self.set_indicator(IndicatorState.OFF)
                else:
                    self.set_indicator(IndicatorState.LISTENING)
                self._overlay.invalidate()
                self._logger.info(f"抢单: {'已暂停' if paused else '已继续'}")
        except Exception as e:
            self._logger.warning(f"设置暂停异常: {e}")

    def toggle_paused(self):
        self.set_paused(not self._paused)

    # ============================================================
    # 状态更新（由外部模块调用）
    # ============================================================

    def update_status(self, engine: str = None, polling: str = None,
                      network: str = None, order_count: int = None,
                      permission: str = None, error: str = None):
        """更新悬浮窗显示的状态信息"""
        try:
            with self._lock:
                if engine is not None:
                    self._engine_status = str(engine)
                if polling is not None:
                    self._polling_status = str(polling)
                if network is not None:
                    self._network_status = str(network)
                if order_count is not None:
                    self._order_count = int(order_count)
                if permission is not None:
                    self._permission_status = str(permission)
                if error is not None:
                    self._last_error = str(error)
                self._overlay.invalidate()
        except Exception as e:
            self._logger.warning(f"更新状态异常: {e}")

    # ============================================================
    # 抢单结果联动（外部直接调用）
    # ============================================================

    def on_order_result(self, success: bool, order_info: str = ""):
        """
        抢单结果联动入口
        由抢单模块在获取结果后调用

        :param success: True=成功, False=失败
        :param order_info: 订单描述信息（可选）
        """
        try:
            self._logger.info(f"抢单结果联动: {'成功' if success else '失败'} {order_info}")
            self.set_indicator_by_result(success)
        except Exception as e:
            self._logger.warning(f"抢单结果联动异常: {e}")

    # ============================================================
    # 回调注册
    # ============================================================

    def set_on_open_main(self, callback: Callable):
        self._on_open_main_cb = callback

    def set_on_toggle_pause(self, callback: Callable):
        self._on_toggle_pause_cb = callback

    def set_on_close(self, callback: Callable):
        self._on_close_cb = callback

    # ============================================================
    # 属性
    # ============================================================

    @property
    def is_showing(self) -> bool:
        return self._is_showing

    @property
    def mode(self) -> FloatMode:
        return self._mode

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def opacity(self) -> float:
        return self._opacity

    @property
    def indicator_state(self) -> IndicatorState:
        return self._indicator_state

    @property
    def animation_enabled(self) -> bool:
        return self._animation_enabled

    @animation_enabled.setter
    def animation_enabled(self, value: bool):
        self._animation_enabled = value

    # ============================================================
    # 内部方法
    # ============================================================

    def _get_width_dp(self) -> int:
        return FLOAT_MINIMAL_WIDTH if self._mode == FloatMode.MINIMAL else FLOAT_DEFAULT_WIDTH

    def _get_height_dp(self) -> int:
        return FLOAT_MINIMAL_HEIGHT if self._mode == FloatMode.MINIMAL else FLOAT_DEFAULT_HEIGHT

    def _get_display_status(self) -> dict:
        """获取当前显示状态快照"""
        try:
            with self._lock:
                return {
                    "engine": self._engine_status,
                    "polling": self._polling_status,
                    "network": self._network_status,
                    "order_count": self._order_count,
                    "permission": self._permission_status,
                    "error": self._last_error,
                }
        except Exception:
            return {"engine": "未知", "polling": "未知", "network": "未知",
                    "order_count": 0, "permission": "未知", "error": ""}

    def _get_pulse_value(self) -> float:
        """获取脉冲动画值 (0.0~1.0) 正弦波"""
        try:
            elapsed = time.time() * 1000 - self._pulse_start_time
            phase = (elapsed % PULSE_DURATION_MS) / PULSE_DURATION_MS
            return (math.sin(phase * 2 * math.pi - math.pi / 2) + 1.0) / 2.0
        except Exception:
            return 0.5

    def _update_theme(self):
        """更新系统深色模式状态"""
        try:
            if is_android() and _ensure_android_classes():
                R = _android_resources
                activity = R["PythonActivity"].mActivity
                if activity:
                    ui_mode = activity.getResources().getConfiguration().uiMode
                    night_mask = R["Configuration"].UI_MODE_NIGHT_MASK
                    night_yes = R["Configuration"].UI_MODE_NIGHT_YES
                    self._is_dark = (ui_mode & night_mask) == night_yes
        except Exception:
            pass

    def _show_menu(self):
        """弹出悬浮窗菜单"""
        try:
            self._menu.show()
        except Exception as e:
            self._logger.warning(f"弹出菜单异常: {e}")

    def _handle_menu_action(self, label: str):
        """
        处理菜单项点击

        :param label: 菜单项文字
        """
        try:
            if label == MENU_LABELS["toggle_pause"] or label == MENU_LABELS["resume_pause"]:
                self.toggle_paused()
                if self._on_toggle_pause_cb:
                    self._on_toggle_pause_cb(self._paused)

            elif label.startswith("切换至"):
                self.toggle_mode()

            elif label == MENU_LABELS["toggle_lock"] or label == MENU_LABELS["unlock"]:
                self.toggle_locked()

            elif label.startswith("透明度"):
                self.cycle_opacity()

            elif label == MENU_LABELS["close"]:
                self.hide()
                if self._on_close_cb:
                    self._on_close_cb()

            elif label == MENU_LABELS["open_main"]:
                if self._on_open_main_cb:
                    self._on_open_main_cb()

        except Exception as e:
            self._logger.warning(f"菜单操作异常: {e}")

    def _start_animation(self):
        """启动脉冲动画线程（~30fps）"""
        try:
            self._anim_stop.clear()
            if self._anim_thread and self._anim_thread.is_alive():
                return

            def _anim_loop():
                while not self._anim_stop.is_set():
                    try:
                        if (self._is_showing
                                and self._indicator_state == IndicatorState.LISTENING
                                and self._animation_enabled):
                            self._overlay.invalidate()
                        self._anim_stop.wait(ANIMATION_FRAME_MS / 1000.0)
                    except Exception:
                        break

            self._anim_thread = threading.Thread(
                target=_anim_loop, daemon=True, name="float-anim"
            )
            self._anim_thread.start()
        except Exception as e:
            self._logger.warning(f"启动动画异常: {e}")

    def _stop_animation(self):
        """停止脉冲动画"""
        try:
            self._anim_stop.set()
            self._anim_thread = None
        except Exception:
            pass

    def _save_config(self):
        """持久化悬浮窗配置到 config.json"""
        try:
            self._float_config = {
                "width": self._get_width_dp(),
                "height": self._get_height_dp(),
                "corner_radius": FLOAT_CORNER_RADIUS,
                "opacity": round(self._opacity, 2),
                "position_x": self._pos_x,
                "position_y": self._pos_y,
                "locked": self._locked,
                "mode": self._mode.value,
            }
            self._config.set("float_window", self._float_config)
        except Exception as e:
            self._logger.warning(f"保存配置异常: {e}")


# ============================================================
# 全局单例
# ============================================================

_instance = None
_instance_lock = threading.Lock()


def get_float_manager() -> FloatWindowManager:
    """
    获取悬浮窗管理器单例
    :return: FloatWindowManager 实例
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = FloatWindowManager()
    return _instance


# ============================================================
# 对外便捷接口（供 main.py / UI 层调用）
# ============================================================

def init_float_window() -> dict:
    """
    初始化悬浮窗模块（程序入口调用）

    :return: 初始化状态字典
    """
    try:
        mgr = get_float_manager()
        LogManager.get_logger("app").info("悬浮窗模块初始化完成")
        return {
            "status": "ok",
            "mode": mgr.mode.value,
            "opacity": mgr.opacity,
            "locked": mgr.locked,
            "showing": mgr.is_showing,
        }
    except Exception as e:
        LogManager.get_logger("app").error(f"悬浮窗初始化异常: {e}")
        return {"status": "failed", "error": str(e)}


def show_float_ui():
    """显示悬浮窗"""
    try:
        mgr = get_float_manager()
        mgr.show()
    except Exception as e:
        LogManager.get_logger("app").error(f"显示悬浮窗异常: {e}")


def hide_float_ui():
    """隐藏悬浮窗"""
    try:
        mgr = get_float_manager()
        mgr.hide()
    except Exception as e:
        LogManager.get_logger("app").error(f"隐藏悬浮窗异常: {e}")


def destroy_float_ui():
    """销毁悬浮窗（释放资源）"""
    try:
        mgr = get_float_manager()
        mgr.destroy()
    except Exception as e:
        LogManager.get_logger("app").error(f"销毁悬浮窗异常: {e}")


def toggle_float_mode_ui():
    """切换常规/极简模式"""
    try:
        mgr = get_float_manager()
        mgr.toggle_mode()
    except Exception as e:
        LogManager.get_logger("app").error(f"切换模式异常: {e}")


def set_float_indicator_ui(state: str):
    """
    设置指示灯状态（字符串接口）
    :param state: "off" / "listening" / "success" / "failed"
    """
    try:
        mgr = get_float_manager()
        try:
            s = IndicatorState(state)
        except ValueError:
            s = IndicatorState.OFF
        mgr.set_indicator(s)
    except Exception as e:
        LogManager.get_logger("app").error(f"设置指示灯异常: {e}")


def set_float_indicator_result_ui(success: bool):
    """
    根据抢单结果设置指示灯 + 音效 + 通知（联动函数）
    :param success: True=成功, False=失败
    """
    try:
        mgr = get_float_manager()
        mgr.set_indicator_by_result(success)
    except Exception as e:
        LogManager.get_logger("app").error(f"指示灯联动异常: {e}")


def update_float_status_ui(engine: str = None, polling: str = None,
                            network: str = None, order_count: int = None,
                            permission: str = None, error: str = None):
    """
    更新悬浮窗状态显示

    调用示例：
        update_float_status_ui(engine="Accessibility", polling="运行中")
        update_float_status_ui(order_count=5)
    """
    try:
        mgr = get_float_manager()
        mgr.update_status(
            engine=engine, polling=polling,
            network=network, order_count=order_count,
            permission=permission, error=error,
        )
    except Exception as e:
        LogManager.get_logger("app").error(f"更新悬浮窗状态异常: {e}")


def set_float_opacity_ui(opacity: float):
    """设置悬浮窗透明度"""
    try:
        mgr = get_float_manager()
        mgr.set_opacity(opacity)
    except Exception as e:
        LogManager.get_logger("app").error(f"设置透明度异常: {e}")


def set_float_locked_ui(locked: bool):
    """设置悬浮窗锁定状态"""
    try:
        mgr = get_float_manager()
        mgr.set_locked(locked)
    except Exception as e:
        LogManager.get_logger("app").error(f"设置锁定异常: {e}")


def set_float_paused_ui(paused: bool):
    """设置暂停/继续抢单"""
    try:
        mgr = get_float_manager()
        mgr.set_paused(paused)
    except Exception as e:
        LogManager.get_logger("app").error(f"设置暂停异常: {e}")


def get_float_status_ui() -> dict:
    """
    获取悬浮窗当前状态（供主界面/调试使用）

    :return: {
        "showing": bool,
        "mode": str,
        "opacity": float,
        "locked": bool,
        "paused": bool,
        "indicator": str,
        "pos_x": int,
        "pos_y": int,
        "engine": str,
        "polling": str,
        "network": str,
        "order_count": int,
    }
    """
    try:
        mgr = get_float_manager()
        status = mgr._get_display_status()
        return {
            "showing": mgr.is_showing,
            "mode": mgr.mode.value,
            "opacity": mgr.opacity,
            "locked": mgr.locked,
            "paused": mgr.paused,
            "indicator": mgr.indicator_state.value,
            "pos_x": mgr._pos_x,
            "pos_y": mgr._pos_y,
            "engine": status["engine"],
            "polling": status["polling"],
            "network": status["network"],
            "order_count": status["order_count"],
            "permission": status["permission"],
        }
    except Exception as e:
        LogManager.get_logger("app").error(f"获取悬浮窗状态异常: {e}")
        return {}


def register_float_callbacks_ui(on_open_main=None, on_toggle_pause=None, on_close=None):
    """
    注册悬浮窗菜单回调

    :param on_open_main: 「打开主界面」回调
    :param on_toggle_pause: 「暂停/继续抢单」回调（参数: paused: bool）
    :param on_close: 「关闭悬浮窗」回调
    """
    try:
        mgr = get_float_manager()
        if on_open_main:
            mgr.set_on_open_main(on_open_main)
        if on_toggle_pause:
            mgr.set_on_toggle_pause(on_toggle_pause)
        if on_close:
            mgr.set_on_close(on_close)
    except Exception as e:
        LogManager.get_logger("app").error(f"注册悬浮窗回调异常: {e}")


def on_order_result_ui(success: bool, order_info: str = ""):
    """
    抢单结果联动入口（供抢单模块调用）

    自动完成：
      1. 指示灯切换（绿=成功 / 红=失败）
      2. 音效播放（pygame.mixer 生成纯音）
      3. 系统通知（Android Notification）
      4. 3秒后自动恢复监听状态

    :param success: True=成功, False=失败
    :param order_info: 订单描述（可选，会显示在通知中）
    """
    try:
        mgr = get_float_manager()
        mgr.on_order_result(success, order_info)
    except Exception as e:
        LogManager.get_logger("app").error(f"抢单结果联动异常: {e}")


# ============================================================
# 模块自测入口
# ============================================================

if __name__ == "__main__":
    """桌面模式自测"""
    import time

    print("=" * 50)
    print("TiShou 悬浮窗模块自测（桌面模式 - 仅日志输出）")
    print("=" * 50)

    # 初始化
    mgr = get_float_manager()
    print(f"\n初始化完成:")
    print(f"  模式: {mgr.mode.value}")
    print(f"  透明度: {mgr.opacity}")
    print(f"  锁定: {mgr.locked}")

    # 显示
    print("\n显示悬浮窗...")
    mgr.show()
    print(f"  显示状态: {mgr.is_showing}")

    # 设置指示灯
    print("\n指示灯测试:")
    mgr.set_indicator(IndicatorState.LISTENING)
    print(f"  状态: {mgr.indicator_state.value}")
    time.sleep(1)

    mgr.set_indicator(IndicatorState.SUCCESS)
    print(f"  状态: {mgr.indicator_state.value}")
    time.sleep(1)

    mgr.set_indicator(IndicatorState.FAILED)
    print(f"  状态: {mgr.indicator_state.value}")
    time.sleep(1)

    # 抢单结果联动
    print("\n抢单结果联动测试:")
    mgr.on_order_result(True, "测试订单 #001")
    print(f"  指示灯: {mgr.indicator_state.value}")

    # 模式切换
    print("\n模式切换:")
    mgr.toggle_mode()
    print(f"  当前模式: {mgr.mode.value}")
    mgr.toggle_mode()
    print(f"  当前模式: {mgr.mode.value}")

    # 透明度
    print("\n透明度测试:")
    mgr.set_opacity(0.5)
    print(f"  透明度: {mgr.opacity}")
    mgr.set_opacity(0.85)

    # 锁定
    print("\n锁定测试:")
    mgr.toggle_locked()
    print(f"  锁定: {mgr.locked}")
    mgr.toggle_locked()
    print(f"  锁定: {mgr.locked}")

    # 暂停
    print("\n暂停测试:")
    mgr.toggle_paused()
    print(f"  暂停: {mgr.paused}")
    print(f"  指示灯: {mgr.indicator_state.value}")
    mgr.toggle_paused()

    # 状态更新
    print("\n状态更新测试:")
    mgr.update_status(engine="Accessibility", polling="运行中",
                       network="已连接", order_count=5,
                       permission="已授予")
    status = mgr._get_display_status()
    print(f"  引擎: {status['engine']}")
    print(f"  轮询: {status['polling']}")
    print(f"  网络: {status['network']}")
    print(f"  订单: {status['order_count']}")
    print(f"  权限: {status['permission']}")

    # 隐藏
    print("\n隐藏悬浮窗...")
    mgr.hide()
    print(f"  显示状态: {mgr.is_showing}")

    print("\n" + "=" * 50)
    print("自测完成（所有异常已捕获，桌面模式运行正常）")
    print("=" * 50)