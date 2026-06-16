# -*- coding: utf-8 -*-
"""
统计模块（第11步）
================
遵守全局约束：
  - 仅适配安卓真机（桌面环境日志模拟）
  - 纯 Python 开发
  - 全异常捕获，不闪退
  - 分级日志
  - 低资源占用（惰性持久化，无轮询线程）

功能清单：
  1. 本地持久化记录当日抢单成功、失败次数
  2. 数据展示在主界面，支持一键重置
  3. 数据写入日志，异常自动初始化
  4. 当日日期变更自动重置当日计数
  5. 历史总量累计
  6. 每日明细历史留存（便于回溯）

数据文件：logs/statistics.json
"""

import sys
import os
import json
import time
import threading
from datetime import datetime, date
from typing import Optional, Dict, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.utils import (
    LogManager, ConfigManager, ExceptionUtil,
    safe_int, safe_float, safe_str,
    LOGS_DIR, PROJECT_DIR,
)

# ============================================================
# 常量
# ============================================================

STATISTICS_FILE = os.path.join(LOGS_DIR, "statistics.json")

# ============================================================
# 默认数据结构
# ============================================================

def _default_stats() -> dict:
    """返回默认统计数据结构"""
    today_str = date.today().isoformat()
    return {
        "today": {
            "date": today_str,
            "success": 0,
            "failed": 0,
        },
        "total": {
            "success": 0,
            "failed": 0,
        },
        "daily": {},
        "meta": {
            "last_reset": None,
            "created_at": datetime.now().isoformat(),
            "version": 1,
        },
    }


# ============================================================
# 统计管理器
# ============================================================

class StatisticsManager:
    """
    统计数据管理器（单例）
    ======================
    记录抢单成功/失败次数，持久化到 logs/statistics.json。

    特色：
      - 当日日期变更自动重置今日计数（历史总量不受影响）
      - 惰性持久化：数据变更才写文件，不启动后台线程
      - 全异常捕获，任何读取失败自动初始化默认数据
      - 低资源占用：无轮询、无定时器

    用法：
        mgr = get_statistics_manager()
        mgr.record_success()
        mgr.record_failure()
        today = mgr.get_today_stats()  # {"date": "2026-06-15", "success": 1, "failed": 0}
        summary = mgr.get_summary()    # 完整摘要（含历史总量、今日明细）
        mgr.reset()                    # 一键重置
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._logger = LogManager.get_logger("app")
        self._data_lock = threading.Lock()
        self._data = _default_stats()
        self._dirty = False          # 是否有未保存的变更

        # 加载持久化数据
        self._load()

        # 检查日期变更，自动重置今日计数
        self._check_date_rollover()

        self._logger.info(
            f"统计模块初始化完成 | 今日: {self._data['today']['date']} "
            f"成功: {self._data['today']['success']} "
            f"失败: {self._data['today']['failed']}"
        )

    # ============================================================
    # 持久化
    # ============================================================

    def _load(self):
        """从文件加载统计数据，异常时自动初始化默认"""
        try:
            if not os.path.exists(STATISTICS_FILE):
                self._logger.info("统计数据文件不存在，使用默认数据")
                self._data = _default_stats()
                return

            with open(STATISTICS_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)

            # 验证基本结构
            if not isinstance(raw, dict) or "today" not in raw:
                self._logger.warning("统计数据文件结构异常，重新初始化")
                self._data = _default_stats()
                return

            # 合并缺失字段（向前兼容）
            defaults = _default_stats()
            for section in ("today", "total", "daily", "meta"):
                if section not in raw:
                    raw[section] = defaults[section]
                elif isinstance(raw[section], dict):
                    for k, v in defaults[section].items():
                        raw[section].setdefault(k, v)

            self._data = raw
            self._dirty = False
            self._logger.info("统计数据加载成功")

        except (json.JSONDecodeError, IOError, Exception) as e:
            self._logger.error(f"统计数据加载失败: {e}，已自动初始化默认")
            self._data = _default_stats()
            self._dirty = True

    def _save(self):
        """保存统计数据到文件（仅在数据变更时执行）"""
        try:
            if not self._dirty:
                return

            os.makedirs(LOGS_DIR, exist_ok=True)

            # 原子写入：先写临时文件，再重命名
            temp_path = STATISTICS_FILE + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)

            if os.path.exists(STATISTICS_FILE):
                os.replace(temp_path, STATISTICS_FILE)
            else:
                os.rename(temp_path, STATISTICS_FILE)

            self._dirty = False

        except Exception as e:
            self._logger.error(f"统计数据保存失败: {e}")

    # ============================================================
    # 日期变更检测
    # ============================================================

    def _check_date_rollover(self):
        """
        检测日期是否变更。
        如果已过午夜，自动重置今日计数（历史总量不受影响）。
        """
        try:
            today_str = date.today().isoformat()
            stored_date = self._data["today"].get("date", "")

            if stored_date != today_str:
                # 将前一天的明细存档到 daily
                if stored_date and self._data["today"].get("success", 0) > 0 \
                        or self._data["today"].get("failed", 0) > 0:
                    self._data.setdefault("daily", {})[stored_date] = {
                        "success": self._data["today"]["success"],
                        "failed": self._data["today"]["failed"],
                    }
                    self._logger.info(
                        f"日统计归档: {stored_date} "
                        f"成功={self._data['today']['success']} "
                        f"失败={self._data['today']['failed']}"
                    )

                # 重置今日
                self._data["today"] = {
                    "date": today_str,
                    "success": 0,
                    "failed": 0,
                }
                self._dirty = True
                self._save()
                self._logger.info(f"日期变更: {stored_date} → {today_str}，今日计数已重置")

        except Exception as e:
            self._logger.warning(f"日期变更检测异常: {e}")

    # ============================================================
    # 记录接口
    # ============================================================

    def record_success(self):
        """
        记录一次抢单成功。

        自动：
          - 增加今日成功计数
          - 增加历史成功总量
          - 写入运行日志
          - 持久化到文件
        """
        try:
            with self._data_lock:
                self._check_date_rollover()
                self._data["today"]["success"] += 1
                self._data.setdefault("total", {})["success"] = \
                    self._data["total"].get("success", 0) + 1
                self._dirty = True
                self._save()

            self._logger.info(
                f"抢单成功 | 今日成功: {self._data['today']['success']} "
                f"今日失败: {self._data['today']['failed']} "
                f"历史成功: {self._data['total']['success']}"
            )

        except Exception as e:
            self._logger.error(f"记录抢单成功异常: {e}")

    def record_failure(self):
        """
        记录一次抢单失败。

        自动：
          - 增加今日失败计数
          - 增加历史失败总量
          - 写入运行日志
          - 持久化到文件
        """
        try:
            with self._data_lock:
                self._check_date_rollover()
                self._data["today"]["failed"] += 1
                self._data.setdefault("total", {})["failed"] = \
                    self._data["total"].get("failed", 0) + 1
                self._dirty = True
                self._save()

            self._logger.info(
                f"抢单失败 | 今日成功: {self._data['today']['success']} "
                f"今日失败: {self._data['today']['failed']} "
                f"历史失败: {self._data['total']['failed']}"
            )

        except Exception as e:
            self._logger.error(f"记录抢单失败异常: {e}")

    # ============================================================
    # 查询接口
    # ============================================================

    def get_today_stats(self) -> dict:
        """
        获取当日统计数据（供主界面展示）

        :return: {
            "date": "2026-06-15",        # 日期
            "success": 0,                 # 今日成功次数
            "failed": 0,                  # 今日失败次数
            "total": 0,                   # 今日总抢单次数
            "success_rate": 0.0,          # 今日成功率（%）
        }
        """
        try:
            with self._data_lock:
                self._check_date_rollover()
                today = self._data["today"]
                success = safe_int(today.get("success", 0))
                failed = safe_int(today.get("failed", 0))
                total = success + failed
                rate = (success / total * 100) if total > 0 else 0.0

                return {
                    "date": safe_str(today.get("date", date.today().isoformat())),
                    "success": success,
                    "failed": failed,
                    "total": total,
                    "success_rate": round(rate, 1),
                }

        except Exception as e:
            self._logger.error(f"获取今日统计异常: {e}")
            return {"date": date.today().isoformat(), "success": 0, "failed": 0,
                    "total": 0, "success_rate": 0.0}

    def get_summary(self) -> dict:
        """
        获取完整统计摘要（供主界面/调试使用）

        :return: {
            "today": {                   # 今日数据
                "date": "...",
                "success": 0,
                "failed": 0,
                "total": 0,
                "success_rate": 0.0,
            },
            "total": {                   # 历史累计
                "success": 0,
                "failed": 0,
                "total": 0,
                "success_rate": 0.0,
            },
            "daily_count": 0,            # 有记录的天数
            "last_reset": None,          # 上次重置时间
        }
        """
        try:
            with self._data_lock:
                self._check_date_rollover()

                # 今日
                today_data = self.get_today_stats()

                # 历史累计
                total_success = safe_int(self._data.get("total", {}).get("success", 0))
                total_failed = safe_int(self._data.get("total", {}).get("failed", 0))
                total_all = total_success + total_failed
                total_rate = (total_success / total_all * 100) if total_all > 0 else 0.0

                # 有记录的天数
                daily_count = len(self._data.get("daily", {}))

                # 如果今天有数据，也计入天数
                if today_data["total"] > 0:
                    daily_count += 1

                return {
                    "today": today_data,
                    "total": {
                        "success": total_success,
                        "failed": total_failed,
                        "total": total_all,
                        "success_rate": round(total_rate, 1),
                    },
                    "daily_count": daily_count,
                    "last_reset": self._data.get("meta", {}).get("last_reset"),
                }

        except Exception as e:
            self._logger.error(f"获取统计摘要异常: {e}")
            return {
                "today": {"date": date.today().isoformat(), "success": 0, "failed": 0,
                          "total": 0, "success_rate": 0.0},
                "total": {"success": 0, "failed": 0, "total": 0, "success_rate": 0.0},
                "daily_count": 0, "last_reset": None,
            }

    def get_daily_history(self, max_days: int = 30) -> list:
        """
        获取每日历史记录列表（按日期倒序）

        :param max_days: 最多返回天数
        :return: [{"date": "2026-06-15", "success": 3, "failed": 1}, ...]
        """
        try:
            with self._data_lock:
                self._check_date_rollover()
                daily = self._data.get("daily", {}).copy()

                # 如果今天有数据，加入
                today = self._data["today"]
                if today.get("success", 0) > 0 or today.get("failed", 0) > 0:
                    daily[today["date"]] = {
                        "success": today["success"],
                        "failed": today["failed"],
                    }

                # 按日期倒序排列
                sorted_dates = sorted(daily.keys(), reverse=True)[:max_days]
                result = []
                for d in sorted_dates:
                    entry = daily[d]
                    s = safe_int(entry.get("success", 0))
                    f = safe_int(entry.get("failed", 0))
                    t = s + f
                    rate = (s / t * 100) if t > 0 else 0.0
                    result.append({
                        "date": d,
                        "success": s,
                        "failed": f,
                        "total": t,
                        "success_rate": round(rate, 1),
                    })

                return result

        except Exception as e:
            self._logger.error(f"获取每日历史异常: {e}")
            return []

    # ============================================================
    # 重置
    # ============================================================

    def reset(self):
        """
        一键重置所有统计数据（包括今日和历史）。

        重置后：
          - 今日计数归零
          - 历史总量归零
          - 每日明细清空
          - 记录重置时间
          - 写入日志
        """
        try:
            with self._data_lock:
                old_data = {
                    "today_success": self._data["today"]["success"],
                    "today_failed": self._data["today"]["failed"],
                    "total_success": self._data.get("total", {}).get("success", 0),
                    "total_failed": self._data.get("total", {}).get("failed", 0),
                }

                self._data = _default_stats()
                self._data["meta"]["last_reset"] = datetime.now().isoformat()
                self._dirty = True
                self._save()

            self._logger.info(
                f"统计数据已重置 | "
                f"清除: 今日({old_data['today_success']}成功/{old_data['today_failed']}失败) "
                f"历史({old_data['total_success']}成功/{old_data['total_failed']}失败)"
            )

        except Exception as e:
            self._logger.error(f"重置统计数据异常: {e}")

    # ============================================================
    # 属性
    # ============================================================

    @property
    def today_success(self) -> int:
        """今日成功次数"""
        try:
            return safe_int(self._data["today"].get("success", 0))
        except Exception:
            return 0

    @property
    def today_failed(self) -> int:
        """今日失败次数"""
        try:
            return safe_int(self._data["today"].get("failed", 0))
        except Exception:
            return 0

    @property
    def total_success(self) -> int:
        """历史成功总量"""
        try:
            return safe_int(self._data.get("total", {}).get("success", 0))
        except Exception:
            return 0

    @property
    def total_failed(self) -> int:
        """历史失败总量"""
        try:
            return safe_int(self._data.get("total", {}).get("failed", 0))
        except Exception:
            return 0

    @property
    def today_date(self) -> str:
        """今日日期字符串"""
        try:
            return safe_str(self._data["today"].get("date", date.today().isoformat()))
        except Exception:
            return date.today().isoformat()


# ============================================================
# 全局单例
# ============================================================

_instance = None
_instance_lock = threading.Lock()


def get_statistics_manager() -> StatisticsManager:
    """
    获取统计管理器单例
    :return: StatisticsManager 实例
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = StatisticsManager()
    return _instance


# ============================================================
# 对外便捷接口（供 main.py / UI 层 / 抢单模块 调用）
# ============================================================

def init_statistics() -> dict:
    """
    初始化统计模块（程序入口调用）

    :return: 初始化状态字典
    """
    try:
        mgr = get_statistics_manager()
        today = mgr.get_today_stats()
        summary = mgr.get_summary()
        LogManager.get_logger("app").info("统计模块初始化完成")
        return {
            "status": "ok",
            "today": today,
            "total_success": summary["total"]["success"],
            "total_failed": summary["total"]["failed"],
        }
    except Exception as e:
        LogManager.get_logger("app").error(f"统计模块初始化异常: {e}")
        return {"status": "failed", "error": str(e)}


def record_order_success_ui():
    """
    记录抢单成功（由抢单模块在成功时调用）

    自动完成：
      1. 增加今日成功计数 + 历史成功总量
      2. 持久化到 statistics.json
      3. 写入运行日志
    """
    try:
        mgr = get_statistics_manager()
        mgr.record_success()
    except Exception as e:
        LogManager.get_logger("app").error(f"记录抢单成功异常: {e}")


def record_order_failed_ui():
    """
    记录抢单失败（由抢单模块在失败时调用）

    自动完成：
      1. 增加今日失败计数 + 历史失败总量
      2. 持久化到 statistics.json
      3. 写入运行日志
    """
    try:
        mgr = get_statistics_manager()
        mgr.record_failure()
    except Exception as e:
        LogManager.get_logger("app").error(f"记录抢单失败异常: {e}")


def get_today_stats_ui() -> dict:
    """
    获取当日统计（供主界面展示）

    :return: {
        "date": "2026-06-15",
        "success": 0,
        "failed": 0,
        "total": 0,
        "success_rate": 0.0,
    }
    """
    try:
        mgr = get_statistics_manager()
        return mgr.get_today_stats()
    except Exception as e:
        LogManager.get_logger("app").error(f"获取今日统计异常: {e}")
        return {"date": date.today().isoformat(), "success": 0, "failed": 0,
                "total": 0, "success_rate": 0.0}


def get_statistics_summary_ui() -> dict:
    """
    获取完整统计摘要（供主界面/调试使用）

    :return: 包含 today、total、daily_count、last_reset 的字典
    """
    try:
        mgr = get_statistics_manager()
        return mgr.get_summary()
    except Exception as e:
        LogManager.get_logger("app").error(f"获取统计摘要异常: {e}")
        return {}


def get_daily_history_ui(max_days: int = 30) -> list:
    """
    获取每日历史记录（供主界面展示趋势）

    :param max_days: 最多返回天数
    :return: [{"date": "...", "success": N, "failed": N, "total": N, "success_rate": N}, ...]
    """
    try:
        mgr = get_statistics_manager()
        return mgr.get_daily_history(max_days)
    except Exception as e:
        LogManager.get_logger("app").error(f"获取每日历史异常: {e}")
        return []


def reset_statistics_ui():
    """
    一键重置统计数据（由主界面「重置」按钮调用）

    重置今日 + 历史全部数据，不可撤销。
    """
    try:
        mgr = get_statistics_manager()
        mgr.reset()
    except Exception as e:
        LogManager.get_logger("app").error(f"重置统计数据异常: {e}")


def get_statistics_status_ui() -> dict:
    """
    获取统计模块状态（供调试/监控使用）

    :return: {
        "today_date": "2026-06-15",
        "today_success": 0,
        "today_failed": 0,
        "total_success": 0,
        "total_failed": 0,
        "daily_records": 0,
        "last_reset": None,
    }
    """
    try:
        mgr = get_statistics_manager()
        summary = mgr.get_summary()
        return {
            "today_date": mgr.today_date,
            "today_success": mgr.today_success,
            "today_failed": mgr.today_failed,
            "total_success": mgr.total_success,
            "total_failed": mgr.total_failed,
            "daily_records": summary.get("daily_count", 0),
            "last_reset": summary.get("last_reset"),
        }
    except Exception as e:
        LogManager.get_logger("app").error(f"获取统计状态异常: {e}")
        return {}


# ============================================================
# 模块自测入口
# ============================================================

if __name__ == "__main__":
    """桌面模式自测"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-q", "--quiet", action="store_true", help="静默模式")
    args, _ = parser.parse_known_args()
    quiet = args.quiet

    def log(msg):
        if not quiet:
            print(msg)

    log("=" * 50)
    log("TiShou 统计模块自测（桌面模式）")
    log("=" * 50)

    # 初始化
    mgr = get_statistics_manager()
    log(f"\n初始化完成:")
    log(f"  今日日期: {mgr.today_date}")
    log(f"  今日成功: {mgr.today_success}")
    log(f"  今日失败: {mgr.today_failed}")
    log(f"  历史成功: {mgr.total_success}")
    log(f"  历史失败: {mgr.total_failed}")

    # 记录成功
    log("\n记录抢单成功 x3...")
    mgr.record_success()
    mgr.record_success()
    mgr.record_success()
    today = mgr.get_today_stats()
    log(f"  今日成功: {today['success']}, 今日失败: {today['failed']}")
    log(f"  成功率: {today['success_rate']}%")

    # 记录失败
    log("\n记录抢单失败 x2...")
    mgr.record_failure()
    mgr.record_failure()
    today = mgr.get_today_stats()
    log(f"  今日成功: {today['success']}, 今日失败: {today['failed']}")
    log(f"  成功率: {today['success_rate']}%")

    # 获取摘要
    log("\n完整摘要:")
    summary = mgr.get_summary()
    log(f"  今日: {summary['today']}")
    log(f"  历史累计: {summary['total']}")
    log(f"  有记录天数: {summary['daily_count']}")

    # 获取日历史
    log("\n每日历史:")
    history = mgr.get_daily_history()
    for h in history[:5]:
        log(f"  {h['date']}: 成功={h['success']} 失败={h['failed']} "
            f"总计={h['total']} 成功率={h['success_rate']}%")

    # 重置
    log("\n一键重置...")
    mgr.reset()
    today = mgr.get_today_stats()
    log(f"  重置后今日: 成功={today['success']} 失败={today['failed']}")
    log(f"  重置后历史: 成功={mgr.total_success} 失败={mgr.total_failed}")

    # UI 接口
    log("\nUI 接口测试:")
    status = get_statistics_status_ui()
    log(f"  状态: {status}")
    init_result = init_statistics()
    log(f"  初始化: {init_result['status']}")

    # 异常容错
    log("\n异常容错测试:")
    try:
        mgr2 = get_statistics_manager()
        assert mgr2 is mgr
        log("  单例: PASS")
    except Exception as e:
        log(f"  单例: FAIL ({e})")

    log("\n" + "=" * 50)
    log("统计模块自测完成")
    log("=" * 50)