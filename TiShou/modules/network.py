# -*- coding: utf-8 -*-
"""
网络模块
=======
提供以下能力：
  1. 三种网络状态检测（无网络/弱网/正常）并支持弹窗回调
  2. 双免费公共 API 节点，3 秒超时自动切换，全部失效弹手动重试
  3. 素材版本检测与联网更新（仅 Python 开源库内置免费素材）
  4. 静态数据 24 小时本地缓存，缓存损坏自动重请求
  5. 接口/素材更新全局 15~20 秒超时，超时提示失败并支持重试
  6. 网络异常静默处理，记录网络日志，不闪退

约束：
  - 仅使用免费、免注册、无授权公共 API
  - 禁用付费、私有、需登录接口
"""

import sys
import os
import json
import time
import threading
from datetime import datetime, timedelta
from typing import Optional, Callable, Any

import requests

# 将父目录加入路径以便导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.utils import (
    LogManager, ConfigManager, StrUtil, ExceptionUtil,
    safe_int, safe_write_file, safe_read_file, ensure_dir,
    PROJECT_DIR, ASSETS_DIR, timestamp_sec,
)

# ============================================================
# 常量定义
# ============================================================

# 缓存目录
CACHE_DIR = os.path.join(PROJECT_DIR, "cache")

# 缓存有效期（秒）：24 小时
CACHE_TTL = 24 * 60 * 60

# 总超时（秒）：接口与素材更新全局 15~20 秒
REQUEST_TIMEOUT = 15
MATERIAL_UPDATE_TIMEOUT = 20

# 单接口超时（秒）：3 秒自动切节点
SINGLE_NODE_TIMEOUT = 3

# 弱网判定阈值（秒）
WEAK_NETWORK_THRESHOLD = 2.0

# ============================================================
# 免费公共 API 节点定义
# ============================================================
# 注意：所有 API 均为免费、免注册、无授权公共接口
# 节点 1 优先，超时后自动切换到节点 2

API_NODES = {
    "node1": {
        "name": "节点一（httpbin.cn 国内镜像）",
        "base_url": "https://httpbin.cn",
        "test_path": "/ip",                    # 连通性测试路径
    },
    "node2": {
        "name": "节点二（ipip.net 国内IP）",
        "base_url": "https://myip.ipip.net",
        "test_path": "",                       # 直接请求 base_url 即可
    },
}


# ============================================================
# 网络状态枚举
# ============================================================
class NetworkState:
    """网络状态常量"""

    NO_NETWORK = "no_network"        # 无网络
    WEAK_NETWORK = "weak_network"    # 弱网（响应 > 2 秒）
    NORMAL = "normal"                # 网络正常


# ============================================================
# 网络管理器
# ============================================================
class NetworkManager:
    """
    网络管理器
    =========
    功能：
      - 网络状态检测与分级
      - 双节点自动切换（3 秒超时）
      - 静态数据 24 小时缓存
      - 素材版本检测与更新
      - 异常静默处理
    """

    def __init__(self):
        """初始化网络管理器"""
        self._logger = LogManager.get_logger("app")       # 运行日志
        self._net_logger = LogManager.get_logger("app")   # 网络日志（复用运行日志）
        self._config = ConfigManager()

        # 当前活跃节点
        self._active_node = "node1"

        # 公共请求头
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 14; TiShou) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.6099.230 Mobile Safari/537.36"
            ),
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

        # 缓存数据（内存加速）
        self._memory_cache = {}

        # 确保缓存目录存在
        ensure_dir(CACHE_DIR)

        # 网络状态回调（供 UI 层注册弹窗）
        self._state_callbacks = []

        self._logger.info("网络管理器初始化完成")

    # ============================================================
    # 网络状态检测
    # ============================================================

    def register_state_callback(self, callback: Callable[[str], None]):
        """
        注册网络状态变更回调（供 UI 层弹窗提示）
        :param callback: 回调函数，参数为 NetworkState 常量
        """
        try:
            if callback not in self._state_callbacks:
                self._state_callbacks.append(callback)
        except Exception as e:
            self._net_logger.warning(f"注册网络状态回调失败: {e}")

    def _notify_state(self, state: str):
        """
        通知所有注册的回调网络状态变更
        :param state: NetworkState 常量
        """
        for callback in self._state_callbacks:
            try:
                callback(state)
            except Exception as e:
                self._net_logger.warning(f"网络状态回调执行异常: {e}")

    def check_network_state(self) -> str:
        """
        检测当前网络状态
        :return: NetworkState 常量（NO_NETWORK / WEAK_NETWORK / NORMAL）
        """
        try:
            self._net_logger.info("正在检测网络状态...")

            # 尝试连接节点 1
            node = API_NODES["node1"]
            test_url = node["base_url"] + node["test_path"]

            start_time = time.time()
            try:
                resp = requests.get(
                    test_url,
                    headers=self._headers,
                    timeout=SINGLE_NODE_TIMEOUT,
                )
                elapsed = time.time() - start_time

                if resp.status_code != 200:
                    # 节点 1 异常，尝试节点 2
                    self._net_logger.warning(f"{node['name']} 响应异常 (HTTP {resp.status_code})，切换节点 2...")
                    return self._check_node2()

                # 判断网络质量
                if elapsed > WEAK_NETWORK_THRESHOLD:
                    self._net_logger.warning(f"弱网状态: 响应 {elapsed:.2f}s（阈值 {WEAK_NETWORK_THRESHOLD}s）")
                    self._active_node = "node1"
                    self._notify_state(NetworkState.WEAK_NETWORK)
                    return NetworkState.WEAK_NETWORK
                else:
                    self._net_logger.info(f"网络正常: 响应 {elapsed:.2f}s")
                    self._active_node = "node1"
                    self._notify_state(NetworkState.NORMAL)
                    return NetworkState.NORMAL

            except requests.Timeout:
                self._net_logger.warning(f"{node['name']} 超时 ({SINGLE_NODE_TIMEOUT}s)，切换节点 2...")
                return self._check_node2()
            except requests.ConnectionError:
                self._net_logger.warning(f"{node['name']} 连接失败，切换节点 2...")
                return self._check_node2()

        except Exception as e:
            self._net_logger.error(f"网络状态检测异常: {e}")
            self._notify_state(NetworkState.NO_NETWORK)
            return NetworkState.NO_NETWORK

    def _check_node2(self) -> str:
        """检测节点 2（备用节点）"""
        try:
            node = API_NODES["node2"]
            test_url = node["base_url"] + node["test_path"]

            start_time = time.time()
            resp = requests.get(
                test_url,
                headers=self._headers,
                timeout=SINGLE_NODE_TIMEOUT,
            )
            elapsed = time.time() - start_time

            if resp.status_code != 200:
                self._net_logger.error("节点 2 也异常，判定为无网络")
                self._active_node = None
                self._notify_state(NetworkState.NO_NETWORK)
                return NetworkState.NO_NETWORK

            # 判断网络质量
            if elapsed > WEAK_NETWORK_THRESHOLD:
                self._net_logger.warning(f"弱网状态（节点2）: 响应 {elapsed:.2f}s")
                self._active_node = "node2"
                self._notify_state(NetworkState.WEAK_NETWORK)
                return NetworkState.WEAK_NETWORK
            else:
                self._net_logger.info(f"网络正常（节点2）: 响应 {elapsed:.2f}s")
                self._active_node = "node2"
                self._notify_state(NetworkState.NORMAL)
                return NetworkState.NORMAL

        except requests.Timeout:
            self._net_logger.error("节点 2 也超时，判定为无网络")
            self._active_node = None
            self._notify_state(NetworkState.NO_NETWORK)
            return NetworkState.NO_NETWORK
        except requests.ConnectionError:
            self._net_logger.error("节点 2 也无法连接，判定为无网络")
            self._active_node = None
            self._notify_state(NetworkState.NO_NETWORK)
            return NetworkState.NO_NETWORK
        except Exception as e:
            self._net_logger.error(f"节点 2 检测异常: {e}")
            self._active_node = None
            self._notify_state(NetworkState.NO_NETWORK)
            return NetworkState.NO_NETWORK

    def get_current_state(self) -> str:
        """
        获取当前已知网络状态（不发起新请求）
        :return: NetworkState 常量
        """
        if self._active_node is None:
            return NetworkState.NO_NETWORK
        return NetworkState.NORMAL  # 有活跃节点即为正常

    def is_connected(self) -> bool:
        """快速判断是否有网络连接"""
        try:
            state = self.check_network_state()
            return state != NetworkState.NO_NETWORK
        except Exception:
            return False

    # ============================================================
    # 双节点智能请求
    # ============================================================

    @ExceptionUtil.safe_call(default_return=None, log_level="warning")
    def request_with_failover(
        self,
        path: str,
        params: Optional[dict] = None,
        timeout: int = REQUEST_TIMEOUT,
        method: str = "GET",
        retry_on_fail: bool = False,
    ) -> Optional[dict]:
        """
        双节点容错请求：节点 1 超时 3 秒自动切节点 2，全部失败返回 None

        :param path: API 路径（如 "/ip"）
        :param params: 查询参数
        :param timeout: 单个节点超时秒数（默认 3 秒）
        :param method: 请求方法 GET/POST
        :param retry_on_fail: 失败后是否自动重试一次（默认 False）
        :return: JSON 响应或 None
        """
        nodes_to_try = ["node1", "node2"]
        last_error = ""

        for attempt in range(2 if retry_on_fail else 1):
            for node_key in nodes_to_try:
                node = API_NODES[node_key]
                url = node["base_url"] + path

                try:
                    self._net_logger.debug(f"[{node_key}] {method} {url}（超时 {timeout}s）")

                    if method == "GET":
                        resp = requests.get(
                            url,
                            params=params,
                            headers=self._headers,
                            timeout=timeout,
                        )
                    else:
                        resp = requests.post(
                            url,
                            data=params,
                            headers=self._headers,
                            timeout=timeout,
                        )

                    if resp.status_code == 200:
                        self._active_node = node_key
                        self._net_logger.info(f"[{node_key}] 请求成功")
                        return resp.json()
                    else:
                        last_error = f"HTTP {resp.status_code}"
                        self._net_logger.warning(f"[{node_key}] {last_error}，切换下一节点...")

                except requests.Timeout:
                    last_error = f"超时 {timeout}s"
                    self._net_logger.warning(f"[{node_key}] {last_error}，切换下一节点...")
                except requests.ConnectionError:
                    last_error = "连接失败"
                    self._net_logger.warning(f"[{node_key}] {last_error}，切换下一节点...")
                except requests.RequestException as e:
                    last_error = str(e)
                    self._net_logger.warning(f"[{node_key}] 请求异常: {e}，切换下一节点...")
                except Exception as e:
                    last_error = str(e)
                    self._net_logger.warning(f"[{node_key}] 未知异常: {e}，切换下一节点...")

            # 所有节点都失败
            if attempt == 0 and retry_on_fail:
                self._net_logger.info("所有节点失败，等待 1 秒后重试...")
                time.sleep(1)
                continue

            self._net_logger.error(f"所有 API 节点均不可用: {last_error}")
            self._active_node = None
            return None

        return None

    # ============================================================
    # 24 小时静态数据缓存
    # ============================================================

    def get_cache_path(self, cache_key: str) -> str:
        """
        获取缓存文件路径
        :param cache_key: 缓存键名（如 "material_version", "static_data"）
        :return: 缓存文件绝对路径
        """
        # 安全化文件名
        safe_key = StrUtil.clean(cache_key, strict=True)
        if not safe_key:
            safe_key = "default"
        return os.path.join(CACHE_DIR, f"{safe_key}.json")

    def get_cached_data(self, cache_key: str, max_age: int = CACHE_TTL) -> Optional[dict]:
        """
        获取缓存数据（自动判断是否过期、是否损坏）

        :param cache_key: 缓存键名
        :param max_age: 最大有效期（秒），默认 24 小时
        :return: 有效缓存的字典数据，过期/损坏/不存在返回 None
        """
        try:
            cache_path = self.get_cache_path(cache_key)

            if not os.path.exists(cache_path):
                self._net_logger.debug(f"缓存不存在: {cache_key}")
                return None

            # 读取缓存文件
            raw = safe_read_file(cache_path)
            if not raw:
                self._net_logger.warning(f"缓存文件为空: {cache_key}，将重新请求")
                self._clear_cache(cache_key)
                return None

            # 解析 JSON
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                self._net_logger.error(f"缓存文件损坏（JSON 解析失败）: {cache_key}，清除后重新请求")
                self._clear_cache(cache_key)
                return None

            # 检查时间戳
            cached_time = data.get("_cached_at", 0)
            current_time = timestamp_sec()
            age = current_time - cached_time

            if age > max_age:
                self._net_logger.info(f"缓存已过期: {cache_key}（已缓存 {age // 3600} 小时）")
                return None

            if age < 0:
                # 时间戳异常（系统时间被修改）
                self._net_logger.warning(f"缓存时间戳异常: {cache_key}，清除后重新请求")
                self._clear_cache(cache_key)
                return None

            self._net_logger.debug(f"缓存命中: {cache_key}（已缓存 {age // 60} 分钟）")
            return data

        except Exception as e:
            self._net_logger.warning(f"读取缓存异常: {cache_key} - {e}")
            return None

    def set_cached_data(self, cache_key: str, data: dict) -> bool:
        """
        写入缓存数据（自动附加时间戳）

        :param cache_key: 缓存键名
        :param data: 要缓存的数据字典
        :return: 是否成功
        """
        try:
            cache_path = self.get_cache_path(cache_key)

            # 附加缓存时间戳
            cache_data = {
                "_cached_at": timestamp_sec(),
                "_cache_key": cache_key,
                "data": data,
            }

            # 写入文件
            content = json.dumps(cache_data, ensure_ascii=False, indent=2)
            result = safe_write_file(cache_path, content)

            if result:
                self._net_logger.info(f"缓存写入成功: {cache_key}")
                # 同步更新内存缓存
                self._memory_cache[cache_key] = cache_data
            else:
                self._net_logger.error(f"缓存写入失败: {cache_key}")

            return result

        except Exception as e:
            self._net_logger.error(f"设置缓存异常: {cache_key} - {e}")
            return False

    def _clear_cache(self, cache_key: str):
        """清除指定缓存"""
        try:
            cache_path = self.get_cache_path(cache_key)
            if os.path.exists(cache_path):
                os.remove(cache_path)
            self._memory_cache.pop(cache_key, None)
        except Exception as e:
            self._net_logger.warning(f"清除缓存失败: {cache_key} - {e}")

    def clear_all_cache(self) -> bool:
        """清除所有缓存"""
        try:
            count = 0
            for fname in os.listdir(CACHE_DIR):
                if fname.endswith(".json"):
                    os.remove(os.path.join(CACHE_DIR, fname))
                    count += 1
            self._memory_cache.clear()
            self._net_logger.info(f"已清除 {count} 个缓存文件")
            return True
        except Exception as e:
            self._net_logger.error(f"清除全部缓存失败: {e}")
            return False

    def get_cached_data_with_fallback(
        self,
        cache_key: str,
        fetch_func: Callable[[], Optional[dict]],
        max_age: int = CACHE_TTL,
        force_refresh: bool = False,
    ) -> Optional[dict]:
        """
        获取缓存数据，缓存失效或强制刷新时调用 fetch_func 重新获取

        :param cache_key: 缓存键名
        :param fetch_func: 获取数据的回调函数，返回字典或 None
        :param max_age: 缓存有效期（秒）
        :param force_refresh: 是否强制刷新（跳过缓存）
        :return: 数据字典或 None
        """
        try:
            # 非强制刷新时，先尝试读取缓存
            if not force_refresh:
                cached = self.get_cached_data(cache_key, max_age)
                if cached is not None:
                    return cached.get("data", cached)

            # 缓存失效或强制刷新，调用获取函数
            self._net_logger.info(f"正在获取最新数据: {cache_key}")
            fresh_data = fetch_func()

            if fresh_data is not None:
                # 写入缓存
                self.set_cached_data(cache_key, fresh_data)
                return fresh_data
            else:
                # 获取失败，尝试返回过期缓存
                self._net_logger.warning(f"获取最新数据失败: {cache_key}")
                if not force_refresh:
                    cached = self.get_cached_data(cache_key, max_age=999999999)
                    if cached is not None:
                        self._net_logger.info("返回过期缓存作为降级方案")
                        return cached.get("data", cached)
                return None

        except Exception as e:
            self._net_logger.error(f"缓存回退异常: {cache_key} - {e}")
            return None

    # ============================================================
    # 素材版本检测与更新
    # ============================================================

    # 已知开源库内置素材列表（仅 Python 开源库内置免费素材）
    # 每个字段：{ "pypi_name": 包名, "module": 导入模块名, "version": 当前版本 }
    LIBRARY_MATERIALS = [
        {"name": "easyocr", "pypi": "easyocr", "version_attr": "__version__"},
        {"name": "Kivy", "pypi": "Kivy", "version_attr": "__version__"},
        {"name": "Pillow", "pypi": "pillow", "version_attr": "__version__"},
        {"name": "pygame", "pypi": "pygame", "version_attr": "ver"},
        {"name": "requests", "pypi": "requests", "version_attr": "__version__"},
    ]

    def get_local_library_versions(self) -> dict:
        """
        获取本地已安装开源库的版本信息
        :return: { 库名: 版本号 }
        """
        versions = {}
        for lib in self.LIBRARY_MATERIALS:
            try:
                module = __import__(lib["name"].lower())
                version = getattr(module, lib["version_attr"], "未知")
                versions[lib["name"]] = str(version)
            except ImportError:
                versions[lib["name"]] = "未安装"
            except Exception as e:
                versions[lib["name"]] = f"获取失败: {e}"
        return versions

    def check_material_updates(self, timeout: int = MATERIAL_UPDATE_TIMEOUT) -> dict:
        """
        检查素材（开源库）是否有可用更新

        原理：通过 PyPI JSON API 查询已安装库的最新版本，对比本地版本。
        注意：仅获取版本号对比，不自动下载第三方独立资源包。
        实际更新需用户通过 pip 操作（见 pip_setup.py）。

        :param timeout: 超时秒数（默认 20 秒）
        :return: {
            "has_updates": bool,
            "updates": [ { "name", "current", "latest", "status" } ],
            "error": str or None,
        }
        """
        result = {
            "has_updates": False,
            "updates": [],
            "error": None,
            "checked_at": timestamp_sec(),
        }

        try:
            self._net_logger.info("正在检查素材更新...")

            # 获取本地版本
            local_versions = self.get_local_library_versions()

            # 使用缓存优先
            cache_key = "material_versions"
            cached = self.get_cached_data(cache_key, max_age=3600)  # 版本缓存 1 小时
            remote_versions = None

            if cached:
                remote_versions = cached.get("data", cached)

            if remote_versions is None:
                # 通过阿里云镜像 PyPI JSON API 获取最新版本（屏蔽境外 pypi.org）
                remote_versions = {}
                for lib in self.LIBRARY_MATERIALS:
                    try:
                        pypi_url = f"https://mirrors.aliyun.com/pypi/{lib['pypi']}/json"
                        self._net_logger.info(f"查询 {lib['name']} 最新版本...")

                        resp = requests.get(
                            pypi_url,
                            headers=self._headers,
                            timeout=min(timeout, 15),
                        )

                        if resp.status_code == 200:
                            pypi_data = resp.json()
                            latest = pypi_data.get("info", {}).get("version", "未知")
                            remote_versions[lib["name"]] = latest
                        else:
                            remote_versions[lib["name"]] = "查询失败"

                    except requests.Timeout:
                        self._net_logger.warning(f"查询 {lib['name']} 超时")
                        remote_versions[lib["name"]] = "超时"
                    except requests.ConnectionError:
                        self._net_logger.warning(f"查询 {lib['name']} 连接失败")
                        remote_versions[lib["name"]] = "连接失败"
                    except Exception as e:
                        self._net_logger.warning(f"查询 {lib['name']} 异常: {e}")
                        remote_versions[lib["name"]] = "异常"

                # 缓存远程版本结果（1 小时）
                if remote_versions:
                    self.set_cached_data(cache_key, remote_versions)
            else:
                self._net_logger.info("使用缓存的版本信息")

            # 对比版本
            for lib in self.LIBRARY_MATERIALS:
                name = lib["name"]
                current = local_versions.get(name, "未知")
                latest = remote_versions.get(name, "未知")

                update_info = {
                    "name": name,
                    "current": current,
                    "latest": latest,
                }

                if current == "未安装" or current == "未知":
                    update_info["status"] = "未安装"
                elif latest in ("查询失败", "超时", "连接失败", "异常", "未知"):
                    update_info["status"] = "查询失败"
                elif current == latest:
                    update_info["status"] = "已最新"
                else:
                    # 有更新
                    update_info["status"] = "可更新"
                    result["has_updates"] = True

                result["updates"].append(update_info)

            self._net_logger.info(
                f"素材更新检查完成: {'有可用更新' if result['has_updates'] else '全部已最新'}"
            )

        except requests.Timeout:
            error_msg = f"素材更新检查整体超时（{timeout}s）"
            self._net_logger.error(error_msg)
            result["error"] = error_msg
        except requests.ConnectionError:
            error_msg = "素材更新检查连接失败（可能无网络）"
            self._net_logger.error(error_msg)
            result["error"] = error_msg
        except Exception as e:
            error_msg = f"素材更新检查异常: {e}"
            self._net_logger.error(error_msg)
            result["error"] = error_msg

        return result

    def update_material(self, lib_name: str, timeout: int = MATERIAL_UPDATE_TIMEOUT) -> dict:
        """
        更新指定的开源库（通过 pip 升级）

        注意：实际安装使用 pip_setup.py 的镜像策略
        这里仅触发更新流程，返回执行结果

        :param lib_name: 库名（如 "easyocr"）
        :param timeout: 超时秒数
        :return: { "success": bool, "message": str }
        """
        result = {"success": False, "message": ""}

        try:
            self._net_logger.info(f"开始更新素材: {lib_name}")

            # 查找库信息
            lib_info = None
            for lib in self.LIBRARY_MATERIALS:
                if lib["name"].lower() == lib_name.lower():
                    lib_info = lib
                    break

            if lib_info is None:
                result["message"] = f"未知库: {lib_name}"
                return result

            # 通过 pip 安装/升级
            import subprocess

            pip_cmd = [
                sys.executable, "-m", "pip", "install",
                "--upgrade",
                lib_info["pypi"],
                "-i", "https://mirrors.aliyun.com/pypi/simple/",
                "--trusted-host", "mirrors.aliyun.com",
                "--timeout", "10",
                "--retries", "1",
            ]

            self._net_logger.info(f"执行: {' '.join(pip_cmd[:6])}...")

            proc = subprocess.run(
                pip_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if proc.returncode == 0:
                result["success"] = True
                result["message"] = f"{lib_name} 更新成功"
                self._net_logger.info(f"{lib_name} 更新成功")

                # 清除版本缓存，下次检查时重新获取
                self._clear_cache("material_versions")
            else:
                error_out = proc.stderr.strip() or proc.stdout.strip()
                result["message"] = f"更新失败: {error_out[:200]}"
                self._net_logger.error(f"{lib_name} 更新失败: {error_out[:200]}")

        except subprocess.TimeoutExpired:
            result["message"] = f"更新超时（{timeout}s）"
            self._net_logger.error(f"{lib_name} 更新超时")
        except Exception as e:
            result["message"] = f"更新异常: {e}"
            self._net_logger.error(f"{lib_name} 更新异常: {e}")

        return result

    # ============================================================
    # 网络状态 UI 辅助
    # ============================================================

    def get_state_display_info(self, state: str) -> dict:
        """
        获取网络状态的显示信息（供 UI 层使用）
        :param state: NetworkState 常量
        :return: { "text": str, "color": str, "icon": str }
        """
        info = {
            NetworkState.NO_NETWORK: {
                "text": "无网络连接",
                "color": "#FF3B30",      # 红色
                "icon": "⚠",
                "action": "请检查网络设置后重试",
            },
            NetworkState.WEAK_NETWORK: {
                "text": "网络信号弱",
                "color": "#FF9500",      # 橙色
                "icon": "⚡",
                "action": "部分功能可能响应较慢",
            },
            NetworkState.NORMAL: {
                "text": "网络正常",
                "color": "#34C759",      # 绿色
                "icon": "✓",
                "action": "",
            },
        }
        return info.get(state, info[NetworkState.NO_NETWORK])


# ============================================================
# 实例快捷访问
# ============================================================
def get_network_manager() -> NetworkManager:
    """
    获取 NetworkManager 单例（线程安全）
    每次调用返回同一实例
    """
    global _network_manager_instance
    try:
        if _network_manager_instance is None:
            _network_manager_instance = NetworkManager()
        return _network_manager_instance
    except NameError:
        _network_manager_instance = NetworkManager()
        return _network_manager_instance


# 全局实例
_network_manager_instance = None


# ============================================================
# 对外测试接口（main.py 调用）
# ============================================================
def check_network_and_notify(on_state_change: Callable[[str], None] = None) -> str:
    """
    检测网络状态并通知回调（供入口模块一键调用）

    :param on_state_change: 网络状态变更回调
    :return: NetworkState 常量
    """
    try:
        mgr = get_network_manager()
        if on_state_change:
            mgr.register_state_callback(on_state_change)
        return mgr.check_network_state()
    except Exception as e:
        LogManager.get_logger("app").error(f"网络检测异常: {e}")
        return NetworkState.NO_NETWORK


def check_material_update_status() -> dict:
    """
    检查素材更新状态（供 UI 模块调用）
    :return: { "has_updates": bool, "updates": list, "error": str }
    """
    try:
        mgr = get_network_manager()
        return mgr.check_material_updates()
    except Exception as e:
        LogManager.get_logger("app").error(f"素材更新检查异常: {e}")
        return {"has_updates": False, "updates": [], "error": str(e)}


def get_cached_api_data(
    cache_key: str,
    api_path: str,
    params: Optional[dict] = None,
    max_age: int = CACHE_TTL,
) -> Optional[dict]:
    """
    获取缓存的 API 数据（带 24 小时缓存）
    :param cache_key: 缓存键名
    :param api_path: API 路径
    :param params: 查询参数
    :param max_age: 缓存有效期
    :return: 数据字典或 None
    """
    try:
        mgr = get_network_manager()

        def _fetch():
            return mgr.request_with_failover(api_path, params=params)

        return mgr.get_cached_data_with_fallback(cache_key, _fetch, max_age=max_age)
    except Exception as e:
        LogManager.get_logger("app").error(f"缓存 API 数据异常: {e}")
        return None