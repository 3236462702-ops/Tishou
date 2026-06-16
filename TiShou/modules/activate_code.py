# -*- coding: utf-8 -*-
"""
卡密验证模块
===========
处理激活码验证逻辑，遵守全局约束：
  - 仅使用免费、免注册、无授权公共 API
  - 全异常捕获，不闪退
  - 联动 utils 读写配置与日志
  - 纯 Python，适配安卓真机

功能：
  1. 优先免费公共时间 API 取北京时间，本地时间兜底，时间异常弹窗提醒校准
  2. 卡密规则：年+月+日+小时（无前导零）拼接数字，
     计算公式：拼接数字 × 1752434006 − 拼接数字；万能卡密：323662702
  3. 验证成功加密存储标记，开机自动读取，已验证直接跳过验证页
  4. 输入框支持明文/密文切换，验证失败可重复输入
  5. 联动 utils 读写配置与日志，异常正常兜底
"""

import sys
import os
import time
import json
import threading
from datetime import datetime
from typing import Optional, Callable

# 将父目录加入路径以便导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.utils import (
    LogManager, ConfigManager, ActivateUtil, ExceptionUtil,
    is_android, safe_int, safe_str, timestamp_sec,
)


# ============================================================
# 常量
# ============================================================

# 万能卡密（始终有效）
UNIVERSAL_CODE = "323662702"

# 卡密计算公式基数
CODE_MULTIPLIER = 1752434006

# 免费公共时间 API 节点（免注册、无授权）
TIME_API_NODES = [
    {
        "name": "世界时间API",
        "url": "http://worldtimeapi.org/api/timezone/Asia/Shanghai",
        "path": "unixtime",           # 返回字段路径
        "timeout": 5,
    },
    {
        "name": "Taobao时间戳",
        "url": "http://api.m.taobao.com/rest/api3.do?api=mtop.common.getTimestamp",
        "path": "data.t",             # 返回字段路径（毫秒时间戳字符串）
        "timeout": 5,
    },
    {
        "name": "TimeAPI",
        "url": "https://timeapi.io/api/Time/current/zone?timeZone=Asia/Shanghai",
        "path": "epochMillis",        # 返回字段路径（毫秒时间戳）
        "timeout": 5,
    },
]

# 时间偏差阈值（秒）：超过此值认为系统时间异常
TIME_DRIFT_THRESHOLD = 300  # 5 分钟

# 卡密在 config.json 中的存储键
CONFIG_ENABLED_KEY = "activate_code.enabled"
CONFIG_CODE_KEY = "activate_code.code"
CONFIG_ACTIVATED_AT_KEY = "activate_code.activated_at"


# ============================================================
# 时间同步器
# ============================================================

class TimeSyncer:
    """
    北京时间同步器
    =============
    通过免费公共时间 API 获取北京时间，本地时间兜底。
    检测系统时间偏差，偏差过大时提供校准提醒。
    """

    def __init__(self):
        """初始化时间同步器"""
        self._logger = LogManager.get_logger("app")

        # 缓存最新的北京时间（秒级时间戳）
        self._beijing_time: Optional[int] = None
        self._last_sync_time: float = 0.0

        # 同步锁
        self._lock = threading.Lock()

        # 时间偏差检测结果
        self._drift_detected = False
        self._drift_seconds = 0

        # 时间回调（供 UI 层弹窗提醒校准）
        self._time_callbacks = []

    def register_time_callback(self, callback: Callable[[dict], None]):
        """
        注册时间异常回调（供 UI 层弹窗提醒校准）
        :param callback: 回调函数，参数: { "drift": int, "message": str }
        """
        try:
            if callback not in self._time_callbacks:
                self._time_callbacks.append(callback)
        except Exception:
            pass

    def _notify_time_issue(self, drift: int, message: str):
        """通知所有注册的回调时间异常"""
        payload = {"drift": drift, "message": message}
        for cb in self._time_callbacks:
            try:
                cb(payload)
            except Exception:
                pass

    @ExceptionUtil.safe_call(default_return=None, log_level="warning")
    def sync_beijing_time(self) -> Optional[int]:
        """
        同步北京时间（优先公共 API，本地时间兜底）

        流程：
          1. 遍历免费公共时间 API 节点
          2. 成功则返回北京时间时间戳
          3. 全部失败则使用本地时间
          4. 检测时间偏差，偏差过大触发回调

        :return: 北京时间秒级时间戳，失败返回本地时间戳
        """
        beijing_time = None
        api_success = False

        for node in TIME_API_NODES:
            try:
                self._logger.info(f"正在从 {node['name']} 获取北京时间...")

                import requests
                resp = requests.get(
                    node["url"],
                    timeout=node["timeout"],
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Linux; Android 14; TiShou) "
                            "AppleWebKit/537.36"
                        ),
                    },
                )

                if resp.status_code != 200:
                    self._logger.warning(f"{node['name']} 响应异常: HTTP {resp.status_code}")
                    continue

                data = resp.json()

                # 根据路径提取时间戳
                timestamp = self._extract_timestamp(data, node["path"])
                if timestamp is not None:
                    beijing_time = timestamp
                    api_success = True
                    self._logger.info(f"从 {node['name']} 获取北京时间成功: {beijing_time}")
                    break

            except ImportError:
                # requests 未安装，直接退出 API 尝试
                self._logger.warning("requests 未安装，跳过网络时间同步")
                break
            except requests.Timeout:
                self._logger.warning(f"{node['name']} 超时 ({node['timeout']}s)")
                continue
            except requests.ConnectionError:
                self._logger.warning(f"{node['name']} 连接失败")
                continue
            except Exception as e:
                self._logger.warning(f"{node['name']} 异常: {e}")
                continue

        # ---- 全部 API 失败：使用本地时间兜底 ----
        if beijing_time is None:
            local_now = int(time.time())
            # 本地时间 + 8 小时 ≈ 北京时间（取决于系统时区）
            local_tz_offset = -time.timezone if time.timezone != 0 else 0
            beijing_offset = 8 * 3600  # UTC+8
            beijing_time = local_now + (beijing_offset - local_tz_offset) // 1
            self._logger.warning(f"API 全部失败，使用本地时间估算: {beijing_time}")

        # ---- 时间偏差检测 ----
        with self._lock:
            local_now = int(time.time())
            drift = abs(beijing_time - local_now)
            self._drift_seconds = drift
            self._beijing_time = beijing_time
            self._last_sync_time = time.time()

            if drift > TIME_DRIFT_THRESHOLD:
                self._drift_detected = True
                drift_minutes = drift // 60
                message = (
                    f"系统时间与北京时间偏差约 {drift_minutes} 分钟，"
                    f"可能影响卡密验证和抢单判定，请校准系统时间"
                )
                self._logger.warning(f"时间偏差过大: {drift}s")
                self._notify_time_issue(drift, message)
            else:
                self._drift_detected = False

        return beijing_time

    def _extract_timestamp(self, data: dict, path: str) -> Optional[int]:
        """
        从 API 响应中提取时间戳

        :param data: API 返回的 JSON 字典
        :param path: 字段路径，如 "data.t" 或 "epochMillis"
        :return: 秒级时间戳，失败返回 None
        """
        try:
            # 按点号分割路径，逐层提取
            keys = path.split(".")
            value = data
            for key in keys:
                if isinstance(value, dict):
                    value = value.get(key)
                else:
                    return None

            if value is None:
                return None

            # 转换为整数（处理字符串类型）
            if isinstance(value, str):
                if len(value) > 13:
                    # 微秒级时间戳
                    return int(value) // 1000000
                elif len(value) > 10:
                    # 毫秒级时间戳
                    return int(value) // 1000
                else:
                    return int(value)
            elif isinstance(value, (int, float)):
                if value > 1000000000000:
                    # 毫秒级
                    return int(value // 1000)
                else:
                    return int(value)

            return None
        except Exception:
            return None

    @ExceptionUtil.safe_call(default_return=None, log_level="warning")
    def get_beijing_time(self, force_sync: bool = False) -> Optional[int]:
        """
        获取最新北京时间

        :param force_sync: True=强制重新同步, False=使用缓存
        :return: 秒级时间戳，失败返回 None
        """
        with self._lock:
            # 缓存有效期 60 秒
            if (not force_sync
                and self._beijing_time is not None
                and time.time() - self._last_sync_time < 60):
                return self._beijing_time

        # 需要重新同步
        return self.sync_beijing_time()

    def get_drift_info(self) -> dict:
        """
        获取时间偏差信息（供 UI 展示）

        :return: {
            "drift_detected": bool,
            "drift_seconds": int,
            "drift_minutes": int,
            "beijing_time": int or None,
            "last_sync": float,
        }
        """
        with self._lock:
            return {
                "drift_detected": self._drift_detected,
                "drift_seconds": self._drift_seconds,
                "drift_minutes": self._drift_seconds // 60,
                "beijing_time": self._beijing_time,
                "last_sync": self._last_sync_time,
            }


# ============================================================
# 卡密生成与验证
# ============================================================

class CodeGenerator:
    """
    卡密生成器
    =========
    根据北京时间生成当日/当时有效的卡密。

    卡密规则：
      - 取北京时间：年 + 月 + 日 + 小时（无前导零），拼接为整数 base
      - 计算公式：code = base × 1752434006 − base
      - 万能卡密：323662702（始终有效，用于特殊场景）
    """

    @staticmethod
    def _get_base_number(dt: Optional[datetime] = None) -> int:
        """
        根据时间生成拼接基数

        :param dt: 日期时间对象，None=使用当前北京时间
        :return: 拼接后的整数，如 202561510 → 2025年6月15日10时
        """
        try:
            if dt is None:
                # 使用当前本地时间（已在北京时区或通过 TimeSyncer 校正）
                dt = datetime.now()

            year = dt.year          # 如 2025
            month = dt.month        # 如 6（无前导零）
            day = dt.day            # 如 15（无前导零）
            hour = dt.hour          # 如 10（无前导零，24小时制）

            # 拼接：年+月+日+小时
            # 注意：月/日/小时均无前导零
            base_str = f"{year}{month}{day}{hour}"
            return int(base_str)

        except Exception:
            # 极端兜底：返回一个基于时间戳的基数
            return int(time.time()) % 100000000

    @staticmethod
    def generate_code(dt: Optional[datetime] = None) -> str:
        """
        生成卡密

        :param dt: 日期时间对象，None=当前时间
        :return: 卡密字符串（纯数字）
        """
        try:
            base = CodeGenerator._get_base_number(dt)
            # 计算公式：base × 1752434006 − base
            code = base * CODE_MULTIPLIER - base
            return str(code)
        except Exception as e:
            LogManager.get_logger("error").error(f"卡密生成异常: {e}")
            return ""

    @staticmethod
    def generate_today_codes() -> list:
        """
        生成今天所有小时的卡密列表
        （供调试或预校验使用）

        :return: 卡密字符串列表，最多 24 个
        """
        codes = []
        try:
            now = datetime.now()
            for hour in range(24):
                dt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
                code = CodeGenerator.generate_code(dt)
                if code:
                    codes.append(code)
        except Exception:
            pass
        return codes

    @staticmethod
    def is_valid_code(input_code: str, beijing_time: Optional[int] = None) -> bool:
        """
        验证卡密是否有效

        验证逻辑：
          1. 万能卡密直接通过
          2. 用北京时间生成当前小时卡密比对
          3. 同时匹配上一小时（容错跨小时）
          4. 空/非数字直接拒绝

        :param input_code: 用户输入的卡密
        :param beijing_time: 北京时间时间戳，None=使用本地时间
        :return: True=有效, False=无效
        """
        try:
            if not input_code:
                return False

            code_str = input_code.strip()

            # ---- 万能卡密 ----
            if code_str == UNIVERSAL_CODE:
                return True

            # ---- 必须是纯数字 ----
            if not code_str.isdigit():
                return False

            # ---- 根据北京时间验证 ----
            if beijing_time is not None:
                dt = datetime.fromtimestamp(beijing_time)
            else:
                dt = datetime.now()

            # 验证当前小时
            current_code = CodeGenerator.generate_code(dt)
            if code_str == current_code:
                return True

            # 验上一小时（容错跨小时/分钟临界）
            from datetime import timedelta
            prev_dt = dt - timedelta(hours=1)
            prev_code = CodeGenerator.generate_code(prev_dt)
            if code_str == prev_code:
                return True

            return False

        except Exception as e:
            LogManager.get_logger("error").error(f"卡密验证异常: {e}")
            return False


# ============================================================
# 卡密验证管理器
# ============================================================

class ActivateCodeManager:
    """
    卡密验证管理器
    =============
    管理卡密验证的完整生命周期：
      - 验证逻辑（时间同步 → 卡密校验）
      - 验证状态持久化（加密存储到 config.json）
      - 开机自动读取验证状态
      - 输入状态管理（明文/密文切换、失败重试）
    """

    def __init__(self):
        """初始化卡密验证管理器"""
        self._logger = LogManager.get_logger("app")
        self._config = ConfigManager()

        # 时间同步器
        self._time_syncer = TimeSyncer()

        # 验证状态（内存缓存）
        self._activated = False          # 是否已验证通过
        self._activated_at = 0           # 验证通过的时间戳
        self._last_verify_time = 0       # 最近一次验证时间
        self._verify_count = 0           # 验证尝试次数
        self._last_error = ""            # 最近一次错误信息

        # 输入状态（供 UI 层使用）
        self._show_plaintext = False     # 是否明文显示密码
        self._input_code = ""            # 当前输入框内容

        # 北京时间缓存
        self._beijing_time: Optional[int] = None

        # 状态变更回调（供 UI 层监听）
        self._state_callbacks = []

        # 启动时读取已存储的验证状态
        self._load_activation_state()

        self._logger.info("卡密验证管理器初始化完成")

    # ============================================================
    # 状态持久化
    # ============================================================

    def _load_activation_state(self):
        """从配置文件读取已存储的验证状态"""
        try:
            enabled = self._config.get("activate_code.enabled", False)
            stored_code = self._config.get("activate_code.code", "")
            activated_at = safe_int(
                self._config.get("activate_code.activated_at"), 0
            )

            if enabled and stored_code:
                # 用 ActivateUtil 验证存储的加密标记是否有效
                # （防止配置文件被篡改或损坏）
                if self._verify_stored_mark(stored_code):
                    self._activated = True
                    self._activated_at = activated_at
                    self._logger.info(
                        f"读取到已验证状态，验证时间: {activated_at}"
                    )
                else:
                    self._logger.warning("存储的验证标记无效，需要重新验证")
                    self._activated = False
            else:
                self._activated = False

        except Exception as e:
            self._logger.error(f"读取验证状态异常: {e}")
            self._activated = False

    def _verify_stored_mark(self, stored_mark: str) -> bool:
        """
        验证存储的加密标记是否有效

        :param stored_mark: ActivateUtil.encrypt_code 加密后的标记
        :return: True=有效
        """
        try:
            if not stored_mark:
                return False

            # 使用万能卡密作为验证密钥（仅用于本地标记验证）
            # 用 ActivateUtil 验证加密标记的一致性
            return ActivateUtil.verify_code(UNIVERSAL_CODE, stored_mark)

        except Exception:
            return False

    def _save_activation_state(self):
        """持久化验证状态到配置文件"""
        try:
            # 用万能卡密生成加密存储标记（仅标记已验证，不存真实卡密）
            encrypted_mark = ActivateUtil.encrypt_code(UNIVERSAL_CODE)

            self._config.set(CONFIG_ENABLED_KEY, True)
            self._config.set(CONFIG_CODE_KEY, encrypted_mark)
            self._config.set(
                CONFIG_ACTIVATED_AT_KEY,
                self._activated_at or int(time.time()),
            )
            self._logger.info("验证状态已持久化到配置")

        except Exception as e:
            self._logger.error(f"持久化验证状态异常: {e}")

    def _clear_activation_state(self):
        """清除验证状态（重置/解绑时使用）"""
        try:
            self._config.set(CONFIG_ENABLED_KEY, False)
            self._config.set(CONFIG_CODE_KEY, "")
            self._config.set(CONFIG_ACTIVATED_AT_KEY, 0)
            self._activated = False
            self._activated_at = 0
            self._logger.info("验证状态已清除")
        except Exception as e:
            self._logger.error(f"清除验证状态异常: {e}")

    # ============================================================
    # 时间同步
    # ============================================================

    def register_time_callback(self, callback: Callable[[dict], None]):
        """
        注册时间异常回调（供 UI 层弹窗）
        :param callback: 回调函数，参数见 TimeSyncer
        """
        self._time_syncer.register_time_callback(callback)

    @ExceptionUtil.safe_call(default_return=None, log_level="warning")
    def sync_time(self, force: bool = False) -> Optional[int]:
        """
        同步北京时间

        :param force: True=强制重新同步
        :return: 北京时间秒级时间戳
        """
        beijing_time = self._time_syncer.get_beijing_time(force_sync=force)
        if beijing_time is not None:
            self._beijing_time = beijing_time
        return beijing_time

    def get_time_info(self) -> dict:
        """
        获取时间同步信息
        :return: 时间状态字典
        """
        return self._time_syncer.get_drift_info()

    # ============================================================
    # 卡密验证
    # ============================================================

    @ExceptionUtil.safe_call(
        default_return=(False, "验证过程异常，请重试"),
        log_level="error",
    )
    def verify(self, code: str) -> tuple:
        """
        验证卡密

        完整流程：
          1. 同步北京时间
          2. 按规则验证卡密
          3. 成功则加密持久化
          4. 失败记录日志，允许重试

        :param code: 用户输入的卡密
        :return: (是否成功, 消息字符串)
        """
        if not code or not code.strip():
            self._verify_count += 1
            self._last_error = "卡密不能为空"
            return False, "卡密不能为空"

        input_code = code.strip()
        self._verify_count += 1

        # ---- 第1步：同步北京时间 ----
        beijing_time = self.sync_time()

        # ---- 第2步：验证卡密 ----
        if CodeGenerator.is_valid_code(input_code, beijing_time):
            # 验证成功
            self._activated = True
            self._activated_at = int(time.time())
            self._last_verify_time = self._activated_at
            self._last_error = ""

            # 持久化到配置文件
            self._save_activation_state()

            self._logger.info(f"卡密验证成功 (尝试次数: {self._verify_count})")
            self._notify_state_change("activated", {
                "message": "验证成功",
                "activated_at": self._activated_at,
            })

            return True, "验证成功"

        # ---- 第3步：验证失败 ----
        self._last_error = "卡密无效或已过期"
        self._logger.warning(
            f"卡密验证失败: {input_code[:4]}**** "
            f"(尝试次数: {self._verify_count})"
        )

        # 时间异常提示
        time_info = self.get_time_info()
        if time_info.get("drift_detected"):
            drift_msg = (
                f"系统时间偏差约 {time_info.get('drift_minutes', 0)} 分钟，"
                f"请校准系统时间后重试"
            )
            return False, drift_msg

        return False, "卡密无效或已过期"

    @ExceptionUtil.safe_call(default_return=(False, "验证异常"), log_level="error")
    def verify_with_time_sync(self, code: str) -> tuple:
        """
        验证卡密（含强制时间同步）

        与 verify() 的区别：先强制同步时间再验证，
        适用于用户手动点击"验证"按钮的场景。

        :param code: 用户输入的卡密
        :return: (是否成功, 消息字符串)
        """
        # 强制同步时间
        beijing_time = self.sync_time(force=True)

        if beijing_time is None:
            self._logger.warning("时间同步失败，使用本地时间验证")

        return self.verify(code)

    # ============================================================
    # 状态查询
    # ============================================================

    @property
    def is_activated(self) -> bool:
        """是否已验证通过"""
        return self._activated

    def is_activation_expired(self, max_age_days: int = 30) -> bool:
        """
        检查验证是否过期（可根据需要定期重新验证）

        :param max_age_days: 最大有效天数
        :return: True=已过期
        """
        try:
            if not self._activated:
                return True
            if self._activated_at <= 0:
                return True
            elapsed = time.time() - self._activated_at
            return elapsed > max_age_days * 86400
        except Exception:
            return True

    def can_skip_verification_page(self) -> bool:
        """
        判断是否可以跳过验证页
        （UI 层启动时调用：已验证且未过期则直接跳转主界面）

        :return: True=跳过, False=需要验证
        """
        try:
            if not self._activated:
                return False
            if not self._activated_at:
                return False

            # 验证状态每 30 天重新校验一次
            if self.is_activation_expired(30):
                self._logger.info("验证状态已过期，需要重新验证")
                return False

            return True

        except Exception:
            return False

    def get_verify_info(self) -> dict:
        """
        获取验证信息（供 UI 展示）

        :return: {
            "activated": bool,
            "activated_at": int,
            "activated_date": str,
            "verify_count": int,
            "last_error": str,
            "show_plaintext": bool,
            "time_info": dict,
        }
        """
        try:
            activated_date = ""
            if self._activated_at > 0:
                activated_date = datetime.fromtimestamp(
                    self._activated_at
                ).strftime("%Y-%m-%d %H:%M:%S")

            return {
                "activated": self._activated,
                "activated_at": self._activated_at,
                "activated_date": activated_date,
                "verify_count": self._verify_count,
                "last_error": self._last_error,
                "show_plaintext": self._show_plaintext,
                "time_info": self.get_time_info(),
                "can_skip": self.can_skip_verification_page(),
            }
        except Exception as e:
            self._logger.error(f"获取验证信息异常: {e}")
            return {
                "activated": False,
                "error": str(e),
            }

    # ============================================================
    # 输入状态管理（供 UI 层使用）
    # ============================================================

    def toggle_plaintext(self) -> bool:
        """
        切换明文/密文显示状态
        :return: 当前状态: True=明文, False=密文
        """
        try:
            self._show_plaintext = not self._show_plaintext
            self._notify_state_change("plaintext_toggled", {
                "show_plaintext": self._show_plaintext,
            })
            return self._show_plaintext
        except Exception:
            return False

    def set_input_code(self, code: str):
        """更新当前输入框内容（UI 层调用）"""
        self._input_code = safe_str(code)

    def get_input_code(self) -> str:
        """获取当前输入框内容"""
        return self._input_code

    def reset_input(self):
        """重置输入状态（清空输入框）"""
        try:
            self._input_code = ""
            self._last_error = ""
            self._notify_state_change("input_reset", {})
        except Exception:
            pass

    # ============================================================
    # 解绑/重置
    # ============================================================

    @ExceptionUtil.safe_call(default_return=False, log_level="warning")
    def deactivate(self) -> bool:
        """
        解除激活状态（解绑设备时使用）
        :return: True=成功
        """
        self._clear_activation_state()
        self._verify_count = 0
        self._last_error = ""
        self._input_code = ""
        self._logger.info("卡密已解除激活")

        self._notify_state_change("deactivated", {
            "message": "已解除激活",
        })
        return True

    # ============================================================
    # 生成示例卡密
    # ============================================================

    @staticmethod
    def get_today_code_example() -> str:
        """
        获取当前小时的有效卡密示例（供 UI 展示提示）

        :return: 卡密字符串
        """
        try:
            return CodeGenerator.generate_code()
        except Exception:
            return ""

    @staticmethod
    def get_universal_code() -> str:
        """获取万能卡密（供特殊场景使用）"""
        return UNIVERSAL_CODE

    # ============================================================
    # 回调管理
    # ============================================================

    def register_state_callback(self, callback: Callable[[str, dict], None]):
        """
        注册状态变更回调（供 UI 层监听）

        :param callback: 回调函数(event_type, data)
            event_type: "activated" / "deactivated" / "plaintext_toggled" / "input_reset"
        """
        try:
            if callback not in self._state_callbacks:
                self._state_callbacks.append(callback)
        except Exception:
            pass

    def _notify_state_change(self, event_type: str, data: dict):
        """通知所有回调状态变更"""
        for cb in self._state_callbacks:
            try:
                cb(event_type, data)
            except Exception:
                pass

    # ============================================================
    # 清理资源
    # ============================================================

    def cleanup(self):
        """清理资源"""
        try:
            self._state_callbacks.clear()
            self._logger.info("卡密验证管理器资源已清理")
        except Exception as e:
            self._logger.error(f"卡密管理器清理异常: {e}")


# ============================================================
# 单例快捷访问
# ============================================================

_instance = None
_instance_lock = threading.Lock()


def get_activate_manager() -> ActivateCodeManager:
    """
    获取卡密验证管理器单例
    :return: ActivateCodeManager 实例
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ActivateCodeManager()
    return _instance


# ============================================================
# 对外便捷接口（供 main.py / UI 层调用）
# ============================================================

def init_activate_code() -> dict:
    """
    初始化卡密验证系统（程序入口调用）

    自动读取已存储的验证状态，
    返回验证信息供 UI 层决定跳转验证页还是主界面。

    :return: 验证信息字典
    """
    try:
        mgr = get_activate_manager()
        info = mgr.get_verify_info()
        LogManager.get_logger("app").info(
            f"卡密验证系统初始化: "
            f"activated={info.get('activated')}, "
            f"can_skip={info.get('can_skip')}"
        )
        return info
    except Exception as e:
        LogManager.get_logger("app").error(f"初始化卡密验证系统异常: {e}")
        return {
            "activated": False,
            "can_skip": False,
            "error": str(e),
        }


def verify_code_ui(code: str) -> tuple:
    """
    UI 层验证卡密

    :param code: 用户输入的卡密
    :return: (是否成功, 消息字符串)
    """
    try:
        mgr = get_activate_manager()
        return mgr.verify_with_time_sync(code)
    except Exception as e:
        LogManager.get_logger("app").error(f"UI 验证卡密异常: {e}")
        return False, f"验证异常: {e}"


def get_verify_info_ui() -> dict:
    """
    UI 层获取验证信息
    :return: 验证信息字典
    """
    try:
        mgr = get_activate_manager()
        return mgr.get_verify_info()
    except Exception as e:
        LogManager.get_logger("app").error(f"UI 获取验证信息异常: {e}")
        return {"activated": False, "error": str(e)}


def toggle_plaintext_ui() -> bool:
    """
    UI 层切换明文/密文显示
    :return: True=明文, False=密文
    """
    try:
        mgr = get_activate_manager()
        return mgr.toggle_plaintext()
    except Exception as e:
        LogManager.get_logger("app").error(f"UI 切换明文异常: {e}")
        return False


def deactivate_code_ui() -> bool:
    """
    UI 层解除激活
    :return: True=成功
    """
    try:
        mgr = get_activate_manager()
        return mgr.deactivate()
    except Exception as e:
        LogManager.get_logger("app").error(f"UI 解除激活异常: {e}")
        return False


def get_today_code_example_ui() -> str:
    """
    UI 层获取当前小时卡密示例（提示用）
    :return: 示例卡密字符串
    """
    try:
        return ActivateCodeManager.get_today_code_example()
    except Exception:
        return ""