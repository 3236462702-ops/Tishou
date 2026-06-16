# -*- coding: utf-8 -*-
"""
屏幕截取与 OCR 识别模块（双采集引擎）
====================================
遵守全局 OCR 规范、延迟规范、异常规范。

主力引擎：accessible-android 无障碍服务抓取（优先）
兜底引擎：easyocr + Pillow 纯本地 OCR

流程：
  1. 先通过 accessible-android 无障碍服务读取订单信息
  2. 读取失败 / 无订单文本 / 控件异常 / 超时 → 自动降级启用 EasyOCR 截图识别
  3. EasyOCR 流程：截取有效区域 → 灰度 → 二值化 → 降噪 → 放大1.3倍
  4. 识别后主动释放图片资源

约束：
  - 仅加载一次 ch_sim 简体模型
  - 关闭模型更新、禁用 GPU
  - 全异常捕获，记录 OCR 日志
  - 防卡顿闪退
"""

import sys
import os
import time
import threading
from datetime import datetime
from typing import Optional, Callable

# 将父目录加入路径以便导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.utils import (
    LogManager, ConfigManager, ExceptionUtil,
    is_android, safe_int, safe_float, safe_bool,
    ensure_dir, safe_delete_file, timestamp_ms,
    PROJECT_DIR, ASSETS_DIR,
)


# ============================================================
# 常量
# ============================================================

# 捕获引擎类型
class CaptureEngine:
    """捕获引擎常量"""

    ACCESSIBILITY = "accessibility"    # accessible-android 主力引擎（优先）
    EASYOCR = "easyocr"                # easyocr + Pillow 兜底引擎


# OCR 识别状态
class OcrStatus:
    """OCR 状态常量"""

    IDLE = "idle"                      # 空闲
    CAPTURING = "capturing"            # 截屏中
    PREPROCESSING = "preprocessing"    # 预处理中
    RECOGNIZING = "recognizing"        # 识别中
    COMPLETED = "completed"            # 完成
    FAILED = "failed"                  # 失败
    TIMEOUT = "timeout"                # 超时
    SWITCHING_ENGINE = "switching_engine"  # 切换引擎


# 默认截屏轮询间隔（毫秒）
DEFAULT_POLL_INTERVAL_MS = 500
LOW_END_POLL_INTERVAL_MS = 1000

# OCR 预处理参数
DEFAULT_IMAGE_SCALE = 1.3

# 识别超时（秒）
OCR_TIMEOUT = 8

# 订单判定延迟（秒）
DEFAULT_JUDGE_DELAY = 5

# 截图缓存目录
CAPTURE_DIR = os.path.join(PROJECT_DIR, "captures")


# ============================================================
# 图片预处理工具
# ============================================================

class ImagePreprocessor:
    """
    图片预处理器
    ============
    对截取区域执行标准化预处理流程：
      裁剪 → 灰度 → 二值化 → 降噪 → 放大

    低配机型可关闭放大步骤以降低性能消耗。
    """

    @staticmethod
    @ExceptionUtil.safe_call(default_return=None, log_level="error")
    def preprocess(
        image_path: str,
        region: Optional[dict] = None,
        scale: float = DEFAULT_IMAGE_SCALE,
        enable_scale: bool = True,
    ) -> Optional[str]:
        """
        完整预处理流水线

        :param image_path: 原始图片路径
        :param region: 裁剪区域 {x, y, w, h}，None=不裁剪
        :param scale: 放大倍数（默认 1.3）
        :param enable_scale: 是否启用放大（低配机关闭）
        :return: 预处理后图片路径，失败返回 None
        """
        from PIL import Image, ImageFilter

        img = None
        try:
            img = Image.open(image_path)
            original_mode = img.mode

            # ---- 第1步：裁剪有效区域 ----
            if region:
                x = safe_int(region.get("x", 0))
                y = safe_int(region.get("y", 0))
                w = safe_int(region.get("w", img.width))
                h = safe_int(region.get("h", img.height))
                img = img.crop((x, y, x + w, y + h))

            # ---- 第2步：灰度化 ----
            if img.mode != "L":
                img = img.convert("L")

            # ---- 第3步：二值化（自适应阈值） ----
            img = img.point(lambda p: 255 if p > 128 else 0, mode="L")

            # ---- 第4步：降噪（中值滤波） ----
            img = img.filter(ImageFilter.MedianFilter(size=3))

            # ---- 第5步：放大（低配机关闭） ----
            if enable_scale and scale > 1.0 and abs(scale - 1.0) > 0.01:
                new_w = int(img.width * scale)
                new_h = int(img.height * scale)
                img = img.resize((new_w, new_h), Image.LANCZOS)

            # ---- 保存预处理结果 ----
            preprocessed_path = image_path.replace(
                ".png", "_preprocessed.png"
            ).replace(
                ".jpg", "_preprocessed.png"
            ).replace(
                ".jpeg", "_preprocessed.png"
            )
            img.save(preprocessed_path, "PNG")

            return preprocessed_path

        except Exception:
            # 预处理失败返回原图路径
            return image_path
        finally:
            if img is not None:
                try:
                    img.close()
                except Exception:
                    pass

    @staticmethod
    @ExceptionUtil.safe_call(default_return=None, log_level="error")
    def fast_preprocess(image_path: str, region: Optional[dict] = None) -> Optional[str]:
        """
        快速预处理（低配机模式：无放大，简化降噪）

        :param image_path: 原始图片路径
        :param region: 裁剪区域
        :return: 预处理后图片路径
        """
        from PIL import Image

        img = None
        try:
            img = Image.open(image_path)

            # 裁剪
            if region:
                x = safe_int(region.get("x", 0))
                y = safe_int(region.get("y", 0))
                w = safe_int(region.get("w", img.width))
                h = safe_int(region.get("h", img.height))
                img = img.crop((x, y, x + w, y + h))

            # 灰度 → 简单二值化
            if img.mode != "L":
                img = img.convert("L")
            img = img.point(lambda p: 255 if p > 128 else 0, mode="L")

            preprocessed_path = image_path.replace(
                ".png", "_fast.png"
            ).replace(
                ".jpg", "_fast.png"
            )
            img.save(preprocessed_path, "PNG")

            return preprocessed_path

        except Exception:
            return image_path
        finally:
            if img is not None:
                try:
                    img.close()
                except Exception:
                    pass


# ============================================================
# easyocr 引擎
# ============================================================

class EasyOcrEngine:
    """
    easyocr 识别引擎
    ===============
    遵守 OCR 规范：
      - 仅加载一次 ch_sim 简体模型
      - 关闭自动更新、禁用 GPU
      - detail=0 简化输出
      - 8 秒超时
      - 识别后释放图片资源
    """

    def __init__(self):
        """初始化 easyocr 引擎（仅在首次使用时惰性加载）"""
        self._logger = LogManager.get_logger("ocr")
        self._reader = None          # easyocr Reader 实例
        self._load_lock = threading.Lock()
        self._loaded = False
        self._load_error = ""

        self._logger.info("easyocr 引擎已创建（等待首次调用时加载模型）")

    @ExceptionUtil.safe_call(default_return=False, log_level="error")
    def _load_model(self) -> bool:
        """
        加载 ch_sim 模型（程序启动后仅加载一次）
        约束：关闭自动更新、禁用 GPU
        """
        if self._loaded:
            return True

        with self._load_lock:
            if self._loaded:
                return True

            try:
                self._logger.info("正在加载 easyocr ch_sim 模型（首次加载）...")
                import easyocr

                # 关键参数：
                # - lang_list=["ch_sim"]  仅加载简体中文
                # - gpu=False             禁用 GPU（纯 CPU 识别）
                # - download_enabled=False 关闭自动更新/下载
                # - model_storage_directory 指定安卓可写路径
                ensure_dir(ASSETS_DIR)
                self._reader = easyocr.Reader(
                    lang_list=["ch_sim"],
                    gpu=False,
                    download_enabled=False,
                    model_storage_directory=ASSETS_DIR,
                    verbose=False,
                )
                self._loaded = True
                self._load_error = ""
                self._logger.info("easyocr ch_sim 模型加载成功")

                # 验证模型：用小尺寸白色图片预热，避免传空串导致内部异常
                try:
                    from PIL import Image
                    warmup_path = os.path.join(self._cache_dir, "_warmup.png")
                    ensure_dir(self._cache_dir)
                    warmup_img = Image.new("L", (100, 30), color=255)
                    warmup_img.save(warmup_path, "PNG")
                    warmup_img.close()
                    self._reader.readtext(warmup_path, detail=0, paragraph=False)
                    safe_delete_file(warmup_path)
                    self._logger.debug("easyocr 模型预热完成")
                except Exception as warmup_e:
                    self._logger.warning(f"easyocr 预热跳过（不影响正常使用）: {warmup_e}")
                return True

            except ImportError:
                self._load_error = "easyocr 未安装"
                self._logger.error(f"easyocr 未安装：{self._load_error}")
                return False
            except Exception as e:
                self._load_error = str(e)
                self._logger.error(f"easyocr 模型加载失败: {e}")
                return False

    @property
    def is_ready(self) -> bool:
        """引擎是否就绪"""
        if not self._loaded:
            self._load_model()
        return self._loaded

    @property
    def load_error(self) -> str:
        """获取加载错误信息"""
        return self._load_error

    @ExceptionUtil.safe_call(default_return=[], log_level="error")
    def recognize(self, image_path: str, timeout: int = OCR_TIMEOUT) -> list:
        """
        对图片执行 OCR 识别

        :param image_path: 预处理后的图片路径
        :param timeout: 识别超时秒数（默认 8 秒）
        :return: 识别结果列表 [ [text], [text], ... ] 或 []
        """
        if not self._load_model():
            self._logger.error("easyocr 模型未就绪，无法识别")
            return []

        if not os.path.exists(image_path):
            self._logger.error(f"图片文件不存在: {image_path}")
            return []

        img = None
        result = []
        try:
            from PIL import Image

            # 打开图片
            img = Image.open(image_path)

            # 记录开始时间
            start_time = time.time()

            # 使用线程执行识别（支持超时控制）
            recognize_result = [None]
            recognize_error = [None]
            recognize_done = threading.Event()

            def _do_recognize():
                try:
                    # detail=0：只返回文字，不返回框坐标和置信度
                    # paragraph=False：不合并段落
                    res = self._reader.readtext(
                        image_path,
                        detail=0,
                        paragraph=False,
                    )
                    recognize_result[0] = res
                except Exception as e:
                    recognize_error[0] = e
                finally:
                    recognize_done.set()

            # 启动识别线程
            recog_thread = threading.Thread(target=_do_recognize, daemon=True)
            recog_thread.start()

            # 等待结果或超时
            if not recognize_done.wait(timeout=timeout):
                # 超时
                elapsed = time.time() - start_time
                self._logger.warning(
                    f"OCR 识别超时 ({elapsed:.1f}s > {timeout}s)"
                )
                return []

            # 检查错误
            if recognize_error[0] is not None:
                raise recognize_error[0]

            raw_result = recognize_result[0]
            if raw_result is None:
                return []

            # 格式化结果：每个元素为 [text]
            result = [[item] if isinstance(item, str) else [str(item)]
                      for item in raw_result]

            elapsed = time.time() - start_time
            self._logger.debug(
                f"OCR 识别完成: {len(result)} 项, 耗时 {elapsed:.2f}s"
            )
            return result

        except Exception as e:
            self._logger.error(f"OCR 识别异常: {e}")
            return []
        finally:
            # 主动释放图片资源
            if img is not None:
                try:
                    img.close()
                    img = None
                except Exception:
                    pass
            # 清理预处理图片（保留原图）
            self._cleanup_temp_image(image_path)

    def _cleanup_temp_image(self, image_path: str):
        """安全删除临时图片（不报错）"""
        try:
            if image_path and os.path.exists(image_path):
                # 只删除预处理生成的临时文件（带 _preprocessed / _fast 标记的）
                basename = os.path.basename(image_path)
                if "_preprocessed" in basename or "_fast" in basename:
                    safe_delete_file(image_path)
        except Exception:
            pass

    def warmup(self) -> bool:
        """
        预热模型（程序启动时调用，提前加载 ch_sim 模型）
        :return: True=加载成功
        """
        return self._load_model()

    def shutdown(self):
        """
        关闭引擎，释放 easyocr Reader 资源
        调用后 self._reader 置为 None，内存可被 GC 回收
        """
        with self._load_lock:
            try:
                if self._reader is not None:
                    self._reader = None
                self._loaded = False
                self._logger.info("EasyOcrEngine 已关闭，资源已释放")
            except Exception as e:
                self._logger.warning(f"关闭 EasyOcrEngine 异常: {e}")


# ============================================================
# accessible-android 无障碍引擎（兜底）
# ============================================================

class AccessibilityEngine:
    """
    无障碍服务抓取引擎（兜底方案）
    ============================
    当 easyocr 不可用或识别失败时自动切换至此引擎。
    通过 Android 无障碍服务获取界面文本信息。
    """

    def __init__(self):
        """初始化无障碍引擎"""
        self._logger = LogManager.get_logger("ocr")
        self._available = False
        self._check_lock = threading.Lock()

        # 检查环境
        self._check_availability()

    def _check_availability(self):
        """检查 accessible-android 是否可用"""
        try:
            # 尝试导入 accessible-android
            import android_accessibility  # noqa
            self._available = True
            self._logger.info("accessible-android 无障碍引擎可用")
        except ImportError:
            self._available = False
            self._logger.warning(
                "accessible-android 未安装，无障碍引擎不可用"
            )
        except Exception as e:
            self._available = False
            self._logger.warning(f"无障碍引擎检查异常: {e}")

    @property
    def is_available(self) -> bool:
        """引擎是否可用"""
        return self._available

    @ExceptionUtil.safe_call(default_return=[], log_level="error")
    def capture_and_recognize(self, timeout: int = OCR_TIMEOUT) -> list:
        """
        通过无障碍服务抓取屏幕文本

        :param timeout: 超时秒数
        :return: 识别结果列表 [ [text], [text], ... ] 或 []
        """
        if not self._available:
            self._logger.error("无障碍引擎不可用")
            return []

        try:
            start_time = time.time()

            # accessible-android 抓取界面节点文本
            # 注意：此代码仅在安卓真机 + accessible-android 安装时生效
            from android_accessibility import AccessibilityService

            service = AccessibilityService()
            nodes = service.get_root_node()

            if not nodes:
                self._logger.warning("无障碍服务未获取到界面节点")
                return []

            # 提取所有文本节点
            texts = []
            self._extract_text_nodes(nodes, texts)

            # 格式化结果
            result = [[text] for text in texts if text.strip()]

            elapsed = time.time() - start_time
            self._logger.debug(
                f"无障碍抓取完成: {len(result)} 项, 耗时 {elapsed:.2f}s"
            )
            return result

        except ImportError:
            self._available = False
            self._logger.warning("accessible-android 未安装")
            return []
        except Exception as e:
            self._logger.error(f"无障碍抓取异常: {e}")
            return []

    def _extract_text_nodes(self, node, texts: list):
        """
        递归提取界面节点的文本内容

        :param node: 当前节点
        :param texts: 文本列表（引用传递）
        """
        try:
            # 提取节点文本
            if hasattr(node, "get_text") and callable(node.get_text):
                text = node.get_text()
                if text and isinstance(text, str) and text.strip():
                    texts.append(text.strip())

            # 提取子节点
            if hasattr(node, "get_children") and callable(node.get_children):
                children = node.get_children()
                if children:
                    for child in children:
                        self._extract_text_nodes(child, texts)

        except Exception:
            pass  # 单个节点异常不影响整体

    @ExceptionUtil.safe_call(default_return=False, log_level="warning")
    def take_screenshot(self, save_path: str) -> bool:
        """
        通过无障碍服务截屏（备用截屏方案）

        :param save_path: 保存路径
        :return: True=成功
        """
        try:
            # 通过无障碍服务截屏
            from android_accessibility import AccessibilityService
            service = AccessibilityService()
            screenshot = service.take_screenshot()

            if screenshot is None:
                self._logger.warning("无障碍截屏失败")
                return False

            # 保存截图
            from PIL import Image
            img = Image.frombytes(
                "RGBA",
                (screenshot.width, screenshot.height),
                screenshot.data,
            )
            ensure_dir(os.path.dirname(save_path))
            img.save(save_path, "PNG")
            img.close()

            self._logger.debug(f"无障碍截屏已保存: {save_path}")
            return True

        except ImportError:
            self._logger.warning("accessible-android 未安装，无法截屏")
            return False
        except Exception as e:
            self._logger.error(f"无障碍截屏异常: {e}")
            return False


# ============================================================
# 截屏与管理器
# ============================================================

class CaptureManager:
    """
    双采集引擎管理器
    ===============
    整合 accessible-android（主力）和 easyocr（兜底）双引擎。

    执行顺序：
      1. 优先使用 accessible-android 无障碍服务读取订单信息
      2. 读取失败 / 无结果 / 异常 / 超时 → 自动降级 EasyOCR 截图识别
      3. 支持手动切换引擎顺序

    功能：
      - 启动时检测无障碍引擎可用性，后台预热 easyocr 兜底模型
      - 无障碍直接获取界面文本（无需截图预处理）
      - EasyOCR 流程：按配置区域裁剪 → 预处理 → OCR 识别
      - 8 秒超时 + 自动降级切换
      - 可配置的轮询间隔（默认 500ms，低配 1000ms）
      - 订单判定延迟（默认 5 秒）
      - 全异常捕获，记录 OCR 日志
    """

    def __init__(self):
        """初始化双引擎管理器"""
        self._logger = LogManager.get_logger("ocr")
        self._config = ConfigManager()

        # ---- 引擎实例（惰性初始化） ----
        self._easyocr_engine: Optional[EasyOcrEngine] = None
        self._accessibility_engine: Optional[AccessibilityEngine] = None

        # ---- 当前活跃引擎 ----
        self._active_engine = CaptureEngine.ACCESSIBILITY  # 默认主力引擎
        self._preferred_engine = self._config.get(
            "preferred_engine", CaptureEngine.ACCESSIBILITY
        )

        # ---- 配置参数 ----
        self._poll_interval_ms = safe_int(
            self._config.get("ocr_poll_interval"), DEFAULT_POLL_INTERVAL_MS
        )
        self._ocr_timeout = safe_float(
            self._config.get("ocr_timeout"), OCR_TIMEOUT
        )
        self._image_scale = safe_float(
            self._config.get("ocr_image_scale"), DEFAULT_IMAGE_SCALE
        )
        self._order_judge_delay = safe_float(
            self._config.get("order_judge_delay"), DEFAULT_JUDGE_DELAY
        )
        self._low_end_mode = safe_bool(
            self._config.get("low_end_device"), False
        )

        # 低配机自动调整轮询间隔
        if self._low_end_mode:
            if self._poll_interval_ms < LOW_END_POLL_INTERVAL_MS:
                self._poll_interval_ms = LOW_END_POLL_INTERVAL_MS

        # ---- 运行状态 ----
        self._running = False
        self._status = OcrStatus.IDLE
        self._status_lock = threading.Lock()
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # ---- 识别结果回调 ----
        self._result_callbacks = []

        # ---- 最后一次识别结果 ----
        self._last_result: list = []
        self._last_capture_time: float = 0.0
        self._last_ocr_time: float = 0.0
        self._last_error: str = ""

        # ---- 判断延迟计时器 ----
        self._judge_timer: Optional[threading.Timer] = None
        self._judge_pending = False

        # 确保截图目录存在
        ensure_dir(CAPTURE_DIR)

        # ---- 预热 easyocr（线程中加载，不阻塞启动） ----
        self._warmup_thread = threading.Thread(
            target=self._warmup_engines, daemon=True
        )
        self._warmup_thread.start()

        self._logger.info(
            f"双引擎管理器初始化完成 (引擎={self._preferred_engine}, "
            f"轮询={self._poll_interval_ms}ms, "
            f"低配={self._low_end_mode})"
        )

    # ============================================================
    # 引擎管理
    # ============================================================

    def _warmup_engines(self):
        """预热引擎（后台加载，不阻塞主线程）"""
        try:
            # 先检查无障碍引擎（主力引擎）
            accessibility_engine = self._get_accessibility()
            if accessibility_engine and accessibility_engine.is_available:
                self._logger.info("accessible-android 主力引擎可用")
            else:
                self._logger.warning("accessible-android 不可用，将使用 EasyOCR 兜底")

            # 预热 easyocr（兜底引擎）
            easyocr_engine = self._get_easyocr()
            if easyocr_engine and easyocr_engine.warmup():
                self._logger.info("easyocr 兜底引擎预热完成")
            else:
                self._logger.warning("easyocr 引擎预热失败")
        except Exception as e:
            self._logger.warning(f"引擎预热异常: {e}")

    def _get_easyocr(self) -> EasyOcrEngine:
        """获取 easyocr 引擎实例（惰性创建）"""
        if self._easyocr_engine is None:
            self._easyocr_engine = EasyOcrEngine()
        return self._easyocr_engine

    def _get_accessibility(self) -> AccessibilityEngine:
        """获取无障碍引擎实例（惰性创建）"""
        if self._accessibility_engine is None:
            self._accessibility_engine = AccessibilityEngine()
        return self._accessibility_engine

    def set_preferred_engine(self, engine: str):
        """
        手动指定优先引擎

        :param engine: CaptureEngine.EASYOCR 或 CaptureEngine.ACCESSIBILITY
        """
        try:
            if engine not in (CaptureEngine.EASYOCR, CaptureEngine.ACCESSIBILITY):
                self._logger.warning(f"无效引擎: {engine}")
                return

            self._preferred_engine = engine
            self._active_engine = engine
            self._config.set("preferred_engine", engine)
            self._logger.info(f"优先引擎已切换为: {engine}")
        except Exception as e:
            self._logger.error(f"切换引擎失败: {e}")

    def get_active_engine(self) -> str:
        """获取当前活跃引擎"""
        return self._active_engine

    def get_engine_status(self) -> dict:
        """
        获取引擎状态（供 UI 展示）

        :return: {
            "active_engine": str,
            "preferred_engine": str,
            "easyocr_ready": bool,
            "accessibility_available": bool,
        }
        """
        return {
            "active_engine": self._active_engine,
            "preferred_engine": self._preferred_engine,
            "easyocr_ready": self._get_easyocr().is_ready if self._easyocr_engine else False,
            "accessibility_available": (
                self._get_accessibility().is_available
                if self._accessibility_engine else False
            ),
        }

    # ============================================================
    # 截屏
    # ============================================================

    @ExceptionUtil.safe_call(default_return="", log_level="error")
    def capture_screen(self) -> str:
        """
        截取屏幕

        优先使用 accessible-android 截屏（安卓环境），
        Windows 开发环境使用模拟截图。

        :return: 截图保存路径，失败返回空字符串
        """
        timestamp = int(time.time() * 1000)
        save_path = os.path.join(CAPTURE_DIR, f"screenshot_{timestamp}.png")

        if is_android():
            # ---- 安卓真机：尝试使用无障碍服务截屏 ----
            accessibility = self._get_accessibility()
            if accessibility.is_available:
                success = accessibility.take_screenshot(save_path)
                if success:
                    self._logger.debug(f"截屏成功: {save_path}")
                    return save_path

            # 无障碍截屏失败，尝试系统截屏命令
            try:
                import subprocess
                result = subprocess.run(
                    ["screencap", "-p", save_path],
                    capture_output=True, timeout=5,
                )
                if result.returncode == 0 and os.path.exists(save_path):
                    self._logger.debug(f"screencap 截屏成功: {save_path}")
                    return save_path
            except Exception as e:
                self._logger.warning(f"screencap 截屏失败: {e}")

            self._logger.error("所有截屏方式均失败")
            return ""
        else:
            # ---- Windows 开发环境：生成模拟截图 ----
            try:
                from PIL import Image, ImageDraw, ImageFont
                img = Image.new("RGB", (1080, 1920), color=(255, 255, 255))
                draw = ImageDraw.Draw(img)
                draw.text((100, 500), "TiShou 模拟截图", fill=(0, 0, 0))
                draw.text(
                    (100, 600),
                    f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    fill=(100, 100, 100),
                )
                ensure_dir(os.path.dirname(save_path))
                img.save(save_path, "PNG")
                img.close()
                self._logger.debug(f"模拟截图已生成: {save_path}")
                return save_path
            except Exception as e:
                self._logger.error(f"生成模拟截图失败: {e}")
                return ""

    # ============================================================
    # 预处理
    # ============================================================

    @ExceptionUtil.safe_call(default_return="", log_level="error")
    def preprocess_image(self, image_path: str) -> str:
        """
        对截图执行标准化预处理

        流程：裁剪有效区域 → 灰度 → 二值化 → 降噪 → 放大

        :param image_path: 原始截图路径
        :return: 预处理后图片路径
        """
        # 读取裁剪区域配置
        capture_cfg = self._config.get("capture", {})
        region = {
            "x": safe_int(capture_cfg.get("region_x")),
            "y": safe_int(capture_cfg.get("region_y")),
            "w": safe_int(capture_cfg.get("region_w", 1080)),
            "h": safe_int(capture_cfg.get("region_h", 1920)),
        }

        if self._low_end_mode:
            # 低配机：快速预处理（无放大）
            return ImagePreprocessor.fast_preprocess(image_path, region)
        else:
            # 标准预处理
            return ImagePreprocessor.preprocess(
                image_path, region,
                scale=self._image_scale,
                enable_scale=True,
            )

    # ============================================================
    # OCR 识别（双引擎自动切换）
    # ============================================================

    @ExceptionUtil.safe_call(default_return=[], log_level="error")
    def recognize(self, image_path: str) -> list:
        """
        对预处理图片执行 OCR 识别

        执行顺序（无障碍优先）：
          1. 先尝试 accessible-android 无障碍服务读取订单信息
          2. 读取失败 / 无订单文本 / 控件异常 / 超时 → 自动降级 EasyOCR
          3. 全部失败 → 返回空列表

        :param image_path: 预处理后的图片路径
        :return: 识别结果列表
        """
        if not os.path.exists(image_path):
            self._logger.error(f"图片不存在: {image_path}")
            return []

        result = []
        engines_to_try = []

        # 确定引擎尝试顺序（无障碍优先）
        if self._preferred_engine == CaptureEngine.ACCESSIBILITY:
            engines_to_try = [
                (CaptureEngine.ACCESSIBILITY, self._try_accessibility),
                (CaptureEngine.EASYOCR, self._try_easyocr),
            ]
        else:
            engines_to_try = [
                (CaptureEngine.EASYOCR, self._try_easyocr),
                (CaptureEngine.ACCESSIBILITY, self._try_accessibility),
            ]

        # 逐个尝试引擎
        for engine_name, try_func in engines_to_try:
            self._logger.info(f"尝试使用引擎: {engine_name}")
            with self._status_lock:
                self._status = OcrStatus.RECOGNIZING
                self._active_engine = engine_name

            result = try_func(image_path)

            if result and len(result) > 0:
                # 识别成功
                self._logger.info(
                    f"引擎 {engine_name} 识别成功: {len(result)} 项"
                )
                with self._status_lock:
                    self._status = OcrStatus.COMPLETED
                return result

            # 切换引擎（无障碍无结果 / 异常 / 超时 → 降级 EasyOCR）
            self._logger.warning(
                f"引擎 {engine_name} 未返回有效结果"
                + ("" if engine_name == CaptureEngine.ACCESSIBILITY
                   else "，所有引擎均尝试完毕")
            )
            with self._status_lock:
                self._status = OcrStatus.SWITCHING_ENGINE

        # 全部失败
        self._logger.error("所有引擎均未返回有效结果")
        with self._status_lock:
            self._status = OcrStatus.FAILED
            self._active_engine = self._preferred_engine  # 复位到首选引擎
        return []

    def _try_easyocr(self, image_path: str) -> list:
        """尝试使用 easyocr 识别"""
        try:
            engine = self._get_easyocr()
            if not engine.is_ready:
                self._logger.warning("easyocr 未就绪")
                return []
            return engine.recognize(image_path, timeout=int(self._ocr_timeout))
        except Exception as e:
            self._logger.warning(f"easyocr 尝试失败: {e}")
            return []

    def _try_accessibility(self, image_path: str) -> list:
        """尝试使用无障碍引擎识别"""
        try:
            engine = self._get_accessibility()
            if not engine.is_available:
                self._logger.warning("无障碍引擎不可用")
                return []
            return engine.capture_and_recognize(timeout=int(self._ocr_timeout))
        except Exception as e:
            self._logger.warning(f"无障碍引擎尝试失败: {e}")
            return []

    # ============================================================
    # 完整采集流程
    # ============================================================

    @ExceptionUtil.safe_call(default_return=[], log_level="error")
    def capture_and_recognize(self) -> list:
        """
        完整采集流程：截屏 → 预处理 → OCR 识别

        :return: 识别结果列表
        """
        with self._status_lock:
            self._status = OcrStatus.CAPTURING

        # 第1步：截屏
        raw_path = self.capture_screen()
        if not raw_path:
            self._logger.error("截屏失败，终止采集流程")
            with self._status_lock:
                self._status = OcrStatus.FAILED
            self._last_error = "截屏失败"
            return []

        try:
            # 第2步：预处理
            with self._status_lock:
                self._status = OcrStatus.PREPROCESSING
            preprocessed_path = self.preprocess_image(raw_path)
            if not preprocessed_path:
                self._logger.warning("预处理返回空，使用原图")
                preprocessed_path = raw_path

            # 第3步：OCR 识别
            result = self.recognize(preprocessed_path)

            # 记录结果
            self._last_result = result
            self._last_capture_time = time.time()
            if result:
                self._last_ocr_time = time.time()
                self._last_error = ""

            return result

        finally:
            # 清理临时截图（保留最近的作为调试）
            self._cleanup_old_captures()

    def _cleanup_old_captures(self, keep_count: int = 10):
        """清理旧的截图文件（保留最近 keep_count 张）"""
        try:
            if not os.path.exists(CAPTURE_DIR):
                return

            files = [
                os.path.join(CAPTURE_DIR, f)
                for f in os.listdir(CAPTURE_DIR)
                if f.endswith((".png", ".jpg"))
            ]
            files.sort(key=os.path.getmtime, reverse=True)

            for f in files[keep_count:]:
                safe_delete_file(f)
        except Exception:
            pass

    # ============================================================
    # 轮询采集（后台线程循环调用）
    # ============================================================

    def register_result_callback(self, callback: Callable[[list], None]):
        """
        注册识别结果回调（供上层模块接收结果）

        :param callback: 回调函数(result_list)
        """
        try:
            if callback not in self._result_callbacks:
                self._result_callbacks.append(callback)
        except Exception:
            pass

    def _notify_result(self, result: list):
        """通知所有回调识别结果"""
        for cb in self._result_callbacks:
            try:
                cb(result)
            except Exception:
                pass

    def start_polling(self):
        """
        启动后台轮询采集

        轮询间隔：
          - 默认：500ms
          - 低配机：1000ms
          - 可自定义（通过 config ocr_poll_interval）
        """
        if self._running:
            self._logger.warning("轮询已在运行中")
            return

        self._running = True
        self._stop_event.clear()
        self._poll_thread = threading.Thread(
            target=self._polling_loop, daemon=True
        )
        self._poll_thread.start()
        self._logger.info(f"后台轮询已启动 (间隔={self._poll_interval_ms}ms)")

    def stop_polling(self):
        """停止后台轮询"""
        self._running = False
        self._stop_event.set()
        self._cancel_judge_timer()
        self._logger.info("后台轮询已停止")

    def _polling_loop(self):
        """轮询循环体"""
        while not self._stop_event.is_set():
            try:
                loop_start = time.time()

                # 执行一次完整采集
                result = self.capture_and_recognize()

                # 有结果时通知回调
                if result:
                    self._notify_result(result)

                # 计算下次轮询等待时间（保证间隔稳定）
                elapsed = (time.time() - loop_start) * 1000  # 转毫秒
                wait_ms = max(0, self._poll_interval_ms - elapsed)
                self._stop_event.wait(wait_ms / 1000.0)

            except Exception as e:
                self._logger.error(f"轮询循环异常: {e}")
                self._stop_event.wait(1.0)  # 异常后等待1秒重试

    # ============================================================
    # 订单判定延迟
    # ============================================================

    def schedule_judge(self, on_judge: Callable[[], None]):
        """
        安排订单判定（延迟执行）

        当 OCR 识别到可能的订单信息时，
        等待判定延迟时间后再执行抢单判定。

        :param on_judge: 到时间后执行的判定回调
        """
        try:
            self._cancel_judge_timer()
            self._judge_pending = True

            self._judge_timer = threading.Timer(
                self._order_judge_delay, self._execute_judge, args=[on_judge]
            )
            self._judge_timer.daemon = True
            self._judge_timer.start()

            self._logger.debug(
                f"订单判定已安排 ({self._order_judge_delay}s 后执行)"
            )
        except Exception as e:
            self._logger.error(f"安排订单判定异常: {e}")

    def _execute_judge(self, on_judge: Callable[[], None]):
        """执行订单判定（定时器回调）"""
        try:
            self._judge_pending = False
            if on_judge:
                on_judge()
        except Exception as e:
            self._logger.error(f"执行订单判定异常: {e}")

    def _cancel_judge_timer(self):
        """取消待执行的判定定时器"""
        try:
            if self._judge_timer is not None:
                self._judge_timer.cancel()
                self._judge_timer = None
            self._judge_pending = False
        except Exception:
            pass

    # ============================================================
    # 状态查询
    # ============================================================

    def get_status(self) -> dict:
        """
        获取管理器当前状态（供 UI 展示）

        :return: {
            "status": str,              # OcrStatus
            "active_engine": str,
            "polling_ms": int,
            "ocr_timeout": float,
            "order_judge_delay": float,
            "low_end_mode": bool,
            "running": bool,
            "judge_pending": bool,
            "last_capture_time": float,
            "last_ocr_time": float,
            "last_result_count": int,
            "last_error": str,
        }
        """
        with self._status_lock:
            return {
                "status": self._status,
                "active_engine": self._active_engine,
                "polling_ms": self._poll_interval_ms,
                "ocr_timeout": self._ocr_timeout,
                "order_judge_delay": self._order_judge_delay,
                "low_end_mode": self._low_end_mode,
                "running": self._running,
                "judge_pending": self._judge_pending,
                "last_capture_time": self._last_capture_time,
                "last_ocr_time": self._last_ocr_time,
                "last_result_count": len(self._last_result),
                "last_error": self._last_error,
            }

    def get_last_result(self) -> list:
        """获取最后一次识别结果"""
        return self._last_result

    def get_order_judge_delay(self) -> float:
        """获取订单判定延迟秒数"""
        return self._order_judge_delay

    def set_order_judge_delay(self, delay: float):
        """
        设置订单判定延迟（自定义）

        :param delay: 延迟秒数
        """
        try:
            delay = max(0.5, float(delay))
            self._order_judge_delay = delay
            self._config.set("order_judge_delay", delay)
            self._logger.info(f"订单判定延迟已设为: {delay}s")
        except Exception as e:
            self._logger.error(f"设置判定延迟异常: {e}")

    # ============================================================
    # 配置热更新
    # ============================================================

    def reload_config(self):
        """热重载配置"""
        try:
            self._config.reload()

            # 重新读取配置
            self._poll_interval_ms = safe_int(
                self._config.get("ocr_poll_interval"), DEFAULT_POLL_INTERVAL_MS
            )
            self._ocr_timeout = safe_float(
                self._config.get("ocr_timeout"), OCR_TIMEOUT
            )
            self._image_scale = safe_float(
                self._config.get("ocr_image_scale"), DEFAULT_IMAGE_SCALE
            )
            self._order_judge_delay = safe_float(
                self._config.get("order_judge_delay"), DEFAULT_JUDGE_DELAY
            )
            self._low_end_mode = safe_bool(
                self._config.get("low_end_device"), False
            )

            # 低配机调整间隔
            if self._low_end_mode:
                if self._poll_interval_ms < LOW_END_POLL_INTERVAL_MS:
                    self._poll_interval_ms = LOW_END_POLL_INTERVAL_MS

            self._logger.info("采集配置已热重载")
        except Exception as e:
            self._logger.error(f"配置热重载异常: {e}")

    # ============================================================
    # 清理资源
    # ============================================================

    def cleanup(self):
        """释放所有资源"""
        try:
            self.stop_polling()

            # 等待线程结束
            if self._poll_thread and self._poll_thread.is_alive():
                self._poll_thread.join(timeout=2)

            # 清理旧截图
            self._cleanup_old_captures(keep_count=0)

            # 清理回调
            self._result_callbacks.clear()

            # 释放 easyocr 模型（释放内存）
            if self._easyocr_engine is not None:
                self._easyocr_engine = None
                self._logger.debug("easyocr 引擎已释放")

            self._logger.info("双引擎管理器资源已清理")
        except Exception as e:
            self._logger.error(f"资源清理异常: {e}")


# ============================================================
# 单例快捷访问
# ============================================================

_instance = None
_instance_lock = threading.Lock()


def get_capture_manager() -> CaptureManager:
    """
    获取双引擎采集管理器单例
    :return: CaptureManager 实例
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = CaptureManager()
    return _instance


# ============================================================
# 对外便捷接口（供 main.py / UI 层调用）
# ============================================================

def init_capture() -> dict:
    """
    初始化采集系统（程序入口调用）

    预热 easyocr 模型、检测无障碍引擎可用性。

    :return: 引擎状态字典
    """
    try:
        mgr = get_capture_manager()
        status = mgr.get_status()
        engine_status = mgr.get_engine_status()
        result = {**status, **engine_status}
        LogManager.get_logger("app").info(
            f"采集系统初始化完成: "
            f"engine={result.get('active_engine')}, "
            f"polling={result.get('running')}"
        )
        return result
    except Exception as e:
        LogManager.get_logger("ocr").error(f"初始化采集系统异常: {e}")
        return {"status": "failed", "error": str(e)}


def capture_once_ui() -> list:
    """
    UI 层执行单次完整采集（手动截图识别）
    :return: 识别结果列表
    """
    try:
        mgr = get_capture_manager()
        return mgr.capture_and_recognize()
    except Exception as e:
        LogManager.get_logger("ocr").error(f"UI 单次采集异常: {e}")
        return []


def start_polling_ui():
    """UI 层启动轮询采集"""
    try:
        mgr = get_capture_manager()
        mgr.start_polling()
    except Exception as e:
        LogManager.get_logger("ocr").error(f"UI 启动轮询异常: {e}")


def stop_polling_ui():
    """UI 层停止轮询采集"""
    try:
        mgr = get_capture_manager()
        mgr.stop_polling()
    except Exception as e:
        LogManager.get_logger("ocr").error(f"UI 停止轮询异常: {e}")


def get_capture_status_ui() -> dict:
    """UI 层获取采集状态"""
    try:
        mgr = get_capture_manager()
        return mgr.get_status()
    except Exception as e:
        LogManager.get_logger("ocr").error(f"UI 获取状态异常: {e}")
        return {"status": "error", "error": str(e)}


def set_engine_ui(engine: str):
    """
    UI 层切换优先引擎
    :param engine: "easyocr" 或 "accessibility"
    """
    try:
        mgr = get_capture_manager()
        mgr.set_preferred_engine(engine)
    except Exception as e:
        LogManager.get_logger("ocr").error(f"UI 切换引擎异常: {e}")


def set_judge_delay_ui(delay: float):
    """
    UI 层设置订单判定延迟
    :param delay: 延迟秒数
    """
    try:
        mgr = get_capture_manager()
        mgr.set_order_judge_delay(delay)
    except Exception as e:
        LogManager.get_logger("ocr").error(f"UI 设置判定延迟异常: {e}")


def get_engine_status_ui() -> dict:
    """UI 层获取引擎状态"""
    try:
        mgr = get_capture_manager()
        return mgr.get_engine_status()
    except Exception as e:
        LogManager.get_logger("ocr").error(f"UI 获取引擎状态异常: {e}")
        return {}


def warmup_engine_ui() -> bool:
    """
    UI 层预热 OCR 引擎

    供 main.py 在启动阶段调用，确保 capture 模块引擎已就绪。
    EasyOcrEngine 内部有锁保护，重复调用安全。

    :return: True=引擎已就绪, False=加载失败
    """
    try:
        mgr = get_capture_manager()
        engine = mgr.get_engine("easyocr")
        if engine:
            return engine.warmup()
        return False
    except Exception as e:
        LogManager.get_logger("ocr").error(f"UI 预热引擎异常: {e}")
        return False


def shutdown_engine_ui():
    """
    UI 层关闭 OCR 引擎，释放资源

    供 main.py 在退出时调用。
    """
    try:
        mgr = get_capture_manager()
        engine = mgr.get_engine("easyocr")
        if engine:
            engine.shutdown()
    except Exception as e:
        LogManager.get_logger("ocr").error(f"UI 关闭引擎异常: {e}")