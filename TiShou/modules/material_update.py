# -*- coding: utf-8 -*-
"""
素材更新模块
===========
遵守全局约束：
  - 仅更新 Python 开源库内置免费素材，不下载第三方独立资源包
  - 全异常捕获，不阻断主流程
  - 联动网络模块与分级日志系统
  - 支持低配机型模式，可关闭自动更新降低性能消耗

功能：
  1. 开机自动检测 + 后台定时轮询（默认 24 小时，支持自定义周期）
  2. 对接 UI 手动更新按钮，进度回调 + 中断支持
  3. 更新失败/网络超时保留原有素材，不阻断主流程
  4. 低配机型开关，关闭自动更新降低性能消耗
  5. 全量异常捕获，联动日志系统
"""

import sys
import os
import time
import threading
import schedule
from datetime import datetime
from typing import Optional, Callable

# 将父目录加入路径以便导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.utils import LogManager, ConfigManager, ExceptionUtil, safe_bool, safe_int
from modules.network import get_network_manager, NetworkState


# ============================================================
# 常量
# ============================================================

# 最小更新间隔（秒）：1 小时
MIN_UPDATE_INTERVAL = 3600

# 进度状态常量
class UpdateStatus:
    """更新状态常量"""

    IDLE = "idle"                    # 空闲
    CHECKING = "checking"            # 检查中
    DOWNLOADING = "downloading"      # 下载中
    INSTALLING = "installing"        # 安装中
    COMPLETED = "completed"          # 完成
    FAILED = "failed"                # 失败
    CANCELLED = "cancelled"          # 已取消


# ============================================================
# 素材更新管理器
# ============================================================
class MaterialUpdateManager:
    """
    素材更新管理器
    =============
    管理 Python 开源库内置素材的版本检测与更新。
    仅操作已安装的开源库，不下载第三方独立资源包。
    """

    def __init__(self):
        """初始化素材更新管理器"""
        self._logger = LogManager.get_logger("material")  # 素材更新日志
        self._config = ConfigManager()

        # ---- 配置参数 ----
        self._auto_update = safe_bool(self._config.get("material_auto_update"), True)
        self._update_interval = safe_int(self._config.get("material_update_interval"), 86400)
        self._low_end_mode = safe_bool(self._config.get("low_end_device"), False)

        # ---- 调度器状态 ----
        self._scheduler_running = False
        self._scheduler_thread = None
        self._scheduler_stop_event = threading.Event()

        # ---- 更新状态 ----
        self._current_status = UpdateStatus.IDLE
        self._status_lock = threading.Lock()
        self._cancel_flag = False          # 中断标记
        self._current_library = ""         # 正在更新的库名
        self._progress = 0.0               # 当前进度 0.0~1.0
        self._last_check_result = {}       # 最近一次检查结果
        self._last_check_time = 0          # 最近一次检查时间戳

        # ---- 进度回调（供 UI 层注册） ----
        self._progress_callbacks = []

        # ---- 网络管理器 ----
        try:
            self._network = get_network_manager()
        except Exception:
            self._network = None

        self._logger.info("素材更新管理器初始化完成")

    # ============================================================
    # 进度回调注册
    # ============================================================

    def register_progress_callback(self, callback: Callable[[dict], None]):
        """
        注册进度回调（供 UI 层展示进度条）

        :param callback: 回调函数，接收参数字典：
            {
                "status": str,        # UpdateStatus 常量
                "library": str,       # 当前操作库名
                "progress": float,    # 进度 0.0~1.0
                "message": str,       # 描述文本
                "error": str or None, # 错误信息
            }
        """
        try:
            if callback not in self._progress_callbacks:
                self._progress_callbacks.append(callback)
        except Exception as e:
            self._logger.warning(f"注册进度回调失败: {e}")

    def _notify_progress(self, status: str, library: str = "",
                         progress: float = 0.0, message: str = "",
                         error: str = None):
        """
        通知所有注册的回调进度更新

        :param status: 状态常量
        :param library: 当前库名
        :param progress: 进度值
        :param message: 描述文本
        :param error: 错误信息
        """
        try:
            payload = {
                "status": status,
                "library": library,
                "progress": progress,
                "message": message,
                "error": error,
                "timestamp": time.time(),
            }
            for cb in self._progress_callbacks:
                try:
                    cb(payload)
                except Exception:
                    pass
        except Exception:
            pass

    # ============================================================
    # 获取状态
    # ============================================================

    def get_status(self) -> dict:
        """
        获取当前更新状态（供 UI 层刷新展示）

        :return: {
            "status": str,
            "library": str,
            "progress": float,
            "is_running": bool,
            "auto_update": bool,
            "low_end_mode": bool,
            "update_interval": int,
            "last_check_time": int,
            "last_check_result": dict,
        }
        """
        try:
            with self._status_lock:
                return {
                    "status": self._current_status,
                    "library": self._current_library,
                    "progress": self._progress,
                    "is_running": self._current_status in (
                        UpdateStatus.CHECKING,
                        UpdateStatus.DOWNLOADING,
                        UpdateStatus.INSTALLING,
                    ),
                    "auto_update": self._auto_update,
                    "low_end_mode": self._low_end_mode,
                    "update_interval": self._update_interval,
                    "last_check_time": self._last_check_time,
                    "last_check_result": self._last_check_result,
                }
        except Exception as e:
            self._logger.error(f"获取状态异常: {e}")
            return {"status": UpdateStatus.IDLE, "error": str(e)}

    # ============================================================
    # 更新检查
    # ============================================================

    @ExceptionUtil.safe_call(default_return={
        "has_updates": False, "updates": [], "error": "检查异常"
    }, log_level="error")
    def check_updates(self) -> dict:
        """
        检查所有素材更新

        联动网络模块：利用 NetworkManager.check_material_updates()
        自动处理双节点切换和缓存。

        :return: {
            "has_updates": bool,
            "updates": [ { "name", "current", "latest", "status" } ],
            "error": str or None,
            "checked_at": int,
        }
        """
        with self._status_lock:
            self._current_status = UpdateStatus.CHECKING
            self._progress = 0.0
            self._cancel_flag = False

        self._notify_progress(UpdateStatus.CHECKING, message="正在检查素材更新...")

        try:
            # 调用网络模块进行版本检测
            if self._network is None:
                self._network = get_network_manager()

            result = self._network.check_material_updates()

            # 记录结果
            self._last_check_result = result
            self._last_check_time = int(time.time())

            has_updates = result.get("has_updates", False)
            error = result.get("error")

            if error:
                self._logger.warning(f"素材检查异常: {error}")
                with self._status_lock:
                    self._current_status = UpdateStatus.FAILED
                self._notify_progress(
                    UpdateStatus.FAILED,
                    message=f"检查失败: {error}",
                    error=error,
                )
            elif has_updates:
                # 统计可更新数量
                updatable = [u for u in result.get("updates", [])
                             if u.get("status") == "可更新"]
                self._logger.info(f"发现 {len(updatable)} 个可更新素材")
                with self._status_lock:
                    self._current_status = UpdateStatus.IDLE
                    self._progress = 1.0
                self._notify_progress(
                    UpdateStatus.COMPLETED,
                    message=f"发现 {len(updatable)} 个可更新素材",
                )
            else:
                self._logger.info("所有素材已是最新版本")
                with self._status_lock:
                    self._current_status = UpdateStatus.IDLE
                    self._progress = 1.0
                self._notify_progress(
                    UpdateStatus.COMPLETED,
                    message="所有素材已是最新版本",
                )

            return result

        except Exception as e:
            self._logger.error(f"检查素材更新异常: {e}")
            with self._status_lock:
                self._current_status = UpdateStatus.FAILED
            self._notify_progress(UpdateStatus.FAILED, message=f"检查异常: {e}", error=str(e))
            return {"has_updates": False, "updates": [], "error": str(e)}

    # ============================================================
    # 更新指定库
    # ============================================================

    @ExceptionUtil.safe_call(default_return=False, log_level="error")
    def update_library(self, lib_name: str) -> bool:
        """
        更新指定的开源库（仅库内置素材，不下载第三方资源包）

        :param lib_name: 库名，如 "easyocr", "Kivy", "pillow", "pygame"
        :return: True=成功, False=失败/已取消
        """
        # 检查中断标记
        if self._cancel_flag:
            self._logger.info(f"更新已取消: {lib_name}")
            return False

        with self._status_lock:
            self._current_status = UpdateStatus.INSTALLING
            self._current_library = lib_name
            self._progress = 0.0

        self._notify_progress(
            UpdateStatus.INSTALLING, library=lib_name,
            progress=0.0, message=f"正在更新 {lib_name}..."
        )

        try:
            # 调用网络模块的 pip 升级
            if self._network is None:
                self._network = get_network_manager()

            # 分阶段进度：连接 0.1 → 下载 0.1~0.8 → 安装 0.8~1.0
            self._update_progress(0.1, f"正在连接镜像源...")

            # 检查中断
            if self._cancel_flag:
                self._finish_cancelled(lib_name)
                return False

            self._update_progress(0.3, f"正在下载 {lib_name}...")

            # 执行更新
            result = self._network.update_material(lib_name)

            if self._cancel_flag:
                self._finish_cancelled(lib_name)
                return False

            if result.get("success"):
                self._update_progress(1.0, f"{lib_name} 更新完成")
                self._logger.info(f"素材更新成功: {lib_name}")
                with self._status_lock:
                    self._current_status = UpdateStatus.IDLE
                return True
            else:
                error_msg = result.get("message", "未知错误")
                self._logger.warning(f"素材更新失败（保留原版）: {lib_name} - {error_msg}")
                with self._status_lock:
                    self._current_status = UpdateStatus.IDLE
                self._notify_progress(
                    UpdateStatus.FAILED, library=lib_name,
                    progress=0.0, message=f"更新失败: {error_msg}",
                    error=error_msg,
                )
                return False

        except Exception as e:
            self._logger.error(f"更新库异常（保留原版）: {lib_name} - {e}")
            with self._status_lock:
                self._current_status = UpdateStatus.IDLE
            self._notify_progress(
                UpdateStatus.FAILED, library=lib_name,
                message=f"更新异常: {e}", error=str(e),
            )
            return False

    def _update_progress(self, value: float, message: str = ""):
        """更新进度（线程安全）"""
        with self._status_lock:
            self._progress = min(max(value, 0.0), 1.0)
        self._notify_progress(
            UpdateStatus.INSTALLING, library=self._current_library,
            progress=self._progress, message=message,
        )

    def _finish_cancelled(self, lib_name: str):
        """处理已取消的更新"""
        self._logger.info(f"更新已中断: {lib_name}")
        with self._status_lock:
            self._current_status = UpdateStatus.CANCELLED
        self._notify_progress(
            UpdateStatus.CANCELLED, library=lib_name,
            message="更新已取消",
        )

    # ============================================================
    # 更新全部可更新库
    # ============================================================

    @ExceptionUtil.safe_call(default_return=False, log_level="error")
    def update_all(self) -> bool:
        """
        更新所有有可用更新的库

        流程：
          1. 先检查更新
          2. 逐个更新有可用更新的库
          3. 更新失败保留原版，继续下一个

        :return: True=全部成功, False=部分失败或全部失败
        """
        self._cancel_flag = False

        # 第一步：检查更新
        check_result = self.check_updates()
        if check_result.get("error"):
            self._logger.error("检查失败，无法执行批量更新")
            return False

        updates = check_result.get("updates", [])
        to_update = [u for u in updates if u.get("status") == "可更新"]

        if not to_update:
            self._logger.info("没有需要更新的素材")
            return True

        self._logger.info(f"开始批量更新 {len(to_update)} 个库...")

        all_success = True
        for i, lib in enumerate(to_update):
            if self._cancel_flag:
                self._logger.info("批量更新已被用户中断")
                return False

            lib_name = lib["name"]
            self._logger.info(f"[{i + 1}/{len(to_update)}] 更新 {lib_name}...")

            # 通知总体进度
            overall_progress = i / len(to_update)
            self._notify_progress(
                UpdateStatus.INSTALLING, library=lib_name,
                progress=overall_progress,
                message=f"[{i + 1}/{len(to_update)}] 正在更新 {lib_name}...",
            )

            success = self.update_library(lib_name)
            if not success:
                all_success = False
                self._logger.warning(f"{lib_name} 更新失败（已保留原版，继续下一项）")

        # 完成
        with self._status_lock:
            self._current_status = UpdateStatus.IDLE
            self._current_library = ""
            self._progress = 1.0

        if all_success:
            self._notify_progress(
                UpdateStatus.COMPLETED,
                message=f"全部 {len(to_update)} 个库更新完成",
            )
        else:
            self._notify_progress(
                UpdateStatus.COMPLETED,
                message="部分库更新完成（失败项已保留原版）",
            )

        self._logger.info(f"批量更新完成: {'全部成功' if all_success else '部分失败'}")
        return all_success

    # ============================================================
    # 中断更新
    # ============================================================

    def cancel_update(self) -> bool:
        """
        中断正在进行的更新

        设置取消标记，正在执行的 update_library 或 update_all
        会在下一个检查点检测该标记并退出。

        :return: True=已设置中断标记
        """
        try:
            self._cancel_flag = True
            self._logger.warning("用户请求中断更新")
            with self._status_lock:
                if self._current_status in (
                    UpdateStatus.CHECKING,
                    UpdateStatus.DOWNLOADING,
                    UpdateStatus.INSTALLING,
                ):
                    self._current_status = UpdateStatus.CANCELLED
            self._notify_progress(
                UpdateStatus.CANCELLED,
                message="更新已中断",
            )
            return True
        except Exception as e:
            self._logger.error(f"中断更新异常: {e}")
            return False

    # ============================================================
    # 自动更新调度
    # ============================================================

    def start_auto_update(self):
        """
        启动自动更新调度

        行为：
          - 低配机型模式下直接返回（不启动）
          - 立即执行首次检查
          - 然后按配置周期定时检查
        """
        try:
            if self._low_end_mode:
                self._logger.info("低配机型模式：自动更新已关闭")
                return

            if not self._auto_update:
                self._logger.info("素材自动更新开关已关闭")
                return

            if self._scheduler_running:
                self._logger.debug("自动更新调度已在运行")
                return

            # ---- 首次立即检查 ----
            self._logger.info("首次启动：立即执行素材检查...")
            try:
                threading.Thread(
                    target=self._run_check_safe,
                    daemon=True,
                    name="material-first-check",
                ).start()
            except Exception as e:
                self._logger.warning(f"首次检查启动失败: {e}")

            # ---- 设置定时调度 ----
            interval_hours = max(1, self._update_interval / 3600)

            # 清除旧调度
            schedule.clear()

            # 注册定时任务
            schedule.every(interval_hours).hours.do(self._run_check_safe)

            # 启动调度线程
            self._scheduler_running = True
            self._scheduler_stop_event.clear()

            self._scheduler_thread = threading.Thread(
                target=self._scheduler_loop,
                daemon=True,
                name="material-scheduler",
            )
            self._scheduler_thread.start()

            self._logger.info(
                f"素材自动更新调度已启动，检查间隔: {interval_hours:.1f} 小时"
            )

        except Exception as e:
            self._logger.error(f"启动自动更新失败: {e}")

    def _run_check_safe(self):
        """安全执行检查（不对外抛异常）"""
        try:
            self.check_updates()
        except Exception as e:
            self._logger.error(f"定时检查异常: {e}")

    def _scheduler_loop(self):
        """调度器主循环"""
        self._logger.debug("调度器线程已启动")
        while not self._scheduler_stop_event.is_set():
            try:
                schedule.run_pending()
                # 每秒唤醒一次检查停止事件
                self._scheduler_stop_event.wait(timeout=1)
            except Exception as e:
                self._logger.error(f"调度循环异常: {e}")
                time.sleep(5)

        self._logger.debug("调度器线程已退出")

    def stop_auto_update(self):
        """停止自动更新调度"""
        try:
            self._scheduler_running = False
            self._scheduler_stop_event.set()
            schedule.clear()
            self._logger.info("素材自动更新调度已停止")
        except Exception as e:
            self._logger.error(f"停止自动更新失败: {e}")

    # ============================================================
    # 开关控制
    # ============================================================

    def set_auto_update(self, enabled: bool):
        """
        设置自动更新开关

        :param enabled: True=开启, False=关闭
        """
        try:
            self._auto_update = enabled
            self._config.set("material_auto_update", enabled)

            if enabled and not self._low_end_mode:
                self.start_auto_update()
            else:
                self.stop_auto_update()

            self._logger.info(f"素材自动更新已{'开启' if enabled else '关闭'}")
        except Exception as e:
            self._logger.error(f"设置自动更新开关失败: {e}")

    def set_low_end_mode(self, enabled: bool):
        """
        设置低配机型模式

        低配模式下：
          - 关闭自动更新检查
          - 仅支持手动更新
          - 减少后台线程消耗

        :param enabled: True=低配模式, False=正常模式
        """
        try:
            self._low_end_mode = enabled
            self._config.set("low_end_device", enabled)

            if enabled:
                # 低配模式：停止自动更新
                self.stop_auto_update()
                self._logger.info("低配机型模式已启用：自动更新已关闭，仅支持手动更新")
            else:
                # 退出低配模式：如果自动更新开启则启动
                if self._auto_update:
                    self.start_auto_update()
                self._logger.info("低配机型模式已禁用")

        except Exception as e:
            self._logger.error(f"设置低配机型模式失败: {e}")

    def set_update_interval(self, interval_seconds: int):
        """
        设置自动更新周期

        :param interval_seconds: 间隔秒数（最少 3600 秒 = 1 小时）
        """
        try:
            self._update_interval = max(MIN_UPDATE_INTERVAL, interval_seconds)
            self._config.set("material_update_interval", self._update_interval)

            # 重启调度以应用新周期
            if self._scheduler_running:
                self.stop_auto_update()
                self.start_auto_update()

            hours = self._update_interval / 3600
            self._logger.info(f"更新周期已设置为: {hours:.1f} 小时")
        except Exception as e:
            self._logger.error(f"设置更新周期失败: {e}")

    # ============================================================
    # 低配模式判断
    # ============================================================

    def is_low_end_mode(self) -> bool:
        """判断是否处于低配机型模式"""
        return self._low_end_mode

    def is_auto_update_enabled(self) -> bool:
        """判断自动更新是否启用"""
        return self._auto_update and not self._low_end_mode

    def is_update_running(self) -> bool:
        """判断是否有更新操作正在执行"""
        with self._status_lock:
            return self._current_status in (
                UpdateStatus.CHECKING,
                UpdateStatus.DOWNLOADING,
                UpdateStatus.INSTALLING,
            )

    # ============================================================
    # 清理资源
    # ============================================================

    def cleanup(self):
        """清理资源（程序退出时调用）"""
        try:
            self.stop_auto_update()
            self._cancel_flag = False
            self._progress_callbacks.clear()
            self._logger.info("素材更新管理器资源已清理")
        except Exception as e:
            self._logger.error(f"清理资源异常: {e}")


# ============================================================
# 单例快捷访问
# ============================================================

_instance = None
_instance_lock = threading.Lock()


def get_material_manager() -> MaterialUpdateManager:
    """
    获取素材更新管理器单例

    :return: MaterialUpdateManager 实例
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = MaterialUpdateManager()
    return _instance


# ============================================================
# 对外便捷接口（供 main.py / UI 层调用）
# ============================================================

def init_material_updater(start_auto: bool = True) -> MaterialUpdateManager:
    """
    初始化素材更新管理器（程序入口调用）

    :param start_auto: 是否立即启动自动更新调度
    :return: MaterialUpdateManager 实例
    """
    mgr = get_material_manager()
    if start_auto:
        mgr.start_auto_update()
    return mgr


def check_material_updates_ui() -> dict:
    """
    UI 层一键检查更新

    :return: 检查结果字典
    """
    try:
        mgr = get_material_manager()
        return mgr.check_updates()
    except Exception as e:
        LogManager.get_logger("material").error(f"UI 检查更新异常: {e}")
        return {"has_updates": False, "updates": [], "error": str(e)}


def update_all_materials_ui(
    progress_callback: Callable[[dict], None] = None
) -> bool:
    """
    UI 层一键更新全部素材

    :param progress_callback: 进度回调
    :return: True=全部成功, False=部分失败
    """
    try:
        mgr = get_material_manager()
        if progress_callback:
            mgr.register_progress_callback(progress_callback)
        return mgr.update_all()
    except Exception as e:
        LogManager.get_logger("material").error(f"UI 批量更新异常: {e}")
        return False


def cancel_material_update_ui() -> bool:
    """
    UI 层中断更新

    :return: True=已中断
    """
    try:
        mgr = get_material_manager()
        return mgr.cancel_update()
    except Exception as e:
        LogManager.get_logger("material").error(f"UI 中断更新异常: {e}")
        return False


def get_material_status_ui() -> dict:
    """
    UI 层获取更新状态

    :return: 状态字典
    """
    try:
        mgr = get_material_manager()
        return mgr.get_status()
    except Exception as e:
        LogManager.get_logger("material").error(f"UI 获取状态异常: {e}")
        return {"status": UpdateStatus.IDLE, "error": str(e)}


def set_low_end_mode_ui(enabled: bool):
    """
    UI 层设置低配机型模式

    :param enabled: True=开启低配模式
    """
    try:
        mgr = get_material_manager()
        mgr.set_low_end_mode(enabled)
    except Exception as e:
        LogManager.get_logger("material").error(f"UI 设置低配模式异常: {e}")


def set_auto_update_ui(enabled: bool):
    """
    UI 层设置自动更新开关

    :param enabled: True=开启自动更新
    """
    try:
        mgr = get_material_manager()
        mgr.set_auto_update(enabled)
    except Exception as e:
        LogManager.get_logger("material").error(f"UI 设置自动更新异常: {e}")