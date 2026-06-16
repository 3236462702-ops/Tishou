# -*- coding: utf-8 -*-
"""极简验证 - 所有输出进文件"""
import sys, os, json, traceback

try:
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _project_dir = os.path.abspath(os.path.join(_script_dir, ".."))
    sys.path.insert(0, _project_dir)
    os.chdir(_project_dir)

    R = {"passed": [], "failed": []}
    def ok(name):
        R["passed"].append(name)
    def fail(name, msg):
        R["failed"].append({"name": name, "detail": msg})

    # 1 导入
    from modules.statistics import get_statistics_manager, init_statistics, record_order_success_ui, record_order_failed_ui, get_today_stats_ui, get_statistics_summary_ui, reset_statistics_ui, get_statistics_status_ui, get_daily_history_ui
    ok("导入")

    # 2 清理旧数据
    f = os.path.join("logs", "statistics.json")
    if os.path.exists(f):
        os.remove(f)

    # 3 初始化
    r = init_statistics()
    if r["status"] == "ok":
        ok("初始化")
    else:
        fail("初始化", str(r))

    mgr = get_statistics_manager()
    ok("默认成功0" if mgr.today_success == 0 else fail("默认成功0", str(mgr.today_success)))
    ok("默认失败0" if mgr.today_failed == 0 else fail("默认失败0", str(mgr.today_failed)))

    # 4 成功x3
    for i in range(3): record_order_success_ui()
    t = get_today_stats_ui()
    ok("成功x3" if t["success"] == 3 else fail("成功x3", str(t)))
    ok("成功率100" if t["success_rate"] == 100.0 else fail("成功率100", str(t)))

    # 5 失败x2
    for i in range(2): record_order_failed_ui()
    t = get_today_stats_ui()
    ok("失败x2" if t["failed"] == 2 else fail("失败x2", str(t)))
    ok("成功率60" if abs(t["success_rate"] - 60.0) < 0.01 else fail("成功率60", str(t)))

    # 6 摘要
    s = get_statistics_summary_ui()
    ok("摘要今日成功" if s["today"]["success"] == 3 else fail("摘要今日成功", str(s)))
    ok("摘要总量" if s["total"]["success"] == 3 else fail("摘要总量", str(s)))

    # 7 历史
    h = get_daily_history_ui()
    ok("每日历史" if len(h) >= 1 else fail("每日历史", str(h)))

    # 8 重置
    reset_statistics_ui()
    t2 = get_today_stats_ui()
    ok("重置归零" if t2["success"] == 0 and t2["failed"] == 0 else fail("重置归零", str(t2)))

    # 9 状态接口
    st = get_statistics_status_ui()
    ok("状态接口" if st["today_success"] == 0 else fail("状态接口", str(st)))

    # 10 单例
    mgr2 = get_statistics_manager()
    ok("单例" if mgr is mgr2 else fail("单例", "不同实例"))

    # 11 持久化文件
    ok("持久化" if os.path.exists(f) else fail("持久化", "文件不存在"))

    # 汇总
    R["total"] = len(R["passed"]) + len(R["failed"])
    R["pass_count"] = len(R["passed"])
    R["fail_count"] = len(R["failed"])
    R["all_pass"] = R["fail_count"] == 0

except Exception as e:
    R = {"error": str(e), "traceback": traceback.format_exc()}

out_path = os.path.join("logs", "validate_result.json")
with open(out_path, "w", encoding="utf-8") as fp:
    json.dump(R, fp, ensure_ascii=False, indent=2)