import base64
import ctypes as C
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter

import windows_driver as native
from coverage import estimate, pixel_metrics
from page_layout import placement


def sample_profile():
    raw = bytearray(228)
    struct.pack_into("<HH", raw, 68, 220, 8)
    struct.pack_into("<hh", raw, 90, 1200, 2)
    struct.pack_into("<h", raw, 96, 1200)
    raw[220:] = b"PRIVATE!"
    return {
        "printer": "TEST",
        "driver": {"name": "fake"},
        "devmode": base64.b64encode(raw).decode(),
        "name": "高",
    }


class RenderingTests(unittest.TestCase):
    def test_pdf_layout_modes(self):
        o = {"pdf_fit": "实际大小"}
        self.assertEqual(
            placement(100, 100, 200, 200, "pdf", o, (72, 72), 100), (50, 50, 100, 100)
        )
        o["pdf_fit"] = "自适应纸张"
        self.assertEqual(
            placement(100, 100, 200, 200, "pdf", o, (72, 72), 100), (0, 0, 200, 200)
        )
        o["pdf_fit"] = "仅缩小超大页面"
        self.assertEqual(
            placement(100, 100, 200, 200, "pdf", o, (72, 72), 100), (50, 50, 100, 100)
        )

    def test_metrics_white_black_half(self):
        img = QImage(100, 100, QImage.Format.Format_RGB32)
        for color, expected in [("white", 0), ("black", 100)]:
            img.fill(QColor(color))
            self.assertAlmostEqual(pixel_metrics(img)["area_percent"], expected)
        img.fill(QColor("white"))
        p = QPainter(img)
        p.fillRect(QRectF(0, 0, 50, 100), QColor("black"))
        p.end()
        self.assertAlmostEqual(pixel_metrics(img)["area_percent"], 50)

    def test_image_estimate_after_layout(self):
        with tempfile.TemporaryDirectory() as d:
            img = QImage(100, 100, QImage.Format.Format_RGB32)
            img.fill(QColor("black"))
            path = str(Path(d) / "black.png")
            img.save(path)
            item = {
                "kind": "image",
                "prepared": path,
                "selected": [0],
                "options": {"paper": "A4", "color": "黑白", "fit": "完整留白"},
            }
            whiteborder = estimate(item)["area_percent"]
            item["options"]["fit"] = "填充裁切"
            fill = estimate(item)["area_percent"]
            self.assertAlmostEqual(whiteborder, 210 / 297 * 100, delta=1)
            self.assertAlmostEqual(fill, 100, delta=0.1)

    def test_private_quality_bytes_preserved(self):
        profile = sample_profile()
        o = {"paper": "A3", "duplex": "双面短边", "color": "黑白"}
        blob = native.job_blob(profile, o)
        self.assertEqual(blob[220:], b"PRIVATE!")
        self.assertEqual(struct.unpack_from("<h", blob, 90)[0], 1200)
        self.assertEqual(struct.unpack_from("<h", blob, 96)[0], 1200)
        self.assertEqual(struct.unpack_from("<h", blob, 78)[0], 8)
        self.assertEqual(struct.unpack_from("<h", blob, 94)[0], 3)

    def test_invalid_driver_buffers_blocked(self):
        for raw in [b"bad", b"x" * 220]:
            with self.assertRaises(ValueError):
                native.validated_blob({"devmode": base64.b64encode(raw).decode()})

    def test_capture_never_updates_system_defaults(self):
        profile = sample_profile()
        raw = native.validated_blob(profile)
        flags_seen = []

        class Spool:
            def DocumentPropertiesW(self, hwnd, h, name, dest, source, flags):
                flags_seen.append(flags)
                if flags == 0:
                    return len(raw)
                C.memmove(dest, raw, len(raw))
                return 1

            def ClosePrinter(self, h):
                pass

        class Fake:
            spool = Spool()

            def open(self, name):
                return 1

            def fingerprint(self, h):
                return profile["driver"]

        with patch("windows_driver.API", return_value=Fake()):
            captured = native.capture("TEST")
        self.assertEqual(native.validated_blob(captured)[220:], b"PRIVATE!")
        self.assertEqual(flags_seen, [0, 2, 14])
        self.assertTrue(all(not f & 1 for f in flags_seen))

    def test_changed_buffer_size_blocks(self):
        profile = sample_profile()

        class Fake:
            def fingerprint(self, h):
                return profile["driver"]

            class spool:
                @staticmethod
                def DocumentPropertiesW(*args):
                    return 1024

        with self.assertRaises(RuntimeError):
            native.normalized_job(
                Fake(),
                1,
                "TEST",
                profile,
                {"paper": "A4", "color": "彩色", "duplex": "单面"},
            )

    def test_native_output_uses_full_profile_without_updates(self):
        profile = sample_profile()
        calls = []

        class Spool:
            def DocumentPropertiesW(self, hwnd, h, name, dest, source, flags):
                calls.append(("flags", flags))
                if flags == 0:
                    return 228
                C.memmove(dest, source, 228)
                return 1

            def ClosePrinter(self, h):
                pass

        class GDI:
            def CreateDCW(self, driver, name, output, blob):
                calls.append(("private", blob.raw[220:228]))
                return 10

            def GetDeviceCaps(self, dc, key):
                return {
                    8: 2480,
                    10: 3508,
                    88: 300,
                    90: 300,
                    110: 2480,
                    111: 3508,
                    112: 0,
                    113: 0,
                }[key]

            def StartDocW(self, *args):
                calls.append(("submitted", True))
                return 1

            def __getattr__(self, name):
                return lambda *args: 1

        class Fake:
            spool = Spool()
            gdi = GDI()

            def open(self, name):
                return 9

            def fingerprint(self, h):
                return profile["driver"]

        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "page.png")
            img = QImage(20, 20, QImage.Format.Format_RGB32)
            img.fill(QColor("white"))
            img.save(path)
            item = {
                "printer": "TEST",
                "kind": "image",
                "prepared": path,
                "selected": [0],
                "options": {
                    "paper": "A4",
                    "color": "彩色",
                    "duplex": "单面",
                    "fit": "完整留白",
                },
            }
            with patch("windows_driver.API", return_value=Fake()):
                native.print_item(item, profile)
        self.assertIn(("flags", 10), calls)
        self.assertIn(("private", b"PRIVATE!"), calls)
        self.assertIn(("submitted", True), calls)

    def test_driver_mismatch_blocks_before_submission(self):
        profile = sample_profile()

        class Fake:
            def fingerprint(self, h):
                return {"name": "new-driver"}

        with self.assertRaises(RuntimeError):
            native.normalized_job(Fake(), 1, "TEST", profile, {"paper": "A4"})


if __name__ == "__main__":
    unittest.main()
