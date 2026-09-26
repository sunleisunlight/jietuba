"""历史记录的后台任务线程。

只做一件事：按提交顺序串行执行 callable。图片编码、PNG 写盘、JSON 写盘、
SQLite 写都放在这里，截图 UI 与列表 UI 都不必等磁盘。

任务 callable 自己持有它需要的数据引用。比如 source.png 的写入任务闭包持有
那份 QImage——QImage 是隐式共享的引用计数对象，只要还有一份活引用，底层像素
就不会随截图会话销毁而释放，所以会话 teardown 之后任务照样安全。
"""

import queue
import traceback

from PySide6.QtCore import QThread

from core.logger import log_debug, log_error, T


class HistoryWorker(QThread):
    """串行执行提交上来的任务。"""

    def __init__(self, repository, parent=None):
        super().__init__(parent)
        self._repository = repository
        self._queue: "queue.Queue" = queue.Queue()
        self._stopped = False
        self.setObjectName("HistoryWorker")

    def submit(self, task):
        """把 callable 排进后台队列；线程已停止时安静丢弃。"""
        if self._stopped or task is None:
            return
        self._queue.put(task)

    def run(self):
        while True:
            task = self._queue.get()
            if task is None:
                break
            try:
                task()
            except Exception as e:
                # 历史是增强功能：单条任务失败必须留下明确日志，但不能把线程打死
                log_error(T("历史后台任务失败: {error}", error=str(e)), "History")
                log_debug(traceback.format_exc(), "History")
        # 线程退出前收掉自己的数据库连接
        try:
            self._repository.close_current_thread()
        except Exception:
            pass

    def shutdown(self, timeout_ms: int = 5000):
        """请求停止并等待队列排空（已提交的写盘任务不会被半途丢弃）。"""
        if self._stopped:
            return
        self._stopped = True
        self._queue.put(None)
        if self.isRunning():
            self.wait(timeout_ms)
        log_debug(T("历史后台线程已停止"), "History")