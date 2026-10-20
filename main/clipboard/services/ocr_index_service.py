# -*- coding: utf-8 -*-
"""
剪贴板图片 OCR 索引服务

后台线程为图片历史建立 OCR 文本索引：
- 新复制的截图入库后优先识别；
- 历史图片分批补录，节流运行，避免占用前台 CPU；
- 识别结果写入 clipboard.ocr_text（由 pyclipboard 落库），
  搜索时与正文、标题一起匹配。

QImage 可以在非 GUI 线程创建/读取；ppocr_rust 的 recognize 会释放 GIL，
识别过程不会卡住主界面。
"""

import threading
from typing import List, Optional, Set

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QImage

from core.logger import T, log_debug, log_exception, log_info

from ..core import ClipboardManager


# 每轮历史补录的批量大小与批间休眠（秒）
_BACKFILL_BATCH = 5
_BACKFILL_IDLE_SECONDS = 8


class _OcrWorker(QThread):
    """串行执行 OCR 任务的工作线程。"""

    processed = Signal(str, int)  # (image_id, 更新条数)

    def __init__(self, manager: ClipboardManager, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._manager = manager
        self._queue: List[str] = []
        self._queued: Set[str] = set()
        self._queue_lock = threading.Lock()
        self._wakeup = threading.Event()
        self._stop_flag = False
        self._engine_ready = False

    def enqueue(self, image_id: str):
        if not image_id:
            return
        with self._queue_lock:
            if image_id in self._queued:
                return
            self._queued.add(image_id)
            self._queue.append(image_id)
        self._wakeup.set()

    def stop(self):
        self._stop_flag = True
        self._wakeup.set()

    def run(self):
        while not self._stop_flag:
            image_id = self._pop_queue()
            if image_id is not None:
                self._recognize_and_store(image_id)
                # 新图连续处理，每张之间稍微喘息
                self._interruptible_wait(0.5)
                continue

            # 队列空闲：补录历史图片
            backfill = self._safe_get_pending()
            if not backfill:
                # 没有待处理图片，等待新图唤醒；每 10 分钟兜底醒一次
                self._interruptible_wait(600)
                continue
            for pending_id in backfill[:_BACKFILL_BATCH]:
                if self._stop_flag:
                    break
                self._recognize_and_store(pending_id)
                self._interruptible_wait(1.0)
            # 一批补录结束，休眠让出 CPU
            self._interruptible_wait(_BACKFILL_IDLE_SECONDS)

    def _pop_queue(self) -> Optional[str]:
        with self._queue_lock:
            if not self._queue:
                return None
            image_id = self._queue.pop(0)
            self._queued.discard(image_id)
            return image_id

    def _interruptible_wait(self, seconds: float):
        """可被新图入队/停止打断的等待。"""
        self._wakeup.wait(timeout=seconds)
        self._wakeup.clear()

    def _safe_get_pending(self) -> List[str]:
        try:
            return self._manager.get_pending_ocr_images(limit=_BACKFILL_BATCH)
        except Exception as e:
            log_exception(e, T("获取待 OCR 历史图片"))
            return []

    def _ensure_engine(self) -> bool:
        if self._engine_ready:
            return True
        try:
            from ocr.ocr_manager import OCRManager

            manager = OCRManager()
            # pp 版打包只携带 ppocr_rust，显式指定避免走系统 OCR 分支
            if manager.initialize(engine_type=OCRManager.ENGINE_PP_RUST):
                self._engine_ready = True
                return True
        except Exception as e:
            log_exception(e, T("初始化剪贴板 OCR 索引引擎"))
        return False

    def _recognize_and_store(self, image_id: str):
        """识别一张图并把文本落库。任何失败都不抛到线程外。"""
        try:
            image_data = self._manager.get_image_data(image_id)
            if not image_data:
                return

            image = QImage.fromData(image_data)
            if image.isNull():
                log_debug(T("OCR 索引：图片数据无法解码 {image_id}", image_id=image_id), "Clipboard")
                return

            if not self._ensure_engine():
                # 引擎不可用（如模型文件缺失）：本轮放弃，等待下次唤醒重试，
                # 不写入空串，避免把"没识别"误标成"已识别"。
                return

            from ocr.ocr_manager import recognize_text

            # dict distinguishes successful empty recognition from inference failure.
            result = recognize_text(image, return_format="dict")
            if not isinstance(result, dict) or result.get("code") != 100:
                log_debug(T("OCR 索引识别失败，保留待重试状态"), "Clipboard")
                return
            lines = []
            for item in result.get("data", []):
                text = item.get("text", "")
                if text.strip():
                    lines.append(text.strip())
            ocr_text = "\n".join(lines).strip()

            affected = self._manager.update_ocr_text(image_id, ocr_text)
            if affected:
                self.processed.emit(image_id, affected)
                if ocr_text:
                    preview = ocr_text.replace("\n", " ")[:40]
                    log_debug(T("OCR 索引已更新 {image_id}: {preview}", image_id=image_id, preview=preview), "Clipboard")
        except Exception as e:
            log_exception(e, T("剪贴板图片 OCR 索引失败"))


class OcrIndexService(QObject):
    """图片 OCR 索引服务（单例）：管理工作线程生命周期。"""

    _instance: Optional["OcrIndexService"] = None
    _instance_lock = threading.Lock()

    def __init__(self, manager: Optional[ClipboardManager] = None):
        super().__init__()
        self._manager = manager or ClipboardManager()
        self._worker: Optional[_OcrWorker] = None
        self._started = False

    @classmethod
    def instance(cls, manager: Optional[ClipboardManager] = None) -> "OcrIndexService":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls(manager)
        return cls._instance

    def start(self):
        """启动后台索引（幂等）。"""
        if self._started:
            return
        if not self._manager.is_available:
            return
        try:
            self._started = True
            self._worker = _OcrWorker(self._manager)
            self._worker.start()
            log_info(T("剪贴板图片 OCR 索引服务已启动"), "Clipboard")
        except Exception as e:
            log_exception(e, T("启动 OCR 索引服务"))
            self._started = False

    def enqueue_image(self, image_id: Optional[str]):
        """新图片入库后调用，优先识别。回调在入库事务完成后触发，无需延迟。"""
        if not image_id or not self._started or self._worker is None:
            return
        self._worker.enqueue(image_id)

    def shutdown(self):
        if self._worker is not None:
            self._worker.stop()
            # 单张截图 OCR 可能耗时数秒，给足时间让线程退出
            if not self._worker.wait(10000):
                # Retain a running QThread; destroying it aborts the process.
                log_info(T("OCR 索引仍在结束当前识别，请稍后重试退出"), "Clipboard")
                return
            self._worker = None
        self._started = False


__all__ = ["OcrIndexService"]
