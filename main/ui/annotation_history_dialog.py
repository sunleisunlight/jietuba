# -*- coding: utf-8 -*-
"""标注历史窗口（继续标注）。

截图状态下按 H 打开本窗口：展示积磊截图保存过的截图工程，点一条就把那一刻
的完整虚拟桌面重新载入 ScreenshotWindow 继续编辑（重新选区、增删改标注、
OCR / 翻译 / 保存 / 复制 / 钉图 全都照旧）。

两条硬约束：
- 列表只读索引元数据 + preview.jpg，一张卡片绝不加载全分辨率 source.png；
  几百上千条历史才不会把内存吃光。
- 分页加载（每批 PAGE_SIZE 条），滚到底再取下一批。
"""

import os
from collections import OrderedDict
from datetime import datetime

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from core.i18n import make_tr
from core.logger import log_debug, log_exception, T
from core.ui_scale import dialog_scaled, scale_dialog_font
from ui.dialogs import show_confirm_dialog, show_warning_dialog
from ui.fluent_lite import SegmentedWidget
from ui.fluent_lite.theme import scrollbar_qss, ui_tokens

_tr = make_tr("AnnotationHistory")


# 一页多少条。太小会频繁查库，太大则一次性创建过多卡片。
PAGE_SIZE = 60
# 缩略图缓存上限（缓存的是已经缩到卡片大小的 pixmap，不是 640px 原图）
_THUMB_CACHE_LIMIT = 300
_THUMB_CACHE = OrderedDict()

CARD_WIDTH = 200
CARD_HEIGHT = 200
PREVIEW_WIDTH = 176
PREVIEW_HEIGHT = 116

# 来源类型 → 展示名（第一版只有截图；导入 / 剪贴来源已在数据模型里预留）
_SOURCE_LABELS = {
    "screenshot": "截图",
    "import": "导入图片",
    "clipboard": "剪贴来源",
}


def _thumb_pixmap(record, size):
    """取一条历史的缩略图（按需缩放并缓存）；文件缺失返回 None。"""
    path = record.preview_path
    if not path or not os.path.isfile(path):
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    key = (path, mtime, size.width(), size.height())
    cached = _THUMB_CACHE.get(key)
    if cached is not None:
        _THUMB_CACHE.move_to_end(key)
        return cached

    source = QPixmap(path)
    if source.isNull():
        return None
    scaled = source.scaled(
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    _THUMB_CACHE[key] = scaled
    while len(_THUMB_CACHE) > _THUMB_CACHE_LIMIT:
        _THUMB_CACHE.popitem(last=False)
    return scaled


def _time_text(timestamp: float) -> str:
    try:
        return datetime.fromtimestamp(float(timestamp)).strftime("%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


def _annotation_text(count: int) -> str:
    """中文界面用自然说法：未标注 / 1 个标注 / 3 个标注。"""
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = 0
    if count <= 0:
        return _tr("未标注")
    return _tr("{n} 个标注").replace("{n}", str(count))


def _source_text(source_type: str) -> str:
    return _tr(_SOURCE_LABELS.get(str(source_type), "截图"))


# ── 悬停预览（行为与档位对齐剪贴板悬停预览） ─────────────────────────

def _preview_size_levels():
    """档位定义直接复用剪贴板悬停预览的同一份常量，保证两处行为一致。"""
    from clipboard.ui.widgets.preview_popup import PREVIEW_SIZE_LEVELS

    return PREVIEW_SIZE_LEVELS


def _read_preview_level() -> str:
    """读取继续标注悬停预览的尺寸档位，非法值回退为 large（默认档）。"""
    try:
        from settings import get_tool_settings_manager

        level = get_tool_settings_manager().get_annotation_preview_size()
        return level if level in _preview_size_levels() else "large"
    except Exception:
        return "large"


def _preview_image_limits(global_pos):
    """按档位算出悬停预览的 (最大宽, 最大高)，基于鼠标所在屏幕的可用区域。"""
    from clipboard.ui.widgets.preview_popup import IMAGE_SCREEN_RATIO

    screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
    # 极端环境（无屏幕 / offscreen）下退化为 1080p 假设，避免 None 崩溃
    geo = screen.availableGeometry() if screen is not None else QRect(0, 0, 1920, 1080)
    conf = IMAGE_SCREEN_RATIO[_read_preview_level()]
    if isinstance(conf[0], float):
        return (
            max(300, int(geo.width() * conf[0])),
            max(240, int(geo.height() * conf[1])),
        )
    return conf


class _HoverPreviewPopup(QWidget):
    """继续标注悬停预览浮窗：鼠标停在卡片上稍候即弹出该工程的预览大图。

    行为对齐剪贴板悬停预览（延迟弹出、避开宿主窗口、钳制在屏幕内）。
    图源只用 preview.jpg（最大边 640），绝不加载 source.png，避免悬停
    一次就把全分辨率母片读进内存；小图不放大，大图收到档位上限内。
    """

    _instance = None  # 单例，避免多个弹窗

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__(None)
        # 无边框 + 工具窗口 + 置顶，与剪贴板预览浮窗一致
        self.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet(
            "background: #FAFAFA; border: 1px solid #D0D0D0; border-radius: 8px;"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self._label)

        self._pending_record = None
        self._pending_pos = None
        self._pending_avoid_rect = None
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._do_show)

    def show_preview(self, record, global_pos, *, delay_ms: int = 500, avoid_rect=None):
        """请求显示预览（带延迟）；record 为 None 时直接隐藏。"""
        if record is None:
            self.hide_preview()
            return
        self._pending_record = record
        self._pending_pos = QPoint(global_pos)
        self._pending_avoid_rect = QRect(avoid_rect) if avoid_rect is not None else None
        self._show_timer.start(max(0, int(delay_ms)))

    def hide_preview(self):
        self._show_timer.stop()
        self._pending_record = None
        self._pending_pos = None
        self._pending_avoid_rect = None
        self.hide()

    def _do_show(self):
        record = self._pending_record
        pos = self._pending_pos
        if record is None or pos is None:
            return

        max_w, max_h = _preview_image_limits(pos)
        pixmap = self._load_pixmap(record, max_w, max_h)
        if pixmap is None:
            return  # 预览缺失：不弹窗，不打断操作

        self._label.setPixmap(pixmap)
        self.adjustSize()

        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen is not None else QRect(0, 0, 1920, 1080)

        # 摆放策略与剪贴板预览一致：优先放在宿主窗口之外，再钳制进屏幕
        gap = 10
        x = pos.x() + 20
        y = pos.y()
        avoid_rect = self._pending_avoid_rect
        if avoid_rect is not None:
            left_space = avoid_rect.left() - geo.left()
            right_space = geo.right() - avoid_rect.right()
            place_left = avoid_rect.left() - self.width() - gap
            place_right = avoid_rect.right() + gap
            if right_space >= self.width() + gap:
                x = place_right
            elif left_space >= self.width() + gap:
                x = place_left
            else:
                x = place_right if right_space >= left_space else place_left

        if x + self.width() > geo.right():
            x = geo.right() - self.width() - gap
        if x < geo.left():
            x = geo.left()
        if y + self.height() > geo.bottom():
            y = geo.bottom() - self.height() - gap
        if y < geo.top():
            y = geo.top()

        self.move(x, y)
        self.show()

    @staticmethod
    def _load_pixmap(record, max_w: int, max_h: int):
        path = record.preview_path
        if not path or not os.path.isfile(path):
            return None
        source = QPixmap(path)
        if source.isNull():
            return None
        # 小图保持原尺寸（不放大以免模糊），大图等比收进档位上限
        target_w = min(max_w, source.width())
        target_h = min(max_h, source.height())
        return source.scaled(
            target_w, target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )


class _HistoryCard(QFrame):
    """一张历史卡片：缩略图 + 时间 + 来源/标注数，悬停出操作。"""

    continue_requested = Signal(str)
    favorite_toggled = Signal(str, bool)
    delete_requested = Signal(str)

    def __init__(self, record, *, is_current: bool = False, parent=None):
        super().__init__(parent)
        self.record = record
        self.is_current = bool(is_current)
        self._favorite = bool(record.favorite)

        self.setObjectName("HistoryCard")
        self.setFixedSize(dialog_scaled(CARD_WIDTH), dialog_scaled(CARD_HEIGHT))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            dialog_scaled(10), dialog_scaled(10), dialog_scaled(10), dialog_scaled(8)
        )
        layout.setSpacing(dialog_scaled(6))

        self._preview = _PreviewArea(record, self)
        layout.addWidget(self._preview)

        time_label = QLabel(_time_text(record.updated_at), self)
        time_label.setStyleSheet(
            f"color: {ui_tokens(self).text}; font-size: {dialog_scaled(12)}px; font-weight: 600;"
        )
        time_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(time_label)

        meta = f"{_source_text(record.source_type)} · {_annotation_text(record.annotation_count)}"
        meta_label = QLabel(meta, self)
        meta_label.setStyleSheet(
            f"color: {ui_tokens(self).text_muted}; font-size: {dialog_scaled(11)}px;"
        )
        meta_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(meta_label)

        # 当前正在编辑的这一条：标出来，并且不允许在这里删掉它
        if self.is_current:
            badge = QLabel(_tr("当前"), self._preview)
            badge.setStyleSheet(
                f"color: #FFFFFF; background: {ui_tokens(self).accent};"
                f"border-radius: {dialog_scaled(7)}px;"
                f"padding: 1px {dialog_scaled(7)}px; font-size: {dialog_scaled(11)}px;"
            )
            badge.move(dialog_scaled(6), dialog_scaled(6))
            badge.adjustSize()

    # ------------------------------------------------------------------

    def _apply_style(self):
        tokens = ui_tokens(self)
        self.setStyleSheet(
            f"""
            QFrame#HistoryCard {{
                background: {tokens.surface};
                border: 1px solid {tokens.border};
                border-radius: {dialog_scaled(10)}px;
            }}
            QFrame#HistoryCard:hover {{
                border: 1px solid {tokens.accent};
            }}
            """
        )

    def refresh_favorite(self, favorite: bool):
        self._favorite = bool(favorite)
        self.record.favorite = self._favorite
        self._preview.set_favorite(self._favorite)

    def mouseDoubleClickEvent(self, event):
        # 双击卡片 == 继续标注
        self.continue_requested.emit(self.record.id)
        super().mouseDoubleClickEvent(event)

    def enterEvent(self, event):
        self._preview.set_actions_visible(True)
        # 悬停出预览浮窗：与剪贴板一致，延迟 500ms，避开宿主窗口
        _HoverPreviewPopup.instance().show_preview(
            self.record,
            QCursor.pos(),
            delay_ms=500,
            avoid_rect=self.window().geometry(),
        )
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._preview.set_actions_visible(False)
        _HoverPreviewPopup.instance().hide_preview()
        super().leaveEvent(event)

    def _on_continue(self):
        self.continue_requested.emit(self.record.id)

    def _on_favorite(self):
        self.favorite_toggled.emit(self.record.id, not self._favorite)

    def _on_delete(self):
        self.delete_requested.emit(self.record.id)


class _PreviewArea(QWidget):
    """卡片上半部分：缩略图 + 悬停操作条。"""

    def __init__(self, record, card: _HistoryCard):
        super().__init__(card)
        self._card = card
        self.setFixedHeight(dialog_scaled(PREVIEW_HEIGHT))
        tokens = ui_tokens(self)
        self.setStyleSheet(
            f"background: {tokens.surface_subtle};"
            f"border-radius: {dialog_scaled(7)}px;"
        )

        self._image = QLabel(self)
        self._image.setGeometry(0, 0, dialog_scaled(PREVIEW_WIDTH), dialog_scaled(PREVIEW_HEIGHT))
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._image.setStyleSheet("background: transparent; border: none;")

        self._load_thumbnail()

        self._actions = _CardActions(card, self)
        self._actions.setGeometry(self.rect())
        self._actions.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._image.setGeometry(self.rect())
        self._actions.setGeometry(self.rect())
        self._load_thumbnail()

    def _load_thumbnail(self):
        size = self.size()
        pixmap = _thumb_pixmap(self._card.record, size)
        if pixmap is None:
            self._image.setText(_tr("预览缺失"))
            self._image.setStyleSheet(
                f"color: {ui_tokens(self).text_muted};"
                f"font-size: {dialog_scaled(11)}px;"
                "background: transparent; border: none;"
            )
            return
        self._image.setText("")
        self._image.setPixmap(pixmap)

    def set_actions_visible(self, visible: bool):
        if visible:
            self._actions.raise_()
            self._actions.show()
        else:
            self._actions.hide()

    def set_favorite(self, favorite: bool):
        self._actions.set_favorite(favorite)


class _CardActions(QWidget):
    """悬停时压在缩略图上的操作条：继续标注 / 收藏 / 删除。"""

    def __init__(self, card: _HistoryCard, parent=None):
        super().__init__(parent)
        self._card = card
        self.setStyleSheet(
            f"background: rgba(0, 0, 0, 120); border-radius: {dialog_scaled(7)}px;"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            dialog_scaled(10), dialog_scaled(8), dialog_scaled(10), dialog_scaled(8)
        )
        layout.setSpacing(dialog_scaled(6))

        self._continue_btn = self._make_button(_tr("继续标注"), primary=True)
        self._continue_btn.clicked.connect(self._card._on_continue)
        layout.addWidget(self._continue_btn)

        if card.is_current:
            self._continue_btn.setText(_tr("当前正在编辑"))

        row = QHBoxLayout()
        row.setSpacing(dialog_scaled(6))

        self._favorite_btn = self._make_button(_tr("收藏"))
        self._favorite_btn.clicked.connect(self._card._on_favorite)
        row.addWidget(self._favorite_btn)

        self._delete_btn = self._make_button(_tr("删除"))
        self._delete_btn.clicked.connect(self._card._on_delete)
        # 正在编辑的这一条不能在这里删掉——那会让当前会话失去来源
        self._delete_btn.setEnabled(not card.is_current)
        row.addWidget(self._delete_btn)

        layout.addLayout(row)
        self.set_favorite(card._favorite)

    def _make_button(self, text: str, *, primary: bool = False) -> QPushButton:
        tokens = ui_tokens(self)
        button = QPushButton(text, self)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if primary:
            button.setStyleSheet(
                f"QPushButton {{ background: {tokens.accent}; color: #FFFFFF; border: none;"
                f" border-radius: {dialog_scaled(5)}px;"
                f" padding: {dialog_scaled(4)}px {dialog_scaled(10)}px;"
                f" font-size: {dialog_scaled(12)}px; font-weight: 600; }}"
            )
        else:
            button.setStyleSheet(
                "QPushButton { background: rgba(255, 255, 255, 220); color: #202124;"
                f" border: none; border-radius: {dialog_scaled(5)}px;"
                f" padding: {dialog_scaled(3)}px {dialog_scaled(8)}px;"
                f" font-size: {dialog_scaled(11)}px; }}"
                "QPushButton:disabled { background: rgba(255, 255, 255, 90); color: #808080; }"
            )
        return button

    def set_favorite(self, favorite: bool):
        self._favorite_btn.setText(_tr("取消收藏") if favorite else _tr("收藏"))


class AnnotationHistoryDialog(QDialog):
    """继续标注 / 标注历史窗口。"""

    def __init__(self, parent=None, current_history_id: str = None):
        super().__init__(parent)

        # 用户选中的历史 id；调用方（ScreenshotWindow）在 exec() 之后读取
        self.chosen_history_id = None
        self._current_history_id = current_history_id

        from history import get_history_manager
        self._manager = get_history_manager()

        self._source_filter = None        # None = 全部；"screenshot" = 只看截图
        self._favorite_only = False
        self._offset = 0
        self._total = 0
        self._columns = 0
        self._cards = []

        scale_dialog_font(self)
        self.setWindowTitle(_tr("继续标注"))
        # 从全屏置顶的截图窗口里打开，必须一起置顶才不会被截图窗口盖住
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setStyleSheet(f"QDialog {{ background: {ui_tokens(self).window}; }}")
        self.setMinimumSize(dialog_scaled(560), dialog_scaled(420))
        self.resize(dialog_scaled(900), dialog_scaled(640))
        # 显式声明应用级模态：截图快捷键处理器靠 activeModalWidget() 判断
        # "现在键盘归对话框"，1~9 / H / Enter / Esc 才不会穿透到截图层。
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        self._build_ui()
        self.reload()

    # ==================================================================
    # UI
    # ==================================================================

    def _build_ui(self):
        tokens = ui_tokens(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(
            dialog_scaled(16), dialog_scaled(14), dialog_scaled(16), dialog_scaled(14)
        )
        root.setSpacing(dialog_scaled(12))

        # ── 顶部：标题 + 来源筛选 + 数量 + 收藏筛选 ──
        header = QHBoxLayout()
        header.setSpacing(dialog_scaled(10))

        title = QLabel(_tr("继续标注"), self)
        title.setStyleSheet(
            f"color: {tokens.text}; font-size: {dialog_scaled(16)}px; font-weight: 600;"
        )
        header.addWidget(title)

        self._source_tabs = SegmentedWidget(self)
        self._source_tabs.addItem("all", _tr("全部"))
        self._source_tabs.addItem("screenshot", _tr("截图"))
        header.addWidget(self._source_tabs)

        self._count_label = QLabel("", self)
        self._count_label.setStyleSheet(
            f"color: {tokens.text_muted}; font-size: {dialog_scaled(12)}px;"
        )
        header.addWidget(self._count_label)

        header.addStretch(1)

        self._sort_tabs = SegmentedWidget(self)
        self._sort_tabs.addItem("recent", _tr("最近"))
        self._sort_tabs.addItem("favorite", _tr("收藏"))
        header.addWidget(self._sort_tabs)

        # ── 预览大小：与剪贴板一样提供 小/中/大/特大 四档，默认"大" ──
        self._preview_size_btn = QPushButton(_tr("预览大小"), self)
        self._preview_size_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._preview_size_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._preview_size_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {tokens.text_muted};"
            f" border: 1px solid {tokens.border}; border-radius: {dialog_scaled(6)}px;"
            f" padding: {dialog_scaled(4)}px {dialog_scaled(10)}px;"
            f" font-size: {dialog_scaled(12)}px; }}"
            f"QPushButton:hover {{ border-color: {tokens.accent}; color: {tokens.text}; }}"
        )
        self._preview_size_btn.clicked.connect(self._show_preview_size_menu)
        header.addWidget(self._preview_size_btn)

        root.addLayout(header)

        # ── 卡片网格 ──
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            + scrollbar_qss(self)
        )

        host = QWidget(self._scroll)
        host.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(host)
        self._grid.setContentsMargins(
            dialog_scaled(2), dialog_scaled(2), dialog_scaled(2), dialog_scaled(12)
        )
        self._grid.setSpacing(dialog_scaled(14))
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._scroll.setWidget(host)
        root.addWidget(self._scroll, 1)

        self._empty_label = QLabel(_tr("还没有保存过的截图历史。"), self)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            f"color: {tokens.text_muted}; font-size: {dialog_scaled(13)}px;"
        )
        self._empty_label.hide()
        root.addWidget(self._empty_label, 1)

        self._scroll.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        # viewport 宽度变化（窗口首次显示、拖动缩放、滚动条出现/消失）都要重排。
        # 不能只靠 dialog 的 resizeEvent：窗口以最终尺寸 exec() 显示时不会触发
        # resizeEvent，而 __init__ 里 reload() 时 viewport 还没布局完，列数算出来
        # 恒为 1，卡片就永远单列、右边全空。
        self._scroll.viewport().installEventFilter(self)
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(30)
        self._relayout_timer.timeout.connect(lambda: self._relayout_grid(force=True))

        # 信号在所有控件都就位之后再接：currentItemChanged 一旦触发就会走
        # reload()，而那需要卡片网格与空状态标签都已经存在。
        self._source_tabs.currentItemChanged.connect(self._on_source_tab_changed)
        self._sort_tabs.currentItemChanged.connect(self._on_sort_tab_changed)
        self._source_tabs.setCurrentItem("all")
        self._sort_tabs.setCurrentItem("recent")

    # ==================================================================
    # 数据
    # ==================================================================

    def reload(self):
        """按当前筛选条件从头加载第一页。"""
        self._clear_cards()
        self._offset = 0
        try:
            self._total = self._manager.count(
                source_type=self._source_filter,
                favorite_only=self._favorite_only,
            )
        except Exception as e:
            log_exception(e, T("统计历史数量"))
            self._total = 0
        self._count_label.setText(f"{self._total:,}")
        self._update_empty_state()
        self._load_next_page()

    def _load_next_page(self):
        try:
            records = self._manager.list_records(
                source_type=self._source_filter,
                favorite_only=self._favorite_only,
                offset=self._offset,
                limit=PAGE_SIZE,
            )
        except Exception as e:
            log_exception(e, T("加载历史列表"))
            return
        if not records:
            return

        for record in records:
            card = _HistoryCard(
                record,
                is_current=(record.id == self._current_history_id),
                parent=self._scroll.widget(),
            )
            card.continue_requested.connect(self._on_continue_requested)
            card.favorite_toggled.connect(self._on_favorite_toggled)
            card.delete_requested.connect(self._on_delete_requested)
            self._cards.append(card)

        self._offset += len(records)
        self._relayout_grid(force=True)
        self._update_empty_state()
        log_debug(T("历史列表已加载 {count}/{total}",
                    count=self._offset, total=self._total), "AnnotationHistory")

    def _clear_cards(self):
        # 重建列表时把可能还挂着的悬停预览一起收掉
        _HoverPreviewPopup.instance().hide_preview()
        for card in self._cards:
            self._grid.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._cards = []
        self._columns = 0

    def _update_empty_state(self):
        empty = not self._cards
        self._empty_label.setVisible(empty)
        self._scroll.setVisible(not empty)

    def _relayout_grid(self, *, force: bool = False):
        columns = self._grid_columns()
        if not force and columns == self._columns:
            return
        self._columns = columns
        for card in self._cards:
            self._grid.removeWidget(card)
        for index, card in enumerate(self._cards):
            self._grid.addWidget(card, index // columns, index % columns)
            card.show()

    def _grid_columns(self) -> int:
        spacing = dialog_scaled(14)
        card_width = dialog_scaled(CARD_WIDTH)
        available = self._scroll.viewport().width() - dialog_scaled(8)
        return max(1, int((available + spacing) // (card_width + spacing)))

    def _on_scrolled(self, value: int):
        bar = self._scroll.verticalScrollBar()
        if value >= bar.maximum() - dialog_scaled(200):
            self._load_next_page()

    # ==================================================================
    # 交互
    # ==================================================================

    def _on_source_tab_changed(self, key: str):
        self._source_filter = None if key == "all" else "screenshot"
        self.reload()

    def _on_sort_tab_changed(self, key: str):
        self._favorite_only = (key == "favorite")
        self.reload()

    def _show_preview_size_menu(self):
        current = _read_preview_level()
        labels = {
            "small": _tr("小"),
            "medium": _tr("中"),
            "large": _tr("大"),
            "xlarge": _tr("特大"),
        }
        tokens = ui_tokens(self)
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {tokens.surface}; color: {tokens.text};"
            f" border: 1px solid {tokens.border}; }}"
            "QMenu::item { padding: 4px 20px; }"
            f"QMenu::item:selected {{ background: {tokens.accent}; color: #FFFFFF; }}"
        )
        for key in _preview_size_levels():
            act = menu.addAction(labels[key])
            act.setCheckable(True)
            act.setChecked(current == key)
            act.triggered.connect(lambda _c, k=key: self._set_preview_size(k))
        menu.exec(self._preview_size_btn.mapToGlobal(QPoint(0, self._preview_size_btn.height())))

    def _set_preview_size(self, level: str):
        try:
            from settings import get_tool_settings_manager

            get_tool_settings_manager().set_annotation_preview_size(level)
        except Exception as e:
            log_exception(e, T("保存悬停预览尺寸档位"))

    def _record_for(self, history_id: str):
        for card in self._cards:
            if card.record.id == history_id:
                return card.record
        return None

    def _on_continue_requested(self, history_id: str):
        record = self._record_for(history_id)
        if record is None:
            return

        # 点自己 == 什么都不用切换，直接关掉窗口继续编辑
        if history_id == self._current_history_id:
            self.reject()
            return

        if not os.path.isfile(record.source_path):
            show_warning_dialog(
                self, _tr("继续标注"),
                _tr("这条历史的母片已丢失，无法继续标注。"),
            )
            return

        self.chosen_history_id = record.id
        self.accept()

    def _on_favorite_toggled(self, history_id: str, favorite: bool):
        record = self._record_for(history_id)
        if record is None:
            return
        self._manager.set_favorite(history_id, favorite)
        record.favorite = bool(favorite)
        for card in self._cards:
            if card.record.id == history_id:
                card.refresh_favorite(favorite)
        # 正在按"收藏"筛选时，取消收藏意味着这条要从列表里消失
        if self._favorite_only and not favorite:
            self.reload()

    def _on_delete_requested(self, history_id: str):
        if history_id == self._current_history_id:
            show_warning_dialog(
                self, _tr("删除历史"),
                _tr("这条历史正在编辑中，请先退出继续标注再删除。"),
            )
            return

        confirmed = show_confirm_dialog(
            self,
            _tr("删除历史"),
            _tr("删除后，这条历史的母片、标注工程与缩略图都会被清除，且无法恢复。\n\n确定删除吗？"),
        )
        if not confirmed:
            return

        self._manager.delete(history_id)
        for card in list(self._cards):
            if card.record.id == history_id:
                self._grid.removeWidget(card)
                self._cards.remove(card)
                card.setParent(None)
                card.deleteLater()
        self._total = max(0, self._total - 1)
        self._offset = max(0, self._offset - 1)
        self._count_label.setText(f"{self._total:,}")
        self._relayout_grid(force=True)
        self._update_empty_state()
        log_debug(T("已删除历史记录: {history_id}", history_id=history_id), "AnnotationHistory")

    # ==================================================================

    def eventFilter(self, obj, event):
        # viewport 尺寸变化（滚动条出现/消失、窗口缩放）→ 防抖重排
        if obj is self._scroll.viewport() and event.type() == event.Type.Resize:
            self._relayout_timer.start()
        return super().eventFilter(obj, event)

    def hideEvent(self, event):
        # 窗口隐藏时同步收掉悬停预览浮窗，避免浮窗残留在屏幕上
        _HoverPreviewPopup.instance().hide_preview()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        # 首次显示时 viewport 才有真实宽度；此时强制按真实宽度重排一次，
        # 覆盖 __init__ 里 reload() 算出单列、而 exec() 又不触发 resize 的情况。
        QTimer.singleShot(0, lambda: self._relayout_grid(force=True))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_grid()
