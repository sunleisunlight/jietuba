"""Per-user single instance with acknowledged activation; never kill an owner."""
import hashlib
import os
from pathlib import Path
import tempfile
import sys

from PySide6.QtCore import QObject, QLockFile, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def refuse_legacy_owner():
    """An older release has no activation protocol: ask for graceful exit."""
    if not getattr(sys, "frozen", False):
        return
    from core.platform_utils import get_process_identity
    path = Path(tempfile.gettempdir()) / (Path(sys.executable).name + ".pid")
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        pid = int(lines[0])
    except (OSError, ValueError, IndexError):
        return  # A corrupt record is not evidence of a running app.
    if pid == os.getpid():
        return
    live = get_process_identity(pid)
    if live and live[1].casefold() == Path(sys.executable).name.casefold():
        raise RuntimeError("旧版积磊截图仍在运行。请保存编辑或录制内容，从旧版菜单退出后再打开；不会强杀旧版。")


class InstanceBroker(QObject):
    activate_requested = Signal()

    def __init__(self, parent=None, *, directory=None, identity=None):
        super().__init__(parent)
        scope = identity or str(Path.home())
        folder = Path(directory or tempfile.gettempdir())
        suffix = hashlib.sha256(f"{scope}:{folder}".encode()).hexdigest()[:20]
        self.name = f"jilei-{suffix}"
        self.lock = QLockFile(str(folder / (self.name + ".lock")))
        # Qt still detects a dead PID; a long-lived app is never stale by age.
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept)
        self._sockets = set()

    def acquire(self, *, activate=True):
        if self.lock.tryLock(0):
            QLocalServer.removeServer(self.name)
            if not self.server.listen(self.name):
                self.lock.unlock()
                raise RuntimeError(f"无法建立单实例服务: {self.server.errorString()}")
            return True
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        if not socket.waitForConnected(3000):
            raise RuntimeError("积磊截图已有实例正在启动或暂时无响应，请稍后重试；不会终止原实例。")
        socket.write(b"activate\n" if activate else b"quiet\n")
        socket.flush()
        if not socket.waitForReadyRead(3000) or bytes(socket.readAll()) != b"ok\n":
            socket.abort()
            raise RuntimeError("已有实例未确认唤起请求，原实例保持不变。")
        socket.disconnectFromServer()
        return False

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self._sockets.add(socket)
            timeout = QTimer(socket)
            timeout.setSingleShot(True)
            timeout.timeout.connect(lambda s=socket: s.abort())
            timeout.start(4000)
            socket.readyRead.connect(lambda s=socket: self._receive(s))
            socket.disconnected.connect(lambda s=socket: self._release(s))
            if socket.bytesAvailable():
                self._receive(socket)

    def _receive(self, socket):
        if not socket.canReadLine():
            return
        message = bytes(socket.readLine(32))
        if message not in (b"activate\n", b"quiet\n"):
            socket.disconnectFromServer()
            return
        if message == b"activate\n":
            self.activate_requested.emit()
        socket.write(b"ok\n")
        socket.flush()
        socket.disconnectFromServer()

    def _release(self, socket):
        self._sockets.discard(socket)
        socket.deleteLater()

    def close(self):
        self.server.close()
        self.lock.unlock()
