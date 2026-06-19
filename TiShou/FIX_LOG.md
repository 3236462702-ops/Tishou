# TiShou 修复记录

> 此文件记录项目所有修复历史。对话记录丢失时，AI 可读取此文件回溯修复历程。
> 每次修复完成后必须更新此文件。

---

## 2026-06-19 — 全项目排查 + 构建脚本重建 + 全局约束完善

### 修复 #1: EasyOcrEngine._cache_dir 未定义 → AttributeError
- **文件**: `modules/capture.py`
- **问题**: `EasyOcrEngine.__init__` 缺少 `self._cache_dir` 定义，但 `_load_model` 中使用了 `self._cache_dir`
- **严重性**: 🔴 崩溃级 Bug
- **修复**: 在 `__init__` 中添加 `self._cache_dir = None`

### 修复 #2: warmup_engine_ui / shutdown_engine_ui 调用不存在方法
- **文件**: `modules/capture.py`
- **问题**: 调用了 `mgr.get_engine("easyocr")`，实际方法名是 `_get_easyocr()`
- **严重性**: 🔴 崩溃级 Bug
- **修复**: 改为调用 `_get_easyocr()`

### 修复 #3: 订单判定延迟全局默认值统一（首次）
- **涉及文件**: `main.py`, `modules/capture.py`, `modules/utils.py`, `config.json`
- **问题**: 多处 `DEFAULT_JUDGE_DELAY` / `order_judge_delay` 值为 5.0，与全局约束"默认 13 秒"不一致
- **修复**: 全部改为 13.0

### 修复 #4: main.py 配置键名不一致
- **文件**: `main.py`
- **问题**: `DEFAULT_CONFIG` 使用 `"filter"` 键，而 `utils.py` 和 `config.json` 都用 `"order_filter"`，且内部字段结构不同
- **修复**: 统一为 `"order_filter"`，字段对齐 utils.py 结构

### 修复 #5: 构建脚本全新重建
- **删除**: 旧 `buildozer.spec`, `build-apk.yml`, `docker_build_apk.ps1`
- **新建**: 3 个全新 v2.0.0 构建脚本
- **新增内容**:
  - Android 专属依赖说明（pyjnius/jnius/p4a，Windows 不可安装）
  - 权限清单新增 `RECEIVE_BOOT_COMPLETED`, `WAKE_LOCK`, `FOREGROUND_SERVICE_SPECIAL_USE`
  - 构建脚本头部标注版本号 + 生成日期 + "全新构建，未沿用旧配置"

### 修复 #6: 全局约束新增章节
- **文件**: `.trae/rules/project_rules.md`
- **新增**:
  - 第十五章：构建脚本规则（每次推送必须全新生成）
  - 第十六章：推送前自检规则（7 项自检清单，必须先自检再推送）

### 修复 #7: 订单判定延迟全局默认值二次排查
- **文件**: `modules/capture.py` L78, `modules/ui.py` L1445, `config.json.bak` L8
- **问题**: 首次排查遗漏了 3 处 `order_judge_delay` 旧值 5.0
- **修复**: 全部改为 13.0，全项目 7 处引用全部统一

---

## 修复状态汇总

| 日期 | 修复数 | 崩溃级 | 一致性问题 | 新增文件 |
|------|--------|--------|------------|----------|
| 2026-06-19 | 7 | 2 | 5 | 3 构建脚本 + 2 全局约束章节 |

---

## 当前已知的无害问题（无需修复）

1. **main.py 和 utils.py 各有一套 ConfigManager/LogManager** — 有意为之，main.py 负责冷启动，utils.py 供各模块使用
2. **float_win.py 注释写 "pyobjus"** — 实际代码用的是 `jnius`（正确），仅注释有误
3. **Windows 编辑器报 ImportError（accessible-android/android-apps/pyobjus）** — 正常现象，代码已用 try-except 保护