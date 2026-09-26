"""history.sqlite 的读写（只存索引/元数据，图片与 state.json 一律放文件）。

线程模型：SQLite 连接不跨线程复用。每个线程第一次用到时各自建一条连接
（threading.local），WAL 模式让"后台写 + 主线程读"互不阻塞。
"""

import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

from core.logger import log_debug, log_exception, T

from .models import (
    SCHEMA_VERSION, SOURCE_SCREENSHOT, STATUS_DRAFT,
    HistoryRecord,
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id                TEXT PRIMARY KEY,
    source_type       TEXT    NOT NULL DEFAULT 'screenshot',
    created_at        REAL    NOT NULL DEFAULT 0,
    updated_at        REAL    NOT NULL DEFAULT 0,
    source_path       TEXT    NOT NULL DEFAULT '',
    state_path        TEXT    NOT NULL DEFAULT '',
    preview_path      TEXT    NOT NULL DEFAULT '',
    source_width      INTEGER NOT NULL DEFAULT 0,
    source_height     INTEGER NOT NULL DEFAULT 0,
    virtual_x         REAL    NOT NULL DEFAULT 0,
    virtual_y         REAL    NOT NULL DEFAULT 0,
    virtual_width     REAL    NOT NULL DEFAULT 0,
    virtual_height    REAL    NOT NULL DEFAULT 0,
    selection_x       REAL    NOT NULL DEFAULT 0,
    selection_y       REAL    NOT NULL DEFAULT 0,
    selection_width   REAL    NOT NULL DEFAULT 0,
    selection_height  REAL    NOT NULL DEFAULT 0,
    annotation_count  INTEGER NOT NULL DEFAULT 0,
    favorite          INTEGER NOT NULL DEFAULT 0,
    status            TEXT    NOT NULL DEFAULT 'draft',
    schema_version    INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_history_updated  ON history(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_history_favorite ON history(favorite, updated_at DESC);
"""


class HistoryRepository:
    """history.sqlite 的 CRUD。所有方法都可能在任意线程调用。"""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._local = threading.local()

    # ------------------------------------------------------------------
    # 连接
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(_SCHEMA)
            conn.commit()
        except Exception:
            conn.close()
            raise
        self._local.conn = conn
        return conn

    def close_current_thread(self):
        """关闭当前线程的连接（线程退出前调用）。"""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception as e:
                log_exception(e, T("关闭历史数据库连接"))
            self._local.conn = None

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------

    def insert(self, record: HistoryRecord):
        conn = self._connect()
        with conn:  # 事务：要么整行写入，要么什么都不留
            conn.execute(
                """
                INSERT OR REPLACE INTO history (
                    id, source_type, created_at, updated_at,
                    source_path, state_path, preview_path,
                    source_width, source_height,
                    virtual_x, virtual_y, virtual_width, virtual_height,
                    selection_x, selection_y, selection_width, selection_height,
                    annotation_count, favorite, status, schema_version
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    record.id, record.source_type, record.created_at, record.updated_at,
                    record.source_path, record.state_path, record.preview_path,
                    int(record.source_width), int(record.source_height),
                    float(record.virtual_x), float(record.virtual_y),
                    float(record.virtual_width), float(record.virtual_height),
                    float(record.selection_x), float(record.selection_y),
                    float(record.selection_width), float(record.selection_height),
                    int(record.annotation_count), record.favorite_int,
                    record.status, int(record.schema_version),
                ),
            )

    def update_meta(self, history_id: str, **fields):
        """局部更新元数据；未知字段直接忽略，不制造 SQL 注入面。"""
        allowed = {
            "updated_at", "preview_path", "state_path",
            "selection_x", "selection_y", "selection_width", "selection_height",
            "annotation_count", "favorite", "status", "source_width",
            "source_height",
        }
        payload = {k: v for k, v in fields.items() if k in allowed}
        if not payload:
            return
        assignments = ", ".join(f"{k} = ?" for k in payload)
        conn = self._connect()
        with conn:
            conn.execute(
                f"UPDATE history SET {assignments} WHERE id = ?",
                (*payload.values(), history_id),
            )

    def set_favorite(self, history_id: str, favorite: bool):
        conn = self._connect()
        with conn:
            conn.execute(
                "UPDATE history SET favorite = ? WHERE id = ?",
                (1 if favorite else 0, history_id),
            )

    def delete(self, history_id: str):
        conn = self._connect()
        with conn:
            conn.execute("DELETE FROM history WHERE id = ?", (history_id,))

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------

    def get(self, history_id: str) -> Optional[HistoryRecord]:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM history WHERE id = ?", (history_id,)
        ).fetchone()
        return HistoryRecord.from_row(row) if row is not None else None

    def list_records(
        self,
        *,
        source_type: Optional[str] = None,
        favorite_only: bool = False,
        offset: int = 0,
        limit: int = 60,
    ) -> List[HistoryRecord]:
        """按 updated_at DESC 分页取元数据（列表只读这一份，不碰大图）。"""
        where = []
        params: list = []
        if source_type:
            where.append("source_type = ?")
            params.append(source_type)
        if favorite_only:
            where.append("favorite = 1")
        clause = f"WHERE {' AND '.join(where)}" if where else ""

        conn = self._connect()
        rows = conn.execute(
            f"""
            SELECT * FROM history
            {clause}
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (*params, max(1, int(limit)), max(0, int(offset))),
        ).fetchall()
        return [HistoryRecord.from_row(row) for row in rows]

    def count(self, *, source_type: Optional[str] = None,
              favorite_only: bool = False) -> int:
        where = []
        params: list = []
        if source_type:
            where.append("source_type = ?")
            params.append(source_type)
        if favorite_only:
            where.append("favorite = 1")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        conn = self._connect()
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM history {clause}", tuple(params)
        ).fetchone()
        return int(row["n"]) if row is not None else 0

    def list_unfinished_drafts(self) -> List[HistoryRecord]:
        """上次异常退出可能留下的、还没确认选区的草稿。"""
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM history WHERE status = ? ORDER BY created_at ASC",
            (STATUS_DRAFT,),
        ).fetchall()
        return [HistoryRecord.from_row(row) for row in rows]

    def total_storage_bytes(self) -> int:
        """索引里所有 source.png / state.json / preview.jpg 的字节总和。

        只统计已知路径，不遍历目录——遍历在记录很多时要扫大量 inode，
        而这里要回答的只是"历史占了多少空间"。
        """
        conn = self._connect()
        rows = conn.execute(
            "SELECT source_path, state_path, preview_path FROM history"
        ).fetchall()
        total = 0
        for row in rows:
            for key in ("source_path", "state_path", "preview_path"):
                path = row[key]
                if not path:
                    continue
                try:
                    total += Path(path).stat().st_size
                except OSError:
                    continue
        return total

    def initialize(self):
        """显式建表，供启动时预检。"""
        self._connect()
        log_debug(T("历史数据库就绪: {path}", path=str(self.db_path)), "History")


def _rect_tuple(value, default=(0.0, 0.0, 0.0, 0.0)):
    """把 QRectF/QRect 或 (x, y, w, h) 统一成四元组。"""
    if value is None:
        return default
    for attr in ("x", "y", "width", "height"):
        if hasattr(value, attr):
            try:
                return (float(value.x()), float(value.y()),
                        float(value.width()), float(value.height()))
            except Exception:
                return default
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        try:
            return (float(value[0]), float(value[1]),
                    float(value[2]), float(value[3]))
        except (TypeError, ValueError):
            return default
    return default


def build_record(
    history_id: str,
    *,
    folder: Path,
    created_at: float,
    source_size,
    virtual_rect,
    selection_rect=None,
    status: str = STATUS_DRAFT,
    source_type: str = SOURCE_SCREENSHOT,
) -> HistoryRecord:
    """按固定的目录结构拼出一条记录。"""
    selection = _rect_tuple(selection_rect)
    virtual = _rect_tuple(virtual_rect)
    return HistoryRecord(
        id=history_id,
        source_type=source_type,
        created_at=float(created_at),
        updated_at=float(created_at),
        source_path=str(folder / "source.png"),
        state_path=str(folder / "state.json"),
        preview_path=str(folder / "preview.jpg"),
        source_width=int(source_size[0]),
        source_height=int(source_size[1]),
        virtual_x=virtual[0],
        virtual_y=virtual[1],
        virtual_width=virtual[2],
        virtual_height=virtual[3],
        selection_x=selection[0],
        selection_y=selection[1],
        selection_width=selection[2],
        selection_height=selection[3],
        annotation_count=0,
        favorite=False,
        status=status,
        schema_version=SCHEMA_VERSION,
    )