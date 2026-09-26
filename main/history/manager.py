"""历史会话的生命周期管理。

对外只暴露"业务语义"的操作（开始一次会话、写一份工程状态、继续某条历史、
删除、收藏），把文件 IO、图片编码、SQLite 都交给后台线程。业务窗口不直接
碰 sqlite3、不直接拼路径、不直接 encode 图片。

磁盘结构（base_dir 由 QStandardPaths / 项目 AppData 规则给出）：

    <AppData>/History/
    ├── history.sqlite
    └── <history_id>/
        ├── source.png    完整纯净虚拟桌面母片（一条历史只写一次）
        ├── state.json    工程状态（选区 + 全部矢量标注）
        └── preview.jpg   列表缩略图（背景 + 当前标注的扁平预览）
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QImage

from core.constants import get_app_data_dir
from core.logger import log_debug, log_info, log_warning, T

from .models import (
    SCHEMA_VERSION, STATUS_DRAFT, STATUS_READY, HistoryRecord,
)
from .repository import HistoryRepository, build_record
from .worker import HistoryWorker


# 缩略图最大边。列表卡片只需这么大，再大就是白占内存与磁盘。
PREVIEW_MAX_EDGE = 640

# 上一次进程遗留的 draft 至少要"这么旧"才会被启动清理删掉，避免误伤本次
# 进程刚建出来、还没来得及确认选区的记录。
_STALE_DRAFT_MIN_AGE = 30.0


class HistoryManager(QObject):
    """历史会话中枢（进程内单例）。"""

    _instance: Optional["HistoryManager"] = None

    @classmethod
    def instance(cls) -> "HistoryManager":
        if cls._instance is None:
            cls._instance = HistoryManager()
        return cls._instance

    def __init__(self, base_dir: Optional[Path] = None):
        super().__init__()
        self.base_dir = Path(base_dir) if base_dir else (get_app_data_dir() / "History")
        self.repository = HistoryRepository(self.base_dir / "history.sqlite")
        self._worker = HistoryWorker(self.repository)
        self._worker.start()
        self._drafts_cleaned = False
        log_info(T("历史存储目录: {path}", path=str(self.base_dir)), "History")

    # ==================================================================
    # 会话生命周期
    # ==================================================================

    def begin_session(self, image: QImage, rect) -> Optional[str]:
        """开始一次截图会话：立即把完整桌面母片交给后台保存。

        主线程只做三件轻量事——生成 id、建目录、写一行索引；PNG 编码与写盘
        全部排在后台队列里，截图 UI 不会因为要落盘而卡住。

        Returns:
            history_id；初始化失败时返回 None（历史不可用，但截图照常进行）。
        """
        if image is None or image.isNull():
            return None
        try:
            history_id = uuid.uuid4().hex
            folder = self.base_dir / history_id
            folder.mkdir(parents=True, exist_ok=True)

            now = time.time()
            record = build_record(
                history_id,
                folder=folder,
                created_at=now,
                source_size=(image.width(), image.height()),
                virtual_rect=(rect.x(), rect.y(), rect.width(), rect.height()),
                status=STATUS_DRAFT,
            )

            # 顺序要紧：上一次异常退出留下的草稿清理必须排在本条记录之前，
            # 否则刚建出来的 draft 会被当成"陈旧草稿"一起删掉。
            if not self._drafts_cleaned:
                self._drafts_cleaned = True
                self._worker.submit(self._cleanup_stale_drafts)

            self._worker.submit(lambda: self.repository.insert(record))

            # QImage 是隐式共享的引用计数对象：这里持有的是同一份像素的另一份
            # 引用，后台任务没跑完之前底层缓冲不会被释放，因此截图会话 teardown
            # 之后写盘依然安全，也不必先复制一份 8MB 出来。
            image_ref = QImage(image)
            source_path = record.source_path

            def _save_source():
                if not image_ref.save(source_path, "PNG"):
                    raise RuntimeError(f"PNG 写入失败: {source_path}")

            self._worker.submit(_save_source)

            return history_id
        except Exception as e:
            log_warning(T("创建历史会话失败: {error}", error=str(e)), "History")
            return None

    def persist(self, history_id: Optional[str], state: dict,
                preview_image: Optional[QImage] = None, *,
                status: Optional[str] = None) -> bool:
        """写入一份工程状态（state.json + preview.jpg + 索引元数据）。

        调用方负责节流；这里假定调用本身已经是一次"值得落盘"的变更。
        返回是否成功排队（不影响截图主流程，失败只记日志）。
        """
        if not history_id:
            return False
        try:
            folder = self.base_dir / history_id
            if not folder.is_dir():
                log_warning(T("历史目录不存在，跳过保存: {history_id}",
                              history_id=history_id), "History")
                return False

            payload = dict(state or {})
            payload.setdefault("schema_version", SCHEMA_VERSION)
            annotations = payload.get("annotations") or []
            selection = payload.get("selection") or {}

            state_path = folder / "state.json"
            preview_path = folder / "preview.jpg"

            self._worker.submit(
                lambda: _write_json_atomic(state_path, payload)
            )

            preview_ref = None
            if preview_image is not None and not preview_image.isNull():
                preview_ref = _scaled_preview(preview_image)
                if preview_ref is not None and not preview_ref.isNull():
                    self._worker.submit(
                        lambda: preview_ref.save(str(preview_path), "JPG", 82)
                    )
                else:
                    preview_ref = None

            now = time.time()
            fields = {
                "updated_at": now,
                "annotation_count": len(annotations),
                "selection_x": float(selection.get("x", 0.0) or 0.0),
                "selection_y": float(selection.get("y", 0.0) or 0.0),
                "selection_width": float(selection.get("width", 0.0) or 0.0),
                "selection_height": float(selection.get("height", 0.0) or 0.0),
            }
            if preview_ref is not None:
                fields["preview_path"] = str(preview_path)
            if status:
                fields["status"] = status

            history_id_ref = history_id
            self._worker.submit(
                lambda: self.repository.update_meta(history_id_ref, **fields)
            )
            return True
        except Exception as e:
            # 历史是增强功能：磁盘满 / 权限错误都不能影响正常截图
            log_warning(T("保存历史状态失败: {error}", error=str(e)), "History")
            return False

    def mark_ready(self, history_id: Optional[str]):
        """把这条历史从 draft 提升为有效记录。"""
        if not history_id:
            return
        self._worker.submit(
            lambda: self.repository.update_meta(history_id, status=STATUS_READY)
        )

    def discard(self, history_id: Optional[str]):
        """丢弃一条从未确认过选区的草稿（文件 + 索引一起清）。"""
        if not history_id:
            return
        log_debug(T("丢弃未确认的历史草稿: {history_id}", history_id=history_id), "History")

        def _discard():
            self._remove_record_files(history_id)
            self.repository.delete(history_id)

        self._worker.submit(_discard)

    def delete(self, history_id: str) -> bool:
        """彻底删除一条历史（索引 + source/state/preview + 目录）。"""
        if not history_id:
            return False

        def _delete():
            self._remove_record_files(history_id)
            self.repository.delete(history_id)

        try:
            self._worker.submit(_delete)
            return True
        except Exception as e:
            log_warning(T("删除历史失败: {error}", error=str(e)), "History")
            return False

    def set_favorite(self, history_id: str, favorite: bool):
        self._worker.submit(
            lambda: self.repository.set_favorite(history_id, bool(favorite))
        )

    # ==================================================================
    # 读取
    # ==================================================================

    def get_record(self, history_id: str) -> Optional[HistoryRecord]:
        try:
            return self.repository.get(history_id)
        except Exception as e:
            log_warning(T("读取历史记录失败: {error}", error=str(e)), "History")
            return None

    def list_records(self, *, source_type: Optional[str] = None,
                     favorite_only: bool = False,
                     offset: int = 0, limit: int = 60) -> List[HistoryRecord]:
        try:
            return self.repository.list_records(
                source_type=source_type, favorite_only=favorite_only,
                offset=offset, limit=limit,
            )
        except Exception as e:
            log_warning(T("读取历史列表失败: {error}", error=str(e)), "History")
            return []

    def count(self, *, source_type: Optional[str] = None,
              favorite_only: bool = False) -> int:
        try:
            return self.repository.count(
                source_type=source_type, favorite_only=favorite_only
            )
        except Exception as e:
            log_warning(T("统计历史数量失败: {error}", error=str(e)), "History")
            return 0

    def load_state(self, history_id: str) -> Optional[dict]:
        """读取 state.json；缺失或损坏返回 None（调用方据此提示"历史不可用"）。"""
        record = self.get_record(history_id)
        if record is None:
            return None
        path = Path(record.state_path)
        if not path.is_file():
            log_warning(T("历史状态文件缺失: {path}", path=str(path)), "History")
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("state.json 根节点不是对象")
            return data
        except Exception as e:
            log_warning(T("解析历史状态失败: {error}", error=str(e)), "History")
            return None

    def load_source_image(self, history_id: str) -> Optional[QImage]:
        """加载历史母片（只在用户真的点了"继续标注"时调用）。"""
        record = self.get_record(history_id)
        if record is None:
            return None
        path = Path(record.source_path)
        if not path.is_file():
            log_warning(T("历史母片缺失: {path}", path=str(path)), "History")
            return None
        image = QImage(str(path))
        if image.isNull():
            log_warning(T("历史母片无法读取: {path}", path=str(path)), "History")
            return None
        return image

    def get_total_storage_size(self) -> int:
        """历史占用的磁盘空间（字节）。设置页以后可以用它展示占用。"""
        try:
            return self.repository.total_storage_bytes()
        except Exception as e:
            log_warning(T("统计历史占用空间失败: {error}", error=str(e)), "History")
            return 0

    # ==================================================================
    # 收尾
    # ==================================================================

    def shutdown(self):
        """应用退出：等后台写盘任务排空再收线程。"""
        try:
            self._worker.shutdown()
        except Exception as e:
            log_warning(T("停止历史后台线程失败: {error}", error=str(e)), "History")
        try:
            self.repository.close_current_thread()
        except Exception:
            pass

    # ==================================================================
    # 内部
    # ==================================================================

    def _remove_record_files(self, history_id: str):
        folder = self.base_dir / history_id
        try:
            if folder.is_dir():
                shutil.rmtree(folder, ignore_errors=False)
        except Exception as e:
            log_warning(T("删除历史目录失败: {error}", error=str(e)), "History")
        # 目录已被单独删掉时，顺手清干净可能残留的单文件
        for name in ("source.png", "state.json", "preview.jpg"):
            try:
                (folder / name).unlink(missing_ok=True)
            except Exception:
                pass

    def _cleanup_stale_drafts(self):
        """启动后清理上次异常退出留下的、未确认选区的草稿。

        只看 status=draft 的记录：正常流程里选区一确认就转成 ready，所以这里
        剩下的基本是"截图刚开始就被关掉/崩掉"的误触记录。source.png 完整与否
        都删——它没有选区，恢复出来也只是完整桌面全图，留着只会污染历史列表。

        再加一道时间保险：只清创建于 `_STALE_DRAFT_MIN_AGE` 之前的记录。本次
        进程刚建出来的 draft 绝不会被这条清理误伤，即便将来有人把清理挪到
        建记录之后也不会有问题。
        """
        try:
            drafts = self.repository.list_unfinished_drafts()
        except Exception as e:
            log_debug(T("扫描历史草稿失败: {error}", error=str(e)), "History")
            return
        cutoff = time.time() - _STALE_DRAFT_MIN_AGE
        for record in drafts:
            if float(record.created_at or 0.0) > cutoff:
                continue
            try:
                self._remove_record_files(record.id)
                self.repository.delete(record.id)
                log_debug(T("已清理历史草稿: {history_id}", history_id=record.id), "History")
            except Exception as e:
                log_debug(T("清理历史草稿失败: {error}", error=str(e)), "History")


def _write_json_atomic(path: Path, payload: dict):
    """先写临时文件再原子替换：中途崩掉不会留下半截 JSON。

    state.json 被截断就等于这条历史打不开，而它是每次编辑都会重写的热文件。
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _scaled_preview(image: QImage) -> Optional[QImage]:
    """把选区合成图缩到缩略图尺寸（最大边 PREVIEW_MAX_EDGE）。"""
    try:
        if image.width() <= PREVIEW_MAX_EDGE and image.height() <= PREVIEW_MAX_EDGE:
            return QImage(image)
        return image.scaled(
            PREVIEW_MAX_EDGE, PREVIEW_MAX_EDGE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    except Exception as e:
        log_warning(T("生成历史缩略图失败: {error}", error=str(e)), "History")
        return None


def get_history_manager() -> HistoryManager:
    """模块级取单例，业务代码统一用这个入口。"""
    return HistoryManager.instance()


def shutdown_history_manager():
    """退出时收尾。

    不在退出路径上新建实例：如果整个进程从来没用过历史（比如用户没截过图），
    这里就不该为了"关闭"去起一个后台线程。
    """
    manager = HistoryManager._instance
    if manager is not None:
        manager.shutdown()