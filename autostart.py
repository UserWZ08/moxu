"""Opt-in Windows logon startup for the current user, with rollback on save errors."""

import logging
import subprocess
import sys
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

logger = logging.getLogger(__name__)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "MoXu.UserWZ08"


def startup_command() -> str:
    if getattr(sys, "frozen", False):
        arguments = [sys.executable, "--startup"]
    else:
        interpreter = Path(sys.executable)
        windowed = interpreter.with_name("pythonw.exe")
        arguments = [
            str(windowed if windowed.is_file() else interpreter),
            str(Path(__file__).with_name("app.py").resolve()),
            "--startup",
        ]
    command = subprocess.list2cmdline(arguments)
    if len(command) > 260:
        raise ValueError(
            "程序路径过长，Windows 自启动命令超过260字符；请将程序移到较短路径"
        )
    return command


def read_registration() -> str | None:
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE
        ) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return value
    except FileNotFoundError:
        return None


def write_registration(command: str | None) -> None:
    """Only edit this application's named value; never request administrator access."""
    if winreg is None:
        raise OSError("开机自启动仅支持 Windows")
    if command is not None:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
    else:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass


def save_preferences(store, configuration: dict) -> None:
    """Commit the requested startup toggle and configuration together, or roll back."""
    enabled = configuration.get("autostart", False)
    previous_enabled = store.config.get("autostart", False)
    previous_registration = read_registration() if enabled or previous_enabled else None
    requested = startup_command() if enabled else None
    changed = (enabled or previous_enabled) and requested != previous_registration
    if changed:
        write_registration(requested)
    try:
        store.save(configuration)
    except Exception:
        if changed:
            try:
                write_registration(previous_registration)
            except OSError:
                logger.exception("Failed to roll back startup registration")
        raise
