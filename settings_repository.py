"""Validated configuration recovery and atomic saves, independent of Qt widgets."""

import json
import logging
import os
from copy import deepcopy
from datetime import datetime
from decimal import InvalidOperation
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


def atomic_json(path: Path, value: dict) -> None:
    """Flush a complete sibling file before replacing the destination."""
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class SettingsRepository:
    def __init__(self, path: Path, normalize: Callable[[dict], dict]):
        self.path = path
        self.normalize = normalize
        self.notice = ""
        self.last_good = path.with_name("settings-last-good.json")

    def read(self, path: Path) -> dict:
        # Windows Notepad can add a UTF-8 BOM to otherwise valid JSON.
        value = json.loads(path.read_text("utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("设置文件顶层必须为对象")
        return self.normalize(value)

    def load(self, default: dict) -> dict:
        if not self.path.exists() and not any(self.path.parent.glob("settings-*.json")):
            return self.normalize(deepcopy(default))
        try:
            return self.read(self.path)
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            InvalidOperation,
        ):
            logger.exception("Configuration rejected: %s", self.path)

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        quarantine = self.path.with_name(f"settings-damaged-{stamp}.json")
        # Keep the original bytes for repair; never replace it with defaults here.
        if self.path.exists():
            try:
                quarantine.write_bytes(self.path.read_bytes())
            except OSError:
                logger.exception("Cannot preserve damaged configuration")

        backups = sorted(
            self.path.parent.glob("settings-before-*.json"),
            key=lambda entry: entry.stat().st_mtime_ns,
            reverse=True,
        )
        candidates = [
            self.last_good,
            self.path.with_name("settings-previous.json"),
            *backups,
        ]
        for backup in candidates:
            if not backup.is_file():
                continue
            try:
                config = self.read(backup)
            except (
                OSError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                InvalidOperation,
            ):
                logger.exception("Configuration backup rejected: %s", backup)
                continue
            self.notice = f"设置文件损坏，已从 {backup.name} 恢复到内存。"
            break
        else:
            config = self.normalize(deepcopy(default))
            self.notice = "设置文件损坏，未找到有效备份，已使用默认设置打开修复界面。"

        config["configuration_review_required"] = True
        self.notice += (
            "请在后台核对地址、打印机和价格后确认保存，再提交打印。原损坏文件已保留。"
        )
        logger.warning(self.notice)
        return config

    def save(self, config: dict) -> dict:
        validated = self.normalize(deepcopy(config))
        if self.path.is_file():
            try:
                previous = self.read(self.path)
            except (
                OSError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                InvalidOperation,
            ):
                previous = None
            if previous is not None:
                atomic_json(self.path.with_name("settings-previous.json"), previous)
        # A failure leaves either the old or the complete new primary file.
        atomic_json(self.path, validated)
        try:
            atomic_json(self.last_good, validated)
        except OSError:
            logger.exception("Primary configuration saved, last-good backup failed")
        return validated
