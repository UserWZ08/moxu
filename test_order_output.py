import base64
import ctypes as C
import struct
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication

import windows_driver as native
from core import DEFAULT, order_quote
from order_pdf import receipt_item, write_order_pdf
from receipt import snapshot_template
from test_rendering import sample_profile

APP = QApplication.instance() or QApplication([])


def payload(count=2):
    items = [
        {
            "source": f"文件{n}_long_document_name_for_layout_test.docx",
            "selected": [0, 1, 2],
            "options": {
                "paper": "A4",
                "color": "黑白",
                "duplex": "双面短边",
                "copies": 2,
            },
            "printer": "测试打印机",
        }
        for n in range(count)
    ]
    config = deepcopy(DEFAULT)
    return {
        "order_id": "20261029-123456-abcdef",
        "community": "星河花园",
        "building": "12栋",
        "room": "1201",
        "customer": "测试客户",
        "phone": "13800000000",
        "qq": "123456",
        "wechat": "test_wechat",
        "note": "测试订单，请核对文件",
        "items": items,
        "quote": order_quote(config, items, "不装订", 1),
        "order_template": snapshot_template(config),
    }


class OrderOutputTests(unittest.TestCase):
    def test_order_pdf_sizes_text_and_multipage(self):
        with tempfile.TemporaryDirectory() as tmp:
            for paper, mm in [
                ("A4", (210, 297)),
                ("A5", (148, 210)),
                ("A3", (297, 420)),
            ]:
                path = Path(tmp) / (paper + ".pdf")
                count = write_order_pdf(
                    path,
                    "ORDER-TEST",
                    payload(40),
                    "已创建",
                    {"paper": paper, "color": "黑白"},
                )
                doc = QPdfDocument()
                self.assertEqual(doc.load(str(path)), QPdfDocument.Error.None_)
                size = doc.pagePointSize(0)
                self.assertAlmostEqual(size.width() * 25.4 / 72, mm[0], delta=0.2)
                self.assertAlmostEqual(size.height() * 25.4 / 72, mm[1], delta=0.2)
                self.assertGreater(count, 1)
                text = "".join(doc.getAllText(n).text() for n in range(count))
                self.assertIn("测试客户", text)
                self.assertIn("13800000000", text)
                self.assertIn("39", text)
                doc.close()
                del doc

    def test_order_pdf_monochrome_including_custom_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = payload()
            image = QImage(100, 100, QImage.Format.Format_RGB32)
            image.fill(QColor("red"))
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            data["order_template"]["images"] = [
                {
                    "data": base64.b64encode(bytes(buffer.data())).decode(),
                    "width_mm": 30,
                    "position": "顶部",
                }
            ]
            for color in ["黑白", "彩色"]:
                path = Path(tmp) / (color + ".pdf")
                write_order_pdf(
                    path, "TEST", data, "已创建", {"paper": "A5", "color": color}
                )
                doc = QPdfDocument()
                doc.load(str(path))
                img = doc.render(0, QSize(592, 840)).convertToFormat(
                    QImage.Format.Format_RGB32
                )
                raw = bytes(img.constBits())
                colored = sum(
                    abs(raw[i] - raw[i + 2]) > 30 for i in range(0, len(raw), 4)
                )
                (
                    self.assertEqual(colored, 0)
                    if color == "黑白"
                    else self.assertGreater(colored, 100)
                )
                doc.close()
                del doc

    def test_optional_receipt_separate_single_sided_one_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = deepcopy(DEFAULT)
            data = payload()
            self.assertIsNone(receipt_item(c, data, tmp, []))
            c["printers"] = [
                {
                    "name": "HP TEST",
                    "enabled": True,
                    "dpi": [600, 1200],
                    "rules": [{"paper": "A5", "color": "黑白", "duplex": "单面"}],
                }
            ]
            c["order_print"] = {
                "enabled": True,
                "paper": "A5",
                "color": "黑白",
                "printer": "HP TEST",
            }
            item = receipt_item(c, data, tmp, ["HP TEST"])
            self.assertEqual(item["options"]["copies"], 1)
            self.assertEqual(item["options"]["duplex"], "单面")
            self.assertEqual(item["printer"], "HP TEST")
            self.assertEqual(len(data["items"]), 2)

    def test_mono_driver_without_color_field_is_accepted_only_for_mono_hardware(self):
        profile = sample_profile()
        options = {"paper": "A4", "color": "黑白", "duplex": "双面短边"}

        class Spool:
            capability = 0
            wrong_copies = False

            def DocumentPropertiesW(self, hwnd, h, name, dest, source, flags):
                if flags == 0:
                    return 228
                raw = bytearray(source.raw)
                fields = struct.unpack_from("<I", raw, 72)[0]
                struct.pack_into("<I", raw, 72, fields & ~0x800)
                struct.pack_into("<h", raw, 92, 0)
                if self.wrong_copies:
                    struct.pack_into("<h", raw, 86, 2)
                C.memmove(dest, bytes(raw), 228)
                return 1

            def DeviceCapabilitiesW(self, *args):
                return self.capability

        class Fake:
            spool = Spool()

            def fingerprint(self, h):
                return profile["driver"]

        api = Fake()
        native.normalized_job(api, 1, "TEST", profile, options)
        api.spool.capability = 1
        with self.assertRaisesRegex(RuntimeError, "颜色"):
            native.normalized_job(api, 1, "TEST", profile, options)
        api.spool.capability = 0
        api.spool.wrong_copies = True
        with self.assertRaisesRegex(RuntimeError, "份数"):
            native.normalized_job(api, 1, "TEST", profile, options)
        api.spool.wrong_copies = False
        with self.assertRaisesRegex(RuntimeError, "颜色"):
            native.normalized_job(api, 1, "TEST", profile, dict(options, color="彩色"))


if __name__ == "__main__":
    unittest.main()
