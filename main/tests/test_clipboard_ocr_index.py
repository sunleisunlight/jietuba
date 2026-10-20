"""Offline OCR indexing and real Rust database schema/search regressions."""
import sqlite3
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage
from clipboard.services.ocr_index_service import _OcrWorker, OcrIndexService


@pytest.mark.parametrize("result,expected", [
    ({"code": -1, "data": []}, []),
    ({"code": 100, "data": []}, [("image", "")]),
    ({"code": 100, "data": [{"text": "测试 Hello 123"}]}, [("image", "测试 Hello 123")]),
])
def test_failed_recognition_is_retryable(qapp, monkeypatch, result, expected):
    image = QImage(10, 10, QImage.Format_RGB32)
    image.fill(0xFFFFFFFF)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, "PNG")
    updates = []
    manager = SimpleNamespace(get_image_data=lambda image_id: bytes(buffer.data()),
                              update_ocr_text=lambda *args: updates.append(args) or 1)
    worker = _OcrWorker(manager)
    monkeypatch.setattr(worker, "_ensure_engine", lambda: True)
    monkeypatch.setattr("ocr.ocr_manager.recognize_text", lambda *a, **kw: result)
    worker._recognize_and_store("image")
    assert updates == expected


def test_queue_deduplicates_and_unavailable_start_can_retry(qapp):
    manager = SimpleNamespace(is_available=False)
    service = OcrIndexService(manager)
    service.start()
    assert not service._started
    worker = _OcrWorker(manager)
    worker.enqueue("one")
    worker.enqueue("one")
    worker.enqueue("two")
    assert [worker._pop_queue(), worker._pop_queue(), worker._pop_queue()] == ["one", "two", None]


def test_rust_image_search_and_existing_database_migration(tmp_path):
    import pyclipboard
    path = str(tmp_path / "history.db")
    native = pyclipboard.ClipboardManager(path)
    text_id = native.add_item("ordinary content", "text", "task3-title")
    image_id = native.add_item("synthetic image", "image", "sample")
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE clipboard SET image_id='synthetic-id' WHERE id=?", (image_id,))
    assert native.get_pending_ocr_images(10) == ["synthetic-id"]
    assert native.update_ocr_text("synthetic-id", "截图测试 Hello 123") == 1
    assert native.get_pending_ocr_images(10) == []
    assert native.get_history(search="Hello")[0].id == image_id
    assert native.get_history(search="task3-title")[0].id == text_id
    del native
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE clipboard DROP COLUMN ocr_text")
    reopened = pyclipboard.ClipboardManager(path)
    assert reopened.get_history(search="ordinary")[0].id == text_id
    assert reopened.get_pending_ocr_images(10) == ["synthetic-id"]
