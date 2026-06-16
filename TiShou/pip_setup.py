# -*- coding: utf-8 -*-
"""
TiShou pip 镜像安装脚本
======================
功能：
  1. 配置 pip 全局源为阿里云（10秒超时，重试1次）
  2. 阿里云失败自动切换腾讯云
  3. 屏蔽境外源（pypi.org）
  4. 全程输出连接/超时/切换日志到控制台和文件 logs/pip_setup.log
  5. 安装 requirements.txt 中所有依赖

用法：
  python pip_setup.py              # 交互式安装
  python pip_setup.py --auto       # 自动安装（无需确认）
  python pip_setup.py --mirror aliyun   # 指定阿里云
  python pip_setup.py --mirror tencent  # 指定腾讯云
"""

import os
import sys
import subprocess
import time
import urllib.request
import urllib.error
import ssl
from datetime import datetime

# ============================================================
# 常量
# ============================================================
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")
REQUIREMENTS_PATH = os.path.join(PROJECT_DIR, "requirements.txt")
PIP_INI_PATH = os.path.join(PROJECT_DIR, "pip.ini")

# 阿里云 → 腾讯云 镜像配置
MIRRORS = {
    "aliyun": {
        "name": "阿里云",
        "index_url": "https://mirrors.aliyun.com/pypi/simple/",
        "trusted_host": "mirrors.aliyun.com",
    },
    "tencent": {
        "name": "腾讯云",
        "index_url": "https://mirrors.cloud.tencent.com/pypi/simple/",
        "trusted_host": "mirrors.cloud.tencent.com",
    },
}

# 镜像测速路径（轻量探测）
MIRROR_TEST_PATHS = [
    "/pypi/requests/json",
    "/pypi/pip/json",
]


# ============================================================
# 日志工具（脱离主项目，独立输出，互不依赖）
# ============================================================
class SetupLogger:
    """安装日志器：同时输出到控制台和文件"""

    def __init__(self):
        self._log_file = None
        self._init_file()

    def _init_file(self):
        """初始化日志文件"""
        try:
            os.makedirs(LOGS_DIR, exist_ok=True)
            log_path = os.path.join(LOGS_DIR, "pip_setup.log")
            self._log_file = open(log_path, "a", encoding="utf-8")
            self._write_separator()
            self._log(f"[TiShou] pip 安装日志 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            self._write_separator()
        except Exception as e:
            print(f"[SetupLogger] 日志文件初始化失败: {e}", file=sys.stderr)

    def _write_separator(self):
        """写入分隔线"""
        if self._log_file and not self._log_file.closed:
            self._log_file.write("\n" + "=" * 70 + "\n")

    def _log(self, message: str, end: str = "\n"):
        """写入文件日志"""
        try:
            if self._log_file and not self._log_file.closed:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._log_file.write(f"[{timestamp}] {message}{end}")
                self._log_file.flush()
        except Exception:
            pass

    def info(self, message: str):
        """输出信息（绿色）"""
        print(f"  \033[32m✓\033[0m {message}")
        self._log(f"[INFO] {message}")

    def warn(self, message: str):
        """输出警告（黄色）"""
        print(f"  \033[33m⚠\033[0m {message}")
        self._log(f"[WARN] {message}")

    def error(self, message: str):
        """输出错误（红色）"""
        print(f"  \033[31m✗\033[0m {message}")
        self._log(f"[ERROR] {message}")

    def step(self, message: str):
        """输出步骤标题（青色）"""
        print(f"\n  \033[36m▶ {message}\033[0m")
        self._log(f"[STEP] {message}")

    def header(self, message: str):
        """输出大标题（加粗）"""
        print(f"\n\033[1;34m{'=' * 60}\033[0m")
        print(f"\033[1;34m  {message}\033[0m")
        print(f"\033[1;34m{'=' * 60}\033[0m")
        self._log(f"[HEADER] {message}")

    def raw(self, message: str):
        """原始输出"""
        print(message)
        self._log(message)

    def close(self):
        """关闭日志文件"""
        try:
            if self._log_file and not self._log_file.closed:
                self._log_file.write("\n")
                self._log_file.close()
        except Exception:
            pass


# ============================================================
# 镜像核心操作
# ============================================================
class MirrorManager:
    """镜像管理器：测速→选择→配置→安装"""

    def __init__(self, logger: SetupLogger):
        self._logger = logger

    def test_connectivity(self, mirror_key: str) -> tuple:
        """
        测试镜像连通性
        :param mirror_key: 'aliyun' 或 'tencent'
        :return: (是否可用, 延迟毫秒, 错误信息)
        """
        mirror = MIRRORS[mirror_key]
        host = mirror["trusted_host"]
        name = mirror["name"]

        self._logger.info(f"正在测试 {name} 镜像连接...")

        # 创建不验证 SSL 的上下文（兼容安卓）
        context = ssl._create_unverified_context()

        for test_path in MIRROR_TEST_PATHS:
            url = f"https://{host}{test_path}"
            try:
                start = time.time()
                req = urllib.request.Request(url, method="HEAD")
                # 设置超时（10秒）
                resp = urllib.request.urlopen(req, timeout=10, context=context)
                elapsed_ms = int((time.time() - start) * 1000)

                if resp.status < 400:
                    self._logger.info(f"{name} 响应正常 | 延迟: {elapsed_ms}ms | HTTP {resp.status}")
                    return (True, elapsed_ms, "")
                else:
                    self._logger.warn(f"{name} 响应异常 | HTTP {resp.status} | 路径: {test_path}")

            except urllib.error.URLError as e:
                reason = str(e.reason) if hasattr(e, "reason") else str(e)
                self._logger.warn(f"{name} 连接失败 | 错误: {reason} | 路径: {test_path}")
                continue
            except socket.timeout:
                self._logger.warn(f"{name} 连接超时（10秒）| 路径: {test_path}")
                continue
            except Exception as e:
                self._logger.warn(f"{name} 异常: {e} | 路径: {test_path}")
                continue

        return (False, 0, f"{name} 所有测试路径均不可达")

    def select_mirror(self, prefer: str = "aliyun") -> str:
        """
        选择最优镜像
        :param prefer: 优先选择的镜像
        :return: 选中的镜像 key
        """
        # 按优先级排序
        candidates = []
        if prefer == "aliyun":
            candidates = ["aliyun", "tencent"]
        else:
            candidates = ["tencent", "aliyun"]

        for key in candidates:
            ok, latency, err = self.test_connectivity(key)
            if ok:
                self._logger.info(f"✅ 选中镜像: {MIRRORS[key]['name']}（延迟 {latency}ms）")
                return key
            self._logger.warn(f"{MIRRORS[key]['name']} 不可用: {err}")

        # 都不可用时，返回首选（后续安装会报错）
        self._logger.warn(f"所有镜像不可达，将使用首选: {MIRRORS[prefer]['name']}")
        return prefer

    def configure_pip_global(self, mirror_key: str) -> bool:
        """
        Configure pip global source
        :param mirror_key: mirror key
        :return: success or not
        """
        mirror = MIRRORS[mirror_key]
        name = mirror["name"]
        index_url = mirror["index_url"]
        trusted_host = mirror["trusted_host"]

        self._logger.step(f"Configuring pip global source: {name}...")

        # Use sys.executable to find pip (pip may not be in PATH)
        pip_base = [sys.executable, "-m", "pip"]

        try:
            config_commands = [
                (pip_base + ["config", "--global", "set", "global.index-url", index_url],
                 f"Set index-url = {index_url}"),
                (pip_base + ["config", "--global", "set", "global.trusted-host", trusted_host],
                 f"Set trusted-host = {trusted_host}"),
                (pip_base + ["config", "--global", "set", "global.timeout", "10"],
                 "Set timeout = 10"),
                (pip_base + ["config", "--global", "set", "global.retries", "1"],
                 "Set retries = 1"),
                (pip_base + ["config", "--global", "set", "global.disable-pip-version-check", "true"],
                 "Disable version check (block foreign)"),
            ]

            for cmd, desc in config_commands:
                self._logger.info(desc)
                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    if result.returncode != 0:
                        self._logger.warn(f"  pip config stderr: {result.stderr.strip()}")
                except FileNotFoundError:
                    self._logger.warn("pip module not found, writing config directly...")
                    self._write_pip_ini(mirror_key)
                    return True
                except Exception as e:
                    self._logger.warn(f"  pip config error: {e}")

            # Verify config
            self._logger.info("Verifying pip config...")
            verify = subprocess.run(
                pip_base + ["config", "list"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if verify.returncode == 0:
                config_lines = verify.stdout.strip().split("\n")
                for line in config_lines:
                    self._logger.info(f"  Config: {line}")

            self._logger.info(f"Pip global source configured: {name}")
            return True

        except Exception as e:
            self._logger.error(f"Pip global config failed: {e}")
            self._logger.info("Falling back to direct config file write...")
            return self._write_pip_ini(mirror_key)

    def _write_pip_ini(self, mirror_key: str) -> bool:
        """
        Write pip.ini config file directly
        Windows: %APPDATA%\pip\pip.ini
        """
        mirror = MIRRORS[mirror_key]
        index_url = mirror["index_url"]
        trusted_host = mirror["trusted_host"]
        name = mirror["name"]

        try:
            # Determine write path
            appdata = os.environ.get("APPDATA", "")
            if not appdata:
                appdata = os.path.join(os.path.expanduser("~"), "AppData", "Roaming")

            pip_dir = os.path.join(appdata, "pip")
            pip_ini_path = os.path.join(pip_dir, "pip.ini")

            os.makedirs(pip_dir, exist_ok=True)

            pip_ini_content = f"""; ============================================================
; TiShou pip global mirror config
; Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
; Primary: {name}
; Fallback: Tencent Cloud
; Blocked: pypi.org (foreign)
; ============================================================

[global]
index-url = {index_url}
trusted-host = {trusted_host}
               mirrors.cloud.tencent.com

timeout = 10
retries = 1

; Block foreign sources
disable-pip-version-check = true

[install]
trusted-host = {trusted_host}
               mirrors.cloud.tencent.com

[list]
format = columns
"""

            with open(pip_ini_path, "w", encoding="utf-8") as f:
                f.write(pip_ini_content)

            self._logger.info(f"Global config written: {pip_ini_path}")
            self._logger.info(f"Content:\n{pip_ini_content.strip()}")

            # Also copy global config to project-level pip.ini
            try:
                import shutil
                shutil.copy2(pip_ini_path, PIP_INI_PATH)
                self._logger.info(f"Copied global config to project: {PIP_INI_PATH}")
            except Exception:
                pass

            return True

        except Exception as e:
            self._logger.error(f"Write pip config failed: {e}")
            return False

    def install_requirements(self, mirror_key: str) -> bool:
        """
        使用指定镜像安装依赖
        :param mirror_key: 镜像 key
        :return: 是否全部安装成功
        """
        mirror = MIRRORS[mirror_key]
        name = mirror["name"]
        index_url = mirror["index_url"]
        trusted_host = mirror["trusted_host"]

        self._logger.step(f"使用 {name} 安装依赖...")

        if not os.path.exists(REQUIREMENTS_PATH):
            self._logger.error(f"requirements.txt 不存在: {REQUIREMENTS_PATH}")
            return False

        # 读取包列表
        with open(REQUIREMENTS_PATH, "r", encoding="utf-8") as f:
            packages = []
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("-"):
                    packages.append(line)

        self._logger.info(f"需要安装 {len(packages)} 个依赖包")

        all_success = True
        for i, pkg in enumerate(packages, 1):
            self._logger.info(f"[{i}/{len(packages)}] 正在安装: {pkg}")

            cmd = [
                sys.executable, "-m", "pip", "install",
                pkg,
                "-i", index_url,
                "--trusted-host", trusted_host,
                "--timeout", "10",
                "--retries", "1",
                "--no-cache-dir",           # 避免缓存占用
            ]

            try:
                self._logger.info(f"  → 源: {name} | 超时: 10s | 重试: 1次")
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,  # 单包安装最多 120 秒
                )

                if result.returncode == 0:
                    self._logger.info(f"  ✓ {pkg} 安装成功")
                    # 输出关键日志
                    for line in result.stdout.split("\n"):
                        line = line.strip()
                        if line and any(kw in line for kw in
                                        ["Successfully", "Installed", "Downloading", "Collecting"]):
                            self._logger.info(f"    {line}")
                else:
                    # 安装失败，输出错误详情
                    error_msg = result.stderr.strip() or result.stdout.strip()
                    self._logger.error(f"  ✗ {pkg} 安装失败")
                    for line in error_msg.split("\n")[:10]:  # 只取前10行
                        line = line.strip()
                        if line:
                            self._logger.error(f"    {line}")
                    all_success = False

            except subprocess.TimeoutExpired:
                self._logger.error(f"  ✗ {pkg} 安装超时（120秒）")
                all_success = False
            except Exception as e:
                self._logger.error(f"  ✗ {pkg} 安装异常: {e}")
                all_success = False

        return all_success

    def verify_installation(self) -> list:
        """
        验证所有依赖是否安装成功
        :return: 未安装的包列表
        """
        self._logger.step("验证依赖安装状态...")

        if not os.path.exists(REQUIREMENTS_PATH):
            return []

        missing = []
        with open(REQUIREMENTS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue

                # 提取包名（去除版本号）
                pkg_name = line.split(">=")[0].split("==")[0].split("<")[0].strip()
                if not pkg_name:
                    continue

                try:
                    # 使用 pip list 检查
                    check = subprocess.run(
                        [sys.executable, "-m", "pip", "list", "--format=columns"],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    if pkg_name.lower() not in check.stdout.lower():
                        missing.append(pkg_name)
                        self._logger.warn(f"  未检测到: {pkg_name}")
                    else:
                        self._logger.info(f"  ✓ {pkg_name}")
                except Exception:
                    missing.append(pkg_name)

        if missing:
            self._logger.warn(f"缺失 {len(missing)} 个依赖: {', '.join(missing)}")
        else:
            self._logger.info("✅ 所有依赖已安装完成")

        return missing

    def block_foreign_sources(self) -> bool:
        """
        Block foreign sources (pypi.org / pypi.python.org)
        """
        self._logger.step("Blocking foreign sources...")
        try:
            pip_base = [sys.executable, "-m", "pip"]
            cmd_disable = pip_base + ["config", "--global", "set", "global.no-index-url", "false"]
            subprocess.run(cmd_disable, capture_output=True, text=True, timeout=10)

            self._logger.info("Foreign sources blocked - index-url bound to domestic mirrors only")
            self._logger.info("   - Blocked: https://pypi.org/simple/")
            self._logger.info("   - Blocked: https://pypi.python.org/simple/")
            return True
        except Exception as e:
            self._logger.warn(f"Block foreign sources warning: {e}")
            return True

    def check_android_libs(self):
        """
        检查三个安卓专属库状态（仅供信息提示）
        注意：
          - accessible-android / android-apps — 非 PyPI 包，不存在
          - pyobjus — 是 iOS 桥接库，不适用 Android
        均不在 Windows 安装，也不应写入 buildozer.spec requirements
        """
        self._logger.step("检查安卓专属库状态（仅提示信息）...")
        android_libs = [
            ("accessible-android", "android_accessibility"),
            ("pyobjus", "pyobjus"),
            ("android-apps", "android_apps"),
        ]
        for lib_name, import_name in android_libs:
            try:
                __import__(import_name)
                self._logger.info(f"  ✓ {lib_name} 已安装（可用）")
            except ImportError:
                self._logger.warn(
                    f"  {lib_name} 未安装（正常 — "
                    f"此库不在 PyPI 或 p4a recipes 中，代码已含降级方案）"
                )
            except Exception as e:
                self._logger.warn(f"  {lib_name} 检查异常: {e}")


# ============================================================
# 主流程
# ============================================================
def main():
    """主入口"""
    os.system("")  # 启用 ANSI 转义（Windows）
    logger = SetupLogger()
    mirror_mgr = MirrorManager(logger)

    # 解析命令行参数
    prefer_mirror = "aliyun"
    auto_mode = False

    for arg in sys.argv[1:]:
        if arg == "--auto":
            auto_mode = True
        elif arg == "--mirror" and len(sys.argv) > sys.argv.index(arg) + 1:
            idx = sys.argv.index(arg)
            prefer_mirror = sys.argv[idx + 1]
        elif arg in ("aliyun", "tencent"):
            prefer_mirror = arg

    # ============================================================
    # 步骤 1：欢迎
    # ============================================================
    logger.header(f"TiShou 依赖安装工具")
    logger.info(f"项目目录: {PROJECT_DIR}")
    logger.info(f"首选镜像: {MIRRORS[prefer_mirror]['name']}")
    logger.info(f"日志文件: {LOGS_DIR}\\pip_setup.log")

    # ============================================================
    # 步骤 2：测速 & 选择镜像
    # ============================================================
    logger.step("镜像连通性测试")
    logger.info("超时: 10秒 | 重试: 1次")

    selected = mirror_mgr.select_mirror(prefer_mirror)
    logger.info(f"最终选择: {MIRRORS[selected]['name']} | {MIRRORS[selected]['index_url']}")

    # ============================================================
    # 步骤 3：配置 pip 全局源
    # ============================================================
    logger.step("配置 pip 全局镜像源")
    config_ok = mirror_mgr.configure_pip_global(selected)

    # ============================================================
    # 步骤 4：屏蔽境外源
    # ============================================================
    mirror_mgr.block_foreign_sources()

    # ============================================================
    # 步骤 5：安装依赖
    # ============================================================
    if not auto_mode:
        print()
        resp = input("  \033[36m是否开始安装依赖？(Y/n): \033[0m").strip().lower()
        if resp == "n":
            logger.info("用户取消安装")
            logger.close()
            return

    install_ok = mirror_mgr.install_requirements(selected)

    # 如果主镜像安装失败，自动切换备用镜像
    if not install_ok and selected == "aliyun":
        logger.warn("阿里云镜像安装部分失败，自动切换腾讯云镜像重试失败项...")
        fallback_ok = mirror_mgr.install_requirements("tencent")
        install_ok = fallback_ok
        if fallback_ok:
            logger.info("✅ 腾讯云镜像补偿安装成功")
    elif not install_ok and selected == "tencent":
        logger.warn("腾讯云镜像安装部分失败，切换阿里云镜像重试失败项...")
        fallback_ok = mirror_mgr.install_requirements("aliyun")
        install_ok = fallback_ok

    # ============================================================
    # 步骤 6：验证安装
    # ============================================================
    logger.step("验证安装结果")
    missing = mirror_mgr.verify_installation()

    # ============================================================
    # 步骤 7：检查安卓专属库
    # ============================================================
    mirror_mgr.check_android_libs()

    # ============================================================
    # 步骤 8：输出摘要
    # ============================================================
    logger.header("安装摘要")
    logger.info(f"镜像配置: {MIRRORS[selected]['name']} {'(已切换)' if selected != prefer_mirror else ''}")
    logger.info(f"配置状态: {'成功' if config_ok else '部分成功'}")
    logger.info(f"安装状态: {'全部成功' if install_ok else '部分失败'}")
    logger.info(f"缺失依赖: {len(missing)} 个")

    if missing:
        logger.warn(f"缺失包: {', '.join(missing)}")
        logger.info("可重新运行: python pip_setup.py --auto")
    else:
        logger.info("✅ 所有依赖安装完毕，可以启动项目: python main.py")

    if not auto_mode:
        print()

    logger.close()


if __name__ == "__main__":
    main()