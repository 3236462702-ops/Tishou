# -*- coding: utf-8 -*-
"""statistics.py 快速功能验证"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 清理旧数据
stats_file = os.path.join("logs", "statistics.json")
if os.path.exists(stats_file):
    os.remove(stats_file)

print("=" * 60)
print("统计模块功能验证")
print("=" * 60)

# 1. 模块导入
from modules.statistics import (
    get_statistics_manager, init_statistics,
    record_order_success_ui, record_order_failed_ui,
    get_today_stats_ui, get_statistics_summary_ui,
    reset_statistics_ui, get_statistics_status_ui,
    get_daily_history_ui,
)
print("1. 模块导入: PASS")

# 2. 初始化
r = init_statistics()
assert r["status"] == "ok"
print("2. 初始化: PASS")

mgr = get_statistics_manager()
assert mgr.today_success == 0
assert mgr.today_failed == 0
print("3. 默认值(0/0): PASS")

# 4. 记录成功 x3
record_order_success_ui()
record_order_success_ui()
record_order_success_ui()
today = get_today_stats_ui()
assert today["success"] == 3
assert today["failed"] == 0
assert today["total"] == 3
assert today["success_rate"] == 100.0
print(f"4. 记录成功x3: success={today['success']} rate={today['success_rate']}% PASS")

# 5. 记录失败 x2
record_order_failed_ui()
record_order_failed_ui()
today = get_today_stats_ui()
assert today["success"] == 3
assert today["failed"] == 2
assert today["total"] == 5
assert today["success_rate"] == 60.0
print(f"5. 记录失败x2: success={today['success']} failed={today['failed']} rate={today['success_rate']}% PASS")

# 6. 摘要
s = get_statistics_summary_ui()
assert s["today"]["success"] == 3
assert s["total"]["success"] == 3
assert s["total"]["failed"] == 2
assert s["daily_count"] == 1
print(f"6. 摘要: today={s['today']} total={s['total']} PASS")

# 7. 重置
reset_statistics_ui()
today = get_today_stats_ui()
assert today["success"] == 0
assert today["failed"] == 0
s = get_statistics_summary_ui()
assert s["total"]["success"] == 0
assert s["total"]["failed"] == 0
assert s["last_reset"] is not None
print("7. 一键重置: PASS")

# 8. 状态接口
st = get_statistics_status_ui()
assert st["today_success"] == 0
assert st["today_failed"] == 0
assert st["total_success"] == 0
assert st["total_failed"] == 0
print(f"8. 状态接口: {st} PASS")

# 9. 每日历史
record_order_success_ui()
record_order_success_ui()
record_order_failed_ui()
hist = get_daily_history_ui()
assert len(hist) >= 1
assert hist[0]["success"] == 2
assert hist[0]["failed"] == 1
print(f"9. 每日历史: {hist[0]} PASS")

# 10. 单例
mgr2 = get_statistics_manager()
assert mgr is mgr2
print("10. 单例: PASS")

# 11. 属性
assert mgr.today_date == "2026-06-15"
assert mgr.total_success == 2
assert mgr.total_failed == 1
print(f"11. 属性: date={mgr.today_date} total_success={mgr.total_success} total_failed={mgr.total_failed} PASS")

# 12. 文件持久化
assert os.path.exists(stats_file)
with open(stats_file, "r") as f:
    data = f.read()
assert "today" in data
assert "total" in data
print("12. 持久化文件: PASS")

print()
print("=" * 60)
print("全部 12 项验证通过!")
print("=" * 60)