"""Desktop lifecycle and service availability regressions; no real startup writes."""

import tempfile
import unittest
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call, patch

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
)

import autostart
from app import Window
from core import DEFAULT, ServiceUnavailableError, Store, migrate_config, quote
from desktop_lifecycle import CloseChoiceDialog, DesktopLifecycle, activate_existing
from desktop_settings import PROJECT_URL, AboutPage, DesktopSettingsPage
from release_info import VERSION

APP = QApplication.instance() or QApplication([])


@contextmanager
def desktop_window(available=True, ipc=False):
    with tempfile.TemporaryDirectory() as directory:
        store = Store(directory)
        with (
            patch("app.Store", return_value=store),
            patch("app.installed_printers", return_value=[]),
            patch.object(
                QSystemTrayIcon, "isSystemTrayAvailable", return_value=available
            ),
            patch.object(QSystemTrayIcon, "show"),
        ):
            window = Window()
            window.desktop = DesktopLifecycle(window, enable_activation=ipc)
            window.show()
            APP.processEvents()
            try:
                yield window
            finally:
                window.busy = False
                window.desktop.tray.hide()
                window.desktop.activation_timer.stop()
                window.desktop = None
                window.close()
                store.db.close()


def choice(action, remember=False, accepted=True):
    dialog = MagicMock()
    dialog.action = action
    dialog.remember.isChecked.return_value = remember
    dialog.exec.return_value = (
        QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected
    )
    return dialog


class ServiceAvailabilityTests(unittest.TestCase):
    def config(self, version=4):
        config = deepcopy(DEFAULT)
        config["schema_version"] = version
        config["prices"] = [
            {
                "paper": "6寸相纸",
                "color": "彩色",
                "duplex": "单面",
                "unit": "张",
                "tiers": [[None, "1.00"]],
            }
        ]
        return config

    def item(self, duplex="单面"):
        return {
            "selected": [0, 1],
            "options": {
                "paper": "6寸相纸",
                "color": "彩色",
                "duplex": duplex,
                "copies": 1,
            },
        }

    def test_single_sided_photo_service_never_requires_duplex_price(self):
        for version in (0, 3, 4, 5):
            with self.subTest(version=version):
                config = migrate_config(self.config(version))
                self.assertFalse(config.get("billing_review_required"))
                self.assertEqual(len(config["prices"]), 1)
                self.assertEqual(quote(config, [self.item()])["total"], "2.00")
                with self.assertRaisesRegex(ServiceUnavailableError, "未提供服务"):
                    quote(config, [self.item("双面长边")])

    def test_previous_missing_price_warnings_are_removed_automatically(self):
        for message in (
            "6寸相纸 彩色：缺少双面价格，请补充或确认不提供该服务。",
            "6寸相纸 彩色：旧配置缺少双面价格，未擅自复制另一种价格，请补充或确认不提供该服务。",
        ):
            config = self.config()
            config.update(migration_notes=[message], billing_review_required=True)
            migrated = migrate_config(config)
            self.assertFalse(migrated.get("billing_review_required"))
            self.assertFalse(migrated.get("migration_notes"))
            self.assertEqual(quote(migrated, [self.item()])["total"], "2.00")
            self.assertEqual(migrate_config(migrated), migrated)

    def test_real_price_changes_remain_visible_and_block_until_review(self):
        config = self.config()
        genuine = "A4 黑白：旧长边/短边价格不同，双面暂按长边迁移，请核对。"
        config.update(
            migration_notes=[
                "6寸相纸 彩色：缺少双面价格，请补充或确认不提供该服务。",
                genuine,
            ],
            billing_review_required=True,
        )
        migrated = migrate_config(config)
        self.assertEqual(migrated["migration_notes"], [genuine])
        self.assertTrue(migrated["billing_review_required"])


class CloseBehaviorTests(unittest.TestCase):
    def test_failed_remember_does_not_pretend_choice_was_saved(self):
        with desktop_window() as window:
            with (
                patch(
                    "desktop_lifecycle.CloseChoiceDialog",
                    return_value=choice("tray", True),
                ),
                patch.object(window.store, "save", side_effect=OSError("disk full")),
                patch.object(QMessageBox, "warning"),
                self.assertLogs("desktop_lifecycle", level="ERROR"),
            ):
                window.closeEvent(QCloseEvent())
                self.assertFalse(window.isVisible())
                self.assertEqual(window.store.config["close_behavior"], "ask")

    def test_first_close_can_hide_and_remember_then_restore(self):
        with desktop_window() as window:
            with patch(
                "desktop_lifecycle.CloseChoiceDialog", return_value=choice("tray", True)
            ) as dialog:
                event = QCloseEvent()
                window.closeEvent(event)
                self.assertFalse(event.isAccepted())
                self.assertFalse(window.isVisible())
                self.assertEqual(window.store.config["close_behavior"], "tray")
                window.desktop.restore()
                self.assertTrue(window.isVisible())
                window.closeEvent(QCloseEvent())
                dialog.assert_called_once()

    def test_do_not_remember_choice_asks_next_time(self):
        with desktop_window() as window:
            with patch(
                "desktop_lifecycle.CloseChoiceDialog", return_value=choice("tray")
            ) as dialog:
                window.closeEvent(QCloseEvent())
                window.desktop.restore()
                window.closeEvent(QCloseEvent())
                self.assertEqual(dialog.call_count, 2)
                self.assertEqual(window.store.config["close_behavior"], "ask")

    def test_cancel_keeps_window_open(self):
        with desktop_window() as window:
            with patch(
                "desktop_lifecycle.CloseChoiceDialog",
                return_value=choice(None, accepted=False),
            ):
                event = QCloseEvent()
                window.closeEvent(event)
                self.assertFalse(event.isAccepted())
                self.assertTrue(window.isVisible())

    def test_exit_choice_remembered_and_finishes_application(self):
        with desktop_window() as window:
            with (
                patch(
                    "desktop_lifecycle.CloseChoiceDialog",
                    return_value=choice("exit", True),
                ),
                patch.object(window.desktop, "finish_exit") as finish,
            ):
                event = QCloseEvent()
                window.closeEvent(event)
                self.assertTrue(event.isAccepted())
                self.assertEqual(window.store.config["close_behavior"], "exit")
                finish.assert_called_once()

    def test_background_during_task_is_allowed_but_exit_is_blocked(self):
        with desktop_window() as window:
            window.store.config["close_behavior"] = "tray"
            window.busy = True
            window.closeEvent(QCloseEvent())
            self.assertFalse(window.isVisible())
            window.desktop.restore()
            window.desktop.exit_requested = True
            with (
                patch.object(QMessageBox, "information"),
                patch.object(window.desktop, "finish_exit") as finish,
            ):
                event = QCloseEvent()
                window.closeEvent(event)
                self.assertFalse(event.isAccepted())
                finish.assert_not_called()

    def test_unavailable_tray_cannot_hide_last_window(self):
        with desktop_window(available=False) as window:
            window.store.config["close_behavior"] = "tray"
            with patch(
                "desktop_lifecycle.CloseChoiceDialog",
                return_value=choice(None, accepted=False),
            ) as dialog:
                window.closeEvent(QCloseEvent())
                dialog.assert_called_once_with(window, False, False)
                self.assertTrue(window.isVisible())

    def test_tray_exit_bypasses_remembered_background_action(self):
        with desktop_window() as window:
            window.store.config["close_behavior"] = "tray"
            with (
                patch("desktop_lifecycle.CloseChoiceDialog") as dialog,
                patch.object(window.desktop, "finish_exit") as finish,
            ):
                window.desktop.request_exit()
                dialog.assert_not_called()
                finish.assert_called_once()

    def test_close_dialog_disables_actions_that_are_not_available(self):
        dialog = CloseChoiceDialog(None, False, True)
        self.assertFalse(dialog.background_button.isEnabled())
        self.assertFalse(dialog.exit_button.isEnabled())
        dialog.reject()

    def test_relaunch_signal_restores_hidden_instance(self):
        with desktop_window(ipc=True) as window:
            self.assertTrue(window.desktop.activation_timer.isActive())
            window.hide()
            self.assertTrue(activate_existing(window.store.root))
            window.desktop.check_activation()
            APP.processEvents()
            self.assertTrue(window.isVisible())


class StartupTests(unittest.TestCase):
    def test_frozen_command_quotes_paths_with_spaces(self):
        with (
            patch.object(autostart.sys, "frozen", True, create=True),
            patch.object(autostart.sys, "executable", r"C:\Print Shop\墨序.exe"),
        ):
            self.assertEqual(
                autostart.startup_command(), '"C:\\Print Shop\\墨序.exe" --startup'
            )

    def test_long_startup_path_is_rejected_before_registration(self):
        with (
            patch.object(autostart.sys, "frozen", True, create=True),
            patch.object(autostart.sys, "executable", "C:/" + "x" * 260 + ".exe"),
        ):
            with self.assertRaisesRegex(ValueError, "260"):
                autostart.startup_command()

    def test_default_settings_do_not_touch_startup_registration(self):
        store = SimpleNamespace(config={"autostart": False}, save=Mock())
        with (
            patch("autostart.write_registration") as write,
            patch("autostart.read_registration") as read,
        ):
            autostart.save_preferences(store, {"autostart": False})
            read.assert_not_called()
            write.assert_not_called()
            store.save.assert_called_once()

    def test_enable_and_disable_only_the_owned_user_run_value(self):
        registry = MagicMock()
        registry.HKEY_CURRENT_USER = "HKCU"
        registry.REG_SZ = 1
        registry.KEY_SET_VALUE = 2
        with patch("autostart.winreg", registry):
            autostart.write_registration("test-command")
            self.assertEqual(
                registry.CreateKeyEx.call_args.args[:2], ("HKCU", autostart.RUN_KEY)
            )
            self.assertEqual(
                registry.SetValueEx.call_args.args[1:],
                (autostart.VALUE_NAME, 0, 1, "test-command"),
            )
            autostart.write_registration(None)
            self.assertEqual(
                registry.DeleteValue.call_args.args[1], autostart.VALUE_NAME
            )

    def test_configuration_failure_rolls_back_startup_value(self):
        store = SimpleNamespace(
            config={"autostart": False}, save=Mock(side_effect=OSError("disk failure"))
        )
        with (
            patch("autostart.read_registration", return_value=None),
            patch("autostart.startup_command", return_value="new-command"),
            patch("autostart.write_registration") as write,
        ):
            with self.assertRaises(OSError):
                autostart.save_preferences(store, {"autostart": True})
            self.assertEqual(write.call_args_list, [call("new-command"), call(None)])

    def test_registration_failure_does_not_save_a_false_success(self):
        store = SimpleNamespace(config={"autostart": False}, save=Mock())
        with (
            patch("autostart.read_registration", return_value=None),
            patch("autostart.startup_command", return_value="new-command"),
            patch(
                "autostart.write_registration", side_effect=PermissionError("blocked")
            ),
        ):
            with self.assertRaises(PermissionError):
                autostart.save_preferences(store, {"autostart": True})
            store.save.assert_not_called()


class DesktopSettingsTests(unittest.TestCase):
    def test_settings_dialog_saves_close_action_and_startup_toggle(self):
        from settings_ui import Settings

        with desktop_window() as window:
            dialog = Settings(window.store, window)
            self.assertEqual(
                dialog.tabs.tabText(dialog.tabs.indexOf(dialog.about_page)), "关于墨序"
            )
            dialog.desktop_page.ask_on_close.setChecked(False)
            dialog.desktop_page.close_action.setCurrentIndex(
                dialog.desktop_page.close_action.findData("exit")
            )
            dialog.desktop_page.autostart.setChecked(True)
            with (
                patch("autostart.read_registration", return_value=None),
                patch("autostart.startup_command", return_value="test-moxu --startup"),
                patch("autostart.write_registration") as write,
            ):
                dialog.save()
                write.assert_called_once_with("test-moxu --startup")
            self.assertTrue(window.store.config["autostart"])
            self.assertEqual(window.store.config["close_behavior"], "exit")
            dialog.desktop_page.autostart.setChecked(False)
            with (
                patch(
                    "autostart.read_registration", return_value="test-moxu --startup"
                ),
                patch("autostart.write_registration") as write,
            ):
                dialog.save()
                write.assert_called_once_with(None)
            self.assertFalse(window.store.config["autostart"])
            dialog.reject()

    def test_preferences_round_trip_and_ask_toggle(self):
        page = DesktopSettingsPage({"close_behavior": "exit", "autostart": True})
        self.assertEqual(page.value(), {"close_behavior": "exit", "autostart": True})
        self.assertTrue(page.close_action.isEnabled())
        page.ask_on_close.setChecked(True)
        self.assertFalse(page.close_action.isEnabled())
        self.assertEqual(page.value()["close_behavior"], "ask")
        page.close()

    def test_about_version_project_buttons_and_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            page = AboutPage(SimpleNamespace(root=Path(directory)))
            self.assertTrue(
                any(VERSION in label.text() for label in page.findChildren(QLabel))
            )
            self.assertIn(PROJECT_URL, page.project_link.text())
            with patch("desktop_settings.QDesktopServices.openUrl") as open_url:
                button = next(
                    button
                    for button in page.findChildren(QPushButton)
                    if button.text() == "打开 GitHub 项目"
                )
                button.click()
                self.assertEqual(open_url.call_args.args[0].toString(), PROJECT_URL)
            clipboard = Mock()
            with patch(
                "desktop_settings.QApplication.clipboard", return_value=clipboard
            ):
                page.copy_diagnostics("测试版")
            self.assertIn(VERSION, clipboard.setText.call_args.args[0])
            self.assertIn(PROJECT_URL, clipboard.setText.call_args.args[0])
            page.close()


if __name__ == "__main__":
    unittest.main()
