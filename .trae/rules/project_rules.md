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