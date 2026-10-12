# -*- coding: utf-8 -*-
"""积磊截图应用内更新：检查 → 提示 → 下载（进度）→ SHA-256 校验 → 重启替换。

交互对齐积磊其它桌面端（积磊ERP 等）：

- **启动后延迟 5 秒静默检查一次**，只有发现新版本才弹窗；无更新 / 网络失败一律静默；
- 运行期间每 2 小时静默复查一次，控制中心新上传版本后在线客户端也能收到提醒；
- 手动「检查更新」无论有没有新版都给反馈；
- 弹窗三选一：立即更新 / 稍后（本次不装，下次仍提示）/ 跳过此版本（记住该版本，
  后台检查不再提示，手动检查仍会提示）；
- 下载显示进度、可取消、失败重试；校验通过后一键重启安装。

线程约定（本模块最容易踩的坑，改动前务必读）：
网络检查与下载都在后台 QThread，**所有对话框只能在 GUI 线程创建**。因此后台线程的
信号一律连到本模块 QObject 的**绑定方法**槽，由 Qt 自动排队回 GUI 线程；把信号连到
普通函数 / 闭包会让槽在后台线程里执行，弹窗就会创建在非 GUI 线程上——表现正是
「点检查更新没反应、什么都不弹」。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QLabel, QProgressBar, QPushButton,
    QVBoxLayout,
)

from core import T
from core import updater
from core.logger import log_warning
from core.ui_scale import dialog_scaled
from core.ui_theme import get_ui_theme
from ui.dialogs import show_info_dialog
from ui.fluent_lite import PrimaryPushButton
from main_app import APP_VERSION

# 启动后多久做第一次静默检查（对齐积磊其它桌面端）
STARTUP_CHECK_DELAY_MS = 5_000
# 运行期间的静默复查间隔
PERIODIC_CHECK_INTERVAL_MS = 2 * 60 * 60 * 1000
# 正在框选 / 标注时推迟弹窗，避免打断用户
BUSY_RETRY_DELAY_MS = 30_000
# 下载失败重试次数（含首次）
DOWNLOAD_ATTEMPTS = 3

_SKIPPED_VERSION_KEY = "update/skipped_version"


def _settings() -> QSettings:
    return QSettings("JileiScreenshot", "JileiScreenshot")


def skipped_update_version() -> str:
    """用户点过「跳过此版本」的版本号（空串表示没有跳过任何版本）。"""
    return str(_settings().value(_SKIPPED_VERSION_KEY, "") or "")


def skip_update_version(version: str) -> None:
    s = _settings()
    s.setValue(_SKIPPED_VERSION_KEY, str(version or ""))
    s.sync()


def _format_size(size: int) -> str:
    if not size or size <= 0:
        return ""
    return f"{size / 1048576:.1f} MB"


class _CheckThread(QThread):
    """后台查询控制中心更新清单；结果经信号回 GUI 线程。

    ``check_for_update()`` 自身不抛异常，这里仍然兜底，避免线程里异常导致
    「点了没反应」（信号永远不发）。
    """

    done = Signal(object)   # updater.UpdateInfo | None

    def run(self) -> None:
        try:
            info = updater.check_for_update()
        except Exception as exc:      # noqa: BLE001 - 后台线程必须兜住，保证信号必达
            log_warning(T("检查更新失败: {e}", e=exc), "Updater")
            info = None
        self.done.emit(info)


class _DownloadThread(QThread):
    """后台下载更新包，失败自动重试。"""

    progress = Signal(int, int)
    downloaded = Signal(str)   # 新 exe 路径 | ""

    def __init__(self, info: updater.UpdateInfo, parent: QObject | None = None):
        super().__init__(parent)
        self.info = info
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        path = ""
        for attempt in range(DOWNLOAD_ATTEMPTS):
            path = updater.download_update(
                self.info,
                progress=lambda done, total: self.progress.emit(done, total),
                cancel_check=lambda: self._cancelled,
            )
            if path or self._cancelled:
                break
            if attempt + 1 < DOWNLOAD_ATTEMPTS:
                self.msleep(2000 * (attempt + 1))
        self.downloaded.emit(path or "")


class _UpdateDialog(QDialog):
    """发现新版本：立即更新 / 稍后 / 跳过此版本，下载时显示进度。"""

    def __init__(self, parent, info: updater.UpdateInfo):
        super().__init__(parent)
        self.info = info
        self._thread: _DownloadThread | None = None
        self._downloading = False

        self.setWindowTitle(self.tr("发现新版本"))
        self.setModal(True)
        self.setMinimumWidth(dialog_scaled(400))

        tokens = get_ui_theme().tokens
        muted = tokens.text_muted
        lay = QVBoxLayout(self)
        lay.setContentsMargins(dialog_scaled(22), dialog_scaled(20),
                               dialog_scaled(22), dialog_scaled(16))
        lay.setSpacing(dialog_scaled(12))

        title = QLabel(self.tr("发现新版本 v%1").replace("%1", info.version))
        f = title.font()
        f.setPixelSize(dialog_scaled(17))
        f.setBold(True)
        title.setFont(f)
        lay.addWidget(title)

        cur = QLabel(
            self.tr("当前版本 v%1 → 最新版本 v%2")
            .replace("%1", APP_VERSION).replace("%2", info.version)
        )
        cur.setStyleSheet(f"color: {muted};")
        lay.addWidget(cur)

        notes = QLabel(info.notes or self.tr("本次更新未提供详细说明。"))
        notes.setWordWrap(True)
        notes.setStyleSheet(
            f"color: {tokens.text}; background: rgba(255, 90, 31, 0.08);"
            f" border: 1px solid rgba(255, 90, 31, 0.28);"
            f" border-radius: 8px; padding: {dialog_scaled(10)}px;"
        )
        lay.addWidget(notes)

        size_text = _format_size(info.size)
        if size_text:
            size_label = QLabel(self.tr("安装包大小：%1").replace("%1", size_text))
            size_label.setStyleSheet(f"color: {muted};")
            lay.addWidget(size_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        lay.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        lay.addWidget(self.status)

        btns = QDialogButtonBox()
        self.install_btn = PrimaryPushButton(self.tr("立即更新"))
        self.later_btn = QPushButton(self.tr("稍后"))
        self.skip_btn = QPushButton(self.tr("跳过此版本"))
        btns.addButton(self.install_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        btns.addButton(self.later_btn, QDialogButtonBox.ButtonRole.RejectRole)
        btns.addButton(self.skip_btn, QDialogButtonBox.ButtonRole.DestructiveRole)
        lay.addWidget(btns)

        self.install_btn.clicked.connect(self._start_download)
        self.later_btn.clicked.connect(self._on_later_clicked)
        self.skip_btn.clicked.connect(self._on_skip_clicked)

    # -------------------------------------------------------------- 交互

    def reject(self) -> None:
        """下载中不接受 Esc / 关闭窗（线程还在跑），必须点「取消下载」，避免线程被析构。"""
        if self._downloading:
            return
        super().reject()

    def _on_later_clicked(self) -> None:
        """下载中是「取消下载」，否则只是关掉本次提示（下次仍会提示）。"""
        if self._downloading:
            if self._thread is not None:
                self._thread.cancel()
            self.status.setText(self.tr("已取消下载。"))
            self._reset_to_idle()
            return
        self.reject()

    def _on_skip_clicked(self) -> None:
        if self._downloading:
            return
        skip_update_version(self.info.version)
        self.reject()

    def _reset_to_idle(self) -> None:
        self._downloading = False
        self.progress.setVisible(False)
        self.install_btn.setEnabled(True)
        self.later_btn.setText(self.tr("稍后"))
        self.skip_btn.setEnabled(True)

    # -------------------------------------------------------------- 下载

    def _start_download(self) -> None:
        if self._downloading:
            return
        self._downloading = True
        self.install_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.later_btn.setText(self.tr("取消下载"))
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.status.setVisible(True)
        self.status.setText(self.tr("正在下载更新…"))

        self._thread = _DownloadThread(self.info, self)
        self._thread.progress.connect(self._on_progress)
        self._thread.downloaded.connect(self._on_downloaded)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_thread_finished(self) -> None:
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.deleteLater()

    @Slot(int, int)
    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            pct = max(0, min(100, int(done * 100 / total)))
            self.progress.setRange(0, 100)
            self.progress.setValue(pct)
            self.status.setText(
                self.tr("正在下载更新… %1%（%2 / %3）")
                .replace("%1", str(pct))
                .replace("%2", _format_size(done))
                .replace("%3", _format_size(total))
            )
        else:
            self.progress.setRange(0, 0)

    @Slot(str)
    def _on_downloaded(self, path: str) -> None:
        if not path:
            if self._downloading:
                # 下载失败：保留窗口，允许再点一次「立即更新」
                self.status.setText(self.tr("下载失败或完整性校验未通过，请检查网络后重试。"))
                self._reset_to_idle()
            return
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.status.setText(self.tr("下载完成，即将退出并安装新版本…"))
        if updater.install_and_restart(path):
            self.accept()
            return
        self.status.setText(
            self.tr("自动替换程序文件失败：请关闭软件后重试，或到积磊官网下载最新版。")
        )
        self._reset_to_idle()


class UpdateController(QObject):
    """更新检查的唯一入口（GUI 线程单例，见 ``get_update_controller``）。"""

    checking_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._thread: _CheckThread | None = None
        self._silent = False
        self._periodic_timer = None

    @property
    def is_checking(self) -> bool:
        return self._thread is not None

    def start_periodic(self, interval_ms: int = PERIODIC_CHECK_INTERVAL_MS) -> None:
        """运行期间按间隔静默复查，控制中心新上传版本后在线客户端也能收到提醒。"""
        from PySide6.QtCore import QTimer

        if self._periodic_timer is None:
            self._periodic_timer = QTimer(self)
            self._periodic_timer.timeout.connect(self._periodic_check)
        self._periodic_timer.setInterval(interval_ms)
        self._periodic_timer.start()

    @Slot()
    def _periodic_check(self) -> None:
        self.check(silent=True)

    def check(self, *, silent: bool = False) -> bool:
        """发起一次检查。返回 False 表示已有检查在进行。"""
        if self.is_checking:
            return False
        self._silent = silent
        thread = _CheckThread(self)
        self._thread = thread
        thread.done.connect(self._on_checked)
        thread.finished.connect(self._on_check_finished)
        self.checking_changed.emit(True)
        thread.start()
        return True

    @Slot()
    def _on_check_finished(self) -> None:
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.wait(2000)
            thread.deleteLater()
        self.checking_changed.emit(False)

    @Slot(object)
    def _on_checked(self, info) -> None:
        """后台线程的信号经 Qt 排队到这里，本方法保证运行在 GUI 线程。"""
        # 网络检查已经结束，按钮立刻恢复可点（后面的弹窗是模态的，不占忙碌态）
        self.checking_changed.emit(False)
        if info is None:
            if not self._silent:
                show_info_dialog(
                    self._dialog_parent(), self.tr("检查更新"),
                    self.tr("当前已是最新版本（v%1）。").replace("%1", APP_VERSION),
                )
            return
        if self._silent and info.version == skipped_update_version():
            return
        _UpdateDialog(self._dialog_parent(), info).exec()

    def _dialog_parent(self):
        """弹窗父窗口：取当前活动窗口，避免持有可能已被销毁的设置窗口。"""
        return QApplication.activeWindow()


_controller: UpdateController | None = None


def get_update_controller() -> UpdateController:
    """GUI 线程内创建更新控制器（首次调用方必须在主线程）。"""
    global _controller
    if _controller is None:
        _controller = UpdateController()
    return _controller


def check_for_update_interactive() -> None:
    """关于页「检查更新」：手动检查，有没有新版都会给反馈。"""
    get_update_controller().check(silent=False)


def start_auto_update_checker() -> None:
    """启动后台静默复查：现在检查一次，此后每 2 小时一次，只有新版本才弹窗。"""
    controller = get_update_controller()
    controller.check(silent=True)
    controller.start_periodic()
