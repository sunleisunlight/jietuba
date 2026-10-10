# -*- coding: utf-8 -*-
"""history.sqlite 的读取过滤。

「继续标注」列表只该出现"真的画过东西"的截图：零标注的记录点进去也无事可做，
混在列表里只会让人以为点错了。这里守两件事：

- 零标注且未收藏的记录不进列表、也不进计数（列表数字和列表内容必须是同一个口径）；
- 已收藏的零标注记录仍然保留——用户显式收藏过就说明他想留着；
- 数据层留了逃生口（annotated_only=False），需要全量时拿得到。
"""
from pathlib import Path

from history.models import STATUS_READY
from history.repository import HistoryRepository, build_record


def _repo(tmp_path) -> HistoryRepository:
    repo = HistoryRepository(tmp_path / "history.sqlite")
    repo.initialize()
    return repo


def _add(repo, history_id, *, annotations, favorite=False, updated_at=1000.0):
    record = build_record(
        history_id,
        folder=Path(repo.db_path).parent / history_id,
        created_at=updated_at,
        source_size=(10, 10),
        virtual_rect=(0, 0, 10, 10),
        status=STATUS_READY,
    )
    record.annotation_count = annotations
    record.favorite = favorite
    record.updated_at = updated_at
    repo.insert(record)


def test_unannotated_screenshots_stay_out_of_the_list(tmp_path):
    repo = _repo(tmp_path)
    _add(repo, "annotated", annotations=2, updated_at=3.0)
    _add(repo, "empty", annotations=0, updated_at=2.0)
    _add(repo, "newer-empty", annotations=0, updated_at=4.0)

    assert [r.id for r in repo.list_records()] == ["annotated"]
    assert repo.count() == 1


def test_favorited_records_survive_even_without_annotations(tmp_path):
    repo = _repo(tmp_path)
    _add(repo, "favorite-empty", annotations=0, favorite=True, updated_at=2.0)
    _add(repo, "empty", annotations=0, updated_at=3.0)

    assert [r.id for r in repo.list_records()] == ["favorite-empty"]
    assert repo.count() == 1


def test_the_raw_query_can_still_ask_for_everything(tmp_path):
    """数据层的逃生口：显式关掉筛选时仍然拿得到全部记录。"""
    repo = _repo(tmp_path)
    _add(repo, "empty", annotations=0)

    assert [r.id for r in repo.list_records(annotated_only=False)] == ["empty"]
    assert repo.count(annotated_only=False) == 1
