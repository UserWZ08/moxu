"""Close-button policy, tray lifecycle and local single-instance activation."""

import logging
import uuid
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
)

from controls import Switch
from release_info import VERSION

logger = logging.getLogger(__name__)
CLOSE_BEHAVIORS = [
    ("ask", "每次询问"),
    ("tray", "退到后台（系统托盘）"),
    ("exit", "直接关闭软件"),
]


def activate_existing(root: Path) -> bool:
    """Signal the locked instance through its private data directory; no listening port."""
    token = uuid.uuid4().hex
    temporary = root / f"activation-{token}.tmp"
    try:
        temporary.write_text(token, "ascii")
        temporary.replace(root / "activation.request")
        return True
    except OSError:
        logger.exception("Could not signal the existing instance")
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False


class CloseChoiceDialog(QDialog):
    def __init__(self, parent, tray_available: bool, busy: bool):
        super().__init__(parent)
        self.setWindowTitle("点击关闭按钮时")
        self.setMinimumWidth(470)
        self.action = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)
        title = QLabel("希望如何处理这个窗口？")
        title.setStyleSheet("font-size:18px;font-weight:600")
        layout.addWidget(title)
        description = QLabel(
            "退到后台后，转换与打印任务继续运行。可从任务栏右侧的墨序图标恢复窗口。"
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self.remember = Switch("记住本次选择（可在设置里修改）")
        layout.addWidget(self.remember)
        if not tray_available:
            layout.addWidget(QLabel("当前系统托盘不可用，不能退到后台。"))
        if busy:
            layout.addWidget(QLabel("当前任务进行中，完成后才可直接关闭。"))
        buttons = QHBoxLayout()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        self.background_button = QPushButton("退到后台")
        self.background_button.setObjectName("primary")
        self.background_button.setEnabled(tray_available)
        self.background_button.clicked.connect(lambda: self.choose("tray"))
        self.exit_button = QPushButton("直接关闭")
        self.exit_button.setEnabled(not busy)
        self.exit_button.clicked.connect(lambda: self.choose("exit"))
        for button in (cancel, self.background_button, self.exit_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def choose(self, action: str) -> None:
        self.action = action
        self.accept()


class DesktopLifecycle(QObject):
    """Installed by main(); unit-created Windows can still close without a prompt."""

    def __init__(self, window, enable_activation: bool = True):
        super().__init__(window)
        self.window = window
        self.exit_requested = False
        self.tray = QSystemTrayIcon(window.windowIcon(), self)
        self.tray.setToolTip(f"墨序 {VERSION} · 打印工作台")
        self.menu = QMenu(window)
        self.menu.addAction("打开打印工作台", self.restore)
        self.menu.addAction("后台设置", self.open_settings)
        self.menu.addSeparator()
        self.menu.addAction("退出墨序", self.request_exit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.activated)
        self.tray.messageClicked.connect(self.restore)
        if self.tray_available():
            self.tray.show()
        self.activation_path = window.store.root / "activation.request"
        self.last_activation = self.activation_signature()
        self.activation_timer = QTimer(self)
        self.activation_timer.setInterval(500)
        self.activation_timer.timeout.connect(self.check_activation)
        if enable_activation:
            self.activation_timer.start()

    def tray_available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.restore()

    def activation_signature(self):
        try:
            metadata = self.activation_path.stat()
            return metadata.st_mtime_ns, metadata.st_size
        except OSError:
            return None

    def check_activation(self) -> None:
        signature = self.activation_signature()
        if signature is None or signature == self.last_activation:
            return
        self.last_activation = signature
        if signature[1] != 32:
            return
        try:
            token = self.activation_path.read_text("ascii")
        except (OSError, UnicodeError):
            logger.warning("Could not read the activation request")
            return
        if len(token) == 32 and all(
            character in "0123456789abcdef" for character in token
        ):
            self.restore()

    def restore(self) -> None:
        self.window.setWindowState(
            self.window.windowState() & ~Qt.WindowState.WindowMinimized
        )
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def open_settings(self) -> None:
        self.restore()
        self.window.settings()

    def request_exit(self) -> None:
        self.exit_requested = True
        self.window.close()

    def intercept_close(self, event) -> bool:
        """Return True if the event was consumed; exit continues to Window's save."""
        if self.exit_requested:
            self.exit_requested = False
            return False
        available = self.tray_available()
        behavior = self.window.store.config.get("close_behavior", "ask")
        if behavior == "ask" or (behavior == "tray" and not available):
            dialog = CloseChoiceDialog(self.window, available, self.window.busy)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                event.ignore()
                return True
            behavior = dialog.action
            if dialog.remember.isChecked():
                config = deepcopy(self.window.store.config)
                config["close_behavior"] = behavior
                try:
                    self.window.store.save(config)
                except Exception:
                    logger.exception("Could not remember close-button choice")
                    QMessageBox.warning(
                        self.window,
                        "未能记住选择",
                        "本次操作仍会执行；下次关闭时会重新询问。",
                    )
        if behavior == "tray":
            self.tray.show()
            self.window.hide()
            event.ignore()
            return True
        return False

    def finish_exit(self) -> None:
        self.tray.hide()
        self.activation_timer.stop()
        QTimer.singleShot(0, QApplication.instance().quit)
