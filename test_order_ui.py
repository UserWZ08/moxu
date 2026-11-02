import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from app import Window
from core import DEFAULT, Store
from settings_ui import Settings

APP = QApplication.instance() or QApplication([])


class OrderUiTests(unittest.TestCase):
    def test_order_settings_pdf_plan_confirmation_and_dispatch_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            config = deepcopy(DEFAULT)
            config["printers"] = [
                {
                    "name": "HP TEST",
                    "enabled": True,
                    "dpi": [600, 1200],
                    "rules": [
                        {"paper": paper, "color": "黑白", "duplex": "单面"}
                        for paper in ["A4", "A5"]
                    ],
                }
            ]
            store.save(config)
            with (
                patch("app.Store", return_value=store),
                patch("app.installed_printers", return_value=["HP TEST"]),
                patch("printing.preview_margins", return_value=(0, 0, 0, 0)),
            ):
                window = Window()
                settings = Settings(store, window)
                settings.order_page.auto_print.setChecked(True)
                settings.order_page.print_paper.setCurrentText("A5")
                settings.order_page.print_color.setCurrentText("黑白")
                settings.order_page.print_printer.setCurrentText("HP TEST")
                settings.save()
                self.assertEqual(
                    store.config["order_print"],
                    {
                        "enabled": True,
                        "paper": "A5",
                        "color": "黑白",
                        "printer": "HP TEST",
                    },
                )
                path = Path(tmp) / "source.png"
                image = QImage(210, 297, QImage.Format.Format_RGB32)
                image.fill(QColor("white"))
                image.save(str(path))
                window.items = [
                    {
                        "source": str(path),
                        "prepared": str(path),
                        "kind": "image",
                        "count": 1,
                        "selected": [0],
                        "options": window.options(),
                        "status": "待打印",
                    }
                ]
                window.refresh()
                payload = window.payload()
                self.assertIsNotNone(payload["receipt_item"])
                self.assertEqual(payload["receipt_item"]["options"]["paper"], "A5")
                self.assertEqual(payload["receipt_item"]["options"]["duplex"], "单面")
                dialog = window.confirmation_dialog(payload)
                self.assertTrue(
                    any(
                        "另打印订单页" in label.text()
                        for label in dialog.findChildren(QLabel)
                    )
                )
                dialog.close()
                outputs = []

                def immediate(fn, done):
                    done(
                        fn(
                            SimpleNamespace(
                                progress=SimpleNamespace(emit=lambda value: None)
                            )
                        )
                    )

                with (
                    patch.object(window, "run", side_effect=immediate),
                    patch("app.make_printer", return_value=object()),
                    patch(
                        "app.render",
                        side_effect=lambda item, *args: outputs.append(
                            item.get("is_receipt", False)
                        ),
                    ),
                ):
                    window.dispatch(payload)
                self.assertEqual(outputs, [False, True])
                saved = json.loads(store.history()[0][3])
                self.assertEqual(saved["receipt_item"]["submitted_copies"], 1)
                self.assertEqual(store.history()[0][2], "已提交")
                # Invalid order printer must be caught before any document is submitted.
                outputs.clear()
                with (
                    patch.object(window, "run", side_effect=immediate),
                    patch(
                        "printing.preview_margins",
                        side_effect=RuntimeError("test preflight failure"),
                    ),
                    patch("app.render", side_effect=lambda *args: outputs.append(True)),
                    patch.object(QMessageBox, "warning"),
                ):
                    again = window.payload()
                    window.dispatch(again)
                self.assertEqual(outputs, [])
                self.assertTrue(
                    next(row for row in store.history() if row[0] == again["order_id"])[
                        2
                    ].startswith("提交前检查失败")
                )
                settings.close()
                window.close()
                store.db.close()


if __name__ == "__main__":
    unittest.main()
