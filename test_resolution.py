import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QMarginsF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QFont,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QTransform,
)
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QApplication

from page_raster import Document, write_proof
from printing import render
from test_print_safety import item

APP = QApplication.instance() or QApplication([])


def text_fixture(path, landscape=False):
    writer = QPdfWriter(str(path))
    writer.setResolution(72)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0))
    p = QPainter(writer)
    for n in range(60):
        p.setFont(QFont("Microsoft YaHei", 4 + n % 8))
        p.drawText(
            QRectF(25, 10 + n * 13, 540, 16),
            f"文字清晰度 / Detail 0123456789 ABCDEFG - line {n}",
        )
    p.end()


class ResolutionTests(unittest.TestCase):
    def test_full_device_resolution_and_direct_scaled_pdf_tiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "text.pdf"
            text_fixture(path)
            obj = item(path)
            document = Document(obj)
            try:
                for paper, w, h in [("A4", 210, 297), ("A3", 297, 420)]:
                    document.item["options"]["paper"] = paper
                    document._options = None
                    for dpi in [600, 1200]:
                        plan = document.plan(0, dpi)
                        self.assertEqual(
                            plan["size"],
                            QSize(round(w * dpi / 25.4), round(h * dpi / 25.4)),
                        )
                        self.assertGreater(
                            plan["size"].width() * plan["size"].height(), 24_000_000
                        )
                plan = document.plan(0, 1200)
                with patch.object(
                    document.doc, "render", wraps=document.doc.render
                ) as renderer:
                    rect, image = next(document.bands(0, 1200))
                    settings = renderer.call_args.args[2]
                    self.assertEqual(settings.scaledSize(), plan["target"].size())
                    self.assertEqual(
                        settings.scaledClipRect().size(),
                        renderer.call_args.args[1] + QSize(1, 1),
                    )
                    self.assertLessEqual(image.width() * image.height(), 4_000_000)
                    self.assertEqual(image.width(), round(297 * 1200 / 25.4))
                    self.assertEqual(image.pixelColor(image.width() - 1, 0).red(), 255)
                del renderer
            finally:
                document.close()
                import gc

                gc.collect()

    def test_tiles_match_direct_render_without_boundary_seams(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "text.pdf"
            text_fixture(path)
            document = Document(item(path, "A4"))
            plan = document.plan(0, 100)
            stitched = QImage(plan["size"], QImage.Format.Format_RGB32)
            stitched.fill(Qt.GlobalColor.white)
            p = QPainter(stitched)
            for rect, image in document.bands(0, 100, maximum_band_pixels=90_000):
                p.drawImage(rect.topLeft(), image)
            p.end()
            raw = document.doc.render(0, plan["target"].size())
            expected = QImage(plan["size"], QImage.Format.Format_RGB32)
            expected.fill(Qt.GlobalColor.white)
            p = QPainter(expected)
            p.drawImage(plan["target"].topLeft(), raw)
            p.end()
            expected = expected.convertToFormat(
                QImage.Format.Format_Grayscale8
            ).convertToFormat(QImage.Format.Format_RGB32)
            self.assertEqual(bytes(stitched.constBits()), bytes(expected.constBits()))
            document.close()

    def test_non_square_device_dpi_preserves_physical_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "text.pdf"
            text_fixture(path)
            document = Document(item(path, "A4", fit="实际大小"))
            plan = document.plan(0, 600, 1200)
            self.assertAlmostEqual(
                plan["target"].width() / 600,
                plan["target"].height() / 1200 * 210 / 297,
                delta=0.01,
            )
            document.close()

    def test_mixed_orientation_tiles_match_rotated_full_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mixed.pdf"
            writer = QPdfWriter(str(path))
            writer.setResolution(72)
            writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            writer.setPageMargins(QMarginsF(0, 0, 0, 0))
            writer.setPageOrientation(QPageLayout.Orientation.Landscape)
            p = QPainter(writer)
            p.drawText(30, 40, "LANDSCAPE FIRST")
            writer.setPageOrientation(QPageLayout.Orientation.Portrait)
            writer.newPage()
            p.setFont(QFont("Microsoft YaHei", 12))
            p.drawText(30, 50, "ROTATE THIS PAGE")
            p.fillRect(QRectF(40, 80, 60, 30), Qt.GlobalColor.black)
            p.end()
            del writer
            obj = item(path, "A4")
            obj["selected"] = [0, 1]
            document = Document(obj)
            plan = document.plan(1, 100)
            self.assertTrue(plan["rotate"])
            stitched = QImage(plan["size"], QImage.Format.Format_RGB32)
            stitched.fill(Qt.GlobalColor.white)
            p = QPainter(stitched)
            for rect, image in document.bands(1, 100, maximum_band_pixels=70_000):
                p.drawImage(rect.topLeft(), image)
            p.end()
            target = plan["target"]
            raw = document.doc.render(
                1, QSize(target.height(), target.width())
            ).transformed(QTransform().rotate(90))
            expected = QImage(plan["size"], QImage.Format.Format_RGB32)
            expected.fill(Qt.GlobalColor.white)
            p = QPainter(expected)
            p.drawImage(target.topLeft(), raw)
            p.end()
            expected = expected.convertToFormat(
                QImage.Format.Format_Grayscale8
            ).convertToFormat(QImage.Format.Format_RGB32)
            document.close()
            # PDFium's shifted float matrix can slightly change glyph antialiasing.
            # Rotation must preserve geometry; allow small edge-tone differences.
            a = bytes(stitched.constBits())[::4]
            b = bytes(expected.constBits())[::4]
            delta = [abs(x - y) for x, y in zip(a, b)]
            ink = sum(min(x, y) < 245 for x, y in zip(a, b))
            self.assertLess(sum(delta) / len(delta), 0.02)
            self.assertLess(sum(delta) / max(1, ink), 3)

    def test_qt_print_never_uses_screen_raster_and_pdf_is_lossless(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "text.pdf"
            text_fixture(source)
            out = Path(tmp) / "print.pdf"
            printer = QPrinter()
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(out))
            printer.setResolution(600)
            printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            with patch.object(
                Document,
                "sheet",
                side_effect=AssertionError("screen raster used for output"),
            ):
                render(item(source, "A4"), printer)
            del printer
            self.assertNotIn(b"/DCTDecode", out.read_bytes())
            proof = Path(tmp) / "proof.pdf"
            with patch.object(
                Document,
                "sheet",
                side_effect=AssertionError("screen raster used for export"),
            ):
                write_proof(item(source, "A4"), proof)
            self.assertNotIn(b"/DCTDecode", proof.read_bytes())


if __name__ == "__main__":
    unittest.main()
