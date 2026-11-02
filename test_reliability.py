"""Business regressions from the P0/P1 review. All print backends are mocked."""

import io
import json
import logging
import queue
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

from openpyxl import Workbook
from PySide6.QtCore import QLockFile
from PySide6.QtGui import QCloseEvent, QImage
from PySide6.QtWidgets import QApplication, QMessageBox

import customers
import office
from app import Window
from core import DEFAULT, Store, migrate_config, quote, validate
from print_models import PrintItem, SubmissionState
from printing import prepare
from quality import resolve

APP = QApplication.instance() or QApplication([])


class ConfigurationRecoveryTests(unittest.TestCase):
    def test_bom_is_accepted_without_reset(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = deepcopy(DEFAULT)
            config["communities"] = {"原小区": ["17栋"]}
            Path(temporary, "settings.json").write_text(json.dumps(config), "utf-8-sig")
            store = Store(temporary)
            self.assertEqual(store.config["communities"], config["communities"])
            self.assertFalse(store.recovery_notice)
            store.db.close()

    def test_truncated_primary_recovers_saved_config_and_keeps_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(temporary)
            config = deepcopy(store.config)
            config["communities"] = {"原小区": ["17栋"]}
            store.save(config)
            identifier = store.order({"saved": True})
            customers.upsert(store.db, {"name": "原客户", "phone": "123"})
            store.db.close()
            store.path.write_bytes(b'{"broken":')
            with self.assertLogs("settings_repository", level="WARNING"):
                recovered = Store(temporary)
            self.assertEqual(recovered.config["communities"], config["communities"])
            self.assertTrue(recovered.config["configuration_review_required"])
            self.assertEqual(recovered.history()[0][0], identifier)
            self.assertEqual(customers.search(recovered.db)[0]["name"], "原客户")
            self.assertEqual(
                next(Path(temporary).glob("settings-damaged-*.json")).read_bytes(),
                b'{"broken":',
            )
            self.assertEqual(recovered.path.read_bytes(), b'{"broken":')
            recovered.db.close()

    def test_legacy_backup_recovery_and_no_backup_repair_mode(self):
        for backup in (True, False):
            with (
                self.subTest(backup=backup),
                tempfile.TemporaryDirectory() as temporary,
            ):
                Path(temporary, "settings.json").write_text("[]", "utf-8")
                if backup:
                    config = deepcopy(DEFAULT)
                    config["communities"] = {"备份小区": ["2栋"]}
                    Path(temporary, "settings-before-v5.json").write_text(
                        json.dumps(config), "utf-8"
                    )
                with self.assertLogs("settings_repository", level="WARNING"):
                    store = Store(temporary)
                self.assertTrue(store.config["configuration_review_required"])
                self.assertIn(
                    "备份小区" if backup else "示例小区", store.config["communities"]
                )
                store.db.close()

    def test_interrupted_save_does_not_destroy_primary(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(temporary)
            store.save(store.config)
            before = store.path.read_bytes()
            changed = deepcopy(store.config)
            changed["theme"] = "深色"
            original_replace = __import__("os").replace

            def fail_primary(source, destination):
                if destination == store.path:
                    raise OSError("simulated interruption")
                original_replace(source, destination)

            with patch("settings_repository.os.replace", side_effect=fail_primary):
                with self.assertRaises(OSError):
                    store.save(changed)
            self.assertEqual(store.path.read_bytes(), before)
            self.assertNotEqual(store.config["theme"], "深色")
            store.db.close()

    def test_missing_duplex_price_means_service_not_offered(self):
        for version in (0, 3, 4):
            config = deepcopy(DEFAULT)
            config["schema_version"] = version
            config["prices"] = [config["prices"][0]]
            migrated = migrate_config(config)
            self.assertEqual([rule["duplex"] for rule in migrated["prices"]], ["单面"])
            self.assertFalse(migrated.get("billing_review_required"))
            self.assertEqual(migrate_config(migrated), migrated)
            self.assertEqual(quote(migrated, [])["total"], "0.00")


class QualityAndImportTests(unittest.TestCase):
    def test_single_resolution_hp_and_unconfigured_epson_can_route(self):
        for name in ("HP 600", "EPSON L15158"):
            config = deepcopy(DEFAULT)
            config["printers"] = [{"name": name, "dpi": [600], "rules": []}]
            for level in ("标准打印", "高质量打印"):
                self.assertEqual(
                    resolve(config, name, {"quality_level": level})["dpi"], 600
                )
                self.assertIsNone(
                    resolve(config, name, {"quality_level": level})["profile"]
                )

    def test_binding_outside_supported_dpi_cannot_be_saved(self):
        config = deepcopy(DEFAULT)
        config["printers"] = [
            {
                "name": "HP",
                "dpi": [600],
                "rules": [],
                "quality_bindings": {"高质量打印": {"mode": "dpi", "dpi": 1200}},
            }
        ]
        with self.assertRaisesRegex(ValueError, "支持列表"):
            validate(config)

    def test_excel_patch_preserves_missing_columns_and_empty_cells(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(temporary)
            original = customers.upsert(
                store.db,
                {
                    "name": "张三",
                    "community": "星河",
                    "building": "12栋",
                    "room": "1201",
                    "wechat": "wx",
                    "phone": "111",
                },
            )
            workbook = Workbook()
            workbook.active.append(["客户编号", "手机号", "微信号"])
            workbook.active.append([original["id"], "222", ""])
            path = Path(temporary, "patch.xlsx")
            workbook.save(path)
            workbook.close()
            self.assertEqual(customers.import_xlsx(store.db, path), 1)
            result = customers.get(store.db, original["id"])
            self.assertEqual(result, dict(original, phone="222"))
            store.db.close()

    def test_excel_conflicting_identity_rolls_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(temporary)
            original = customers.upsert(store.db, {"name": "张三", "wechat": "wx"})
            workbook = Workbook()
            workbook.active.append(["客户编号", "姓名", "手机号"])
            workbook.active.append(["", "新增客户", "111"])
            workbook.active.append([original["id"], "另一个人", "222"])
            path = Path(temporary, "bad.xlsx")
            workbook.save(path)
            workbook.close()
            with self.assertRaisesRegex(ValueError, "姓名不符"):
                customers.import_xlsx(store.db, path)
            self.assertEqual(customers.search(store.db), [original])
            store.db.close()

    def test_three_page_tiff_preserves_all_frames(self):
        # Minimal uncompressed grayscale TIFF, independent of Pillow/libtiff tools.
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary, "scan.tiff")
            page_size = 2 + 9 * 12 + 4 + 4
            content = bytearray(b"II" + struct.pack("<HI", 42, 8))
            for page in range(3):
                start = 8 + page * page_size
                offset = start + 2 + 9 * 12 + 4
                tags = [
                    (256, 3, 1, 2),
                    (257, 3, 1, 2),
                    (258, 3, 1, 8),
                    (259, 3, 1, 1),
                    (262, 3, 1, 1),
                    (273, 4, 1, offset),
                    (277, 3, 1, 1),
                    (278, 4, 1, 2),
                    (279, 4, 1, 4),
                ]
                content.extend(struct.pack("<H", len(tags)))
                for tag in tags:
                    content.extend(struct.pack("<HHII", *tag))
                content.extend(struct.pack("<I", start + page_size if page < 2 else 0))
                content.extend(bytes([page * 100]) * 4)
            path.write_bytes(content)
            prepared, count, kind = prepare(path, Path(temporary, "cache"))
            self.assertEqual((count, kind), (3, "images"))
            self.assertEqual(
                [QImage(frame).pixelColor(0, 0).red() for frame in prepared],
                [0, 100, 200],
            )


class QueueAndUiTests(unittest.TestCase):
    def test_repeat_confirmation_cannot_be_bypassed_by_option_edit(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(temporary)
            with (
                patch("app.Store", return_value=store),
                patch("app.installed_printers", return_value=[]),
            ):
                window = Window()
                window.items = [
                    {
                        "source": "x.pdf",
                        "count": 1,
                        "status": "已提交",
                        "selected": [0],
                        "options": window.options(),
                    }
                ]
                PrintItem(window.items[0]).apply_options(window.options(), [0])
                with (
                    patch.object(window, "payload", return_value={}),
                    patch.object(
                        QMessageBox,
                        "question",
                        return_value=QMessageBox.StandardButton.No,
                    ) as question,
                    patch.object(window, "dispatch") as dispatch,
                ):
                    window.print_all()
                    question.assert_called_once()
                    dispatch.assert_not_called()
                window.close()
            store.db.close()

    def test_recovered_settings_cannot_print_until_reviewed(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(temporary)
            store.config["configuration_review_required"] = True
            with (
                patch("app.Store", return_value=store),
                patch("app.installed_printers", return_value=[]),
            ):
                window = Window()
                with self.assertRaisesRegex(ValueError, "恢复后的设置尚未核对"):
                    window.payload()
                window.close()
            store.db.close()

    def test_editing_preserves_submitted_and_uncertain_evidence(self):
        for state in (SubmissionState.SUBMITTED, SubmissionState.UNCERTAIN):
            record = {
                "source": "x.pdf",
                "status": "待打印",
                "options": {},
                "selected": [0],
            }
            model = PrintItem(record)
            model.finish_submission("old-order", 2, state)
            for copies in (3, 1, 5):
                model.apply_options({"copies": copies}, [0, 1])
                self.assertEqual(model.submission_state, state)
                self.assertTrue(model.needs_repeat_confirmation)
                self.assertEqual(record["last_order_id"], "old-order")
                self.assertEqual(record["submitted_copies"], 2)

    def test_settings_refresh_preserves_choices_and_missing_address_blocks(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(temporary)
            config = deepcopy(DEFAULT)
            config["communities"] = {"甲小区": ["1栋"], "乙小区": ["2栋", "12栋"]}
            config["printers"] = [
                {"name": name, "dpi": [600], "rules": []} for name in ("HP A", "HP B")
            ]
            store.save(config)
            with (
                patch("app.Store", return_value=store),
                patch("app.installed_printers", return_value=[]),
            ):
                window = Window()
                window.community.setCurrentText("乙小区")
                window.building.setCurrentText("12栋")
                window.printer.setCurrentText("HP B")
                window.binding.setCurrentText("胶装")
                window.reload_settings_choices()
                self.assertEqual(
                    (
                        window.community.currentText(),
                        window.building.currentText(),
                        window.printer.currentText(),
                        window.binding.currentText(),
                    ),
                    ("乙小区", "12栋", "HP B", "胶装"),
                )
                store.config["communities"].pop("乙小区")
                window.reload_settings_choices()
                self.assertEqual(window.community.currentIndex(), -1)
                window.items = [
                    {
                        "source": "x.pdf",
                        "count": 1,
                        "options": {},
                        "selected": [0],
                        "status": "待打印",
                    }
                ]
                with self.assertRaisesRegex(ValueError, "小区和楼栋"):
                    window.payload()
                with (
                    patch.object(store, "save", side_effect=ValueError("bad setting")),
                    self.assertLogs("app", level="ERROR"),
                ):
                    event = QCloseEvent()
                    window.closeEvent(event)
                    self.assertTrue(event.isAccepted())
                window.items = []
                window.close()
            store.db.close()


class OfficeSessionTests(unittest.TestCase):
    def test_owned_process_cleanup_terminates_only_registered_handle(self):
        import ctypes
        from ctypes import wintypes

        from office_processes import OwnedOfficeProcesses

        child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(45)"])
        owned = OwnedOfficeProcesses()
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            self.assertTrue(
                owned.kernel.GetProcessTimes(
                    int(child._handle), *(ctypes.byref(value) for value in times)
                )
            )
            timestamp = times[0].dwLowDateTime | (times[0].dwHighDateTime << 32)
            owned.register(child.pid, timestamp + 1)
            self.assertEqual(len(owned.handles), 0)
            self.assertIsNone(child.poll())
            owned.register(child.pid, timestamp)
            self.assertEqual(len(owned.handles), 1)
            owned.close()
            self.assertIsNotNone(child.wait(timeout=5))
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            owned.close()

    def test_timeout_clears_process_and_old_response_queue(self):
        session = office.ConversionSession(timeout=0.001)
        old = Mock()
        old.stdin = io.StringIO()
        old.stdout = io.StringIO()
        session.process = old
        session.owned = Mock()
        old_queue = session.responses
        with (
            self.assertLogs("office", level="ERROR"),
            self.assertRaisesRegex(RuntimeError, "会话已重置"),
        ):
            session.native(Path("a.docx"), Path("a.pdf"), "word")
        self.assertIsNone(session.process)

        old.kill.assert_called_once()
        old_queue.put({"code": 99})

        def restart():
            session.process = Mock(stdin=io.StringIO(), stdout=io.StringIO())
            session.responses = queue.Queue()
            session.responses.put({"code": 0})

        with patch.object(session, "_start", side_effect=restart):
            self.assertEqual(
                session.native(Path("b.docx"), Path("b.pdf"), "word"), {"code": 0}
            )
        session.close()

    def test_broken_pipe_resets_session(self):
        session = office.ConversionSession()
        process = Mock()
        process.stdin.write.side_effect = OSError(22, "invalid pipe")
        session.process = process
        with (
            self.assertLogs("office", level="ERROR"),
            self.assertRaisesRegex(RuntimeError, "重新建立会话"),
        ):
            session.native(Path("a.docx"), Path("a.pdf"), "word")
        self.assertIsNone(session.process)


class SingleInstanceTests(unittest.TestCase):
    def test_live_lock_is_protected_and_dead_process_lock_recovers(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary, "session.lock")
            script = (
                "from PySide6.QtCore import QCoreApplication,QLockFile;import sys,time;"
                "app=QCoreApplication([]);lock=QLockFile(sys.argv[1]);"
                "lock.setStaleLockTime(0);print(lock.tryLock(0),flush=True);time.sleep(45)"
            )
            child = subprocess.Popen(
                [sys.executable, "-c", script, str(path)],
                stdout=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(child.stdout.readline().strip(), "True")
                contender = QLockFile(str(path))
                contender.setStaleLockTime(0)
                self.assertFalse(contender.tryLock(0))
                child.kill()
                child.wait(timeout=5)
                self.assertTrue(contender.tryLock(0))
                contender.unlock()
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
                child.stdout.close()


class DiagnosticsTests(unittest.TestCase):
    def test_local_log_keeps_exception_stack_and_order_context(self):
        from diagnostics import configure_logging

        root_logger = logging.getLogger()
        old_handlers = list(root_logger.handlers)
        old_level = root_logger.level
        old_hook, old_thread_hook = sys.excepthook, threading.excepthook
        with tempfile.TemporaryDirectory() as temporary:
            try:
                configure_logging(Path(temporary))
                try:
                    raise RuntimeError("simulated driver failure")
                except RuntimeError:
                    logging.getLogger("print_jobs").exception(
                        "Order TEST-ORDER printer=TEST-PRINTER"
                    )
                path = Path(temporary, "logs", "moxu.log")
                for handler in root_logger.handlers:
                    handler.flush()
                contents = path.read_text("utf-8")
                self.assertIn("TEST-ORDER", contents)
                self.assertIn("TEST-PRINTER", contents)
                self.assertIn("Traceback", contents)
                self.assertIn("simulated driver failure", contents)
            finally:
                for handler in root_logger.handlers[:]:
                    if handler not in old_handlers:
                        root_logger.removeHandler(handler)
                        handler.close()
                root_logger.setLevel(old_level)
                sys.excepthook, threading.excepthook = old_hook, old_thread_hook


if __name__ == "__main__":
    unittest.main()
