"""Startup/close preferences and a local About page with explicit project links."""

import platform
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QUrl, qVersion
from PySide6.QtGui import QDesktopServices, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from controls import CleanCombo, Switch
from desktop_lifecycle import CLOSE_BEHAVIORS
from release_info import VERSION

PROJECT_URL = "https://github.com/UserWZ08/moxu"


class DesktopSettingsPage(QWidget):
    def __init__(self, configuration: dict, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        title = QLabel("启动与关闭")
        title.setStyleSheet("font-size:20px;font-weight:600")
        layout.addWidget(title)
        form = QFormLayout()
        self.ask_on_close = Switch("点击 X 时询问（不记住选择）")
        self.close_action = CleanCombo()
        for code, label in CLOSE_BEHAVIORS[1:]:
            self.close_action.addItem(label, code)
        form.addRow("关闭前询问", self.ask_on_close)
        form.addRow("记住的关闭方式", self.close_action)
        self.autostart = Switch("登录 Windows 后自动启动墨序")
        form.addRow("开机自启动", self.autostart)
        layout.addLayout(form)
        explanation = QLabel(
            "关闭前询问开启时，每次点击 X 都会让你选择退到后台或直接关闭。\n"
            "关闭询问后，按上面记住的方式执行；托盘菜单始终可以直接退出。\n\n"
            "自启动在保存设置后生效，默认关闭；自动启动后进入系统托盘。"
            "系统托盘不可用时显示主窗口。免安装版移动位置后，请重新开启自启动。"
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        layout.addStretch()
        self.ask_on_close.toggled.connect(self.sync_controls)
        self.load(configuration)

    def load(self, configuration: dict) -> None:
        behavior = configuration.get("close_behavior", "ask")
        self.ask_on_close.setChecked(behavior == "ask")
        self.close_action.setCurrentIndex(max(0, self.close_action.findData(behavior)))
        self.autostart.setChecked(configuration.get("autostart", False))
        self.sync_controls()

    def sync_controls(self, *args) -> None:
        self.close_action.setEnabled(not self.ask_on_close.isChecked())

    def value(self) -> dict:
        behavior = (
            "ask" if self.ask_on_close.isChecked() else self.close_action.currentData()
        )
        return {"close_behavior": behavior, "autostart": self.autostart.isChecked()}


class AboutPage(QWidget):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        header = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(
            QPixmap(str(Path(__file__).parent / "assets" / "moxu.png")).scaledToWidth(
                72
            )
        )
        header.addWidget(icon)
        name = QLabel(f"墨序\n版本 {VERSION}")
        name.setStyleSheet("font-size:23px;font-weight:600")
        header.addWidget(name)
        header.addStretch()
        layout.addLayout(header)
        description = QLabel("本地打印工作台 · 文件排版、设备分配、订单与客户管理")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.project_link = QLabel(f'<a href="{PROJECT_URL}">{PROJECT_URL}</a>')
        self.project_link.setOpenExternalLinks(True)
        self.update_link_color()
        layout.addWidget(self.project_link)
        links = QHBoxLayout()
        for label, suffix in [
            ("打开 GitHub 项目", ""),
            ("查看发布版本", "/releases"),
            ("报告问题 / 建议", "/issues/new/choose"),
        ]:
            button = QPushButton(label)
            button.clicked.connect(
                lambda checked=False, url=PROJECT_URL + suffix: self.open_url(url)
            )
            links.addWidget(button)
        layout.addLayout(links)
        form = QFormLayout()
        mode = (
            "免安装版"
            if getattr(sys, "frozen", False)
            and (Path(sys.executable).parent / "portable.flag").exists()
            else "安装版" if getattr(sys, "frozen", False) else "源码运行"
        )
        form.addRow("运行方式", QLabel(mode))
        form.addRow(
            "运行环境", QLabel(f"Python {platform.python_version()} · Qt {qVersion()}")
        )
        location = QLabel(str(store.root))
        location.setWordWrap(True)
        form.addRow("本机数据目录", location)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        data = QPushButton("打开数据目录")
        data.clicked.connect(lambda: self.open_folder(store.root))
        logs = QPushButton("打开日志目录")
        logs.clicked.connect(self.open_logs)
        notices = QPushButton("第三方组件声明")
        notices.clicked.connect(self.open_notices)
        copy = QPushButton("复制诊断信息")
        copy.clicked.connect(lambda: self.copy_diagnostics(mode))
        for button in (data, logs, notices, copy):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        note = QLabel(
            "版本与诊断信息在本机生成，不自动检查更新或上传文件。点击 GitHub 按钮后会用默认浏览器访问项目页面。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

    @staticmethod
    def open_url(url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def update_link_color(self) -> None:
        dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        color = "#ffb06e" if dark else "#a34d08"
        self.project_link.setText(
            f'<a style="color:{color}" href="{PROJECT_URL}">{PROJECT_URL}</a>'
        )

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "project_link"):
            self.update_link_color()

    @staticmethod
    def open_folder(path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def open_logs(self) -> None:
        directory = self.store.root / "logs"
        directory.mkdir(parents=True, exist_ok=True)
        self.open_folder(directory)

    def open_notices(self) -> None:
        candidates = [
            Path(__file__).parent / "THIRD_PARTY_NOTICES.md",
            Path(sys.executable).parent / "THIRD_PARTY_NOTICES.md",
        ]
        path = next((path for path in candidates if path.is_file()), None)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    @staticmethod
    def copy_diagnostics(mode: str) -> None:
        QApplication.clipboard().setText(
            f"墨序 {VERSION}\n运行方式：{mode}\nPython：{platform.python_version()}\nQt：{qVersion()}\n系统：{platform.system()} {platform.release()}\n项目：{PROJECT_URL}"
        )
