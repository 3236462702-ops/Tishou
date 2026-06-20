# TiShou 项目规则

## 1. 每次 Git 推送前必须重新生成构建脚本

每次修改、修复、新增功能后，推送到 Git 之前，必须根据项目当前状况重新生成以下两个构建脚本：

### 1.1 GitHub Actions CI 脚本
- 路径：`TiShou/.github/workflows/build-apk.yml`
- 触发条件：push 到 main 分支 + workflow_dispatch 手动触发
- 构建方式：ubuntu-latest + Docker (kivy/buildozer)
- 产物：debug APK，保留 7 天

### 1.2 本地 Docker 构建脚本
- 路径：`TiShou/docker_build_apk.ps1`
- 用途：Windows 开发机本地构建
- 版本号必须与 buildozer.spec 同步

### 1.3 脚本中必须包含安卓专属依赖声明
以下三个依赖在 Windows 上无法安装，由 Docker 容器内的 p4a 编译注入：
- **pyjnius** — Android Java 桥接（悬浮窗/通知/AudioTrack/权限检测）
- **jnius** — 访问 Android 系统 API
- **p4a** — python-for-android 运行时（提供 android 模块）

## 2. 版本号同步规则

每次修改后，以下三个文件头部版本号必须同步更新：
- `TiShou/buildozer.spec`
- `TiShou/docker_build_apk.ps1`
- `TiShou/.github/workflows/build-apk.yml`

## 3. 全局约束（修改代码时必须遵守）

1. 仅适配安卓真机（桌面环境日志模拟）
2. 纯 Python 开发，不混用 C/C++/NDK/Java/Kotlin（除已声明的自定义 Java Service）
3. 仅免费、免注册、无授权公共 API
4. 仅 Python 开源库内置免费素材
5. pip 镜像优先阿里云→腾讯云回退
6. 全代码异常捕获，杜绝闪退
7. 分级日志（运行/错误/OCR/素材）
8. easyocr + Pillow 纯本地 OCR
9. 抢单判定延迟默认 13s
10. HyperOS + iOS 融合风 UI

## 4. 修改后必须同步检查的文件

每次修改代码后，必须检查以下关联文件是否受影响：
- `buildozer.spec` — 权限、依赖、资源配置
- `main.py` — 启动流程、权限检查、模块加载
- `modules/permission.py` — 权限请求逻辑
- `modules/ui.py` — UI 页面、加载动画
- `AndroidManifest.tmpl.xml` — 服务声明、权限模板

## 5. 构建命令

本地构建：`cd TiShou && .\docker_build_apk.ps1`
Git 推送后自动构建：GitHub Actions 监听 main 分支 push 事件

## 6. 安卓专属库不可移除规则（铁律）

如果构建失败，经排查是因 pyjnius / jnius / p4a 这三个安卓专属库导致，**绝对禁止删除或替换它们**。
原因：没有这些库，权限检测（悬浮窗、通知、定位、存储、无障碍）将无法正常工作。

修复思路优先级：
1. 检查 `buildozer.spec` 中 `requirements` 行格式是否正确（逗号分隔，无多余空格）
2. 检查 `android.ndk`、`android.api`、`android.minapi` 版本是否兼容
3. 检查 Docker 镜像版本是否过旧（`kivy/buildozer:latest`）
4. 检查 `buildozer.spec` 中 `android.gradle = True` 是否开启
5. 清理构建缓存后重试：`buildozer android distclean`
6. 如属 p4a 配方（recipe）版本问题，尝试锁定 NDK/SDK 版本而非升级依赖

## 7. 构建脚本必须完整列出安卓权限清单（新增约束）

每次生成/更新构建脚本（`docker_build_apk.ps1` 和 `.github/workflows/build-apk.yml`）时，
脚本中**必须包含**以下完整的安卓权限清单及用途说明，以注释形式写在脚本头部。

Windows 开发环境无法直接安装/测试这些安卓专属权限，只有 Docker 容器内的 p4a 编译才能注入。
因此每次构建前必须确保这 17 个权限全部声明，缺一不可。

### 7.1 核心功能权限（6 个）
| 权限 | 用途 |
|------|------|
| `BIND_ACCESSIBILITY_SERVICE` | 无障碍服务：读取屏幕内容 + 模拟点击抢单 |
| `SYSTEM_ALERT_WINDOW` | 悬浮窗：在屏幕顶层显示抢单状态窗口 |
| `FOREGROUND_SERVICE` | 前台服务：后台保活，防止被系统杀掉 |
| `FOREGROUND_SERVICE_SPECIAL_USE` | 前台服务特殊用途声明（Android 14+ 必须） |
| `POST_NOTIFICATIONS` | 通知栏：显示抢单结果通知 |
| `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` | 电池优化白名单：防止后台被系统限制 |

### 7.2 存储权限（3 个）
| 权限 | 用途 |
|------|------|
| `READ_EXTERNAL_STORAGE` | 读取存储：加载配置、日志、素材 |
| `WRITE_EXTERNAL_STORAGE` | 写入存储：保存日志、截图缓存、素材下载 |
| `MANAGE_EXTERNAL_STORAGE` | 全部存储访问（Android 11+ 必须） |

### 7.3 定位权限（2 个）
| 权限 | 用途 |
|------|------|
| `ACCESS_FINE_LOCATION` | 精确定位：GPS 区域筛选 |
| `ACCESS_COARSE_LOCATION` | 粗略定位：网络/WiFi 区域筛选 |

### 7.4 网络权限（3 个）
| 权限 | 用途 |
|------|------|
| `INTERNET` | 网络访问：API 对接、素材更新、版本检查 |
| `ACCESS_NETWORK_STATE` | 网络状态检测：WiFi/移动数据切换 |
| `ACCESS_WIFI_STATE` | WiFi 状态检测：信号强度判断 |

### 7.5 系统权限（3 个）
| 权限 | 用途 |
|------|------|
| `RECEIVE_BOOT_COMPLETED` | 开机自启：设备重启后自动恢复服务 |
| `WAKE_LOCK` | 唤醒锁：防止 CPU 休眠导致抢单延迟 |
| `VIBRATE` | 振动反馈：抢单成功/失败触感提示 |

### 7.6 脚本注释模板
构建脚本头部必须包含以下注释块：
```
# =============================================================================
# TiShou 安卓权限清单（共 17 项，Windows 环境无法处理，由 Docker p4a 编译注入）
# =============================================================================
# 核心功能: BIND_ACCESSIBILITY_SERVICE, SYSTEM_ALERT_WINDOW, FOREGROUND_SERVICE,
#           FOREGROUND_SERVICE_SPECIAL_USE, POST_NOTIFICATIONS, REQUEST_IGNORE_BATTERY_OPTIMIZATIONS
# 存储:    READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE, MANAGE_EXTERNAL_STORAGE
# 定位:    ACCESS_FINE_LOCATION, ACCESS_COARSE_LOCATION
# 网络:    INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE
# 系统:    RECEIVE_BOOT_COMPLETED, WAKE_LOCK, VIBRATE
# =============================================================================
# 无障碍服务注册链（3 文件联动，缺一不可，Android 15/16 严格校验）:
#   AndroidManifest.tmpl.xml → <service> + intent-filter + meta-data
#   res/xml/accessibility_service_config.xml → 服务能力声明
#   src/main/java/.../TiShouAccessibilityService.java → 服务实现
# buildozer.spec 必须配置:
#   android.add_src = src/main/java
#   android.add_resources = res/xml:xml
#   android.permissions 含 BIND_ACCESSIBILITY_SERVICE
# =============================================================================
```

### 7.7 无障碍服务完整注册链（Android 15/16 必须）

构建脚本中**必须注明**以下无障碍服务注册的三文件联动关系，
因为 Android 15/16 对无障碍服务的校验非常严格：
- `AndroidManifest.tmpl.xml` — 声明 `<service>` + `intent-filter` + `meta-data`
- `res/xml/accessibility_service_config.xml` — 服务能力 XML 配置
- `src/main/java/.../TiShouAccessibilityService.java` — 继承 `AccessibilityService`

同时 `buildozer.spec` 必须配置：
- `android.add_src = src/main/java` — 编译 Java 源码
- `android.add_resources = res/xml:xml` — 打包 XML 配置
- `android.permissions` 含 `BIND_ACCESSIBILITY_SERVICE` — 绑定权限

**缺任意一个文件或配置，App 安装后不会出现在系统无障碍列表中，Android 15/16 直接拒绝加载。**