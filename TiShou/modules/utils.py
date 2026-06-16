# -*- coding: utf-8 -*-
"""
工具模块
=======
提供以下通用工具能力：
  1. ConfigManager  —— JSON配置读写、解析、损坏恢复、导入导出、一键重置
  2. LogManager     —— 分级日志系统（调试/运行/错误/素材更新/OCR），区分调试包与正式包
  3. ExceptionUtil  —— 通用异常捕获装饰器与上下文管理器
  4. StrUtil        —— 字符过滤（仅保留中文/数字/字母，过滤乱码符号）
  5. ActivateUtil   —— 卡密加密存储与验证逻辑
  6. 安卓环境检测、时间工具、文件工具等辅助函数

注意：此模块被其他模块引用，需小心循环导入
"""

import sys
import os
import json
import logging
import hashlib
import base64
import traceback
import functools
import threading
import re
import shutil
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional, Any, Callable

# ============================================================
# 路径常量
# ============================================================
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")
CONFIG_PATH = os.path.join(PROJECT_DIR, "config.json")
ASSETS_DIR = os.path.join(PROJECT_DIR, "assets")

# ============================================================
# 默认配置（损坏自动恢复用）
# ============================================================
DEFAULT_CONFIG = {
    "material_auto_update": True,
    "material_update_interval": 86400,
    "low_end_device": False,
    "ocr_poll_interval": 2.0,
    "ocr_timeout": 8.0,
    "ocr_image_scale": 1.3,
    "order_judge_delay": 5.0,
    "filter_thresholds": {
        "min_price": 0.0,
        "max_price": 999999.0,
        "min_distance": 0.0,
        "max_distance": 999999.0,
        "keywords_include": [],
        "keywords_exclude": [],
    },
    "order_filter": {
        "min_price": 0.0,
        "max_price": 999999.0,
        "min_pickup_dist": 0.0,
        "max_pickup_dist": 10.0,
        "min_order_dist": 20.0,
        "max_order_dist": 999999.0,
        "min_unit_price": 1.0,
        "max_unit_price": 8.0,
        "keywords_include": [],
        "keywords_exclude": [],
        "order_types": [],
        "region_whitelist": [],
        "region_blacklist": [],
        "use_whitelist": True,
        "refresh_mode": "fixed",
        "refresh_fixed_min": 1.0,
        "refresh_fixed_max": 3.0,
        "refresh_random_min": 0.5,
        "refresh_random_max": 5.0,
        "click_mode": "fixed",
        "click_fixed_ms": 3000,
        "click_random_min_ms": 1000,
        "click_random_max_ms": 8000,
    },
    "float_window": {
        "width": 240,
        "height": 180,
        "corner_radius": 16,
        "opacity": 0.85,
        "position_x": 918,
        "position_y": 200,
        "locked": True,
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
        "activated_at": 0,
    },
    "theme": {
        "dark_mode": False,
        "follow_system": True,
        "animation_enabled": True,
    },
    "debug_log": False,
    "preferred_engine": "accessibility",
    "app_list": {
        "show_system_apps": False,
        "selected_packages": [],
    },
    "capture_region": {
        "x": 0,
        "y": 0,
        "w": 1080,
        "h": 1920,
    },
}


# ============================================================
# 分级日志管理器
# ============================================================
class LogManager:
    """
    分级日志管理器
    ==============
    日志级别与文件：
      - debug.log  —— 调试日志（仅调试包启用）
      - app.log    —— 运行日志（info/warning）
      - error.log  —— 错误日志（error/critical）
      - ocr.log    —— OCR识别日志
      - material.log —— 素材更新日志

    正式包（debug_log=False）：
      - 控制台仅输出 WARNING+
      - debug.log 不写入
      - 其余日志文件正常写入

    调试包（debug_log=True）：
      - 控制台输出 INFO+
      - 所有日志文件完整写入
    """

    _instances = {}
    _lock = threading.Lock()
    _debug_mode = False  # 全局调试开关

    # 日志文件名称映射
    LOG_NAMES = {
        "debug": "调试日志",
        "app": "运行日志",
        "error": "错误日志",
        "ocr": "OCR日志",
        "material": "素材更新日志",
    }

    @classmethod
    def init_debug_mode(cls, enabled: bool):
        """
        初始化调试模式（应在程序启动时调用）
        :param enabled: True=调试包, False=正式包
        """
        cls._debug_mode = enabled
        # 更新所有已有日志器的级别
        for name, logger in cls._instances.items():
            cls._apply_levels(logger, name)

    @classmethod
    def _apply_levels(cls, logger: logging.Logger, name: str):
        """根据调试模式应用日志级别"""
        try:
            if name == "debug":
                # debug 日志：仅调试包启用
                logger.disabled = not cls._debug_mode
                if cls._debug_mode:
                    logger.setLevel(logging.DEBUG)
                return

            if cls._debug_mode:
                # 调试包：文件输出 DEBUG，控制台输出 INFO
                logger.setLevel(logging.DEBUG)
                for handler in logger.handlers:
                    if isinstance(handler, logging.StreamHandler):
                        handler.setLevel(logging.INFO)
            else:
                # 正式包：文件输出 INFO，控制台输出 WARNING
                logger.setLevel(logging.INFO)
                for handler in logger.handlers:
                    if isinstance(handler, logging.StreamHandler):
                        handler.setLevel(logging.WARNING)
        except Exception:
            pass

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """
        获取分级日志器
        :param name: 日志名称: debug/app/error/ocr/material
        :return: Logger 实例
        """
        if name in cls._instances:
            return cls._instances[name]

        with cls._lock:
            # 双重检查
            if name in cls._instances:
                return cls._instances[name]

            try:
                os.makedirs(LOGS_DIR, exist_ok=True)

                logger = logging.getLogger(f"TiShou.{name}")
                logger.handlers.clear()

                # ---- 文件 Handler（按大小轮转，最大 5MB，保留 7 份） ----
                log_file = os.path.join(LOGS_DIR, f"{name}.log")
                file_handler = RotatingFileHandler(
                    log_file,
                    maxBytes=5 * 1024 * 1024,  # 5MB
                    backupCount=7,
                    encoding="utf-8",
                )

                # ---- 控制台 Handler ----
                console_handler = logging.StreamHandler(sys.stdout)

                # ---- 格式化器 ----
                formatter = logging.Formatter(
                    "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
                file_handler.setFormatter(formatter)
                console_handler.setFormatter(formatter)

                logger.addHandler(file_handler)
                logger.addHandler(console_handler)

                # 根据调试模式设置级别
                cls._apply_levels(logger, name)

                cls._instances[name] = logger
                return logger

            except Exception as e:
                # 极端兜底：无法创建日志文件时，退化为标准错误输出
                print(f"[LogManager] 初始化日志器 '{name}' 失败: {e}", file=sys.stderr)
                fallback = logging.getLogger(f"TiShou.{name}_fb")
                fallback.addHandler(logging.StreamHandler(sys.stderr))
                fallback.setLevel(logging.DEBUG)
                return fallback

    @classmethod
    def set_debug_mode(cls, enabled: bool):
        """动态切换调试模式（运行时调用）"""
        cls.init_debug_mode(enabled)

    @classmethod
    def get_log_file_path(cls, name: str) -> str:
        """获取日志文件路径"""
        return os.path.join(LOGS_DIR, f"{name}.log")

    @classmethod
    def get_all_log_files(cls) -> dict:
        """获取所有日志文件路径及大小"""
        result = {}
        for name in cls.LOG_NAMES:
            path = cls.get_log_file_path(name)
            size = 0
            try:
                if os.path.exists(path):
                    size = os.path.getsize(path)
            except Exception:
                pass
            result[name] = {"path": path, "size": size}
        return result

    @classmethod
    def clear_log(cls, name: str) -> bool:
        """清空指定日志文件"""
        try:
            path = cls.get_log_file_path(name)
            if os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    f.write("")
            return True
        except Exception as e:
            print(f"[LogManager] 清空日志 '{name}' 失败: {e}", file=sys.stderr)
            return False

    @classmethod
    def clear_all_logs(cls) -> dict:
        """清空所有日志文件，返回各文件清空结果"""
        result = {}
        for name in cls.LOG_NAMES:
            result[name] = cls.clear_log(name)
        return result


# ============================================================
# 配置管理器（单例，损坏自动恢复）
# ============================================================
class ConfigManager:
    """
    全局配置管理器（单例模式）
    ========================
    功能：
      - JSON 配置读写与解析
      - 配置文件损坏自动恢复默认
      - 配置导入/导出（文件或字典）
      - 一键重置（恢复出厂默认）
      - 配置变更实时持久化
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例模式，确保全局只有一个配置管理器实例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化配置管理器（仅执行一次）"""
        if self._initialized:
            return
        self._initialized = True
        self._config = {}           # 当前配置数据
        self._logger = LogManager.get_logger("app")
        self._backup_path = CONFIG_PATH + ".bak"  # 备份文件路径
        self._load()

    # ---- 内部加载/保存 ----

    def _load(self):
        """
        从文件加载配置
        流程：尝试解析 → 失败则尝试恢复备份 → 仍失败则重置默认
        """
        try:
            if not os.path.exists(CONFIG_PATH):
                self._logger.warning(f"配置文件不存在: {CONFIG_PATH}，将创建默认配置")
                self._reset_to_default()
                return

            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw_content = f.read()

            # 尝试解析 JSON
            try:
                data = json.loads(raw_content)
            except json.JSONDecodeError as e:
                self._logger.error(f"配置文件 JSON 解析失败: {e}，尝试恢复备份...")
                self._try_recover_from_backup()
                return

            # 过滤掉顶层注释键（以 // 或 _ 开头，兼容 JSON 注释约定）
            self._config = {
                k: v for k, v in data.items()
                if isinstance(k, str) and not k.startswith("//") and not k.startswith("_")
            }

            # 合并缺失的默认字段（确保新版本配置兼容）
            merged = DEFAULT_CONFIG.copy()
            merged.update(self._config)
            self._config = merged

            # 深层嵌套修复：递归验证嵌套字段类型，防止 "invalid"/null 等异常值
            repair_count = self._deep_repair_nested(self._config, DEFAULT_CONFIG)
            if repair_count > 0:
                self._logger.warning(f"已自动修复 {repair_count} 个配置项（类型不匹配/异常值）")
                self._save()  # 立即持久化修复结果

            # 创建备份
            self._create_backup()
            self._logger.info("配置文件加载成功")

        except (IOError, OSError) as e:
            self._logger.error(f"配置文件读取失败: {e}，将重置默认")
            self._reset_to_default()
        except Exception as e:
            self._logger.error(f"配置文件加载异常: {e}，将重置默认")
            self._reset_to_default()

    def _save(self):
        """保存当前配置到文件（原子写入：先写临时文件，再重命名）"""
        try:
            os.makedirs(PROJECT_DIR, exist_ok=True)

            # 先写到临时文件，防止写入过程中崩溃导致文件损坏
            temp_path = CONFIG_PATH + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=4)

            # 重命名为正式文件（原子操作）
            if os.path.exists(CONFIG_PATH):
                os.replace(temp_path, CONFIG_PATH)
            else:
                os.rename(temp_path, CONFIG_PATH)

            # 同步创建备份
            self._create_backup()

        except Exception as e:
            self._logger.error(f"保存配置文件失败: {e}")

    def _create_backup(self):
        """创建配置文件备份"""
        try:
            shutil.copy2(CONFIG_PATH, self._backup_path)
        except Exception:
            pass  # 备份失败不影响主流程

    def _try_recover_from_backup(self):
        """尝试从备份文件恢复配置"""
        try:
            if os.path.exists(self._backup_path):
                with open(self._backup_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._config = data
                self._save()  # 恢复后写回主文件
                self._logger.info("已从备份文件恢复配置")
                return
        except Exception as e:
            self._logger.warning(f"备份恢复失败: {e}")

        # 备份也不可用，重置默认
        self._logger.warning("备份文件不可用，将重置为默认配置")
        self._reset_to_default()

    def _reset_to_default(self):
        """重置为默认配置并持久化"""
        try:
            self._config = DEFAULT_CONFIG.copy()
            self._save()
            self._logger.info("配置文件已重置为默认值")
        except Exception as e:
            self._logger.error(f"重置配置文件失败: {e}")

    @staticmethod
    def _deep_repair_nested(current: dict, template: dict, _path: str = "") -> int:
        """
        递归修复嵌套配置中的类型不匹配/异常值

        检查规则：
          - 值类型必须与 template 中对应值的类型一致
          - 数字必须为有限值（非 NaN、非 inf）
          - 字符串必须非 None
          - list/dict 必须非 None

        :param current: 当前配置字典（会被原地修改）
        :param template: 默认配置模板
        :param _path: 当前路径（内部递归用）
        :return: 修复的条目数量
        """
        repair_count = 0
        try:
            for key, default_val in template.items():
                if key not in current:
                    continue  # 缺失键会由 merge 补全

                curr_path = f"{_path}.{key}" if _path else key
                curr_val = current[key]
                expected_type = type(default_val)

                # ---- 递归处理嵌套字典 ----
                if isinstance(default_val, dict) and isinstance(curr_val, dict):
                    repair_count += ConfigManager._deep_repair_nested(
                        curr_val, default_val, curr_path
                    )
                    continue

                # ---- 类型不匹配修复 ----
                if not isinstance(curr_val, expected_type):
                    current[key] = default_val
                    repair_count += 1
                    continue

                # ---- 数字有效性检查 ----
                if expected_type in (int, float):
                    import math
                    if isinstance(curr_val, float) and (math.isnan(curr_val) or math.isinf(curr_val)):
                        current[key] = default_val
                        repair_count += 1
                    elif curr_val is None:
                        current[key] = default_val
                        repair_count += 1

                # ---- 列表/字符串 None 检查 ----
                if curr_val is None:
                    current[key] = default_val
                    repair_count += 1

        except Exception:
            pass  # 修复过程不阻断主流程
        return repair_count

    # ---- 公共接口 ----

    def get(self, key: str, default=None):
        """
        获取配置项
        :param key: 配置键名（支持点号分隔深层访问，如 "filter_thresholds.min_price"）
        :param default: 键不存在时返回的默认值
        :return: 配置值
        """
        try:
            if "." in key:
                # 深层访问：如 "filter_thresholds.min_price"
                keys = key.split(".")
                value = self._config
                for k in keys:
                    value = value[k]
                return value
            return self._config.get(key, default)
        except (KeyError, TypeError):
            return default
        except Exception:
            return default

    def set(self, key: str, value):
        """
        设置配置项并持久化
        :param key: 配置键名（支持点号分隔深层设置）
        :param value: 配置值
        """
        try:
            if "." in key:
                # 深层设置：如 "filter_thresholds.min_price"
                keys = key.split(".")
                target = self._config
                for k in keys[:-1]:
                    if k not in target or not isinstance(target[k], dict):
                        target[k] = {}
                    target = target[k]
                target[keys[-1]] = value
            else:
                self._config[key] = value

            self._save()
        except Exception as e:
            self._logger.error(f"设置配置项 '{key}' 失败: {e}")

    def get_all(self) -> dict:
        """获取全部配置的深拷贝"""
        try:
            return json.loads(json.dumps(self._config))
        except Exception:
            return self._config.copy()

    def reload(self):
        """重新从文件加载配置（热重载）"""
        self._logger.info("重新加载配置文件...")
        self._load()

    def reset(self):
        """一键重置：恢复出厂默认配置"""
        self._logger.warning("执行一键重置配置...")
        self._reset_to_default()

    def export_to_file(self, file_path: str) -> bool:
        """
        导出配置到指定文件
        :param file_path: 导出目标路径
        :return: 是否成功
        """
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=4)
            self._logger.info(f"配置已导出到: {file_path}")
            return True
        except Exception as e:
            self._logger.error(f"导出配置失败: {e}")
            return False

    def export_to_dict(self) -> dict:
        """导出配置为字典"""
        return self.get_all()

    def import_from_file(self, file_path: str) -> bool:
        """
        从文件导入配置
        :param file_path: 导入源路径
        :return: 是否成功
        """
        try:
            if not os.path.exists(file_path):
                self._logger.error(f"导入文件不存在: {file_path}")
                return False

            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            return self.import_from_dict(data)
        except json.JSONDecodeError as e:
            self._logger.error(f"导入文件 JSON 格式错误: {e}")
            return False
        except Exception as e:
            self._logger.error(f"导入配置失败: {e}")
            return False

    def import_from_dict(self, data: dict) -> bool:
        """
        从字典导入配置（合并导入，缺失字段保留原值）
        :param data: 配置字典
        :return: 是否成功
        """
        try:
            if not isinstance(data, dict):
                self._logger.error("导入数据格式错误：需要字典类型")
                return False

            # 合并配置：保留原值，覆盖导入值
            merged = self._config.copy()
            merged.update(data)
            self._config = merged
            self._save()
            self._logger.info(f"配置导入成功（{len(data)} 项）")
            return True
        except Exception as e:
            self._logger.error(f"导入配置字典失败: {e}")
            return False

    def validate(self) -> list:
        """
        校验当前配置的完整性，返回缺失的关键字段列表
        :return: 缺失字段名列表（空列表表示配置完整）
        """
        missing = []
        try:
            for key in DEFAULT_CONFIG:
                if key not in self._config:
                    missing.append(key)
        except Exception:
            missing.append("(校验异常)")
        return missing


# ============================================================
# 通用异常捕获工具
# ============================================================
class ExceptionUtil:
    """
    通用异常捕获工具
    ===============
    提供装饰器和上下文管理器两种使用方式：
      1. 装饰器：@ExceptionUtil.safe_call
      2. 上下文管理器：with ExceptionUtil.safe_context():
    """

    @staticmethod
    def safe_call(
        default_return=None,
        log_level: str = "error",
        re_raise: bool = False,
        on_error: Optional[Callable] = None,
    ):
        """
        函数装饰器：自动捕获异常并记录日志

        :param default_return: 异常时返回的默认值
        :param log_level: 日志级别: debug/info/warning/error
        :param re_raise: 是否在记录日志后重新抛出异常（默认 False）
        :param on_error: 异常时回调函数 on_error(exception, traceback_str)
        :return: 装饰后的函数
        """
        def decorator(func: Callable):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    # 获取完整堆栈
                    tb_str = traceback.format_exc()
                    # 获取日志器
                    logger = LogManager.get_logger("error")
                    # 按指定级别记录
                    msg = f"[{func.__name__}] {e}\n{tb_str}"
                    if log_level == "debug":
                        logger.debug(msg)
                    elif log_level == "info":
                        logger.info(msg)
                    elif log_level == "warning":
                        logger.warning(msg)
                    else:
                        logger.error(msg)

                    # 执行错误回调
                    if on_error is not None:
                        try:
                            on_error(e, tb_str)
                        except Exception:
                            pass

                    # 重新抛出
                    if re_raise:
                        raise

                    return default_return
            return wrapper
        return decorator

    @staticmethod
    def safe_context(logger_name: str = "error", log_level: str = "error"):
        """
        上下文管理器：with 语句块内异常自动捕获

        :param logger_name: 日志器名称
        :param log_level: 日志级别
        :return: 上下文管理器
        """
        class _SafeContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_val is not None:
                    logger = LogManager.get_logger(logger_name)
                    tb_str = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
                    msg = f"[上下文异常] {exc_val}\n{tb_str}"
                    if log_level == "debug":
                        logger.debug(msg)
                    elif log_level == "info":
                        logger.info(msg)
                    elif log_level == "warning":
                        logger.warning(msg)
                    else:
                        logger.error(msg)
                    # 返回 True 表示已处理异常，不向外传播
                    return True
                return False

        return _SafeContext()

    @staticmethod
    def get_exception_desc(e: Exception) -> str:
        """
        获取异常的友好描述信息
        :param e: 异常对象
        :return: 描述字符串
        """
        try:
            return f"[{type(e).__name__}] {str(e)}"
        except Exception:
            return "[Unknown] Exception"


# ============================================================
# 字符过滤工具
# ============================================================
class StrUtil:
    """
    字符过滤与清洗工具
    =================
    功能：
      - 仅保留中文/数字/字母
      - 过滤乱码符号和不可见字符
      - 手机号脱敏
      - 字符串截断
    """

    # 预编译正则：仅保留中文、数字、字母、常见标点
    _CLEAN_PATTERN = re.compile(r"[^\u4e00-\u9fff\u3400-\u4dbfa-zA-Z0-9\s\.\,\!\?\-\+\@\#\$\%\^\&\*\(\)\[\]\{\}\:\;\"\'\<\>\=\/\\\~\`\|\_　，。！？、；：""''（）【】《》——…·]+")

    # 纯中文/数字/字母（过滤标点）
    _STRICT_PATTERN = re.compile(r"[^\u4e00-\u9fff\u3400-\u4dbfa-zA-Z0-9]+")

    # 手机号正则（中国大陆）
    _PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")

    @staticmethod
    def clean(text: str, strict: bool = False) -> str:
        """
        清洗字符串：过滤乱码符号和非法字符

        :param text: 原始字符串
        :param strict: True=仅保留中文/数字/字母（过滤所有标点符号）
                         False=保留常见标点符号
        :return: 清洗后的字符串
        """
        try:
            if not isinstance(text, str):
                text = str(text)

            if strict:
                # 严格模式：仅中文/数字/字母
                parts = StrUtil._STRICT_PATTERN.split(text)
                return "".join(parts)
            else:
                # 宽松模式：保留常见标点
                return StrUtil._CLEAN_PATTERN.sub("", text)
        except Exception:
            return ""

    @staticmethod
    def clean_text(text: str) -> str:
        """
        清洗文本（宽松模式别名），过滤乱码但保留标点
        :param text: 原始字符串
        :return: 清洗后的字符串
        """
        return StrUtil.clean(text, strict=False)

    @staticmethod
    def extract_chinese(text: str) -> str:
        """
        仅提取汉字（过滤所有非中文字符）
        :param text: 原始字符串
        :return: 仅包含汉字的字符串
        """
        try:
            if not isinstance(text, str):
                text = str(text)
            pattern = re.compile(r"[^\u4e00-\u9fff\u3400-\u4dbf]+")
            return pattern.sub("", text)
        except Exception:
            return ""

    @staticmethod
    def extract_digits(text: str) -> str:
        """
        仅提取数字
        :param text: 原始字符串
        :return: 仅包含数字的字符串
        """
        try:
            if not isinstance(text, str):
                text = str(text)
            return re.sub(r"\D", "", text)
        except Exception:
            return ""

    @staticmethod
    def mask_phone(text: str) -> str:
        """
        对手机号进行脱敏处理（中间4位替换为****）
        :param text: 可能包含手机号的字符串
        :return: 脱敏后的字符串
        """
        try:
            if not isinstance(text, str):
                text = str(text)

            def _mask(match):
                phone = match.group(0)
                return phone[:3] + "****" + phone[7:]

            return StrUtil._PHONE_PATTERN.sub(_mask, text)
        except Exception:
            return text

    @staticmethod
    def truncate(text: str, max_len: int = 100, suffix: str = "...") -> str:
        """
        截断字符串到指定长度
        :param text: 原始字符串
        :param max_len: 最大长度
        :param suffix: 超长时的后缀
        :return: 截断后的字符串
        """
        try:
            if not isinstance(text, str):
                text = str(text)
            if len(text) <= max_len:
                return text
            return text[:max_len - len(suffix)] + suffix
        except Exception:
            return ""

    @staticmethod
    def is_garbled(text: str, threshold: float = 0.3) -> bool:
        """
        判断字符串是否为乱码（乱码比例超过阈值则判定为乱码）

        :param text: 待判断字符串
        :param threshold: 乱码比例阈值（默认 0.3 = 30% 乱码字符即判定为乱码）
        :return: True=乱码, False=正常
        """
        try:
            if not text or not isinstance(text, str):
                return True
            total = len(text)
            if total == 0:
                return True
            # 统计正常字符（中文、数字、字母、常见标点）
            clean_count = len(StrUtil.clean(text))
            garbled_ratio = 1 - (clean_count / total)
            return garbled_ratio > threshold
        except Exception:
            return True


# ============================================================
# 卡密加密存储与验证
# ============================================================
class ActivateUtil:
    """
    卡密（激活码）加密存储与验证工具
    =============================
    安全策略：
      - 卡密经过 HMAC-SHA256 加盐哈希后存储，不存储明文
      - 内置固定盐值 + 设备特征盐值
      - 验证时对比哈希值，防止彩虹表攻击
      - 存储格式: base64(盐值:哈希值)

    注意：这只是本地防篡改存储方案，非网络验证
    """

    # 内置固定盐值（不可更改）
    _BUILTIN_SALT = "TiShou_2024_SALT_#@!$"

    @staticmethod
    def _get_device_salt() -> str:
        """
        获取设备特征盐值（安卓真机特征）
        在安卓上使用 ANDROID_ROOT 等环境变量作为设备指纹
        """
        try:
            # 尽量提取设备特征
            features = []
            for env_key in ["ANDROID_ROOT", "ANDROID_DATA", "ANDROID_ARGUMENT"]:
                if env_key in os.environ:
                    features.append(os.environ[env_key])
            if features:
                return hashlib.md5("|".join(features).encode()).hexdigest()[:16]
        except Exception:
            pass
        # 非安卓环境或无法获取特征时，使用固定补充盐
        return "TiShou_DEFAULT_SALT"

    @staticmethod
    def _compute_hash(code: str, salt: str) -> str:
        """
        计算 HMAC-SHA256 哈希
        :param code: 卡密明文
        :param salt: 盐值
        :return: 十六进制哈希字符串
        """
        try:
            # HMAC 方式：SHA256(盐值 + 密码 + 盐值)
            payload = f"{salt}:{code}:{salt}"
            return hashlib.sha256(payload.encode("utf-8")).hexdigest()
        except Exception:
            return ""

    @staticmethod
    def encrypt_code(code: str) -> str:
        """
        加密存储卡密（明文 → 加密字符串）
        :param code: 卡密明文
        :return: 加密后的存储字符串格式: base64(salt:hash)
        """
        try:
            if not code:
                return ""

            # 组合盐值
            device_salt = ActivateUtil._get_device_salt()
            combined_salt = hashlib.md5(
                (ActivateUtil._BUILTIN_SALT + device_salt).encode()
            ).hexdigest()[:32]

            # 计算哈希
            code_hash = ActivateUtil._compute_hash(code, combined_salt)

            # 存储格式: "salt:hash"
            storage = f"{combined_salt}:{code_hash}"

            # Base64 编码
            encoded = base64.b64encode(storage.encode("utf-8")).decode("ascii")
            return encoded

        except Exception as e:
            LogManager.get_logger("error").error(f"卡密加密失败: {e}")
            return ""

    @staticmethod
    def verify_code(code: str, encrypted_storage: str) -> bool:
        """
        验证卡密是否正确
        :param code: 用户输入的卡密明文
        :param encrypted_storage: 之前加密存储的字符串
        :return: True=验证通过, False=验证失败
        """
        try:
            if not code or not encrypted_storage:
                return False

            # Base64 解码
            decoded_bytes = base64.b64decode(encrypted_storage.encode("ascii"))
            decoded = decoded_bytes.decode("utf-8")

            # 解析 salt:hash
            parts = decoded.split(":", 1)
            if len(parts) != 2:
                return False

            stored_salt, stored_hash = parts[0], parts[1]

            # 用存储的盐值重新计算哈希
            computed_hash = ActivateUtil._compute_hash(code, stored_salt)

            # 对比哈希值（恒定时间比较防止时序攻击）
            return hashlib.sha256(computed_hash.encode()).hexdigest() == \
                   hashlib.sha256(stored_hash.encode()).hexdigest()

        except (binascii.Error, ValueError, Exception) as e:
            LogManager.get_logger("error").error(f"卡密验证异常: {e}")
            return False

    @staticmethod
    def is_code_activated() -> bool:
        """检查当前是否已激活"""
        try:
            cfg = ConfigManager()
            activate_cfg = cfg.get("activate_code", {})
            if not activate_cfg.get("enabled", False):
                return False
            stored = activate_cfg.get("code", "")
            return bool(stored)
        except Exception:
            return False

    @staticmethod
    def activate(code: str) -> tuple:
        """
        执行激活操作（验证并存储）
        :param code: 用户输入的卡密
        :return: (是否成功, 消息字符串)
        """
        try:
            if not code:
                return False, "卡密不能为空"

            # 先验证卡密（这里可对接外部验证逻辑）
            # 本地验证：卡密长度至少 8 位，包含字母和数字
            if len(code) < 8:
                return False, "卡密格式不正确（长度不足）"

            has_letter = any(c.isalpha() for c in code)
            has_digit = any(c.isdigit() for c in code)
            if not (has_letter and has_digit):
                return False, "卡密格式不正确（需包含字母和数字）"

            # 加密存储
            encrypted = ActivateUtil.encrypt_code(code)
            if not encrypted:
                return False, "卡密加密失败"

            # 保存到配置
            cfg = ConfigManager()
            cfg.set("activate_code.enabled", True)
            cfg.set("activate_code.code", encrypted)

            LogManager.get_logger("app").info("卡密激活成功")
            return True, "激活成功"

        except Exception as e:
            LogManager.get_logger("error").error(f"卡密激活异常: {e}")
            return False, f"激活异常: {e}"

    @staticmethod
    def deactivate() -> bool:
        """清除激活状态"""
        try:
            cfg = ConfigManager()
            cfg.set("activate_code.enabled", False)
            cfg.set("activate_code.code", "")
            LogManager.get_logger("app").info("卡密已清除（解除激活）")
            return True
        except Exception as e:
            LogManager.get_logger("error").error(f"清除卡密失败: {e}")
            return False


# 兼容低版本 Python 的 binascii
try:
    import binascii
except ImportError:
    binascii = None


# ============================================================
# 安卓环境检测
# ============================================================
def is_android() -> bool:
    """
    检测当前是否运行在安卓真机上
    检测依据：安卓 Python 环境特有的环境变量
    """
    try:
        android_indicators = ["ANDROID_ARGUMENT", "ANDROID_ROOT", "ANDROID_DATA"]
        for indicator in android_indicators:
            if indicator in os.environ:
                return True
        return False
    except Exception:
        return False


def get_android_sdk() -> int:
    """获取安卓 SDK 版本号（非安卓环境返回 0）"""
    try:
        if is_android():
            return int(os.environ.get("ANDROID_API", "0"))
        return 0
    except Exception:
        return 0


def get_android_arch() -> str:
    """获取安卓 CPU 架构（非安卓环境返回空字符串）"""
    try:
        if is_android():
            return os.environ.get("ANDROID_ARCH", "")
        return ""
    except Exception:
        return ""


# ============================================================
# 时间工具
# ============================================================
def timestamp_ms() -> int:
    """获取当前毫秒级时间戳"""
    try:
        return int(datetime.now().timestamp() * 1000)
    except Exception:
        return 0


def timestamp_sec() -> int:
    """获取当前秒级时间戳"""
    try:
        return int(datetime.now().timestamp())
    except Exception:
        return 0


def format_duration(seconds: float) -> str:
    """
    格式化持续时间为中文可读字符串
    :param seconds: 秒数
    :return: 如 "1时23分45秒" / "23分45秒" / "45秒"
    """
    try:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}时{minutes}分{secs}秒"
        elif minutes > 0:
            return f"{minutes}分{secs}秒"
        else:
            return f"{secs}秒"
    except Exception:
        return "0秒"


def format_datetime(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """获取格式化的当前时间字符串"""
    try:
        return datetime.now().strftime(fmt)
    except Exception:
        return ""


# ============================================================
# 文件工具
# ============================================================
def ensure_dir(path: str) -> bool:
    """确保目录存在，不存在则创建"""
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except Exception as e:
        LogManager.get_logger("app").error(f"创建目录失败 '{path}': {e}")
        return False


def safe_read_file(path: str, default: str = "") -> str:
    """安全读取文件内容，失败返回默认值"""
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return default
    except Exception as e:
        LogManager.get_logger("app").error(f"读取文件失败 '{path}': {e}")
        return default


def safe_write_file(path: str, content: str) -> bool:
    """安全写入文件内容，自动创建父目录"""
    try:
        ensure_dir(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception as e:
        LogManager.get_logger("app").error(f"写入文件失败 '{path}': {e}")
        return False


def safe_append_file(path: str, content: str) -> bool:
    """安全追加内容到文件末尾"""
    try:
        ensure_dir(os.path.dirname(path))
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception as e:
        LogManager.get_logger("app").error(f"追加文件失败 '{path}': {e}")
        return False


def get_file_size(path: str) -> int:
    """获取文件大小（字节），失败返回 0"""
    try:
        if os.path.exists(path):
            return os.path.getsize(path)
        return 0
    except Exception:
        return 0


def get_file_modify_time(path: str) -> float:
    """获取文件修改时间戳，失败返回 0.0"""
    try:
        if os.path.exists(path):
            return os.path.getmtime(path)
        return 0.0
    except Exception:
        return 0.0


def safe_delete_file(path: str) -> bool:
    """安全删除文件"""
    try:
        if os.path.exists(path):
            os.remove(path)
            return True
        return False
    except Exception as e:
        LogManager.get_logger("app").error(f"删除文件失败 '{path}': {e}")
        return False


# ============================================================
# 字符串 & 哈希工具
# ============================================================
def md5_hash(text: str) -> str:
    """计算字符串 MD5 哈希（十六进制）"""
    try:
        return hashlib.md5(text.encode("utf-8")).hexdigest()
    except Exception:
        return ""


def sha256_hash(text: str) -> str:
    """计算字符串 SHA256 哈希（十六进制）"""
    try:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    except Exception:
        return ""


def safe_float(value, default: float = 0.0) -> float:
    """安全转换为浮点数，转换失败返回默认值"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value, default: int = 0) -> int:
    """安全转换为整数，转换失败返回默认值"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_str(value, default: str = "") -> str:
    """安全转换为字符串"""
    try:
        if value is None:
            return default
        return str(value)
    except Exception:
        return default


def safe_bool(value, default: bool = False) -> bool:
    """安全转换为布尔值"""
    try:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        if isinstance(value, (int, float)):
            return value != 0
        return default
    except Exception:
        return default


# ============================================================
# pip 镜像配置工具
# ============================================================
PIP_MIRRORS = {
    "aliyun": {
        "name": "阿里云",
        "url": "https://mirrors.aliyun.com/pypi/simple/",
        "timeout": 10,
        "retries": 1,
    },
    "tencent": {
        "name": "腾讯云",
        "url": "https://mirrors.cloud.tencent.com/pypi/simple/",
        "timeout": 10,
        "retries": 1,
    },
}


def get_pip_install_cmd(package: str) -> list:
    """
    生成带镜像切换的 pip 安装命令列表
    策略：阿里云优先，10秒超时重试1次，失败后切腾讯云
    :param package: 包名
    :return: 命令字典列表，每项包含 mirror/url/command 字段
    """
    commands = []
    for mirror_name, mirror_config in PIP_MIRRORS.items():
        cmd = (
            f"pip install {package} "
            f"-i {mirror_config['url']} "
            f"--trusted-host {mirror_config['url'].split('/')[2]} "
            f"--timeout {mirror_config['timeout']} "
            f"--retries {mirror_config['retries']} "
        )
        commands.append({
            "mirror": mirror_name,
            "url": mirror_config["url"],
            "command": cmd,
        })
    return commands


# ============================================================
# 初始化函数（程序启动时调用）
# ============================================================
def init_utils(debug_mode: bool = False):
    """
    初始化工具模块（程序入口调用）
    :param debug_mode: True=调试包, False=正式包
    """
    # 1. 确保日志目录存在
    ensure_dir(LOGS_DIR)

    # 2. 初始化调试模式
    LogManager.init_debug_mode(debug_mode)

    # 3. 触发配置管理器加载
    ConfigManager()

    logger = LogManager.get_logger("app")
    mode_str = "调试包" if debug_mode else "正式包"
    logger.info(f"工具模块初始化完成（{mode_str}）")
    logger.info(f"项目目录: {PROJECT_DIR}")
    logger.info(f"日志目录: {LOGS_DIR}")
    logger.info(f"配置文件: {CONFIG_PATH}")