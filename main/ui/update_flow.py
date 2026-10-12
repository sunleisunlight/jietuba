# -*- coding: utf-8 -*-
"""积磊截图应用内更新交互：检查 → 展示 → 下载（进度）→ SHA-256 校验 → 重启替换。

所有网络/下载都在后台 QThread，UI 不卡顿。仅 Windows onefile 支持应用内重启安装；
其它环境或开发模式下回退为"已是最新/打开下载页"。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QProgressBar, QPushButton, QVBoxLayout,
)

from core import T
from core import updater
from core.ui_scale import dialog_scaled
from ui.dialogs import show_info_dialog, show_warning_dialog
from ui.fluent_lite import PrimaryPushButton
from main_app import APP_VERSION


class _CheckWorker(QObject):
    done = Signal(object)   # UpdateInfo | None

    def run(self):
        self.done.emit(updater.check_for_update())


class _DownloadWorker(QObject):
    progress = Signal(int, int)
    finished = Signal(str)   # new exe path | ""

    def __init__(self, info):
        super().__init__()
        self.info = info
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        path = updater.download_update(
            self.info,
            progress=lambda d, t: self.progress.emit(d, t),
            cancel_check=lambda: self._cancel,
        )
        self.finished.emit(path or "")


class _UpdateDialog(QDialog):
    """有新版本时展示版本说明并发起下载。"""

    def __init__(self, parent, info: updater.UpdateInfo):
        super().__init__(parent)
        self.info = info
        self.setWindowTitle(self.tr("发现新版本"))
        self.setModal(True)
        self.setMinimumWidth(dialog_scaled(360))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(dialog_scaled(20), dialog_scaled(18),
                               dialog_scaled(20), dialog_scaled(16))
        lay.setSpacing(dialog_scaled(12))

        title = QLabel(f"{self.tr('新版本')} v{info.version}")
        f = title.font(); f.setPixelSize(dialog_scaled(17)); f.setBold(True)
        title.setFont(f)
        title.setStyleSheet("color: #FF5A1F;")
        lay.addWidget(title)

        cur = QLabel(self.tr("当前版本：v%1").replace("%1", APP_VERSION))
        cur.setStyleSheet("color: #666;")
        lay.addWidget(cur)

        notes = QLabel(info.notes or self.tr("本次更新未提供详细说明。"))
        notes.setWordWrap(True)
        notes.setStyleSheet("color: #333; background: #FFF8F3; border: 1px solid #FFE1CF;"
                            f" border-radius: 8px; padding: {dialog_scaled(10)}px;")
        lay.addWidget(notes)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        self.progress.setTextVisible(True)
        lay.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        lay.addWidget(self.status)

        btns = QDialogButtonBox()
        self.install_btn = PrimaryPushButton(self.tr("立即更新"))
        self.later_btn = QPushButton(self.tr("以后再说"))
        btns.addButton(self.install_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        btns.addButton(self.later_btn, QDialogButtonBox.ButtonRole.RejectRole)
        lay.addWidget(btns)

        self.install_btn.clicked.connect(self._start_download)
        self.later_btn.clicked.connect(self.reject)

        self._thread = None
        self._worker = None

    def _start_download(self):
        self.install_btn.setEnabled(False)
        self.later_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.status.setVisible(True)
        self.status.setText(self.tr("正在下载更新…"))

        self._thread = QThread(self)
        self._worker = _DownloadWorker(self.info)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_downloaded)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_progress(self, done: int, total: int):
        if total > 0:
            pct = max(0, min(100, int(done * 100 / total)))
            self.progress.setValue(pct)
            mb = done / 1048576
            total_mb = total / 1048576
            self.status.setText(self.tr("正在下载更新… %1%（%2%.1f / %3%.1f MB）")
                                .replace("%1", str(pct))
                                .replace("%2", f"{mb:.1f}")
                                .replace("%3", f"{total_mb:.1f}"))
        else:
            self.progress.setRange(0, 0)

    def _on_downloaded(self, path: str):
        self.progress.setRange(0, 100)
        if not path:
            self.status.setText(self.tr("下载失败或校验未通过，请稍后重试。"))
            show_warning_dialog(
                self, self.tr("更新失败"),
                self.tr("更新包下载失败或完整性校验未通过。你也可以到积磊官网下载最新版。"),
            )
            self.reject()
            return
        self.progress.setValue(100)
        self.status.setText(self.tr("下载完成，即将退出并安装新版本。"))
        if updater.install_and_restart(path):
            self.accept()
        else:
            show_warning_dialog(self, self.tr("无法自动安装"),
                                self.tr("请手动到积磊官网下载最新版。"))
            self.reject()


def check_and_offer_update(parent) -> None:
    """关于页「检查更新」入口：后台检查，有新版走应用内下载安装。"""
    thread = QThread(parent)
    worker = _CheckWorker()
    worker.moveToThread(thread)

    def cleanup():
        thread.quit()
        thread.wait(3000)

    def on_done(info):
        cleanup()
        if info is None:
            # 无更新（含网络失败：检查更新失败不打扰，按"已是最新"轻提示）
            show_info_dialog(parent, parent.tr("检查更新"),
                             parent.tr("当前已是最新版本（v%1）。").replace("%1", APP_VERSION))
            return
        dlg = _UpdateDialog(parent, info)
        dlg.exec()

    thread.started.connect(worker.run)
    worker.done.connect(on_done)
    thread.start()
    # 保持 worker 在线程结束前存活
    parent._update_check_worker = worker
    parent._update_check_thread = thread
