# -*- coding: utf-8 -*-
"""
TiShou modules 包
================
所有模块遵循全局约束：
  - 纯 Python
  - 仅适配安卓真机
  - 全异常捕获
  - 分级日志
"""

# 权限模块导出
from modules.permission import (
    PermissionManager,
    PermissionStage,
    PermissionState,
    PermissionDegradation,
    SystemInfo,
    get_permission_manager,
    init_permissions,
    start_permission_flow,
    get_permission_status_ui,
    open_settings_page_ui,
    open_all_settings_ui,
    set_manual_region_ui,
)

# 卡密验证模块导出
from modules.activate_code import (
    ActivateCodeManager,
    CodeGenerator,
    TimeSyncer,
    get_activate_manager,
    init_activate_code,
    verify_code_ui,
    get_verify_info_ui,
    toggle_plaintext_ui,
    deactivate_code_ui,
    get_today_code_example_ui,
)

# 双采集引擎模块导出
from modules.capture import (
    CaptureManager,
    CaptureEngine,
    OcrStatus,
    ImagePreprocessor,
    EasyOcrEngine,
    AccessibilityEngine,
    get_capture_manager,
    init_capture,
    capture_once_ui,
    start_polling_ui,
    stop_polling_ui,
    get_capture_status_ui,
    set_engine_ui,
    set_judge_delay_ui,
    get_engine_status_ui,
)

# 应用列表模块导出
from modules.app_list import (
    AppListManager,
    AndroidAppReader,
    get_app_list_manager,
    get_app_reader,
    init_app_list,
    get_apps_ui,
    get_selected_apps_ui,
    toggle_select_ui,
    select_all_ui,
    deselect_all_ui,
    invert_selection_ui,
    search_apps_ui,
    set_show_system_ui,
    get_app_stats_ui,
    refresh_apps_ui,
)

# 订单筛选模块导出
from modules.order_filter import (
    OrderFilter,
    RegionManager,
    RefreshMode,
    ClickMode,
    ORDER_TYPES,
    PROVINCES,
    get_order_filter,
    get_region_manager,
    init_order_filter,
    should_grab_ui,
    get_filter_params_ui,
    set_price_range_ui,
    set_pickup_distance_ui,
    set_order_distance_ui,
    set_unit_price_ui,
    toggle_order_type_ui,
    set_refresh_mode_ui,
    set_refresh_fixed_ui,
    set_refresh_random_ui,
    set_click_mode_ui,
    set_click_fixed_ui,
    set_click_random_ui,
    reset_filter_ui,
    get_refresh_interval_ui,
    get_click_delay_ui,
    auto_locate_ui,
    get_provinces_ui,
    get_cities_ui,
    set_manual_location_ui,
    is_location_ok_ui,
    get_current_location_ui,
    add_region_ui,
    remove_region_ui,
    select_all_regions_ui,
    invert_regions_ui,
    clear_regions_ui,
    set_region_mode_ui,
    is_region_allowed_ui,
)

# 悬浮窗模块导出
from modules.float_win import (
    FloatWindowManager,
    FloatMode,
    IndicatorState,
    MenuAction,
    get_float_manager,
    init_float_window,
    show_float_ui,
    hide_float_ui,
    destroy_float_ui,
    toggle_float_mode_ui,
    set_float_indicator_ui,
    set_float_indicator_result_ui,
    update_float_status_ui,
    set_float_opacity_ui,
    set_float_locked_ui,
    set_float_paused_ui,
    get_float_status_ui,
    register_float_callbacks_ui,
)

# 统计模块导出（惰性导入，避免 `-m` 运行时循环导入）
# 直接使用时请: from modules.statistics import ...
# 或通过便捷函数访问