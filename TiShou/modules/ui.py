# -*- coding: utf-8 -*-
"""
UI 模块（第12步：Kivy 全套界面）
=================================
HyperOS + iOS 融合风，4 页面完整实现。

页面顺序：
  ① 免责页 → ② 卡密验证页 → ③ 加载进度页 → ④ 主设置页

风格规范：
  - 主卡片 18~22dp 圆角，按钮胶囊圆角
  - 背景色 #F2F2F7
  - 深浅主题跟随系统
  - 弥散模糊、弹性动画（可关闭）
  - 全量异常捕获，绝不闪退
"""

import sys
import os
import json
import threading
import math
from datetime import datetime
from typing import Optional, Callable, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.utils import (
    LogManager, ConfigManager, ExceptionUtil,
    safe_int, safe_float, safe_str, DEFAULT_CONFIG,
)

# ---- Kivy 核心导入（模块级，供子类继承使用） ----
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.screenmanager import Screen
from kivy.uix.widget import Widget


# ============================================================
# 风格常量
# ============================================================
class StyleConstants:
    """UI 风格常量（HyperOS + iOS 融合风）"""

    # ---- 颜色 ----
    BACKGROUND_COLOR = "#F2F2F7"
    CARD_COLOR_LIGHT = "#FFFFFF"
    CARD_COLOR_DARK = "#1C1C1E"
    TEXT_PRIMARY_LIGHT = "#000000"
    TEXT_PRIMARY_DARK = "#FFFFFF"
    TEXT_SECONDARY_LIGHT = "#8E8E93"
    TEXT_SECONDARY_DARK = "#EBEBF5"
    ACCENT_COLOR = "#007AFF"
    DANGER_COLOR = "#FF3B30"
    SUCCESS_COLOR = "#34C759"
    WARNING_COLOR = "#FF9500"
    SEPARATOR_COLOR_LIGHT = "#C6C6C8"
    SEPARATOR_COLOR_DARK = "#38383A"
    SHADOW_COLOR = "rgba(0,0,0,0.08)"
    FROST_GLASS = "rgba(255,255,255,0.6)"

    # ---- 圆角 ----
    CARD_RADIUS_DP = 20
    BUTTON_RADIUS_DP = 25
    FLOAT_WIN_RADIUS_DP = 16
    INPUT_RADIUS_DP = 12
    PROGRESS_RADIUS_DP = 10

    # ---- 尺寸 ----
    CARD_PADDING_DP = 16
    BUTTON_HEIGHT_DP = 44
    INPUT_HEIGHT_DP = 40
    ICON_SIZE_DP = 24
    SECTION_SPACING_DP = 12

    # ---- 动画 ----
    ANIM_DURATION_SHORT = 0.15
    ANIM_DURATION_NORMAL = 0.3
    ANIM_DURATION_LONG = 0.5
    ELASTIC_DAMPING = 0.6
    ELASTIC_STIFFNESS = 200


# ============================================================
# 主题管理器
# ============================================================
class ThemeManager:
    """深浅主题管理器"""

    def __init__(self):
        self._logger = LogManager.get_logger("app")
        self._config = ConfigManager()
        self._theme_config = self._config.get("theme", {})
        self._is_dark = self._theme_config.get("dark_mode", False)
        self._follow_system = self._theme_config.get("follow_system", True)
        self._anim_enabled = self._theme_config.get("animation_enabled", True)
        self._listeners: list = []

    @property
    def is_dark(self) -> bool:
        return self._is_dark

    @property
    def animation_enabled(self) -> bool:
        return self._anim_enabled

    def toggle_theme(self):
        """切换深浅主题"""
        try:
            self._is_dark = not self._is_dark
            self._theme_config["dark_mode"] = self._is_dark
            self._config.set("theme", self._theme_config)
            self._notify()
        except Exception as e:
            self._logger.error(f"切换主题失败: {e}")

    def set_animation(self, enabled: bool):
        """开关动画"""
        try:
            self._anim_enabled = enabled
            self._theme_config["animation_enabled"] = enabled
            self._config.set("theme", self._theme_config)
        except Exception as e:
            self._logger.error(f"设置动画开关失败: {e}")

    def add_listener(self, callback: Callable):
        """添加主题变更监听"""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def _notify(self):
        """通知所有监听器"""
        for cb in self._listeners:
            try:
                cb(self._is_dark)
            except Exception:
                pass

    # ---- 颜色获取 ----
    def bg(self) -> str:
        return self._card_bg()

    def card_bg(self) -> str:
        return "#1C1C1E" if self._is_dark else "#FFFFFF"

    def text_primary(self) -> str:
        return "#FFFFFF" if self._is_dark else "#000000"

    def text_secondary(self) -> str:
        return "#EBEBF5" if self._is_dark else "#8E8E93"

    def separator(self) -> str:
        return "#38383A" if self._is_dark else "#C6C6C8"

    def page_bg(self) -> str:
        return "#000000" if self._is_dark else "#F2F2F7"

    def _card_bg(self) -> str:
        return "#1C1C1E" if self._is_dark else "#FFFFFF"


# ============================================================
# 工具函数
# ============================================================
def dp_to_px(dp_value: float, density: float = 1.0) -> float:
    """dp 转 px（安卓适配）"""
    try:
        return dp_value * density
    except Exception:
        return dp_value


def hex_to_rgba(hex_color: str, alpha: float = 1.0) -> tuple:
    """十六进制颜色转 RGBA 元组"""
    try:
        hex_color = hex_color.lstrip("#")
        r = int(hex_color[0:2], 16) / 255.0
        g = int(hex_color[2:4], 16) / 255.0
        b = int(hex_color[4:6], 16) / 255.0
        return (r, g, b, alpha)
    except Exception:
        return (0.949, 0.949, 0.969, 1.0)


# ============================================================
# 全局单例
# ============================================================
_theme_manager = None


def get_theme_manager() -> ThemeManager:
    """获取主题管理器单例"""
    global _theme_manager
    if _theme_manager is None:
        _theme_manager = ThemeManager()
    return _theme_manager


# ============================================================
# Kivy 界面（4 页面）
# ============================================================

class TiShouUI:
    """
    TiShou 主 UI：4 页面 Kivy 应用

    页面流程：
      免责(disclaimer) → 卡密验证(activation) → 加载(loading) → 主设置(main)

    每页全量异常防护，销毁立即释放资源。
    """

    def __init__(self, biz_app=None):
        self._logger = LogManager.get_logger("app")
        self._error_logger = LogManager.get_logger("error")
        self._config = ConfigManager()
        self._theme = get_theme_manager()
        self._app = None
        self._screen_manager = None
        self._widgets_cache = {}
        self._biz_app = biz_app

    # ----------------------------------------------------------
    # Kivy 配置
    # ----------------------------------------------------------
    def _configure_kivy(self):
        """Kivy 环境预配置（Android 适配版）"""
        try:
            os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")
            os.environ.setdefault("KIVY_ORIENTATION", "Portrait")
            # ❌ 不设置 KIVY_METRICS_DENSITY，让 Kivy 自动检测屏幕密度

            from kivy.config import Config
            Config.set("kivy", "log_level", "warning")
            # Android 上 fullscreen=auto 由 buildozer.spec 的 fullscreen=0 控制
            # 不在代码中额外设置，避免冲突
            Config.set("graphics", "resizable", False)
            # ❌ 不要设置 borderless=1（在 Android SDL2 后端会导致渲染异常黑屏）
            Config.set("input", "mouse", "mouse,disable_multitouch")
        except Exception as e:
            self._logger.warning(f"Kivy 配置异常: {e}")

    # ----------------------------------------------------------
    # 运行入口
    # ----------------------------------------------------------
    def run(self):
        """启动 UI（在主线程调用）"""
        try:
            self._logger.info("正在启动 UI（HyperOS + iOS 融合风）...")
            self._configure_kivy()

            from kivy.app import App
            from kivy.uix.screenmanager import ScreenManager, SlideTransition
            from kivy.core.window import Window

            # 存储引用供内部方法访问
            self._ui_app_ref = None
            self._sm_ref = None

            class TiShouApp(App):
                """Kivy 主应用"""

                def build(self):
                    try:
                        sm = ScreenManager()
                        sm.transition = SlideTransition(
                            duration=0.35
                        )
                        # ❌ 不在 ScreenManager 上设背景（各 Screen 自己负责背景，
                        #    双重背景在 Android SDL2 后端可能导致渲染异常）
                        Window.bind(on_keyboard=self._on_keyboard)

                        # 添加 4 个页面
                        from kivy.uix.screenmanager import Screen
                        sm.add_widget(DisclaimerScreen(name="disclaimer"))
                        sm.add_widget(ActivationScreen(name="activation"))
                        sm.add_widget(LoadingScreen(name="loading"))
                        sm.add_widget(MainSettingsScreen(name="main"))

                        # ✅ 从加载页开始，Kivy 渲染后再后台冷启动
                        sm.current = "loading"
                        self.sm = sm
                        # 存储引用到外部
                        self._outer()._sm_ref = sm
                        self._outer()._ui_app_ref = self
                        return sm
                    except Exception as e:
                        self._log_error(f"构建 UI 失败: {e}")
                        from kivy.uix.label import Label
                        return Label(text=f"启动失败: {e}")

                def _outer(self):
                    """获取外层 TiShouUI 实例"""
                    return self._outer_instance

                def on_start(self):
                    """Kivy 渲染完成后调度后台冷启动"""
                    try:
                        from kivy.clock import Clock
                        # 先让 LoadingScreen 启动自己的占位动画
                        loading = self._get_loading_screen()
                        if loading:
                            loading.start_loading()
                        # 0.5 秒后启动后台冷启动
                        Clock.schedule_once(lambda dt: self._begin_cold_start(), 0.5)
                    except Exception as e:
                        self._log_error(f"调度冷启动失败: {e}")

                def _begin_cold_start(self):
                    """在后台线程执行完整冷启动"""
                    import threading
                    t = threading.Thread(target=self._cold_start_runner, daemon=True)
                    t.start()

                def _cold_start_runner(self):
                    """
                    后台冷启动线程：
                    1. 获取 biz_app 实例（优先使用传入的引用）
                    2. 注册进度回调到 TiShouApp（业务逻辑）
                    3. 调用 biz_app.start()
                    4. 完成后切换到对应页面
                    5. 触发权限申请流程
                    """
                    try:
                        # ---- 获取业务 App 单例 ----
                        biz_app = None
                        # 优先使用传入的引用（最可靠，避免 __main__ 问题）
                        _outer = self._outer()
                        if _outer and hasattr(_outer, "_biz_app") and _outer._biz_app is not None:
                            biz_app = _outer._biz_app
                        else:
                            # 兜底：尝试从 __main__ 获取
                            import sys as _sys
                            _main_mod = _sys.modules.get("__main__")
                            if _main_mod and hasattr(_main_mod, "get_app"):
                                biz_app = _main_mod.get_app()
                            else:
                                # 最后兜底：导入 main 模块
                                _sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
                                from main import get_app as _get_app
                                biz_app = _get_app()

                        if biz_app is None:
                            self._log_error("无法获取 biz_app 实例，冷启动中止")
                            return

                        from kivy.clock import Clock

                        def _progress_cb(stage, name, event, ok, progress=None):
                            """冷启动阶段回调 → 更新 LoadingScreen
                            :param progress: 可选，直接指定进度百分比（0-100），
                                             若为 None 则只更新状态文字不改变进度
                            """
                            def _update(dt):
                                try:
                                    loading = self._get_loading_screen()
                                    if loading:
                                        if progress is not None:
                                            loading._update_progress(progress, name)
                                        elif name:
                                            loading._update_status_text(name)
                                except Exception:
                                    pass
                            try:
                                Clock.schedule_once(_update, 0)
                            except Exception:
                                pass

                        biz_app.register_progress_callback("kivy_ui", _progress_cb)

                        # ---- 执行冷启动 ----
                        self._log_info("后台冷启动开始...")
                        ok = biz_app.start()
                        self._log_info(f"后台冷启动完成, ok={ok}")

                        # ---- 完成后切换页面 ----
                        def _after_cold_start(dt):
                            try:
                                loading = self._get_loading_screen()
                                if loading:
                                    loading._update_progress(100, "准备就绪")
                                    loading._cold_start_done = True

                                # 判断跳转到免责页还是主设置页
                                try:
                                    eula_accepted = biz_app.config.get("eula_accepted", False)
                                except Exception:
                                    eula_accepted = False

                                if eula_accepted:
                                    target = "main"
                                else:
                                    target = "disclaimer"

                                self._log_info(f"冷启动完成，跳转到 {target}")
                                self.sm.current = target

                                # 触发权限申请流程（延迟 1 秒避免与页面切换冲突）
                                from kivy.clock import Clock as _Clock
                                _Clock.schedule_once(
                                    lambda dt2: self._trigger_permission_flow(), 1.0
                                )
                            except Exception as exc:
                                self._log_error(f"冷启动后跳转异常: {exc}")
                                # 兜底：直接跳转到主设置页
                                try:
                                    self.sm.current = "main"
                                except Exception:
                                    pass

                        import time
                        time.sleep(0.3)
                        try:
                            Clock.schedule_once(_after_cold_start, 0)
                        except Exception:
                            pass

                    except Exception as exc:
                        self._log_error(f"冷启动线程异常: {exc}")
                        import traceback
                        self._log_error(traceback.format_exc())
                        # 冷启动失败也跳转到主设置页（而非卡死在加载页）
                        from kivy.clock import Clock as _Clock2
                        def _fallback(dt):
                            try:
                                loading = self._get_loading_screen()
                                if loading:
                                    loading._update_progress(0, f"启动异常: {exc}")
                                    loading._cold_start_done = True
                                # 尝试跳转到设置页
                                try:
                                    self.sm.current = "main"
                                    # 即使冷启动失败也尝试触发权限申请
                                    from kivy.clock import Clock as _Clock3
                                    _Clock3.schedule_once(
                                        lambda dt2: self._trigger_permission_flow(), 1.5
                                    )
                                except Exception:
                                    pass
                            except Exception:
                                pass
                        try:
                            _Clock2.schedule_once(_fallback, 0.5)
                        except Exception:
                            pass

                def _trigger_permission_flow(self):
                    """触发分步权限申请流程（异步，不阻塞 UI）"""
                    try:
                        import threading
                        def _run_perm_flow():
                            try:
                                from modules.permission import start_permission_flow
                                start_permission_flow()
                            except Exception as exc:
                                self._log_error(f"权限申请流程异常: {exc}")
                        t = threading.Thread(target=_run_perm_flow, daemon=True)
                        t.start()
                        self._log_info("权限申请流程已触发")
                    except Exception as e:
                        self._log_error(f"触发权限申请失败: {e}")

                def _log_info(self, msg):
                    try:
                        LogManager.get_logger("app").info(msg)
                    except Exception:
                        pass

                def _get_loading_screen(self):
                    """获取 LoadingScreen 实例"""
                    try:
                        if hasattr(self, "sm"):
                            return self.sm.get_screen("loading")
                    except Exception:
                        pass
                    return None

                def _calc_stage_progress(self, stage):
                    """根据启动阶段计算进度百分比"""
                    stages_map = {
                        "init": 5,
                        "network_check": 15,
                        "permission_check": 25,
                        "disclaimer": 35,
                        "activation": 45,
                        "resource_load": 60,
                        "ocr_load": 70,
                        "material_update": 80,
                        "services_start": 90,
                        "completed": 100,
                    }
                    try:
                        return stages_map.get(stage, 0)
                    except Exception:
                        return 0

                def _on_keyboard(self, window, key, scancode, codepoint, modifier):
                    """全局拦截返回键"""
                    try:
                        from kivy.core.window import Keycode
                        if key == Keycode.back or key == 27:
                            current = self.sm.current if hasattr(self, "sm") else None
                            if current == "disclaimer":
                                return True  # 免责页不让返回
                            return False
                    except Exception:
                        pass
                    return False

                def _log_error(self, msg):
                    try:
                        LogManager.get_logger("error").error(msg)
                    except Exception:
                        pass

                def on_pause(self):
                    return True

                def on_resume(self):
                    pass

            self._app = TiShouApp()
            # 将外部实例注入内部类，避免闭包问题
            self._app._outer_instance = self
            self._app.run()

        except ImportError as e:
            self._logger.error(f"Kivy 导入失败（仅安卓真机支持）: {e}")
            print(f"[TiShou] Kivy 不可用，UI 无法启动: {e}")
        except Exception as e:
            self._logger.error(f"UI 启动异常: {e}")
            print(f"[TiShou] UI 启动失败: {e}")


# ============================================================
# 自定义 Kivy 组件
# ============================================================

def _card_box(**kwargs):
    """创建圆角卡片容器（18~22dp 圆角）"""
    from kivy.uix.boxlayout import BoxLayout
    return BoxLayout(**kwargs)


class CardContainer(BoxLayout):
    """圆角卡片容器（带弥散阴影）"""

    def __init__(self, radius=StyleConstants.CARD_RADIUS_DP, **kwargs):
        super().__init__(**kwargs)
        self._radius = radius
        self._shadow_visible = True
        self.bind(pos=self._update_canvas, size=self._update_canvas)

    def _update_canvas(self, *args):
        try:
            self.canvas.before.clear()
            theme = get_theme_manager()
            with self.canvas.before:
                from kivy.graphics import Color, RoundedRectangle
                bg = theme.card_bg()
                r, g, b, a = hex_to_rgba(bg)
                Color(r, g, b, a)
                RoundedRectangle(
                    pos=self.pos, size=self.size,
                    radius=[self._radius] * 4
                )
        except Exception:
            pass


class CapsuleButton(Button):
    """胶囊圆角按钮"""

    def __init__(self, text="", color=StyleConstants.ACCENT_COLOR,
                 text_color="#FFFFFF", **kwargs):
        super().__init__(**kwargs)
        self._bg_color = color
        self._text_col = text_color
        self._radius = StyleConstants.BUTTON_RADIUS_DP
        self.text = text
        self.size_hint_y = None
        self.height = dp_to_px(StyleConstants.BUTTON_HEIGHT_DP)
        self.bind(pos=self._redraw, size=self._redraw)

    def _redraw(self, *args):
        try:
            self.canvas.before.clear()
            self.canvas.after.clear()
            with self.canvas.before:
                from kivy.graphics import Color, RoundedRectangle
                r, g, b, a = hex_to_rgba(self._bg_color)
                Color(r, g, b, a)
                RoundedRectangle(
                    pos=self.pos, size=self.size,
                    radius=[self._radius] * 4
                )
        except Exception:
            pass


# ============================================================
# ① 免责页
# ============================================================
class DisclaimerScreen(Screen):
    """免责声明页——必须同意才能继续，拦截返回键"""

    eula_text = (
        "【TiShou 替手 — 用户协议与隐私声明】\n"
        "\n"
        "欢迎使用 TiShou 替手（以下简称“本软件”）。请您务必仔细阅读并充分理解本协议各条款内容，特别是免除或限制责任的条款。您使用本软件即视为您已阅读并同意接受本协议的约束。如您不同意本协议，请立即停止使用并卸载本软件。\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "一、服务说明\n"
        "\n"
        "1.1 本软件是一款基于安卓系统的自动化辅助工具，旨在为用户提供便捷的订单信息获取与筛选功能。\n"
        "\n"
        "1.2 本软件仅供个人学习、研究、交流使用，严禁用于任何商业用途或非法活动。\n"
        "\n"
        "1.3 本软件不隶属于任何第三方出行平台，亦未获得任何第三方平台的授权或认可。\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "二、免责声明\n"
        "\n"
        "2.1 本软件按“现状”提供，不提供任何明示或默示的担保，包括但不限于适销性、特定用途适用性及不侵权的担保。\n"
        "\n"
        "2.2 本软件不保证抢单成功率，不保证服务的连续性、及时性、安全性及准确性。因网络状况、设备性能、第三方平台规则变更等因素导致的抢单失败，本软件不承担任何责任。\n"
        "\n"
        "2.3 使用者应自行评估使用本软件的风险，并自行承担因使用本软件而产生的一切后果，包括但不限于：\n"
        "  • 第三方平台账号被封禁、限制或处罚；\n"
        "  • 设备损坏、数据丢失或系统异常；\n"
        "  • 任何直接、间接、附带、特殊或惩罚性损失。\n"
        "\n"
        "2.4 使用者应遵守所在国家/地区的法律法规及第三方平台的使用条款。因违规使用产生的一切法律责任及后果由使用者自行承担。\n"
        "\n"
        "2.5 本软件开发者不对以下情况承担责任：\n"
        "  • 因不可抗力（自然灾害、战争、政府行为等）导致的服务中断；\n"
        "  • 因黑客攻击、病毒入侵、系统崩溃等不可控因素导致的数据损失；\n"
        "  • 因使用者操作不当或误判导致的任何损失。\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "三、用户义务\n"
        "\n"
        "3.1 您承诺不利用本软件从事任何违法违规活动，包括但不限于：侵犯他人隐私、侵害他人合法权益、干扰第三方平台正常运营秩序。\n"
        "\n"
        "3.2 您应妥善保管自有设备及第三方平台账号密码，因账号信息泄露导致的损失由您自行承担。\n"
        "\n"
        "3.3 如发现本软件存在安全漏洞，您有义务及时通知开发者，不得利用漏洞进行非法操作。\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "四、隐私声明\n"
        "\n"
        "4.1 本软件高度重视用户隐私保护。我们承诺：\n"
        "  • 本软件为纯本地运行工具，不注册账号、不收集个人身份信息（姓名、手机号、身份证号等）；\n"
        "  • 所有配置数据（筛选参数、抢单记录等）仅存储在您设备本地，不会上传至任何服务器；\n"
        "  • 本软件不包含任何第三方统计、广告或追踪 SDK；\n"
        "  • 本软件不会读取、上传或分享您的第三方平台账号密码、聊天记录、通讯录等隐私数据。\n"
        "\n"
        "4.2 本软件在运行中可能获取以下信息，仅用于功能实现，不做其他用途：\n"
        "  • 设备已安装应用列表（用于应用筛选功能）；\n"
        "  • 设备大致位置信息（用于订单区域筛选）；\n"
        "  • 屏幕截图内容（用于 OCR 订单识别，识别完成后立即释放）。\n"
        "\n"
        "4.3 网络请求仅用于以下目的：\n"
        "  • 获取标准北京时间（用于卡密验证）；\n"
        "  • 检测开源素材库版本更新。\n"
        "所有网络请求均使用公共免费 API，不传输任何用户个人信息。\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "五、知识产权\n"
        "\n"
        "5.1 本软件（包括但不限于代码、界面设计、图标、文档）的知识产权归开发者所有，受著作权法及国际版权条约保护。\n"
        "\n"
        "5.2 未经开发者书面许可，任何人不得对本软件进行反向工程、反编译、反汇编、修改、复制、分发或创建衍生作品。\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "六、年龄限制\n"
        "\n"
        "6.1 本软件仅面向年满 18 周岁的用户。\n"
        "如您未满 18 周岁，请在监护人的陪同下阅读本协议，并在获得监护人同意后使用本软件。\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "七、协议变更\n"
        "\n"
        "7.1 开发者保留随时更新本协议的权利。\n"
        "协议变更后，您继续使用本软件即视为接受更新后的协议条款。\n"
        "\n"
        "7.2 重大变更将在软件启动时以弹窗方式重新征求您的同意。\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "八、其他\n"
        "\n"
        "8.1 本协议中部分条款因与适用法律冲突而无效的，不影响其他条款的效力。\n"
        "\n"
        "8.2 本协议最终解释权归开发者所有。\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "如您已充分阅读并理解以上全部条款，\n"
        "请点击下方“同意并继续”按钮。\n"
        "如您不同意，请点击“拒绝退出”关闭本软件。\n"
    )
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._build_ui()

    def _build_ui(self):
        try:
            from kivy.uix.boxlayout import BoxLayout
            from kivy.uix.scrollview import ScrollView
            from kivy.uix.label import Label
            from kivy.uix.button import Button
            from kivy.uix.image import Image
            from kivy.core.window import Window

            _ensure_cjk_font()
            cjk_font = _get_cjk_font_name()

            root = BoxLayout(orientation="vertical", padding=24, spacing=20)
            theme = get_theme_manager()
            bg = theme.page_bg()
            r, g, b, a = hex_to_rgba(bg)

            with root.canvas.before:
                from kivy.graphics import Color, Rectangle
                Color(r, g, b, a)
                self._bg_rect = Rectangle(size=Window.size)
                root.bind(pos=lambda w, v: setattr(self._bg_rect, "pos", v))
                root.bind(size=lambda w, v: setattr(self._bg_rect, "size", v))

            # 标题
            title = Label(
                text="欢迎使用 TiShou",
                font_size=dp_to_px(22),
                bold=True,
                color=hex_to_rgba(theme.text_primary()),
                size_hint_y=None,
                height=dp_to_px(60),
                font_name=cjk_font,
            )
            root.add_widget(title)

            # 免责内容滚动
            scroll = ScrollView(size_hint=(1, 1))
            eula_label = Label(
                text=self.eula_text,
                font_size=dp_to_px(15),
                color=hex_to_rgba(theme.text_secondary()),
                halign="left",
                valign="top",
                text_size=(Window.width - dp_to_px(48), None),
                size_hint_y=None,
                padding=(dp_to_px(16), dp_to_px(16)),
                font_name=cjk_font,
            )
            eula_label.bind(
                texture_size=lambda inst, val: setattr(inst, "height", val[1] + dp_to_px(32))
            )
            scroll.add_widget(eula_label)
            root.add_widget(scroll)

            # 按钮区
            btn_box = BoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=dp_to_px(52),
                spacing=16,
            )
            decline_btn = Button(
                text="拒绝退出",
                font_size=dp_to_px(16),
                color=hex_to_rgba(StyleConstants.DANGER_COLOR),
                background_color=(0, 0, 0, 0),
                size_hint_x=0.5,
            )
            accept_btn = Button(
                text="同意并继续",
                font_size=dp_to_px(16),
                color=hex_to_rgba("#FFFFFF"),
                background_color=hex_to_rgba(StyleConstants.ACCENT_COLOR),
                size_hint_x=0.5,
            )
            decline_btn.bind(on_release=self._on_decline)
            accept_btn.bind(on_release=self._on_accept)
            btn_box.add_widget(decline_btn)
            btn_box.add_widget(accept_btn)
            root.add_widget(btn_box)

            self.add_widget(root)
        except Exception as e:
            self._log_error(f"免责页构建失败: {e}")

    def _on_decline(self, instance):
        """拒绝退出"""
        try:
            from kivy.app import App
            App.get_running_app().stop()
        except Exception as e:
            self._log_error(f"退出异常: {e}")

    def _on_accept(self, instance):
        """同意进入卡密验证"""
        try:
            # 保存 EULA 同意状态，下次启动跳过免责页
            try:
                from main import get_app as _get_app
                biz_app = _get_app()
                biz_app.config.set("eula_accepted", True)
                biz_app.config.save()
            except Exception:
                pass
            self.manager.current = "activation"
        except Exception as e:
            self._log_error(f"页面跳转异常: {e}")

    def _log_error(self, msg):
        try:
            LogManager.get_logger("error").error(f"[免责页] {msg}")
        except Exception:
            pass


# ============================================================
# ② 卡密验证页
# ============================================================
class ActivationScreen(Screen):
    """卡密验证页——对接 activate_code 模块"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._code_input = None
        self._status_label = None
        self._verify_btn = None
        self._toggle_btn = None
        self._loading_popup = None
        self._build_ui()

    def _build_ui(self):
        try:
            from kivy.uix.boxlayout import BoxLayout
            from kivy.uix.label import Label
            from kivy.uix.textinput import TextInput
            from kivy.uix.button import Button
            from kivy.core.window import Window

            _ensure_cjk_font()
            cjk_font = _get_cjk_font_name()

            root = BoxLayout(orientation="vertical", padding=32, spacing=20)
            theme = get_theme_manager()
            bg = theme.page_bg()
            r, g, b, a = hex_to_rgba(bg)
            with root.canvas.before:
                from kivy.graphics import Color, Rectangle
                Color(r, g, b, a)
                rect = Rectangle(size=Window.size)
                root.bind(pos=lambda w, v: setattr(rect, "pos", v))
                root.bind(size=lambda w, v: setattr(rect, "size", v))

            # 标题
            title = Label(
                text="卡密验证",
                font_size=dp_to_px(24),
                bold=True,
                color=hex_to_rgba(theme.text_primary()),
                size_hint_y=None,
                height=dp_to_px(60),
                font_name=cjk_font,
            )
            root.add_widget(title)

            # 说明
            desc = Label(
                text="请输入您的激活码以继续使用",
                font_size=dp_to_px(14),
                color=hex_to_rgba(theme.text_secondary()),
                size_hint_y=None,
                height=dp_to_px(30),
                font_name=cjk_font,
            )
            root.add_widget(desc)

            # 输入框
            input_box = BoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=dp_to_px(44),
                spacing=8,
            )
            self._code_input = TextInput(
                hint_text="请输入激活码",
                font_size=dp_to_px(16),
                password=True,
                password_mask="●",
                multiline=False,
                size_hint_x=0.7,
            )
            self._toggle_btn = Button(
                text="显示",
                font_size=dp_to_px(14),
                size_hint_x=0.3,
                background_color=hex_to_rgba(StyleConstants.ACCENT_COLOR),
                color=hex_to_rgba("#FFFFFF"),
            )
            self._toggle_btn.bind(on_release=self._toggle_visible)
            input_box.add_widget(self._code_input)
            input_box.add_widget(self._toggle_btn)
            root.add_widget(input_box)

            # 状态提示
            self._status_label = Label(
                text="",
                font_size=dp_to_px(14),
                color=hex_to_rgba(StyleConstants.WARNING_COLOR),
                size_hint_y=None,
                height=dp_to_px(30),
            )
            root.add_widget(self._status_label)

            # 验证按钮
            self._verify_btn = Button(
                text="验证卡密",
                font_size=dp_to_px(18),
                size_hint_y=None,
                height=dp_to_px(50),
                background_color=hex_to_rgba(StyleConstants.ACCENT_COLOR),
                color=hex_to_rgba("#FFFFFF"),
            )
            self._verify_btn.bind(on_release=self._verify)
            root.add_widget(self._verify_btn)

            # 弹性占位
            root.add_widget(BoxLayout())

            self.add_widget(root)
        except Exception as e:
            self._log_error(f"卡密页构建失败: {e}")

    def _toggle_visible(self, instance):
        """切换明文/密文"""
        try:
            self._code_input.password = not self._code_input.password
            self._toggle_btn.text = "隐藏" if not self._code_input.password else "显示"
        except Exception as e:
            self._log_error(f"切换可见性失败: {e}")

    def _verify(self, instance):
        """验证卡密"""
        try:
            code = self._code_input.text.strip()
            if not code:
                self._set_status("请输入激活码", StyleConstants.WARNING_COLOR)
                return

            from modules.activate_code import verify_code_ui
            success, msg = verify_code_ui(code)

            if success:
                self._set_status("验证成功！正在进入...", StyleConstants.SUCCESS_COLOR)
                self._verify_btn.disabled = True
                threading.Thread(target=self._go_loading, daemon=True).start()
            else:
                self._set_status(msg or "验证失败，请重试", StyleConstants.DANGER_COLOR)
        except Exception as e:
            self._log_error(f"验证异常: {e}")
            self._set_status("验证异常，请稍后重试", StyleConstants.DANGER_COLOR)

    def _go_loading(self):
        """验证成功后直接进入主设置页（冷启动已在后台完成）"""
        try:
            import time
            time.sleep(0.5)
            from kivy.clock import mainthread
            @mainthread
            def switch():
                try:
                    self.manager.current = "main"
                except Exception as e:
                    self._log_error(f"跳转主设置页失败: {e}")
            switch()
        except Exception:
            pass

    def _set_status(self, text, color):
        """设置状态文字"""
        try:
            self._status_label.text = text
            self._status_label.color = hex_to_rgba(color)
        except Exception:
            pass

    def _log_error(self, msg):
        try:
            LogManager.get_logger("error").error(f"[卡密页] {msg}")
        except Exception:
            pass


# ============================================================
# ③ 加载进度页
# ============================================================

# CJK 字体缓存
_cjk_font_name = None
_cjk_font_registered = False


def _ensure_cjk_font():
    """
    确保注册了支持中文的 CJK 字体。
    Kivy 默认使用 Roboto 字体，不含中文字符，导致中文显示为方块/乱码。
    在 Android 上尝试使用系统 DroidSansFallback.ttf 中文字体。
    """
    global _cjk_font_name, _cjk_font_registered
    if _cjk_font_registered:
        return

    _cjk_font_registered = True
    try:
        from kivy.core.text import LabelBase
        import os

        # Android 系统 CJK 字体路径列表
        cjk_paths = [
            "/system/fonts/DroidSansFallback.ttf",
            "/system/fonts/NotoSansCJK-Regular.ttc",
            "/system/fonts/NotoSansSC-Regular.otf",
            "/system/fonts/NotoSansHans-Regular.otf",
            "/system/fonts/Fallback.ttf",
        ]

        for path in cjk_paths:
            if os.path.isfile(path):
                try:
                    LabelBase.register(name="CJKFont", fn_regular=path)
                    _cjk_font_name = "CJKFont"
                    return
                except Exception:
                    continue

        # 如果系统字体都不存在，尝试使用 Kivy 内置字体（可能支持部分 CJK）
        _cjk_font_name = None
    except Exception:
        _cjk_font_name = None


def _get_cjk_font_name():
    """获取 CJK 字体名称，若未注册则返回 None（使用默认字体）"""
    _ensure_cjk_font()
    return _cjk_font_name


class LoadingSpinner(Widget):
    """
    旋转加载动画圈（追光点效果）
    =========================
    8 个点环形排列，持续旋转 + 渐隐效果，视觉上永不"卡住"。
    纯 Canvas 绘制，性能开销极低。
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._phase = 0.0
        self._anim_event = None
        self._num_dots = 8
        self._dot_radius = 5
        self.bind(pos=self._draw, size=self._draw)

    def start(self):
        from kivy.clock import Clock
        if self._anim_event is None:
            self._anim_event = Clock.schedule_interval(self._update, 1.0 / 30.0)

    def stop(self):
        if self._anim_event:
            self._anim_event.cancel()
            self._anim_event = None

    def _update(self, dt):
        self._phase = (self._phase + dt * 2.0) % 1.0
        self._draw()

    def _draw(self, *args):
        import math
        from kivy.graphics import Color, Ellipse

        self.canvas.clear()
        w, h = self.width, self.height
        if w <= 0 or h <= 0:
            return

        cx = w / 2.0
        cy = h / 2.0
        outer_r = min(w, h) / 2.0 - 4
        d2 = self._dot_radius * 2

        for i in range(self._num_dots):
            angle = (float(i) / self._num_dots + self._phase) * 2.0 * math.pi
            # 渐隐：最亮→最暗→最亮，循环
            alpha = 0.12 + 0.88 * (0.5 + 0.5 * math.cos((float(i) / self._num_dots + self._phase) * 2.0 * math.pi))
            x = cx + outer_r * math.cos(angle) - self._dot_radius
            y = cy + outer_r * math.sin(angle) - self._dot_radius

            with self.canvas:
                Color(0.0, 0.48, 1.0, float(alpha))
                Ellipse(pos=(x, y), size=(d2, d2))


class LoadingScreen(Screen):
    """
    加载进度页——圆角进度条+百分比+旋转动画，不可手动跳过
    =====================================================
    改进特性：
      1. 旋转追光动画圈（LoadingSpinner）——视觉上持续运动，不会"卡住"
      2. 状态文字跳动省略号（".", "..", "..."）——动态变化
      3. 百分比脉冲缩放——轻微呼吸效果
      4. on_enter 自动启动占位动画（不依赖外部调用）
      5. 15 秒无冷启动更新 → 显示超时提示但不阻塞
      6. 后台 _cold_start_done 标记 + 兜底跳转
    """

    # 冷启动超时（秒）→ 显示提示但仍等待
    COLD_START_TIMEOUT = 20

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._progress_bar = None
        self._percent_label = None
        self._status_label = None
        self._title_label = None
        self._spinner = None
        self._loading = False
        self._cold_start_done = False
        self._fallback_triggered = False
        self._real_progress_received = False  # 真实进度接管标记
        self._dot_anim_event = None  # 状态文字跳动事件
        self._pulse_anim_event = None  # 百分比脉冲事件
        self._status_base_text = "请稍候"  # 状态文字基础文本
        self._build_ui()

    def _build_ui(self):
        try:
            from kivy.uix.boxlayout import BoxLayout
            from kivy.uix.label import Label
            from kivy.uix.widget import Widget
            from kivy.uix.floatlayout import FloatLayout
            from kivy.core.window import Window
            from kivy.core.text import LabelBase

            # 注册 CJK 字体，解决中文字符显示为方块/乱码的问题
            _ensure_cjk_font()

            root = BoxLayout(orientation="vertical", padding=32, spacing=16)
            theme = get_theme_manager()
            bg = theme.page_bg()
            r, g, b, a = hex_to_rgba(bg)
            with root.canvas.before:
                from kivy.graphics import Color, Rectangle
                Color(r, g, b, a)
                rect = Rectangle(size=Window.size)
                root.bind(pos=lambda w, v: setattr(rect, "pos", v))
                root.bind(size=lambda w, v: setattr(rect, "size", v))

            root.add_widget(BoxLayout())  # 顶部弹性占位

            # 标题
            self._title_label = Label(
                text="TiShou 正在初始化",
                font_size=dp_to_px(22),
                bold=True,
                color=hex_to_rgba(theme.text_primary()),
                size_hint_y=None,
                height=dp_to_px(50),
                font_name=_get_cjk_font_name(),
            )
            root.add_widget(self._title_label)

            # 状态文字（模块名称，显示在进度条上方）
            self._status_label = Label(
                text="请稍候",
                font_size=dp_to_px(14),
                color=hex_to_rgba(theme.text_secondary()),
                size_hint_y=None,
                height=dp_to_px(30),
                halign="center",
                valign="middle",
                font_name=_get_cjk_font_name(),
            )
            root.add_widget(self._status_label)

            # 进度条容器
            bar_box = BoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=dp_to_px(20),
                padding=(0, 0, 0, 0),
            )
            bar_box.add_widget(BoxLayout(size_hint_x=0.1))
            self._progress_bar = LoadingProgressBar(
                size_hint=(0.8, 1),
                max_value=100,
            )
            bar_box.add_widget(self._progress_bar)
            bar_box.add_widget(BoxLayout(size_hint_x=0.1))
            root.add_widget(bar_box)

            # 旋转圈 + 百分比（圈套在百分比外面，百分比浮在圈正中央）
            percent_container = FloatLayout(
                size_hint_y=None,
                height=dp_to_px(160),
            )
            self._spinner = LoadingSpinner(
                size_hint=(0.7, 0.8),
                pos_hint={"center_x": 0.5, "center_y": 0.5},
            )
            percent_container.add_widget(self._spinner)

            self._percent_label = Label(
                text="0%",
                font_size=dp_to_px(36),
                bold=True,
                color=hex_to_rgba(StyleConstants.ACCENT_COLOR),
                size_hint=(None, None),
                width=dp_to_px(150),
                height=dp_to_px(60),
                pos_hint={"center_x": 0.5, "center_y": 0.5},
                halign="center",
                valign="middle",
                font_name=_get_cjk_font_name(),
            )
            percent_container.add_widget(self._percent_label)
            root.add_widget(percent_container)

            root.add_widget(BoxLayout())  # 底部弹性占位

            self.add_widget(root)
        except Exception as e:
            self._log_error(f"加载页构建失败: {e}")

    def on_enter(self):
        """进入页面时自动启动加载动画"""
        self.start_loading()

    def start_loading(self):
        """开始加载（含动画圈 + 占位动画 + 冷启动超时兜底）"""
        if self._loading:
            return
        self._loading = True

        # 启动旋转动画圈
        if self._spinner:
            self._spinner.start()

        # 启动状态文字跳动省略号动画
        self._start_dot_animation()

        # 启动百分比脉冲动画
        self._start_pulse_animation()

        # 启动占位动画线程（每 2 秒增加一些进度，直到冷启动接管）
        threading.Thread(target=self._placeholder_anim, daemon=True).start()

        # 启动超时兜底线程
        threading.Thread(target=self._timeout_fallback, daemon=True).start()

    def _start_dot_animation(self):
        """状态文字跳动省略号动画（".", "..", "..."）"""
        try:
            from kivy.clock import Clock
            self._dot_frame = 0

            def _animate_dots(dt):
                if not self._loading:
                    return False
                try:
                    self._dot_frame = (self._dot_frame + 1) % 4
                    dots = "." * self._dot_frame
                    if hasattr(self, "_status_label") and self._status_label:
                        current = self._status_label.text
                        base = getattr(self, "_status_base_text", "请稍候")
                        if current.startswith(base):
                            self._status_label.text = base + dots
                except Exception:
                    pass

            self._dot_anim_event = Clock.schedule_interval(_animate_dots, 0.5)
        except Exception:
            pass

    def _start_pulse_animation(self):
        """百分比脉冲缩放动画（呼吸效果）"""
        try:
            from kivy.clock import Clock
            self._pulse_phase = 0.0

            def _animate_pulse(dt):
                if not self._loading:
                    return False
                try:
                    self._pulse_phase += dt * 2.5
                    import math
                    scale = 1.0 + 0.04 * math.sin(self._pulse_phase)
                    if hasattr(self, "_percent_label") and self._percent_label:
                        self._percent_label.font_size = dp_to_px(36) * scale
                except Exception:
                    pass

            self._pulse_anim_event = Clock.schedule_interval(_animate_pulse, 1/30)
        except Exception:
            pass

    def _placeholder_anim(self):
        """
        占位动画：冷启动接管前，让进度条缓慢前进
        最大到 30%（避免与真实进度冲突）
        一旦真实冷启动进度到达（>30%），立即停止占位动画
        """
        import time
        progress = 5
        try:
            while self._loading and not self._cold_start_done and progress < 30:
                # 检查真实进度是否已接管（>30% 说明冷启动已开始汇报进度）
                if self._real_progress_received:
                    break
                self._update_progress(progress, "正在准备")
                progress += 3
                time.sleep(1.5)
        except Exception:
            pass

    def _timeout_fallback(self):
        """
        冷启动超时兜底：
        如果 COLD_START_TIMEOUT 秒后冷启动仍未完成，
        显示提示但仍保持加载状态（不卡死，OCR 模型首次加载较慢）
        """
        import time
        time.sleep(self.COLD_START_TIMEOUT)
        try:
            if not self._cold_start_done and not self._fallback_triggered:
                self._fallback_triggered = True
                self._update_progress(
                    self._progress_bar.value if self._progress_bar else 70,
                    "首次加载较慢，请耐心等待（OCR 模型初始化中）…"
                )
                self._log_error("冷启动超时，仍在等待（可能 OCR 模型加载中）")
        except Exception:
            pass

    def _update_progress(self, value, text=""):
        """更新进度（线程安全）"""
        try:
            from kivy.clock import Clock
            Clock.schedule_once(lambda dt: self._do_update_progress(value, text), 0)
        except Exception:
            pass

    def _update_status_text(self, text):
        """仅更新状态文字，不改变进度条"""
        try:
            if self._status_label and text:
                self._status_base_text = text
                self._status_label.text = text
        except Exception:
            pass

    def _do_update_progress(self, value, text=""):
        """在主线程更新UI"""
        try:
            if self._progress_bar:
                self._progress_bar.value = value
            if self._percent_label:
                self._percent_label.text = f"{int(value)}%"
            if self._status_label and text:
                # 更新基础文本（跳动动画会在后面加省略号）
                self._status_base_text = text
                self._status_label.text = text
            # 真实冷启动进度到达（>30%）→ 停掉占位动画
            if value > 30:
                self._real_progress_received = True
        except Exception:
            pass

    def _log_error(self, msg):
        try:
            LogManager.get_logger("error").error(f"[加载页] {msg}")
        except Exception:
            pass


class LoadingProgressBar(Widget):
    """自定义圆角进度条"""

    def __init__(self, max_value=100, **kwargs):
        super().__init__(**kwargs)
        self._max_value = max_value
        self._value = 0
        self.bind(pos=self._redraw, size=self._redraw)

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._value = max(0, min(v, self._max_value))
        self._redraw()

    def _redraw(self, *args):
        try:
            self.canvas.clear()
            r = StyleConstants.PROGRESS_RADIUS_DP
            from kivy.graphics import Color, RoundedRectangle
            # 背景
            Color(0.9, 0.9, 0.9, 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[r] * 4)
            # 填充
            if self._value > 0:
                ratio = self._value / self._max_value
                fill_w = self.width * ratio
                if fill_w > r * 2:
                    Color(0, 0.48, 1, 1)
                    RoundedRectangle(
                        pos=self.pos,
                        size=(fill_w, self.height),
                        radius=[r] * 4
                    )
        except Exception:
            pass


# ============================================================
# ④ 主设置页
# ============================================================
class MainSettingsScreen(Screen):
    """主设置页——整合所有开关、参数、OCR、素材、重置、导入导出"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._widgets = {}
        self._dev_tap_count = 0          # 标题连击计数（触发调试面板）
        self._debug_section = None       # 调试面板引用
        self._debug_label = None         # 调试信息文本引用
        self._ui_built = False           # 是否已构建完整 UI

        # ⚠️ 不在 __init__ 中构建 UI，避免 build() 阶段阻塞主线程
        # 完整 UI 在 on_enter() 中按需构建
        self._build_placeholder()

    def _build_placeholder(self):
        """显示占位标签，避免黑屏"""
        try:
            from kivy.uix.label import Label
            from kivy.core.window import Window
            from kivy.graphics import Color, Rectangle

            theme = get_theme_manager()
            bg = theme.page_bg()
            r, g, b, a = hex_to_rgba(bg)
            with self.canvas.before:
                Color(r, g, b, a)
                self._placeholder_rect = Rectangle(size=Window.size)
                self.bind(pos=lambda w, v: setattr(self._placeholder_rect, "pos", v))
                self.bind(size=lambda w, v: setattr(self._placeholder_rect, "size", v))

            self._placeholder_label = Label(
                text="正在加载设置…",
                font_size=dp_to_px(16),
                color=hex_to_rgba(theme.text_secondary()),
                halign="center",
                valign="middle",
                font_name=_get_cjk_font_name(),
            )
            self.add_widget(self._placeholder_label)
        except Exception:
            pass

    def on_enter(self):
        """进入页面时按需构建完整 UI"""
        if not self._ui_built:
            self._ui_built = True
            try:
                # 移除占位标签
                if hasattr(self, "_placeholder_label") and self._placeholder_label:
                    self.remove_widget(self._placeholder_label)
                    self._placeholder_label = None
            except Exception:
                pass
            # 构建完整 UI（在后台线程准备，主线程添加）
            from kivy.clock import Clock
            Clock.schedule_once(lambda dt: self._build_ui(), 0.05)

    def _build_ui(self):
        try:
            from kivy.uix.boxlayout import BoxLayout
            from kivy.uix.scrollview import ScrollView
            from kivy.uix.gridlayout import GridLayout
            from kivy.uix.label import Label
            from kivy.uix.button import Button
            from kivy.uix.textinput import TextInput
            from kivy.uix.switch import Switch
            from kivy.uix.spinner import Spinner
            from kivy.core.window import Window

            theme = get_theme_manager()
            root = BoxLayout(orientation="vertical")
            bg = theme.page_bg()
            r, g, b, a = hex_to_rgba(bg)
            with root.canvas.before:
                from kivy.graphics import Color, Rectangle
                Color(r, g, b, a)
                rect = Rectangle(size=Window.size)
                root.bind(pos=lambda w, v: setattr(rect, "pos", v))
                root.bind(size=lambda w, v: setattr(rect, "size", v))

            # 标题栏
            header = BoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=dp_to_px(56),
                padding=(dp_to_px(16), 0),
            )
            header.add_widget(Label(
                text="TiShou 设置",
                font_size=dp_to_px(20),
                bold=True,
                color=hex_to_rgba(theme.text_primary()),
                halign="left",
            ))
            root.add_widget(header)

            # 可滚动内容
            scroll = ScrollView()
            content = BoxLayout(
                orientation="vertical",
                padding=dp_to_px(16),
                spacing=dp_to_px(StyleConstants.SECTION_SPACING_DP),
                size_hint_y=None,
            )
            content.bind(
                minimum_height=content.setter("height")
            )

            # ---- 各设置区块 ----
            self._build_section_capture(content)
            self._build_section_ocr(content)
            self._build_section_filter(content)
            self._build_section_float(content)
            self._build_section_stats(content)
            self._build_section_theme(content)
            self._build_section_actions(content)

            # ---- 隐藏调试面板（标题连击5次触发） ----
            self._debug_section = self._build_section_debug(content)
            self._debug_section.opacity = 0
            self._debug_section.disabled = True

            # 标题连击触发调试面板
            def on_title_tap(inst):
                self._dev_tap_count += 1
                if self._dev_tap_count >= 5:
                    self._dev_tap_count = 0
                    self._toggle_debug_panel()

            title_label = None
            for child in header.children:
                if isinstance(child, Label):
                    title_label = child
                    break
            if title_label:
                title_label.bind(on_touch_down=lambda inst, touch: (
                    on_title_tap(inst) if inst.collide_point(*touch.pos) else None
                ))

            scroll.add_widget(content)
            root.add_widget(scroll)

            self.add_widget(root)
        except Exception as e:
            self._log_error(f"主设置页构建失败: {e}")

    def _make_section(self, title: str) -> tuple:
        """创建设置区块"""
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        section = BoxLayout(
            orientation="vertical",
            spacing=dp_to_px(8),
            size_hint_y=None,
        )
        theme = get_theme_manager()
        title_label = Label(
            text=title,
            font_size=dp_to_px(16),
            bold=True,
            color=hex_to_rgba(theme.text_primary()),
            size_hint_y=None,
            height=dp_to_px(30),
            halign="left",
        )
        title_label.bind(
            texture_size=lambda inst, val: setattr(inst, "height", val[1] + dp_to_px(8))
        )
        section.add_widget(title_label)
        inner = BoxLayout(
            orientation="vertical",
            spacing=dp_to_px(4),
            size_hint_y=None,
        )
        inner.bind(minimum_height=inner.setter("height"))
        section.add_widget(inner)
        section.bind(minimum_height=section.setter("height"))
        return section, inner

    def _add_row(self, container, label_text, widget, desc=""):
        """添加一行设置项"""
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        theme = get_theme_manager()
        row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp_to_px(44),
            spacing=dp_to_px(8),
            padding=(dp_to_px(8), 0),
        )
        lbl = Label(
            text=label_text,
            font_size=dp_to_px(15),
            color=hex_to_rgba(theme.text_primary()),
            size_hint_x=0.5,
            halign="left",
        )
        lbl.bind(texture_size=lambda inst, val: setattr(lbl, "text_size", (val[0], None)))
        row.add_widget(lbl)
        row.add_widget(widget)
        container.add_widget(row)
        if desc:
            desc_label = Label(
                text=desc,
                font_size=dp_to_px(12),
                color=hex_to_rgba(theme.text_secondary()),
                size_hint_y=None,
                height=dp_to_px(20),
                padding=(dp_to_px(8), 0),
            )
            container.add_widget(desc_label)

    def _build_section_capture(self, parent):
        """采集引擎设置"""
        from kivy.uix.spinner import Spinner
        section, inner = self._make_section("采集引擎")
        spinner = Spinner(
            text="easyocr",
            values=("easyocr", "accessibility"),
            size_hint_x=0.5, size_hint_y=None, height=dp_to_px(36),
        )
        spinner.bind(text=lambda inst, val: self._on_engine_change(val))
        self._add_row(inner, "引擎选择", spinner, "切换 OCR / 无障碍采集引擎")
        parent.add_widget(section)

    def _build_section_ocr(self, parent):
        """OCR 配置"""
        from kivy.uix.textinput import TextInput
        from kivy.uix.boxlayout import BoxLayout
        section, inner = self._make_section("OCR 配置")
        config = ConfigManager()
        timeout = config.get("ocr_timeout", 8.0)
        scale = config.get("ocr_image_scale", 1.3)
        delay = config.get("order_judge_delay", 13.0)

        timeout_input = TextInput(
            text=str(timeout), font_size=dp_to_px(15),
            size_hint_x=0.5, size_hint_y=None, height=dp_to_px(36),
            multiline=False, input_filter="float",
        )
        timeout_input.bind(text=lambda inst, val: self._on_config_change("ocr_timeout", val))
        self._add_row(inner, "识别超时(s)", timeout_input)

        scale_input = TextInput(
            text=str(scale), font_size=dp_to_px(15),
            size_hint_x=0.5, size_hint_y=None, height=dp_to_px(36),
            multiline=False, input_filter="float",
        )
        scale_input.bind(text=lambda inst, val: self._on_config_change("ocr_image_scale", val))
        self._add_row(inner, "图片放大倍数", scale_input)

        delay_input = TextInput(
            text=str(delay), font_size=dp_to_px(15),
            size_hint_x=0.5, size_hint_y=None, height=dp_to_px(36),
            multiline=False, input_filter="float",
        )
        delay_input.bind(text=lambda inst, val: self._on_config_change("order_judge_delay", val))
        self._add_row(inner, "抢单判定延迟(s)", delay_input)
        parent.add_widget(section)

    def _build_section_filter(self, parent):
        """订单筛选"""
        from kivy.uix.textinput import TextInput
        from kivy.uix.switch import Switch
        section, inner = self._make_section("订单筛选")
        config = ConfigManager()
        filters = config.get("filter_thresholds", {})
        min_p = filters.get("min_price", 0)
        max_p = filters.get("max_price", 999)

        min_input = TextInput(
            text=str(min_p), font_size=dp_to_px(15),
            size_hint_x=0.5, size_hint_y=None, height=dp_to_px(36),
            multiline=False, input_filter="float",
        )
        self._add_row(inner, "最低价格", min_input)
        max_input = TextInput(
            text=str(max_p), font_size=dp_to_px(15),
            size_hint_x=0.5, size_hint_y=None, height=dp_to_px(36),
            multiline=False, input_filter="float",
        )
        self._add_row(inner, "最高价格", max_input)
        parent.add_widget(section)

    def _build_section_float(self, parent):
        """悬浮窗"""
        from kivy.uix.textinput import TextInput
        from kivy.uix.switch import Switch
        section, inner = self._make_section("悬浮窗")
        config = ConfigManager()
        fw = config.get("float_window", {})
        opacity = fw.get("opacity", 0.85)
        locked = fw.get("locked", False)

        op_input = TextInput(
            text=str(opacity), font_size=dp_to_px(15),
            size_hint_x=0.5, size_hint_y=None, height=dp_to_px(36),
            multiline=False, input_filter="float",
        )
        self._add_row(inner, "透明度(0.25~1.0)", op_input)

        lock_switch = Switch(active=locked)
        lock_switch.bind(active=lambda inst, val: self._on_float_locked(val))
        self._add_row(inner, "锁定位置", lock_switch)
        parent.add_widget(section)

    def _build_section_stats(self, parent):
        """抢单统计"""
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        from kivy.uix.boxlayout import BoxLayout
        section, inner = self._make_section("抢单统计")
        try:
            from modules.statistics import (
                get_today_stats_ui, get_statistics_summary_ui,
                reset_statistics_ui,
            )
            today = get_today_stats_ui()
            summary = get_statistics_summary_ui()
        except Exception:
            today = {"success": 0, "failed": 0, "total": 0, "success_rate": 0}
            summary = {"total": {"success": 0, "failed": 0}}

        theme = get_theme_manager()
        stats_text = (
            f"今日: 成功 {today.get('success', 0)} / "
            f"失败 {today.get('failed', 0)} / "
            f"成功率 {today.get('success_rate', 0)}%\n"
            f"累计: 成功 {summary.get('total', {}).get('success', 0)} / "
            f"失败 {summary.get('total', {}).get('failed', 0)}"
        )
        stats_label = Label(
            text=stats_text,
            font_size=dp_to_px(14),
            color=hex_to_rgba(theme.text_primary()),
            size_hint_y=None,
            height=dp_to_px(50),
            halign="left",
        )
        inner.add_widget(stats_label)

        reset_btn = Button(
            text="重置统计数据",
            font_size=dp_to_px(14),
            size_hint_y=None, height=dp_to_px(40),
            background_color=hex_to_rgba(StyleConstants.DANGER_COLOR),
            color=hex_to_rgba("#FFFFFF"),
        )
        reset_btn.bind(on_release=lambda inst: self._on_reset_stats())
        inner.add_widget(reset_btn)
        parent.add_widget(section)

    def _build_section_theme(self, parent):
        """主题与动画"""
        from kivy.uix.switch import Switch
        from kivy.uix.button import Button
        section, inner = self._make_section("主题与动画")
        theme = get_theme_manager()

        theme_btn = Button(
            text="切换为深色模式" if not theme.is_dark else "切换为浅色模式",
            font_size=dp_to_px(14),
            size_hint_y=None, height=dp_to_px(40),
        )
        theme_btn.bind(on_release=lambda inst: self._on_toggle_theme(inst))
        inner.add_widget(theme_btn)

        anim_switch = Switch(active=theme.animation_enabled)
        anim_switch.bind(active=lambda inst, val: self._on_anim_toggle(val))
        self._add_row(inner, "启用动画", anim_switch)
        parent.add_widget(section)

    def _build_section_actions(self, parent):
        """操作按钮"""
        from kivy.uix.button import Button
        from kivy.uix.boxlayout import BoxLayout
        section, inner = self._make_section("操作")
        btn_style = {
            "font_size": dp_to_px(14),
            "size_hint_y": None,
            "height": dp_to_px(40),
        }

        def make_btn(text, color, callback):
            btn = Button(
                text=text, **btn_style,
                background_color=hex_to_rgba(color),
                color=hex_to_rgba("#FFFFFF"),
            )
            btn.bind(on_release=callback)
            return btn

        inner.add_widget(make_btn("素材更新", StyleConstants.ACCENT_COLOR, self._on_update_material))
        inner.add_widget(make_btn("导出配置", StyleConstants.SUCCESS_COLOR, self._on_export_config))
        inner.add_widget(make_btn("导入配置", StyleConstants.WARNING_COLOR, self._on_import_config))
        inner.add_widget(make_btn("导出日志", StyleConstants.TEXT_SECONDARY_LIGHT, self._on_export_logs))
        inner.add_widget(make_btn("重置全部设置", StyleConstants.DANGER_COLOR, self._on_reset_all))

        # 底部占位
        spacer = BoxLayout(size_hint_y=None, height=dp_to_px(40))
        inner.add_widget(spacer)
        parent.add_widget(section)

    # ----------------------------------------------------------
    # 调试面板（标题连击5次触发）
    # ----------------------------------------------------------
    def _build_section_debug(self, parent) -> BoxLayout:
        """构建隐藏调试面板（始终构建，默认隐藏）"""
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        from kivy.uix.scrollview import ScrollView

        section, inner = self._make_section("🔧 调试信息")

        # 刷新按钮
        refresh_btn = Button(
            text="刷新",
            font_size=dp_to_px(12),
            size_hint_y=None,
            height=dp_to_px(30),
            background_color=hex_to_rgba(StyleConstants.ACCENT_COLOR),
            color=hex_to_rgba("#FFFFFF"),
        )
        refresh_btn.bind(on_release=lambda inst: self._refresh_debug_info(info_label))
        inner.add_widget(refresh_btn)

        # 信息文本区（可滚动）
        info_label = Label(
            text="点击刷新加载调试信息...",
            font_size=dp_to_px(11),
            color=hex_to_rgba("#8E8E93"),
            size_hint_y=None,
            markup=True,
            halign="left",
            valign="top",
        )
        info_label.bind(texture_size=lambda inst, val: setattr(inst, "height", val[1] + dp_to_px(8)))
        self._debug_label = info_label
        scroll = ScrollView(size_hint_y=None, height=dp_to_px(280))
        scroll.add_widget(info_label)
        inner.add_widget(scroll)

        parent.add_widget(section)
        return section

    def _toggle_debug_panel(self):
        """切换调试面板显示/隐藏（opacity + disabled，Kivy 无 visible 属性）"""
        try:
            if not self._debug_section:
                return
            # 用 opacity 模拟显示/隐藏
            showing = self._debug_section.opacity > 0.5
            self._debug_section.opacity = 0 if showing else 1
            self._debug_section.disabled = showing

            # 展开时自动刷新
            if not showing and self._debug_label:
                self._refresh_debug_info(self._debug_label)
            self._show_toast("调试面板已打开" if not showing else "调试面板已关闭")
        except Exception as e:
            self._log_error(f"切换调试面板失败: {e}")

    def _refresh_debug_info(self, label):
        """刷新调试信息"""
        try:
            lines = []
            lines.append("[b]系统状态[/b]")
            lines.append(f"  安卓环境: {'是' if _is_android() else '否（桌面模拟）'}")

            # 网络
            try:
                from modules.network import get_network_manager, NetworkState
                nm = get_network_manager()
                state = nm.check_network_state()
                state_names = {NetworkState.NORMAL: "正常", NetworkState.WEAK_NETWORK: "弱网", NetworkState.NO_NETWORK: "无网络"}
                lines.append(f"  网络: {state_names.get(state, '未知')}")
            except Exception as e:
                lines.append(f"  网络: 无法检测 ({e})")

            # 时间同步
            try:
                from modules.activate_code import TimeSyncer
                ts = TimeSyncer()
                bt = ts.get_beijing_time()
                lines.append(f"  北京时间: {bt if bt else '未同步'}")
            except Exception:
                lines.append("  北京时间: 未同步")

            # 卡密状态
            try:
                from modules.activate_code import get_verify_info_ui
                info = get_verify_info_ui()
                if info and info.get("verified"):
                    lines.append(f"  卡密: 已验证 (激活时间: {info.get('activated_at', '未知')})")
                else:
                    lines.append("  卡密: 未激活")
            except Exception as e:
                lines.append(f"  卡密: 检测失败 ({e})")

            # 采集引擎
            try:
                from modules.capture import get_engine_status_ui
                eng = get_engine_status_ui()
                if eng:
                    lines.append(f"  引擎: {eng.get('current_engine', '未知')} (可用: {eng.get('available_engines', [])})")
            except Exception as e:
                lines.append(f"  引擎: 检测失败 ({e})")

            # 轮询状态
            try:
                from modules.capture import get_capture_status_ui
                cap = get_capture_status_ui()
                if cap:
                    lines.append(f"  轮询: {'运行中' if cap.get('polling', False) else '已停止'}")
            except Exception:
                lines.append("  轮询: 未知")

            # OCR 模型
            try:
                import easyocr
                lines.append(f"  easyocr: 已安装 ({easyocr.__version__ if hasattr(easyocr, '__version__') else '?'})")
            except ImportError:
                lines.append("  easyocr: 未安装")
            except Exception as e:
                lines.append(f"  easyocr: {e}")

            # 权限
            try:
                from modules.permission import get_permission_status_ui
                perm = get_permission_status_ui()
                if perm:
                    missing = perm.get("missing", [])
                    lines.append(f"  权限缺失: {missing if missing else '无'}")
            except Exception:
                lines.append("  权限: 未检测")

            # 素材
            try:
                from modules.material_update import get_material_status_ui
                mat = get_material_status_ui()
                if mat:
                    lines.append(f"  素材: {'自动更新' if mat.get('auto_update', False) else '手动'} | 状态: {mat.get('status', '？')}")
            except Exception as e:
                lines.append(f"  素材: {e}")

            # 统计
            try:
                from modules.statistics import get_today_stats_ui, get_statistics_summary_ui
                today = get_today_stats_ui()
                total = get_statistics_summary_ui()
                if today:
                    lines.append(f"  今日: 成功 {today.get('success', 0)} 失败 {today.get('failed', 0)}")
                if total:
                    lines.append(f"  总计: 成功 {total.get('total_success', 0)} 失败 {total.get('total_failed', 0)}")
            except Exception as e:
                lines.append(f"  统计: {e}")

            # 主题
            try:
                theme = get_theme_manager()
                lines.append(f"  主题: {'深色' if theme.is_dark else '浅色'} | 动画: {'开' if theme.animation_enabled else '关'}")
            except Exception:
                lines.append("  主题: 未知")

            label.text = "\n".join(lines)
            label.color = hex_to_rgba("#8E8E93")
        except Exception as e:
            label.text = f"刷新失败: {e}"

    # ----------------------------------------------------------
    # 日志导出
    # ----------------------------------------------------------
    def _on_export_logs(self, instance):
        """导出全部日志到 logs/export/ 目录"""
        try:
            from datetime import datetime
            export_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "logs", "export",
            )
            os.makedirs(export_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")

            log_files = ["app.log", "error.log", "ocr.log", "material.log"]
            logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
            exported = []

            for name in log_files:
                src = os.path.join(logs_dir, name)
                if os.path.exists(src):
                    dst = os.path.join(export_dir, f"{ts}_{name}")
                    with open(src, "r", encoding="utf-8") as f_in:
                        content = f_in.read()
                    with open(dst, "w", encoding="utf-8") as f_out:
                        f_out.write(content)
                    exported.append(name)

            if exported:
                self._show_toast(f"已导出 {len(exported)} 个日志文件 → logs/export/")
            else:
                self._show_toast("未找到日志文件")
        except Exception as e:
            self._log_error(f"导出日志失败: {e}")
            self._show_toast("导出日志失败")

    # ----------------------------------------------------------
    # 事件处理
    # ----------------------------------------------------------
    def _on_engine_change(self, val):
        try:
            from modules.capture import set_engine_ui
            set_engine_ui(val)
        except Exception as e:
            self._log_error(f"切换引擎失败: {e}")

    def _on_config_change(self, key, val):
        try:
            config = ConfigManager()
            config.set(key, safe_float(val, 0))
        except Exception as e:
            self._log_error(f"设置 {key} 失败: {e}")

    def _on_float_locked(self, val):
        try:
            from modules.float_win import set_float_locked_ui
            set_float_locked_ui(val)
        except Exception as e:
            self._log_error(f"锁定悬浮窗失败: {e}")

    def _on_reset_stats(self):
        try:
            from modules.statistics import reset_statistics_ui
            reset_statistics_ui()
            self._show_toast("统计数据已重置")
        except Exception as e:
            self._log_error(f"重置统计失败: {e}")

    def _on_toggle_theme(self, btn):
        try:
            theme = get_theme_manager()
            theme.toggle_theme()
            btn.text = "切换为深色模式" if not theme.is_dark else "切换为浅色模式"
            self._show_toast("主题已切换")
        except Exception as e:
            self._log_error(f"切换主题失败: {e}")

    def _on_anim_toggle(self, val):
        try:
            theme = get_theme_manager()
            theme.set_animation(val)
        except Exception as e:
            self._log_error(f"设置动画失败: {e}")

    def _on_update_material(self, instance):
        try:
            from modules.material_update import update_all_materials_ui
            success = update_all_materials_ui()
            if success:
                self._show_toast("素材更新完成")
            else:
                self._show_toast("素材更新失败，请查看日志")
        except Exception as e:
            self._log_error(f"素材更新失败: {e}")
            self._show_toast("素材更新异常")

    def _on_export_config(self, instance):
        try:
            from modules.utils import ConfigManager
            config = ConfigManager()
            data = config.get_all()
            export_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config_export.json"
            )
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            self._show_toast(f"配置已导出到 {export_path}")
        except Exception as e:
            self._log_error(f"导出配置失败: {e}")

    def _on_import_config(self, instance):
        try:
            from kivy.uix.filechooser import FileChooserListView
            from kivy.uix.popup import Popup
            from kivy.uix.boxlayout import BoxLayout
            from kivy.uix.button import Button

            layout = BoxLayout(orientation="vertical")
            fc = FileChooserListView(path=os.path.expanduser("~"))
            layout.add_widget(fc)
            btn_box = BoxLayout(size_hint_y=None, height=dp_to_px(44))
            cancel_btn = Button(text="取消")
            import_btn = Button(text="导入")
            btn_box.add_widget(cancel_btn)
            btn_box.add_widget(import_btn)
            layout.add_widget(btn_box)
            popup = Popup(title="选择配置文件", content=layout, size_hint=(0.9, 0.9))

            def do_import(inst):
                try:
                    sel = fc.selection
                    if sel:
                        with open(sel[0], "r", encoding="utf-8") as f:
                            data = json.load(f)
                        config = ConfigManager()
                        for k, v in data.items():
                            config.set(k, v)
                        self._show_toast("配置已导入")
                    popup.dismiss()
                except Exception as e:
                    self._log_error(f"导入配置失败: {e}")
                    self._show_toast("导入失败，文件格式错误")

            cancel_btn.bind(on_release=popup.dismiss)
            import_btn.bind(on_release=do_import)
            popup.open()
        except Exception as e:
            self._log_error(f"导入配置弹窗失败: {e}")

    def _on_reset_all(self, instance):
        """重置全部设置"""
        try:
            from kivy.uix.popup import Popup
            from kivy.uix.label import Label
            from kivy.uix.boxlayout import BoxLayout
            from kivy.uix.button import Button

            layout = BoxLayout(orientation="vertical", spacing=dp_to_px(16), padding=dp_to_px(16))
            layout.add_widget(Label(
                text="确定重置全部设置？\n此操作不可撤销！",
                font_size=dp_to_px(16),
            ))
            btn_box = BoxLayout(size_hint_y=None, height=dp_to_px(44), spacing=dp_to_px(12))
            cancel_btn = Button(text="取消")
            confirm_btn = Button(text="确认重置", background_color=hex_to_rgba(StyleConstants.DANGER_COLOR))
            btn_box.add_widget(cancel_btn)
            btn_box.add_widget(confirm_btn)
            layout.add_widget(btn_box)
            popup = Popup(title="重置确认", content=layout, size_hint=(0.7, 0.4))

            def do_reset(inst):
                try:
                    config = ConfigManager()
                    from modules.utils import DEFAULT_CONFIG
                    for k, v in DEFAULT_CONFIG.items():
                        config.set(k, v)
                    self._show_toast("已重置全部设置")
                    popup.dismiss()
                except Exception as e:
                    self._log_error(f"重置设置失败: {e}")

            cancel_btn.bind(on_release=popup.dismiss)
            confirm_btn.bind(on_release=do_reset)
            popup.open()
        except Exception as e:
            self._log_error(f"重置弹窗失败: {e}")

    def _show_toast(self, msg):
        """显示短暂提示"""
        try:
            from kivy.uix.popup import Popup
            from kivy.uix.label import Label
            popup = Popup(
                title="",
                content=Label(text=msg, font_size=dp_to_px(15)),
                size_hint=(0.6, 0.2),
                auto_dismiss=True,
            )
            popup.open()
            threading.Thread(target=self._dismiss_after, args=(popup, 2), daemon=True).start()
        except Exception:
            pass

    def _dismiss_after(self, popup, secs):
        try:
            import time
            time.sleep(secs)
            from kivy.clock import mainthread
            @mainthread
            def dismiss():
                try:
                    popup.dismiss()
                except Exception:
                    pass
            dismiss()
        except Exception:
            pass

    def _log_error(self, msg):
        try:
            LogManager.get_logger("error").error(f"[主设置页] {msg}")
        except Exception:
            pass


# ============================================================
# 安卓环境检测
# ============================================================
def _is_android() -> bool:
    """检测是否运行在安卓真机环境"""
    try:
        import jnius
        return True
    except ImportError:
        return False
    except Exception:
        return False


# ============================================================
# 对外便捷接口
# ============================================================

def run_ui(biz_app=None):
    """启动 UI（外部入口）
    
    :param biz_app: TiShouApp 业务逻辑实例（由 main.py 传入）
    """
    try:
        ui = TiShouUI(biz_app=biz_app)
        ui.run()
    except Exception as e:
        LogManager.get_logger("error").error(f"UI 启动失败: {e}")
        print(f"[TiShou] UI 异常: {e}")


def get_ui_status() -> dict:
    """获取 UI 模块状态"""
    try:
        theme = get_theme_manager()
        return {
            "theme_dark": theme.is_dark,
            "animation_enabled": theme.animation_enabled,
            "status": "ok",
        }
    except Exception as e:
        return {"status": "error", "msg": str(e)}


# ============================================================
# 模块自测
# ============================================================
if __name__ == "__main__":
    """桌面模式自测——仅测试导入和接口，不启动 Kivy 循环"""
    import sys

    print("=" * 50)
    print("TiShou UI 模块自测（桌面模式）")
    print("=" * 50)

    # 1. 风格常量
    print(f"1. 风格常量: BACKGROUND={StyleConstants.BACKGROUND_COLOR}")
    assert StyleConstants.BACKGROUND_COLOR == "#F2F2F7"
    assert StyleConstants.CARD_RADIUS_DP in (18, 19, 20, 21, 22)

    # 2. 主题管理器
    theme = get_theme_manager()
    print(f"2. 主题: dark={theme.is_dark} anim={theme.animation_enabled}")
    assert theme.animation_enabled is True

    # 3. 颜色转换
    rgba = hex_to_rgba("#F2F2F7")
    print(f"3. 颜色转换: {rgba}")
    assert len(rgba) == 4

    # 4. 页面导入
    from kivy.uix.screenmanager import Screen
    d = DisclaimerScreen()
    a = ActivationScreen()
    print(f"4. 免责页: {d.name}")
    print(f"5. 卡密页: {a.name}")

    # 6. 加载页
    l = LoadingScreen()
    print(f"6. 加载页: {l.name}")

    # 7. 主设置页
    m = MainSettingsScreen()
    print(f"7. 主设置页: {m.name}")

    # 8. UI 状态
    st = get_ui_status()
    print(f"8. UI 状态: {st}")

    # 9. EULA 文案
    assert "TiShou" in DisclaimerScreen.eula_text
    print("9. EULA 文案: PASS")

    print("\n" + "=" * 50)
    print("全部 9 项检查通过")
    print("=" * 50)