"""截图窗口 - 核心事务控制

主程序的截图功能中枢，协调画布、工具栏、选区面板、遮罩等组件。
实现窗口复用、会话存活周期管理、工具信号转发、导出触发等功能。
"""

import gc
from PySide6.QtWidgets import QApplication, QWidget, QGraphicsTextItem
from PySide6.QtCore import Qt, QTimer, QRect, QRectF
from PySide6.QtGui import QColor, QPixmap
from ui.dialogs import show_modeless_warning_dialog

from canvas import CanvasScene, CanvasView
from capture.capture_service import CaptureService
from ui.toolbar import Toolbar
from ui.magnifier import MagnifierOverlay
from ui.mask_overlay import MaskOverlayWidget
from ui.selection_overlay import SelectionOverlayWidget
from ui.selection_info import SelectionInfoPanel, SelectionInfoController
from tools.action import ActionTools
from settings import get_tool_settings_manager
from settings.tool_settings import SMART_SELECTION_MODES
from core.logger import log_debug, log_info, log_warning, log_exception, T
from core import safe_event
from core.shortcut_manager import ShortcutManager, ShortcutHandler


# 历史状态的防抖落盘延迟：鼠标停手 500ms 之后才序列化一次，避免每个
# mouseMove 都写磁盘。关键出口（确认/保存/钉图/按 H/结束会话）会强制 flush。
HISTORY_FLUSH_DELAY_MS = 500


def _status_ready() -> str:
    """history 包的"有效历史"状态常量（延迟导入，避免顶层多拖一份依赖）。"""
    from history.models import STATUS_READY
    return STATUS_READY


def _is_alive(widget) -> bool:
    """Qt 对象是否还没被销毁（历史窗口持有的是可能已失效的壳）。"""
    if widget is None:
        return False
    try:
        import shiboken6
        return bool(shiboken6.isValid(widget))
    except Exception:
        return True



class ScreenshotShortcutHandler(ShortcutHandler):
    """截图窗口快捷键处理器 - 优先级最高(100)"""

    def __init__(self, window: 'ScreenshotWindow'):
        self._window = window
        from settings.tool_settings import ALL_TOOL_SHORTCUTS

        self._tool_shortcuts = tuple(ALL_TOOL_SHORTCUTS)
        self.reload_bindings()

    def reload_bindings(self):
        """重新读取应用内快捷键配置。

        截图窗口创建时读一次；用户在当前截图里打开“自定义工具栏”改完并确定后，
        __init__ 里缓存的绑定就过期了，调用方再调一次即可让新快捷键立即生效，
        不必退出重开截图。
        """
        from core.shortcut_manager import (
            load_inapp_bindings, load_inapp_mouse_bindings, load_move_keys,
        )
        from settings.tool_settings import SCREENSHOT_ACTION_SHORTCUTS

        action_keys = [key for key, _label in SCREENSHOT_ACTION_SHORTCUTS]
        bound_keys = action_keys + [entry[0] for entry in self._tool_shortcuts]
        self._bindings = load_inapp_bindings(bound_keys)
        self._mouse_bindings = load_inapp_mouse_bindings(bound_keys)
        self._move_keys = load_move_keys()

    @property
    def priority(self) -> int:
        return 100

    @property
    def handler_name(self) -> str:
        return "ScreenshotWindow"

    def is_active(self) -> bool:
        w = self._window
        # ShortcutManager 是应用级事件过滤器，按键先经过这里才到对话框。截图中打开的
        # 模态对话框（工具栏「调整」）必须让出键盘，否则在对话框里按 ESC 会直接结束截图、
        # 按 Enter 会确认截图。截图开始前就存在的模态窗口会被
        # MainApp._activate_blocking_modal 挡掉，所以这里遇到的模态窗口只会属于本次截图。
        return (w is not None
                and not getattr(w, '_is_closing', True)
                and w.isVisible()
                and QApplication.activeModalWidget() is None)

    def _match(self, event, cfg_key: str) -> bool:
        """检查事件是否匹配某个绑定（键盘组合或鼠标键）"""
        from core.shortcut_manager import match_inapp_binding
        return match_inapp_binding(
            event, cfg_key, self._bindings, self._mouse_bindings
        )

    def handle_mouse(self, event) -> bool:
        """中键走和键盘完全相同的那条 if 链，见 ShortcutHandler.handle_mouse。"""
        return self.handle_key(event)

    def handle_key(self, event) -> bool:
        from core.shortcut_manager import event_is_auto_repeat, event_key

        w = self._window
        # 中键也走这条链（见 handle_mouse）。鼠标事件没有 key()，这里取到的是
        # Key_unknown，所以下面所有键专属的分支——文字编辑放行、ESC、鼠标微移、
        # 硬编码的取色 C 和 Enter——对中键自然全部落空，只剩 _match 驱动的那些
        # 分支有效。不必逐条再加「这是不是鼠标事件」的判断。
        key = event_key(event)
        if hasattr(w, "view") and hasattr(w.view, "invalidate_double_click_candidate"):
            w.view.invalidate_double_click_candidate()
        is_text_editing = w._is_text_editing()

        # 文字编辑模式下，按键优先交给 QGraphicsTextItem。
        # 不带 Ctrl/Alt 的按键（数字、字母、Shift+字符、标点）都是可打印输入，
        # 不能被截图快捷键抢走——否则默认的 1~9 会吃掉用户正在输入的数字。
        # Esc、Ctrl+Z/Ctrl+Y、Ctrl+C/Ctrl+D 等既有编辑语义仍按下面的分支处理。
        if is_text_editing:
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                return False
            has_shortcut_modifier = bool(
                event.modifiers()
                & (Qt.KeyboardModifier.ControlModifier
                   | Qt.KeyboardModifier.AltModifier
                   | Qt.KeyboardModifier.MetaModifier)
            )
            if not has_shortcut_modifier and key != Qt.Key.Key_Escape:
                return False
            if key in (Qt.Key.Key_C, Qt.Key.Key_D):
                return False
            if (key in (Qt.Key.Key_Z, Qt.Key.Key_Y)
                    and event.modifiers() == Qt.KeyboardModifier.ControlModifier):
                return False

        # ESC — 固定不可自定义
        if key == Qt.Key.Key_Escape:
            w.cleanup_and_close()
            return True

        # 恢复上次截图区域
        if self._match(event, "inapp_restore_last_region"):
            if self._restore_last_region():
                return True

        # 继续标注：打开标注历史，把过去的截图工程重新载入继续编辑。
        # 刻意不要求 selection 已确认——刚进截图、还没框选时也要能翻历史。
        # 按住不放只消费自动重复的那几次，避免叠出多个历史窗口。
        if self._match(event, "inapp_continue_annotate"):
            if not event_is_auto_repeat(event):
                w.open_annotation_history()
            return True

        # 确认截图
        if self._match(event, "inapp_confirm"):
            if w.scene and w.scene.selection_model.is_confirmed:
                w.action_handler.handle_confirm()
                return True

        # 钉图。按住不放只消费自动重复的那几次，不再重复执行动作。
        if self._match(event, "inapp_pin"):
            if w.scene and w.scene.selection_model.is_confirmed:
                if not event_is_auto_repeat(event):
                    w.action_handler.handle_pin()
                return True

        # 撤销
        if self._match(event, "inapp_undo"):
            if w.scene and w.scene.undo_stack.canUndo():
                w.scene.undo_stack.undo()
            return True

        # 重做
        if self._match(event, "inapp_redo"):
            if w.scene and w.scene.undo_stack.canRedo():
                w.scene.undo_stack.redo()
            return True

        # 删除选中图元。文字编辑时这个键（默认 Delete）要留给文字框删字符，
        # 不能在这里连事件一起吞掉——之前 return True 写在 if 外面，编辑文字时
        # 按 Delete 键选中图元没删（判断对了），但事件已经被吃掉，文字框根本
        # 收不到这次按键，光标后面的字删不掉。
        if self._match(event, "inapp_delete"):
            if not is_text_editing:
                if hasattr(w.view, 'smart_edit_controller'):
                    w.view.smart_edit_controller.delete_selected()
                return True

        # 截图翻译
        if self._match(event, "inapp_translate"):
            if w.scene and w.scene.selection_model.is_confirmed:
                if not event_is_auto_repeat(event) and hasattr(w, 'toolbar') and w.toolbar:
                    w.toolbar.screenshot_translate_clicked.emit()
                return True

        # 文字识别
        if self._match(event, "inapp_text_recognize"):
            if w.scene and w.scene.selection_model.is_confirmed:
                if not event_is_auto_repeat(event) and hasattr(w, 'toolbar') and w.toolbar:
                    w.toolbar.text_recognize_clicked.emit()
                return True

        # 保存 / 长截图 / 扫码 / GIF：与点击工具栏同名按钮走同一条信号，
        # 默认都不绑键，用户在“自定义工具栏”里绑了才生效。
        for cfg_key, signal_name in (
            ("inapp_save", "save_clicked"),
            ("inapp_long_screenshot", "long_screenshot_clicked"),
            ("inapp_scan_code", "scan_code_clicked"),
            ("inapp_gif", "gif_record_clicked"),
        ):
            if self._match(event, cfg_key):
                if w.scene and w.scene.selection_model.is_confirmed:
                    toolbar = getattr(w, 'toolbar', None)
                    if not event_is_auto_repeat(event) and toolbar is not None:
                        getattr(toolbar, signal_name).emit()
                    return True

        # 放大镜缩放属于可配置截图动作，优先于工具键。
        if self._match(event, "inapp_zoom_in"):
            mo = getattr(w, 'magnifier_overlay', None)
            if mo and mo.cursor_scene_pos is not None and mo._should_render():
                mo.adjust_zoom(1)
                return True

        if self._match(event, "inapp_zoom_out"):
            mo = getattr(w, 'magnifier_overlay', None)
            if mo and mo.cursor_scene_pos is not None and mo._should_render():
                mo.adjust_zoom(-1)
                return True

        # 标注工具：选区确认后生效；自动重复只消费不重复激活。
        if not is_text_editing and w.scene and w.scene.selection_model.is_confirmed:
            for cfg_key, tool_id, _label, _default in self._tool_shortcuts:
                if not self._match(event, cfg_key):
                    continue
                if not event_is_auto_repeat(event) and hasattr(w, "toolbar") and w.toolbar:
                    w.toolbar.select_tool(tool_id, toggle=False)
                return True

        # ── 鼠标微移（配置动作/工具之后）──
        if not is_text_editing:
            delta = self._move_keys.get(key)
            if delta and event.modifiers() == Qt.KeyboardModifier.NoModifier:
                from PySide6.QtGui import QCursor
                p = QCursor.pos()
                QCursor.setPos(p.x() + delta[0], p.y() + delta[1])
                return True

        # 取色（单键 C，无修饰键 — 保留硬编码）
        if key == Qt.Key.Key_C:
            if event.modifiers() == Qt.KeyboardModifier.NoModifier:
                mo = getattr(w, 'magnifier_overlay', None)
                if mo and mo.cursor_scene_pos is not None and mo._should_render():
                    if mo.copy_color_info():
                        w.cleanup_and_close()
                        return True

        # Enter 确认（固定）
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if w.scene and w.scene.selection_model.is_confirmed:
                w.action_handler.handle_confirm()
                return True

        return False

    def _restore_last_region(self) -> bool:
        """把选区还原成上次截图使用过的区域。

        只在没有任何绘制工具开着时响应（同 view.py 的 is_drawing_tool 判断），
        避免覆盖正在使用的标注。记忆的是虚拟桌面绝对坐标，也就是场景坐标，
        落在当前虚拟桌面范围外（换了显示器排布等）就安静地不做任何事，不当
        错误处理。
        """
        w = self._window
        if not w.scene:
            return False
        if w.scene.tool_controller.current_tool_id != "cursor":
            return False

        from core.last_capture_region import get_last_region
        absolute = get_last_region()
        if absolute is None:
            return False

        # 副屏在主屏左边/上边时虚拟桌面左上角是负的，范围不能从原点量起。
        virtual_bounds = QRect(round(w.virtual_x), round(w.virtual_y),
                               round(w.virtual_width), round(w.virtual_height))
        if not virtual_bounds.contains(absolute):
            return False

        w.scene.selection_model.initialize_confirmed_rect(QRectF(absolute))
        return True


class ScreenshotWindow(QWidget):
    def __init__(self, config_manager=None, prefetched_image=None, prefetched_rect=None):
        super().__init__()
        
        # 不设置 WA_DeleteOnClose —— 窗口复用，由 main_app 管理生命周期
        
        # Config manager for auto-save settings
        self.config_manager = config_manager if config_manager else get_tool_settings_manager()
        # 关闭标记，防止已销毁窗口继续响应回调
        self._is_closing = False
        self._session_active = False

        # ── 历史（继续标注）相关的持久状态 ──
        # 窗口是复用的，这些字段跟着窗口活；每次会话开始时重新绑定 history_id。
        self.history_id = None            # 当前会话对应的历史记录 id
        self.is_history_session = False   # True = 本次会话是从历史恢复出来的
        self._history_dialog = None       # 已打开的历史窗口（防重复创建）
        self._history_offscreen = False   # 历史桌面不在当前屏幕范围内（只记日志）
        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(HISTORY_FLUSH_DELAY_MS)
        self._history_timer.timeout.connect(self._flush_history_state)
        
        import time
        _t0 = time.perf_counter()
        _timings = {}   # 收集各阶段耗时，最后统一输出
        
        # 1. 获取屏幕截图：优先使用调用方预取的图像（已在后台线程截好），否则同步截图
        if prefetched_image is not None and prefetched_rect is not None:
            self.original_image = prefetched_image
            rect = prefetched_rect
            _timings['截屏'] = 0.0  # 预取，主线程耗时为 0
        else:
            capture_service = CaptureService()
            self.original_image, rect = capture_service.capture_all_screens()
            _timings['截屏'] = (time.perf_counter() - _t0) * 1000
        
        _t1 = time.perf_counter()
        
        self.virtual_x = rect.x()
        self.virtual_y = rect.y()
        self.virtual_width = rect.width()
        self.virtual_height = rect.height()
        
        log_debug(T("虚拟桌面: {width}x{height} at ({x}, {y})",
                     width=self.virtual_width, height=self.virtual_height,
                     x=self.virtual_x, y=self.virtual_y), "ScreenshotWindow")
        log_debug(T("图像尺寸: {width}x{height}",
                     width=self.original_image.width(), height=self.original_image.height()), "ScreenshotWindow")

        # 2. 窗口属性 & 几何形状（必须在创建子控件之前完成）
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setGeometry(int(self.virtual_x), int(self.virtual_y), int(self.virtual_width), int(self.virtual_height))

        # 3. 初始化场景和视图
        self.scene = CanvasScene(self.original_image, rect, enable_mosaic=True)
        self.view = self._create_canvas_view(self.scene)
        self.view.setGeometry(0, 0, int(self.virtual_width), int(self.virtual_height))
        
        _t2 = time.perf_counter()
        _timings['Scene+View'] = (_t2 - _t1) * 1000
        
        # 启用智能选区（从配置读取）
        self.smart_selection_mode = self._get_configured_smart_selection_mode()
        self.smart_selection_enabled = self.smart_selection_mode != "off"
        self.view.enable_smart_selection(self.smart_selection_mode)
        self.view.smart_selection_animated = self.config_manager.get_smart_selection_animation()
        
        # 4. 初始化工具栏（一次性创建，后续复用）
        self.toolbar = Toolbar(self)
        self.toolbar.hide() # 初始隐藏，选区确认后显示
        
        _t3 = time.perf_counter()
        _timings['Toolbar'] = (_t3 - _t2) * 1000
        
        # 5. 创建ActionTools来处理工具栏按钮逻辑
        self.action_handler = ActionTools(
            scene=self.scene,
            config_manager=self.config_manager,
            parent_window=self
        )

        # 6. 遮罩叠层（QWidget），覆盖整个窗口，位于 View 之上
        self.mask_overlay = MaskOverlayWidget(self, self.scene.selection_model)
        self.mask_overlay.setGeometry(0, 0, int(self.virtual_width), int(self.virtual_height))

        # 6.1 选区装饰浮层，必须在遮罩之上，否则边框/手柄跨出选区的部分会被压暗
        self.selection_overlay = SelectionOverlayWidget(
            self, self.scene.selection_item, self.scene.selection_model
        )
        self.selection_overlay.setGeometry(0, 0, int(self.virtual_width), int(self.virtual_height))
        self.selection_overlay.raise_()

        _t4 = time.perf_counter()
        _timings['Action+Mask'] = (_t4 - _t3) * 1000

        # 6.5 选区信息面板（坐标/尺寸 + 圆角/锁定比例等快捷按钮）
        self.info_panel = SelectionInfoPanel(self, self.view)
        self.info_controller = SelectionInfoController(
            panel=self.info_panel,
            selection_model=self.scene.selection_model,
            selection_item=self.scene.selection_item,
            export_service=self.action_handler.export_service,
            mask_overlay=self.mask_overlay,
            parent_widget=self,
            config_manager=self.config_manager,
        )

        _t5 = time.perf_counter()
        _timings['InfoPanel'] = (_t5 - _t4) * 1000

        # 7. 叠加鼠标放大镜，复刻老版 UI 的色彩信息视图
        self.magnifier_overlay = MagnifierOverlay(self, self.scene, self.view, self.config_manager)
        # 放大镜现在是独立小浮层，无需 setGeometry(self.rect())
        
        # 工具栏初始位置（底部居中）
        self.update_toolbar_position()
        
        # 6. 连接信号（一次性 toolbar→self + 本次 session 信号）
        self._connect_toolbar_signals()
        self._connect_session_signals()

        _t6 = time.perf_counter()
        _timings['Magnifier+信号'] = (_t6 - _t5) * 1000
        _timings['总计'] = (_t6 - _t0) * 1000

        # ── 统一输出初始化计时 ──
        parts = [f"{k}={v:.1f}ms" for k, v in _timings.items()]
        log_debug(T("[计时] 初始化完成 | {parts}", parts=' | '.join(parts)), "ScreenshotWindow")
        
        # 截图期间压制 pin 窗口的置顶，避免同级 TopMost 窗口抢 Z-order
        from pin.pin_manager import PinManager
        PinManager.instance().suppress_topmost()
        
        # 注册全局快捷键处理器（优先级最高）
        self._shortcut_handler = ScreenshotShortcutHandler(self)
        ShortcutManager.instance().register(self._shortcut_handler)
        
        self._session_active = True
        self.show()
        self.activateWindow()
        self.raise_()
        self.setFocus()
        
        # Ensure focus after a short delay (workaround for Windows focus stealing prevention)
        QTimer.singleShot(50, self._safe_activate_and_focus)

        # 历史会话：立刻把完整虚拟桌面母片交给后台保存（不阻塞截图 UI）
        self._attach_history_session(self._start_history_session(self.original_image, rect))
        
        # 初始状态：进入选区模式
        # CanvasView 默认处理鼠标按下进入选区

    def _create_canvas_view(self, scene):
        """创建使用当前截图交互设置的画布视图。"""
        return CanvasView(
            scene,
            self,
            confirm_on_double_click=(
                self.config_manager.get_double_click_copy_close_enabled()
            ),
            cross_tool_select=self.config_manager.get_cross_tool_selection_enabled(),
        )

    def _get_configured_smart_selection_mode(self) -> str:
        """读取检测方式；没有这项设置的旧配置对象退回窗口级，和默认值一致。"""
        getter = getattr(self.config_manager, "get_smart_selection_mode", None)
        if callable(getter):
            mode = str(getter() or "").lower()
            if mode in SMART_SELECTION_MODES:
                return mode
        return "window" if self.config_manager.get_smart_selection() else "off"

    # ------------------------------------------------------------------
    # 窗口复用：准备新的截图会话
    # ------------------------------------------------------------------
    def prepare_new_session(self, prefetched_image, prefetched_rect):
        """复用已有窗口，准备新一次截图会话。
        
        释放旧会话的重数据（~66MB 图像），保留轻量 UI 壳（toolbar/magnifier 等），
        然后用新截图数据重建 Scene/View，节省 ~250ms 创建耗时。
        """
        import time
        _t0 = time.perf_counter()

        self._install_session(prefetched_image, prefetched_rect)

        # 历史会话：把这张完整虚拟桌面母片交给后台保存，并挂上自动落盘
        self._attach_history_session(
            self._start_history_session(prefetched_image, prefetched_rect)
        )
        
        _elapsed = (time.perf_counter() - _t0) * 1000
        log_debug(T("[计时] 复用窗口会话准备完成 | 耗时={elapsed:.1f}ms", elapsed=_elapsed), "ScreenshotWindow")

    def prepare_history_session(self, image, rect, state, history_id):
        """复用截图窗口，把一条历史截图工程重新载入继续编辑。

        视觉原理和钉图一样是"把过去那一刻的桌面冻结在最上方"，但底层继续用
        ScreenshotWindow：选区模型、放大镜、工具栏、全部标注工具、OCR/翻译/
        扫码/GIF/长截图/保存/复制/钉图 这些流程都是现成的，不需要第二套编辑器。

        与 prepare_new_session 的唯一区别是数据来源：这里不调用
        CaptureService（不能重新截当前桌面），背景直接用历史母片，并额外还原
        当时的选区与全部矢量标注。
        """
        import time
        _t0 = time.perf_counter()

        self._install_session(image, rect)
        self._restore_history_state(state)

        # 恢复过程本身会触发大量 changed 信号，这里挂上监听前先落一次干净的基线
        self._attach_history_session(history_id, is_restored=True)
        self._flush_history_state()

        _elapsed = (time.perf_counter() - _t0) * 1000
        log_debug(T("[计时] 历史会话载入完成 | history_id={history_id} | 耗时={elapsed:.1f}ms",
                    history_id=history_id, elapsed=_elapsed), "ScreenshotWindow")

    def _install_session(self, image, rect):
        """把一副图像 + 虚拟桌面几何装成一次可交互的截图会话。

        prepare_new_session（实时截图）与 prepare_history_session（历史恢复）
        共用这一份：Scene/View/遮罩/选区装饰/信息面板/放大镜/工具栏/快捷键的
        创建顺序只有一套，两条路径不会各自漂移。
        """
        self._is_closing = False
        self.is_history_session = False

        self.original_image = image
        self.virtual_x = rect.x()
        self.virtual_y = rect.y()
        self.virtual_width = rect.width()
        self.virtual_height = rect.height()
        
        # 更新窗口几何形状（多显示器可能变化）
        self.setGeometry(int(self.virtual_x), int(self.virtual_y),
                         int(self.virtual_width), int(self.virtual_height))
        
        # 创建新的 Scene + View（每次截图内容不同，不可复用）
        self.scene = CanvasScene(image, rect, enable_mosaic=True)
        self.view = self._create_canvas_view(self.scene)
        self.view.setGeometry(0, 0, int(self.virtual_width), int(self.virtual_height))
        self.view.lower()  # 确保 view 在最底层，overlay 在上方
        
        self.smart_selection_mode = self._get_configured_smart_selection_mode()
        self.smart_selection_enabled = self.smart_selection_mode != "off"
        self.view.enable_smart_selection(self.smart_selection_mode)
        self.view.smart_selection_animated = self.config_manager.get_smart_selection_animation()
        
        # 创建新的 ActionHandler（引用新 scene）
        self.action_handler = ActionTools(
            scene=self.scene,
            config_manager=self.config_manager,
            parent_window=self
        )
        
        # 复用 mask_overlay —— 重新绑定到新的 selection_model
        self.mask_overlay.rebind_model(self.scene.selection_model)
        self.mask_overlay.setGeometry(0, 0, int(self.virtual_width), int(self.virtual_height))
        self.mask_overlay.raise_()

        # 复用 selection_overlay —— 绑到新 scene 的 item/model，并保持在遮罩之上
        self.selection_overlay.rebind(self.scene.selection_item, self.scene.selection_model)
        self.selection_overlay.setGeometry(0, 0, int(self.virtual_width), int(self.virtual_height))
        self.selection_overlay.raise_()
        
        # 复用 info_panel —— swap view 引用，重建 controller
        self.info_panel._view = self.view
        self.info_controller = SelectionInfoController(
            panel=self.info_panel,
            selection_model=self.scene.selection_model,
            selection_item=self.scene.selection_item,
            export_service=self.action_handler.export_service,
            mask_overlay=self.mask_overlay,
            parent_widget=self,
            config_manager=self.config_manager,
        )
        
        # 复用 magnifier_overlay —— 重新指向新 scene/view
        self.magnifier_overlay.rebind(self.scene, self.view)
        
        # 复用 toolbar —— 重置状态
        self.toolbar.reset_session_state()
        self.toolbar.raise_()
        
        # 连接本次会话的信号
        self._connect_session_signals()
        
        # 工具栏定位
        self.update_toolbar_position()
        
        # 压制 pin 窗口
        from pin.pin_manager import PinManager
        PinManager.instance().suppress_topmost()
        
        # 注册快捷键
        self._shortcut_handler = ScreenshotShortcutHandler(self)
        ShortcutManager.instance().register(self._shortcut_handler)
        
        self._session_active = True
        self.show()
        self.activateWindow()
        self.raise_()
        self.setFocus()
        QTimer.singleShot(50, self._safe_activate_and_focus)

    # ------------------------------------------------------------------
    # 会话结束：释放重数据，保留 UI 壳
    # ------------------------------------------------------------------
    def _teardown_session(self):
        """释放本次截图会话的重数据（~66MB 图像 + scene/view），
        保留 toolbar/magnifier/mask_overlay/info_panel 等可复用的轻量 UI 壳。
        """
        if not self._session_active:
            return
        self._session_active = False

        # 历史：离开会话之前必须把最后的工程状态落盘。放在 _is_closing 置位
        # 之前——flush 要读写 scene，而 _is_closing 会让一部分路径提前返回。
        self._finalize_history_session()

        self._is_closing = True
        
        # 立即隐藏窗口
        self.hide()
        
        log_debug(T("开始释放截图会话资源（保留 UI 壳）"), "ScreenshotWindow")
        
        # 恢复窗口对截图 API 的可见性
        if getattr(self, '_exclude_from_capture_set', False):
            self._set_exclude_from_capture(False)
            self._exclude_from_capture_set = False
        
        # 注销快捷键处理器
        if hasattr(self, '_shortcut_handler') and self._shortcut_handler:
            ShortcutManager.instance().unregister(self._shortcut_handler)
            self._shortcut_handler._window = None
            self._shortcut_handler = None
        
        # 恢复 pin 窗口
        try:
            from pin.pin_manager import PinManager
            PinManager.instance().restore_topmost()
        except Exception as e:
            log_exception(e, T("恢复 pin 窗口"))
        
        # 断开 toolbar → smart_edit_controller 的会话信号
        # （toolbar 是持久对象，不 disconnect 会导致信号累积，每次截图多加一个 handler）
        self._disconnect_session_signals()
        
        # 停止定时器
        if hasattr(self, 'visibility_timer') and self.visibility_timer:
            self.visibility_timer.stop()
            self.visibility_timer.deleteLater()
            self.visibility_timer = None
        
        # 释放大图片内存
        if hasattr(self, 'original_image'):
            self.original_image = None
        
        # 清空放大镜缓存（保留 widget）
        if hasattr(self, 'magnifier_overlay') and self.magnifier_overlay:
            self.magnifier_overlay.rebind(None, None)
        
        # 销毁 info_controller（复杂，必须重建）
        if hasattr(self, 'info_controller') and self.info_controller:
            self.info_controller.cleanup()
            self.info_controller = None
        
        # 重置 info_panel 的 checkable 按钮状态，防止下次会话遗留
        if hasattr(self, 'info_panel') and self.info_panel:
            for btn in (self.info_panel.btn_rounded, self.info_panel.btn_lock, self.info_panel.btn_border):
                btn.setChecked(False)
            self.info_panel.set_confirmed(False)
            self.info_panel.hide()

        # 先断开 view/controller 与当前 scene 的会话连接，再销毁 scene。
        if hasattr(self, 'view') and self.view and hasattr(self.view, 'cleanup'):
            self.view.cleanup()
        
        # 清理 Scene
        if hasattr(self, 'scene') and self.scene:
            if hasattr(self.scene, 'background') and self.scene.background:
                self.scene.background.release_image_cache()
                self.scene.background.setPixmap(QPixmap())
            if hasattr(self.scene, 'tool_controller'):
                self.scene.tool_controller = None
            if hasattr(self.scene, 'undo_stack'):
                self.scene.undo_stack.clear()
            # 释放所有图元的大图内存（Pixmap），然后交给 deleteLater 统一销毁
            for item in self.scene.items():
                if hasattr(item, 'setPixmap'):
                    item.setPixmap(QPixmap())
            self.scene.deleteLater()
            self.scene = None
        
        # 清理 View
        if hasattr(self, 'view') and self.view:
            self.view.setScene(None)
            self.view.setParent(None)
            self.view.deleteLater()
            self.view = None
        
        # 清理 ActionHandler
        if hasattr(self, 'action_handler') and self.action_handler:
            self.action_handler.scene = None
            self.action_handler.parent_window = None
            self.action_handler.export_service = None
            self.action_handler.save_service = None
            self.action_handler = None
        
        gc.collect()
        log_info(T("截图会话资源释放完成"), "ScreenshotWindow")

    def _disconnect_session_signals(self):
        """断开本次会话连接到持久 toolbar 上的信号。
        
        _connect_session_signals() 每次会话把 toolbar 信号连到新的
        smart_edit_controller 上；如果不在 teardown 中 disconnect，
        信号会累积——第 N 次截图时触发 N 个 handler。
        """
        if not hasattr(self, 'view') or not self.view:
            return
        controller = getattr(self.view, 'smart_edit_controller', None)
        if not controller:
            return
        from core.qt_utils import safe_disconnect
        safe_disconnect(self.toolbar.text_font_changed, controller.on_text_font_changed)
        safe_disconnect(self.toolbar.color_changed, controller.on_text_color_changed)
        safe_disconnect(self.toolbar.text_background_changed, controller.on_text_background_changed)
        safe_disconnect(self.toolbar.text_outline_changed, controller.on_text_outline_changed)
        safe_disconnect(self.toolbar.text_shadow_changed, controller.on_text_shadow_changed)

    # ------------------------------------------------------------------
    # 历史 / 继续标注
    # ------------------------------------------------------------------
    def _start_history_session(self, image, rect):
        """把完整虚拟桌面母片交给 HistoryManager 后台保存，返回 history_id。

        历史是增强功能：任何一步失败都只记日志并返回 None，截图本身照常可用。
        """
        try:
            from history import get_history_manager
            return get_history_manager().begin_session(image, rect)
        except Exception as e:
            log_exception(e, T("创建历史会话"))
            return None

    def _attach_history_session(self, history_id, *, is_restored=False):
        """把当前会话与一条历史记录绑起来，并挂上"状态变化 → 防抖落盘"。"""
        self.history_id = history_id
        self.is_history_session = bool(is_restored) and history_id is not None
        if not history_id:
            return
        scene = getattr(self, 'scene', None)
        if scene is None:
            return
        # 标注增删/移动、样式修改都会让 scene 变脏；选区调整单独也走一路。
        # 两个信号都只负责"重置防抖计时器"，不在这里做任何序列化。
        scene.changed.connect(self._on_history_scene_changed)
        scene.selection_model.rectChanged.connect(self._on_history_selection_changed)

    def _on_history_scene_changed(self, *_args):
        if self.history_id:
            self._history_timer.start()

    def _on_history_selection_changed(self, *_args):
        if self.history_id:
            self._history_timer.start()

    def _finalize_history_session(self):
        """会话收尾：把最后的工程状态落盘，或丢弃一条从未确认选区的草稿。"""
        history_id = self.history_id
        self.history_id = None
        timer = getattr(self, '_history_timer', None)
        if timer is not None:
            timer.stop()
        if not history_id:
            return

        scene = getattr(self, 'scene', None)
        if scene is None:
            return

        try:
            from history import get_history_manager
            manager = get_history_manager()
        except Exception as e:
            log_exception(e, T("获取历史管理器"))
            return

        try:
            confirmed = bool(scene.selection_model.is_confirmed)
        except Exception:
            confirmed = False

        # 没有确认过选区 = 用户只是误触了一下截图，不该在历史里留记录
        if not confirmed:
            manager.discard(history_id)
            return

        state = self._build_history_state()
        if state is None:
            manager.mark_ready(history_id)
            return
        manager.persist(history_id, state, self._render_history_preview(),
                        status=_status_ready())

    def _flush_history_state(self, *_args):
        """强制把当前工程状态写进历史（关键出口调用，不走防抖）。"""
        history_id = self.history_id
        timer = getattr(self, '_history_timer', None)
        if timer is not None:
            timer.stop()
        if not history_id:
            return
        scene = getattr(self, 'scene', None)
        if scene is None:
            return
        state = self._build_history_state()
        if state is None:
            return
        try:
            from history import get_history_manager
            confirmed = bool(scene.selection_model.is_confirmed)
            get_history_manager().persist(
                history_id, state, self._render_history_preview(),
                status=_status_ready() if confirmed else None,
            )
        except Exception as e:
            log_exception(e, T("保存历史状态"))

    def _build_history_state(self) -> dict:
        """把当前场景序列化成一份可 JSON 化的工程状态。

        source.png 不在这里——那是母片，一条历史只写一次。这里存的是"编辑工程"：
        选区 + 全部矢量标注 + 序号计数 + 聚光灯暗度。
        """
        scene = getattr(self, 'scene', None)
        if scene is None:
            return None
        try:
            from history.annotation_codec import AnnotationCodec
            from history.models import SCHEMA_VERSION

            codec = AnnotationCodec()
            annotations = codec.serialize_all(scene.get_annotation_items())

            selection_rect = scene.selection_model.rect()
            scene_rect = scene.scene_rect
            state = {
                "schema_version": SCHEMA_VERSION,
                "scene_rect": {
                    "x": float(scene_rect.x()), "y": float(scene_rect.y()),
                    "width": float(scene_rect.width()),
                    "height": float(scene_rect.height()),
                },
                "selection": {
                    "confirmed": bool(scene.selection_model.is_confirmed),
                    "x": float(selection_rect.x()), "y": float(selection_rect.y()),
                    "width": float(selection_rect.width()),
                    "height": float(selection_rect.height()),
                },
                "annotations": annotations,
            }

            # 序号：记下"下一个该用几"，继续标注以后新增的序号从它接着走
            try:
                from tools.number import NumberTool
                state["number_next"] = int(NumberTool.get_next_number(scene))
            except Exception as e:
                log_debug(T("记录序号计数器失败: {error}", error=str(e)), "ScreenshotWindow")

            # 聚光灯的暗度属于整张幕布而不是某个孔，单独记一份
            try:
                from canvas.items import SpotlightCurtain
                curtain = SpotlightCurtain.find(scene)
                if curtain is not None:
                    state["spotlight_darkness"] = float(curtain.opacity())
            except Exception as e:
                log_debug(T("记录聚光灯暗度失败: {error}", error=str(e)), "ScreenshotWindow")

            return state
        except Exception as e:
            log_exception(e, T("序列化历史状态"))
            return None

    def _render_history_preview(self):
        """历史列表用的缩略图：背景 + 当前标注的扁平预览。

        selection 还没确认时退化成母片本身——列表里总得有个东西可看，而
        这时候也确实没有"选区内容"可言。
        """
        scene = getattr(self, 'scene', None)
        if scene is None:
            return None
        try:
            if scene.selection_model.is_confirmed:
                rect = scene.selection_model.rect()
                if not rect.isEmpty():
                    image = self.action_handler.export_service.export(rect)
                    if image is not None and not image.isNull():
                        return image
        except Exception as e:
            log_debug(T("生成历史预览失败: {error}", error=str(e)), "ScreenshotWindow")

        image = getattr(self, 'original_image', None)
        if image is not None and not image.isNull():
            from PySide6.QtGui import QImage
            return QImage(image)
        return None

    def _restore_history_state(self, state):
        """把历史工程状态还原进刚建好的场景。

        Undo 栈在最后被清空：载入的这 N 个标注是"这张历史工程的初始状态"，
        不是用户刚做的 N 次操作。恢复之后 Ctrl+Z 只撤销新动作。
        """
        scene = getattr(self, 'scene', None)
        if scene is None:
            return
        state = state if isinstance(state, dict) else {}

        annotations = state.get("annotations") or []
        if annotations:
            try:
                from history.annotation_codec import AnnotationCodec
                AnnotationCodec().restore_all(scene, annotations)
            except Exception as e:
                log_exception(e, T("恢复历史标注"))

        self._restore_history_selection(state.get("selection"))
        self._restore_number_counter(state.get("number_next"))
        self._restore_spotlight_darkness(state.get("spotlight_darkness"))

        # 旧标注视为基线：清掉撤销栈，用户之后的操作才进新的撤销栈
        try:
            if hasattr(scene, 'undo_stack') and scene.undo_stack is not None:
                scene.undo_stack.clear()
        except Exception as e:
            log_debug(T("清空撤销栈失败: {error}", error=str(e)), "ScreenshotWindow")

        # 默认回到光标工具：不要保留按 H 之前的矩形/备注工具，避免一回来就误画
        if hasattr(self, 'toolbar') and self.toolbar is not None:
            self.toolbar.select_tool("cursor", toggle=False)
        if hasattr(scene, 'activate_tool'):
            scene.activate_tool("cursor")

    def _restore_history_selection(self, selection):
        if not isinstance(selection, dict) or not selection.get("confirmed"):
            return
        try:
            rect = QRectF(
                float(selection.get("x", 0.0) or 0.0),
                float(selection.get("y", 0.0) or 0.0),
                float(selection.get("width", 0.0) or 0.0),
                float(selection.get("height", 0.0) or 0.0),
            )
        except (TypeError, ValueError):
            return
        if rect.width() < 1.0 or rect.height() < 1.0:
            return
        self.scene.selection_model.initialize_confirmed_rect(rect)
        self.scene.selection_item.show()
        # selection_model.confirmed 没有对外接线，这里显式走窗口自己的确认收尾
        self.on_selection_confirmed()

    def _restore_number_counter(self, number_next):
        if not isinstance(number_next, int) or number_next < 1:
            return
        try:
            from tools.number import NumberTool
            NumberTool.set_next_number_and_refresh(
                self.scene, number_next, force_cursor=False
            )
        except Exception as e:
            log_debug(T("恢复序号计数器失败: {error}", error=str(e)), "ScreenshotWindow")

    def _restore_spotlight_darkness(self, darkness):
        if not isinstance(darkness, (int, float)):
            return
        try:
            from canvas.items import SpotlightCurtain
            curtain = SpotlightCurtain.find(self.scene)
            if curtain is not None:
                curtain.setOpacity(max(0.0, min(1.0, float(darkness))))
        except Exception as e:
            log_debug(T("恢复聚光灯暗度失败: {error}", error=str(e)), "ScreenshotWindow")

    def open_annotation_history(self):
        """H：先保存当前工程，再打开标注历史窗口。

        H 不要求选区已确认——刚进截图、还没框选时也要能翻历史。
        """
        if self._is_closing:
            return

        # 已经开着就别再开第二个（长按 H 的自动重复也走这条，见快捷键处理器）
        existing = getattr(self, '_history_dialog', None)
        if existing is not None and _is_alive(existing) and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return

        # 打开之前先 flush：历史列表里必须能看到"我现在这张"的最新状态
        self._flush_history_state()

        from ui.annotation_history_dialog import AnnotationHistoryDialog

        dialog = AnnotationHistoryDialog(self, current_history_id=self.history_id)
        self._history_dialog = dialog
        try:
            # 模态执行：截图快捷键处理器靠 activeModalWidget() 让出键盘，
            # 1~9 / H / Enter / Esc 不会穿透到下面的截图窗口。
            dialog.exec()
        except Exception as e:
            log_exception(e, T("打开标注历史窗口"))
        finally:
            self._history_dialog = None

        chosen = getattr(dialog, 'chosen_history_id', None)
        if chosen and chosen != self.history_id:
            self._switch_to_history(chosen)

    def _switch_to_history(self, history_id):
        """从当前会话切换到另一条历史：先把 A 落盘销毁，再载入 B。"""
        try:
            from history import get_history_manager
            manager = get_history_manager()
            record = manager.get_record(history_id)
            if record is None:
                show_modeless_warning_dialog(
                    self, T("继续标注"), T("这条历史不存在或已损坏。"))
                return
            state = manager.load_state(history_id)
            image = manager.load_source_image(history_id)
            if state is None or image is None or image.isNull():
                show_modeless_warning_dialog(
                    self, T("继续标注"), T("这条历史的母片或工程状态已损坏，无法继续标注。"))
                return

            rect = QRectF(float(record.virtual_x), float(record.virtual_y),
                          float(record.virtual_width), float(record.virtual_height))
            if rect.width() < 1.0 or rect.height() < 1.0:
                rect = QRectF(0.0, 0.0, float(image.width()), float(image.height()))
            self._warn_if_history_offscreen(rect)

            log_info(T("切换到历史记录: {history_id}", history_id=history_id), "ScreenshotWindow")
            self._teardown_session()          # 内部会 flush A（未确认选区则丢弃）
            self.prepare_history_session(image, rect, state, history_id)
        except Exception as e:
            log_exception(e, T("切换历史记录"))

    def _warn_if_history_offscreen(self, rect: QRectF):
        """历史桌面不在当前屏幕范围内时留一条明确日志。

        数据坐标一律保持原始（不为了适应当前屏幕去改标注几何），窗口本身仍按
        历史的虚拟桌面几何摆放，所以桌面布局变了也只会"有一部分看不到"，
        不会损坏内容，也不会把窗口甩到屏幕外导致完全不可用。
        """
        self._history_offscreen = False
        try:
            from PySide6.QtGui import QGuiApplication
            screens = QGuiApplication.screens()
            if not screens:
                return
            bounds = QRectF(screens[0].geometry())
            for screen in screens[1:]:
                bounds = bounds.united(QRectF(screen.geometry()))
            intersection = QRectF(rect).intersected(bounds)
            if intersection.width() >= rect.width() - 1.0 and \
                    intersection.height() >= rect.height() - 1.0:
                return
            self._history_offscreen = True
            log_warning(
                T("历史桌面 {history_rect} 超出当前屏幕范围 {screen_rect}，只能在可见区域内继续标注",
                  history_rect=rect, screen_rect=bounds),
                "ScreenshotWindow",
            )
        except Exception as e:
            log_debug(T("检查历史桌面可见性失败: {error}", error=str(e)), "ScreenshotWindow")

    # ------------------------------------------------------------------
    # 窗口截图可见性控制
    # ------------------------------------------------------------------
    def _set_exclude_from_capture(self, exclude: bool):
        """设置本窗口是否对屏幕截图 API 不可见。
        
        使用 Windows 10 2004+ 的 WDA_EXCLUDEFROMCAPTURE 标志，
        让 mss / BitBlt / DXGI 等截图 API 在捕获屏幕时跳过本窗口。
        窗口在屏幕上仍然正常显示，用户看得到。
        """
        from core.platform_utils import set_window_exclude_from_capture, get_last_error
        hwnd = int(self.winId())
        result = set_window_exclude_from_capture(hwnd, exclude)
        if result:
            log_debug(T("SetWindowDisplayAffinity({mode}) 成功",
                         mode='EXCLUDE' if exclude else 'NONE'), "ScreenshotWindow")
        else:
            log_debug(T("SetWindowDisplayAffinity 失败, GetLastError={error_code}",
                         error_code=get_last_error()), "ScreenshotWindow")

    def _connect_toolbar_signals(self):
        """连接工具栏信号（一次性，toolbar→self 的稳定连接）。
        
        注意：toolbar→action_handler 的信号用 wrapper 方法间接调用，
        因为 action_handler 每次会话都会重建。
        """
        # 工具切换
        self.toolbar.tool_changed.connect(self.on_tool_changed)
        
        # 样式改变
        self.toolbar.color_changed.connect(self.on_color_changed)
        self.toolbar.stroke_width_changed.connect(self.on_stroke_width_changed)
        self.toolbar.opacity_changed.connect(self.on_opacity_changed)
        
        # 箭头/线条/序号样式为self方法，安全
        self.toolbar.arrow_style_changed.connect(self.on_arrow_style_changed)
        self.toolbar.line_style_changed.connect(self.on_line_style_changed)
        if hasattr(self.toolbar, "note_style_changed"):
            self.toolbar.note_style_changed.connect(self.on_note_style_changed)
        if hasattr(self.toolbar, "number_next_changed"):
            self.toolbar.number_next_changed.connect(self.on_number_next_changed)
        if hasattr(self.toolbar, "number_style_changed"):
            self.toolbar.number_style_changed.connect(self.on_number_style_changed)
        if hasattr(self.toolbar, "mosaic_style_changed"):
            self.toolbar.mosaic_style_changed.connect(self.on_mosaic_style_changed)
        if hasattr(self.toolbar, "mosaic_block_size_changed"):
            self.toolbar.mosaic_block_size_changed.connect(self.on_mosaic_block_size_changed)

        # 操作按钮 → wrapper 方法（间接调用 action_handler）
        self.toolbar.undo_clicked.connect(self.on_undo)
        self.toolbar.redo_clicked.connect(self.on_redo)
        self.toolbar.confirm_clicked.connect(self._handle_confirm)
        self.toolbar.cancel_clicked.connect(self.cleanup_and_close)
        self.toolbar.copy_clicked.connect(self._handle_copy)
        self.toolbar.save_clicked.connect(self._handle_save)
        self.toolbar.pin_clicked.connect(self._handle_pin)
        self.toolbar.long_screenshot_clicked.connect(self.start_long_screenshot_mode)
        self.toolbar.screenshot_translate_clicked.connect(self._handle_screenshot_translate)
        self.toolbar.text_recognize_clicked.connect(self._handle_text_recognize)
        self.toolbar.scan_code_clicked.connect(self._handle_scan_code)
        self.toolbar.gif_record_clicked.connect(self.start_gif_record_mode)

    def _connect_session_signals(self):
        """连接每次会话的信号（scene→self + toolbar→view.smart_edit_controller）。"""
        # 场景信号
        self.scene.selectionConfirmed.connect(self.on_selection_confirmed)
        self.scene.selection_model.rectChanged.connect(self.update_toolbar_position)
        self.scene.selection_model.draggingChanged.connect(self.on_selection_dragging_changed)
        
        # 文字工具信号连接（新 view 的 controller）
        if hasattr(self.view, 'smart_edit_controller'):
            controller = self.view.smart_edit_controller
            self.toolbar.text_font_changed.connect(controller.on_text_font_changed)
            self.toolbar.color_changed.connect(controller.on_text_color_changed)
            self.toolbar.text_background_changed.connect(controller.on_text_background_changed)
            self.toolbar.text_outline_changed.connect(controller.on_text_outline_changed)
            self.toolbar.text_shadow_changed.connect(controller.on_text_shadow_changed)

    # -- action_handler wrapper 方法（toolbar 信号的稳定接收端）--
    # 这四个出口都会结束或输出当前截图，先强制 flush 一次历史状态：
    # 用户"刚移动完一个备注就马上 Ctrl+C"时，历史里记的必须是移动后的位置。
    def _handle_confirm(self):
        self._flush_history_state()
        if self.action_handler:
            self.action_handler.handle_confirm()

    def _handle_copy(self):
        self._flush_history_state()
        if self.action_handler:
            self.action_handler.handle_copy()

    def _handle_save(self):
        self._flush_history_state()
        if self.action_handler:
            self.action_handler.handle_save()

    def _handle_pin(self):
        self._flush_history_state()
        if self.action_handler:
            self.action_handler.handle_pin()

    def _handle_screenshot_translate(self):
        if self.action_handler:
            self.action_handler.handle_screenshot_translate()

    def _handle_text_recognize(self):
        if self.action_handler:
            self.action_handler.handle_text_recognize()

    def _handle_scan_code(self):
        if self.action_handler:
            self.action_handler.handle_scan_code()

    def reload_shortcut_bindings(self):
        """应用内快捷键改完后立即生效：重载处理器绑定并刷新工具栏角标。

        截图窗口和工具栏都是复用的实例，改完快捷键不需要退出重开截图。
        """
        handler = getattr(self, "_shortcut_handler", None)
        if handler is not None:
            handler.reload_bindings()
        toolbar = getattr(self, "toolbar", None)
        if toolbar is not None:
            toolbar.refresh_shortcut_badges()

    def _safe_activate_and_focus(self):
        """避免已销毁窗口执行激活/聚焦导致崩溃"""
        if getattr(self, "_is_closing", False):
            return
        try:
            import shiboken6
            if not shiboken6.isValid(self):
                return
        except Exception as e:
            log_exception(e, T("shiboken6 有效性检查"))
        try:
            if not self.isVisible():
                return
            self.activateWindow()
            self.setFocus()
        except RuntimeError:
            # 窗口已被删除或无效
            return

    def on_selection_dragging_changed(self, is_dragging: bool):
        """
        选区拖拽状态改变时的处理
        拖拽时隐藏工具栏，结束拖拽后显示并更新位置
        """
        if self._is_closing:
            return
        if not hasattr(self, 'toolbar'):
            return
            
        if is_dragging:
            # 开始拖拽：隐藏工具栏以减少重绘
            self.toolbar.hide()
            # 同时隐藏二级菜单
            if hasattr(self.toolbar, 'paint_menu') and self.toolbar.paint_menu.isVisible():
                self.toolbar.paint_menu.hide()
        else:
            # 结束拖拽：显示工具栏并更新位置
            if self.scene.selection_model.is_confirmed:
                self.toolbar.show()
                self.toolbar.raise_()
                self.update_toolbar_position()

    def on_selection_confirmed(self):
        if self._is_closing:
            return
        
        # 选区确认后，显示工具栏
        self.toolbar.show()
        self.toolbar.raise_()  # 只提升到顶层，不激活窗口
        self.update_toolbar_position()
        if hasattr(self, 'magnifier_overlay') and self.magnifier_overlay:
            self.magnifier_overlay.refresh()
        
        # 确保主窗口保持焦点
        self.activateWindow()
        self.setFocus()

        # 选区一确认，这条历史就从 draft 变成有效记录：此刻落一次盘，之后
        # 即使异常退出也不会被当成"误触草稿"清掉。
        self._flush_history_state()

    @safe_event
    def showEvent(self, event):
        """
        窗口显示事件 - 在窗口首次显示时初始化智能选区和放大镜
        """
        super().showEvent(event)

        if self._is_closing:
            return
        
        # 智能选区：根据当前鼠标位置立即显示选区预览
        if self.smart_selection_enabled:
            self._init_smart_selection_at_cursor()
        
        # 放大镜：在当前鼠标位置初始化
        self._init_magnifier_at_cursor()

    def _init_smart_selection_at_cursor(self):
        """根据当前鼠标位置初始化智能选区预览，在窗口显示后立即调用"""
        from PySide6.QtGui import QCursor
        from PySide6.QtCore import QPointF
        
        cursor_pos = QCursor.pos()
        scene_pos = QPointF(cursor_pos.x(), cursor_pos.y())
        
        if hasattr(self.view, '_get_smart_selection_rect'):
            smart_rect = self.view._get_smart_selection_rect(scene_pos)
            if not smart_rect.isEmpty():
                self.scene.selection_model.activate()
                # 首次出现没有起点可补间，直接到位
                self.view._apply_smart_selection_rect(smart_rect, animate=False)
                log_debug(T("智能选区初始化: 鼠标位置({x}, {y}) -> 选区{rect}",
                             x=cursor_pos.x(), y=cursor_pos.y(), rect=smart_rect), "ScreenshotWindow")

    def _init_magnifier_at_cursor(self):
        """在当前鼠标位置初始化放大镜，在窗口显示后立即调用"""
        from PySide6.QtGui import QCursor
        from PySide6.QtCore import QPointF
        
        if not (hasattr(self, 'magnifier_overlay') and self.magnifier_overlay):
            return
        cursor_pos = QCursor.pos()
        self.magnifier_overlay.update_cursor(QPointF(cursor_pos.x(), cursor_pos.y()))
        log_debug(T("放大镜初始化: 位置({x}, {y})", x=cursor_pos.x(), y=cursor_pos.y()), "ScreenshotWindow")

    @safe_event
    def resizeEvent(self, event):
        if self._is_closing:
            return
        self.view.setGeometry(self.rect())
        self.mask_overlay.setGeometry(self.rect())
        self.selection_overlay.setGeometry(self.rect())
        # 放大镜是独立小浮层，无需在 resizeEvent 中同步尺寸
        if self.scene.selection_model.is_confirmed:
            self.update_toolbar_position()
        super().resizeEvent(event)
        
    def update_toolbar_position(self):
        """更新工具栏位置 - 完全参考老代码的逻辑"""
        if self._is_closing:
            return
        if not hasattr(self, 'toolbar') or not self.toolbar.isVisible():
            return
            
        rect = self.scene.selection_model.rect()
        if rect.isEmpty():
            return
            
        # 将场景坐标转换为视图坐标
        view_polygon = self.view.mapFromScene(rect)
        view_rect = view_polygon.boundingRect()
        
        # 使用 View 作为父窗口进行坐标转换
        self.toolbar.position_near_rect(view_rect, self.view)
        
        # 如果二级菜单可见，也更新其位置（但不重复调用 show_paint_menu）
        if hasattr(self.toolbar, 'paint_menu') and self.toolbar.paint_menu.isVisible():
            # 直接更新二级菜单位置，不重新显示
            toolbar_pos = self.toolbar.pos()
            menu_x = toolbar_pos.x()
            menu_y = toolbar_pos.y() + self.toolbar.height() + 5
            
            # 检查屏幕边界
            screen = QApplication.screenAt(toolbar_pos)
            if screen:
                screen_rect = screen.geometry()
                if menu_y + self.toolbar.paint_menu.height() > screen_rect.y() + screen_rect.height():
                    menu_y = toolbar_pos.y() - self.toolbar.paint_menu.height() - 5
                if menu_x + self.toolbar.paint_menu.width() > screen_rect.x() + screen_rect.width():
                    menu_x = screen_rect.x() + screen_rect.width() - self.toolbar.paint_menu.width() - 5
            
            if self.toolbar.paint_menu.pos().x() != menu_x or self.toolbar.paint_menu.pos().y() != menu_y:
                self.toolbar.paint_menu.move(menu_x, menu_y)
    
    def cleanup_and_close(self):
        """结束当前截图会话 - 释放重数据，保留 UI 壳供下次复用。"""
        self._teardown_session()
        # 释放工作集（去抖：多次快速截图只触发最后一次，避免 page fault 风暴）
        from core.platform_utils import request_trim_working_set
        request_trim_working_set(1500)

    def full_destroy(self):
        """完全销毁窗口（应用退出时调用）。"""
        self._teardown_session()
        
        # 销毁所有缓存的 UI 壳
        if hasattr(self, 'toolbar') and self.toolbar:
            panel_names = ['paint_panel', 'shape_panel', 'arrow_panel', 'number_panel', 'text_panel']
            for panel_name in panel_names:
                panel = getattr(self.toolbar, panel_name, None)
                if panel:
                    panel.close()
                    panel.deleteLater()
            self.toolbar.close()
            self.toolbar.deleteLater()
            self.toolbar = None
        
        if hasattr(self, 'magnifier_overlay') and self.magnifier_overlay:
            self.magnifier_overlay.deleteLater()
            self.magnifier_overlay = None
        
        if hasattr(self, 'mask_overlay') and self.mask_overlay:
            self.mask_overlay.deleteLater()
            self.mask_overlay = None
        if getattr(self, 'selection_overlay', None) is not None:
            self.selection_overlay.deleteLater()
            self.selection_overlay = None
        
        if hasattr(self, 'info_panel') and self.info_panel:
            self.info_panel.deleteLater()
            self.info_panel = None
        
        gc.collect()
        self.close()
        self.deleteLater()

    @safe_event
    def keyPressEvent(self, event):
        """
        键盘事件处理 - 快捷键已委托给 ShortcutManager，
        此处仅保留文字编辑模式的事件传递。
        """
        super().keyPressEvent(event)

    def _is_text_editing(self) -> bool:
        focus_item = self.scene.focusItem() if hasattr(self.scene, 'focusItem') else None
        if isinstance(focus_item, QGraphicsTextItem) and focus_item.hasFocus():
            flags = focus_item.textInteractionFlags()
            return bool(flags & Qt.TextInteractionFlag.TextEditorInteraction)
        return False

    # --- 槽函数 ---

    def on_tool_changed(self, tool_id):
        """工具切换 - 确保主窗口保持焦点"""
        self.scene.activate_tool(tool_id)
        
        # 同步 UI：工具激活后，其设置已加载到 ToolContext，现在同步到工具栏 UI
        ctx = self.scene.tool_controller.ctx
        
        # 阻止工具栏信号，避免 set_xxx() 触发回调形成循环
        self.toolbar.blockSignals(True)
        try:
            # 每次激活都从当前工具上下文与持久化设置完整重建面板，避免
            # 跨工具临时投影残留到稍后的工具切换。
            self.toolbar.restore_active_tool_state(tool_id, ctx, self.scene)
        finally:
            self.toolbar.blockSignals(False)
        
        # 切换工具后，将焦点还给 View（确保快捷键可用）
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.view.setFocus)
        if hasattr(self, 'magnifier_overlay') and self.magnifier_overlay:
            self.magnifier_overlay.refresh()

    def on_number_next_changed(self, next_value: int):
        """序号工具下一数字变化 - 更新场景偏移和光标预览"""
        from tools.number import NumberTool

        NumberTool.set_next_number_and_refresh(self.scene, next_value)
        
    def on_number_style_changed(self, style: str):
        """序号样式改变，交给 NumberTool 统一处理。"""
        from tools.number import NumberTool

        NumberTool.apply_style_change(style, getattr(self, "view", None), self.scene.undo_stack)

    def on_color_changed(self, color):
        view = getattr(self, 'view', None)
        if view and hasattr(view, 'apply_cross_tool_selection_style'):
            consumed = view.apply_cross_tool_selection_style(color=color)
            if consumed is not None:
                return
        self.scene.update_style(color=color)
        
    def on_stroke_width_changed(self, width):
        view = getattr(self, 'view', None)
        if view and hasattr(view, 'apply_cross_tool_selection_style'):
            consumed = view.apply_cross_tool_selection_style(width=width)
            if consumed is not None:
                return
        ctx = getattr(self.scene.tool_controller, 'ctx', None)
        prev_width = max(1.0, float(getattr(ctx, 'stroke_width', width))) if ctx else float(width)
        self.scene.update_style(width=width)
        new_width = max(1.0, float(getattr(ctx, 'stroke_width', width))) if ctx else float(width)

        view = getattr(self, 'view', None)
        if view and hasattr(view, '_apply_size_change_to_selection') and prev_width > 0:
            scale = new_width / prev_width
            if abs(scale - 1.0) > 1e-6:
                view._apply_size_change_to_selection(scale)

        if view and hasattr(view, 'cursor_manager'):
            view.cursor_manager.update_tool_cursor_size(int(width))
        
    def on_opacity_changed(self, opacity_int):
        # opacity_int 是 0-255，转换为 0.0-1.0
        opacity = opacity_int / 255.0
        view = getattr(self, 'view', None)
        if view and hasattr(view, 'apply_cross_tool_selection_style'):
            consumed = view.apply_cross_tool_selection_style(opacity=opacity)
            if consumed is not None:
                return
        self.scene.update_style(opacity=opacity)
        if view and hasattr(view, '_apply_opacity_change_to_selection'):
            view._apply_opacity_change_to_selection(opacity)

    def on_arrow_style_changed(self, style: str):
        """箭头样式变化 - 更新当前选中的箭头图元"""
        
        # 获取 SmartEditController 中选中的图元
        if not hasattr(self.view, 'smart_edit_controller'):
            return
        
        controller = self.view.smart_edit_controller
        item = controller.selected_item
        
        # 检查是否是箭头图元
        from canvas.items import ArrowItem
        if isinstance(item, ArrowItem):
            if hasattr(item, 'arrow_style'):
                # 记录旧状态用于撤销
                old_state = self._capture_arrow_state(item)
                
                # 应用新样式
                item.arrow_style = style
                
                # 记录新状态
                new_state = self._capture_arrow_state(item)
                
                # 推送撤销命令
                from canvas.undo import EditItemCommand
                undo_stack = getattr(self.scene, 'undo_stack', None)
                if undo_stack:
                    command = EditItemCommand(item, old_state, new_state, "修改箭头样式")
                    undo_stack.push(command)
                
                item.update()
                log_debug(T("箭头样式已更新: {style}", style=style), "ScreenshotWindow")

    def on_note_style_changed(self, state: dict):
        """备注面板改动 → 应用到当前选中的那一条备注。

        撤销粒度在这里定死：颜色 / 线宽 / 透明度 / 字号是样式，和文字面板一样
        **不**进撤销栈（撤销栈留给画布内容，面板上调样式不该占掉用户的 Ctrl+Z）；
        方向改的是备注的排版结构，和拖目标框、拖文本宽度同类，一次改动推一条
        EditItemCommand。面板一次只发一条信号，所以一次操作最多也就一条命令。
        """
        from canvas.items import NoteItem

        controller = getattr(getattr(self, 'view', None), 'smart_edit_controller', None)
        item = getattr(controller, 'selected_item', None)
        if not isinstance(item, NoteItem):
            return

        editor = getattr(controller, 'layer_editor', None)
        direction = NoteItem.normalize_position(
            state.get('label_position', item.direction)
        )
        old_state = None
        if editor is not None and direction != item.direction:
            old_state = editor.capture_state(item)

        self._apply_note_style(item, state)

        if old_state is not None:
            new_state = editor.capture_state(item)
            if old_state != new_state:
                from canvas.undo import EditItemCommand
                undo_stack = getattr(self.scene, 'undo_stack', None)
                if undo_stack is not None:
                    command = EditItemCommand(item, old_state, new_state, T("修改备注方向"))
                    if hasattr(undo_stack, 'push_command'):
                        undo_stack.push_command(command)
                    else:
                        undo_stack.push(command)
        item.update()
        log_debug(T("备注样式已更新"), "ScreenshotWindow")

    @staticmethod
    def _apply_note_style(item, state: dict):
        """把面板状态落到一条备注上；state 里缺的字段保持原样。"""
        color = state.get("color")
        if isinstance(color, QColor) and color.isValid():
            item.set_note_color(color)

        width = state.get("stroke_width")
        if width is not None:
            item.set_note_stroke_width(float(width))

        font_size = state.get("font_size")
        if font_size is not None:
            item.set_note_font_size(int(font_size))

        opacity = state.get("opacity")
        if opacity is not None:
            item.set_visual_opacity(float(opacity))

        position = state.get("label_position")
        if position is not None:
            item.set_direction(position)

    def on_mosaic_style_changed(self, style: str):
        """马赛克种类变化（马赛克/模糊），交给 MosaicTool 统一处理。"""
        from tools.mosaic import MosaicTool

        if MosaicTool.apply_style_change(style, getattr(self, "view", None)):
            log_debug(T("马赛克种类已更新: {style}", style=style), "ScreenshotWindow")

    def on_mosaic_block_size_changed(self, block_size: int):
        """马赛克粒度变化，交给 MosaicTool 统一处理。"""
        from tools.mosaic import MosaicTool

        if MosaicTool.apply_block_size_change(block_size, getattr(self, "view", None)):
            log_debug(T("马赛克粒度已更新: {size}", size=block_size), "ScreenshotWindow")

    def on_line_style_changed(self, style: str):
        """线条样式变化 - 更新当前选中的画笔图元"""
        log_debug(f"line style change -> {style}", "ScreenshotWindow")
        view = getattr(self, 'view', None)
        if view and hasattr(view, '_apply_line_style_change_to_selection'):
            view._apply_line_style_change_to_selection(style)
            log_debug(T("线条样式已更新: {style}", style=style), "ScreenshotWindow")

    def _capture_arrow_state(self, item) -> dict:
        """捕获箭头图元的状态"""
        from PySide6.QtCore import QPointF
        state = {}
        if hasattr(item, 'start_pos'):
            state['start'] = QPointF(item.start_pos)
        if hasattr(item, 'end_pos'):
            state['end'] = QPointF(item.end_pos)
        if hasattr(item, '_control_pos'):
            state['control'] = QPointF(item._control_pos)
        if hasattr(item, '_control_modified'):
            state['control_modified'] = item._control_modified
        if hasattr(item, '_arrow_style'):
            state['arrow_style'] = item._arrow_style
        return state

    def on_undo(self):
        """撤销"""
        if self.scene.undo_stack.canUndo():
            self.scene.undo_stack.undo()
        
    def on_redo(self):
        """重做"""
        if self.scene.undo_stack.canRedo():
            self.scene.undo_stack.redo()
    
    def start_gif_record_mode(self):
        """启动 GIF 录制模式"""
        log_info(T("启动GIF录制模式"), "ScreenshotWindow")
        
        if self.scene.selection_model.is_confirmed:
            selection_rect = self.scene.selection_model.rect()
            
            real_x = int(selection_rect.x())
            real_y = int(selection_rect.y())
            real_width = int(selection_rect.width())
            real_height = int(selection_rect.height())
            
            capture_rect = QRect(real_x, real_y, real_width, real_height)
            log_debug(T("GIF录制区域: x={x}, y={y}, w={w}, h={h}",
                         x=real_x, y=real_y, w=real_width, h=real_height), "ScreenshotWindow")
            
            from gif import GifRecordWindow
            
            # 若已有旧的录制窗口（单例），先关闭并释放资源
            app = QApplication.instance()
            old_win = getattr(app, "_gif_window", None)
            if old_win is not None:
                try:
                    old_win.close_all()
                except Exception as e:
                    log_exception(e, T("关闭旧 GIF 窗口"))
                app._gif_window = None

            gif_win = GifRecordWindow(capture_rect)
            log_debug(T("GifRecordWindow已创建, overlay visible={visible}",
                         visible=gif_win._overlay.isVisible()), "ScreenshotWindow")
            
            # 把引用挂到 QApplication，防止截图窗口销毁后被 GC
            app = QApplication.instance()
            app._gif_window = gif_win
            
            # 窗口关闭后自动清除全局引用，释放内存
            gif_win.destroyed.connect(lambda: setattr(app, '_gif_window', None))
            log_info(T("GIF录制窗口已启动"), "ScreenshotWindow")
            
            # 关闭截图窗口
            self.cleanup_and_close()
        else:
            show_modeless_warning_dialog(self, "警告", "请先选择一个有效的截图区域！")

    def start_long_screenshot_mode(self):
        """启动长截图模式"""
        log_info(T("启动长截图模式"), "ScreenshotWindow")
        
        # 获取当前选中的区域
        if self.scene.selection_model.is_confirmed:
            selection_rect = self.scene.selection_model.rect()
            
            log_debug(T("selection_rect（场景坐标）: x={x}, y={y}, w={w}, h={h}",
                         x=selection_rect.x(), y=selection_rect.y(),
                         w=selection_rect.width(), h=selection_rect.height()), "LongScreenshot")
            log_debug(T("virtual偏移: x={x}, y={y}", x=self.virtual_x, y=self.virtual_y), "LongScreenshot")
            
            # 场景坐标已经是屏幕的全局坐标，背景图层通过 setOffset 保留了系统提供的虚拟桌面偏移
            # 因此此处不需要再次叠加 virtual_x / virtual_y，否则会导致坐标被重复平移
            real_x = int(selection_rect.x())
            real_y = int(selection_rect.y())
            real_width = int(selection_rect.width())
            real_height = int(selection_rect.height())
            
            # 创建屏幕坐标的选区矩形
            capture_rect = QRect(real_x, real_y, real_width, real_height)
            
            log_debug(T("选中区域（屏幕坐标）: x={x}, y={y}, w={w}, h={h}",
                         x=real_x, y=real_y, w=real_width, h=real_height), "LongScreenshot")
            
            # 保存配置，用于长截图窗口
            save_dir = self.config_manager.get_screenshot_save_path()
            
            # 创建独立的长截图窗口（不传递 parent，让它独立运行）。按需导入：长截图模块
            # 加载时就会读设置、配置拼接引擎，放在文件顶部会被启动预加载带进工作线程。
            from stitch import ScrollCaptureWindow
            scroll_window = ScrollCaptureWindow(capture_rect, parent=None, config_manager=self.config_manager)
            scroll_window.set_save_directory(save_dir)  # 设置保存目录
            
            # 把引用挂到 QApplication，防止截图窗口销毁后被 GC 回收
            app = QApplication.instance()
            old_scroll = getattr(app, "_scroll_window", None)
            if old_scroll is not None:
                try:
                    old_scroll.close()
                except Exception as e:
                    log_exception(e, T("关闭旧滚动截图窗口"))
            app._scroll_window = scroll_window
            
            # 窗口关闭后自动清除全局引用，释放内存
            def _on_scroll_window_destroyed():
                app._scroll_window = None
                from core.platform_utils import request_trim_working_set
                request_trim_working_set(1000)
            scroll_window.destroyed.connect(_on_scroll_window_destroyed)
            
            # 显示长截图窗口
            log_debug(T("长截图窗口创建完成，准备显示"), "LongScreenshot")
            scroll_window.show()
            scroll_window.raise_()
            scroll_window.activateWindow()

            log_info(T("滚动截图窗口已显示并激活"), "LongScreenshot")

            # 立即关闭截图窗口，释放内存
            log_debug(T("释放截图窗口内存"), "LongScreenshot")
            self.cleanup_and_close()
        else:
            # 如果没有确认选区，显示提示
            show_modeless_warning_dialog(self, "警告", "请先选择一个有效的截图区域！")

    @safe_event
    def closeEvent(self, event):
        """窗口关闭事件 - 确保资源被正确释放
        
        统一走 cleanup_and_close() 路径，避免遗漏资源释放。
        如果已经清理过（_is_closing=True），直接放行。
        """
        if not getattr(self, '_is_closing', False):
            # 尚未走过 cleanup_and_close，在这里补救
            self.cleanup_and_close()
        super().closeEvent(event)
