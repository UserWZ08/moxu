import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication

from photo_layout import center_crop, layout_rects, write_pdf

_app = QApplication.instance() or QApplication([])


class PhotoTests(unittest.TestCase):
    def test_layouts_keep_physical_dimensions(self):
        pages = layout_rects((210, 297), (143, 105), 2, 10, 8)
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(pages[0]), 2)
        self.assertTrue(all(r[2:] == (143, 105) for r in pages[0]))
        with self.assertRaises(ValueError):
            layout_rects((89, 127), (143, 105), 2)

    def test_center_crop_has_requested_aspect(self):
        x, y, w, h = center_crop(1200, 800, 25 / 35)
        self.assertAlmostEqual(w * 1200 / (h * 800), 25 / 35)
        self.assertGreater(x, 0)

    def test_pdf_page_size_and_identity_image_dimensions(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "id.pdf"
            image = QImage(856, 540, QImage.Format.Format_RGB32)
            image.fill(QColor("black"))
            write_pdf(path, (210, 297), (85.6, 54), [image], 2, 10, 8, False)
            doc = QPdfDocument(None)
            self.assertEqual(doc.load(str(path)), QPdfDocument.Error.None_)
            size = doc.pagePointSize(0)
            self.assertAlmostEqual(size.width() * 25.4 / 72, 210, delta=0.2)
            self.assertAlmostEqual(size.height() * 25.4 / 72, 297, delta=0.2)
            rendered = doc.render(0, QSize(827, 1169))
            raster = QImage(827, 1169, QImage.Format.Format_RGB32)
            raster.fill(QColor("white"))
            p = QPainter(raster)
            p.drawImage(0, 0, rendered)
            p.end()
            doc.close()
            del doc
            raster = raster.convertToFormat(QImage.Format.Format_Grayscale8)
            raw = raster.constBits()
            stride = raster.bytesPerLine()
            segments = None
            row_count = 0
            for y in range(raster.height()):
                xs = [x for x in range(raster.width()) if raw[y * stride + x] < 40]
                if len(xs) > 300:
                    row_count += 1
                    if segments is None:
                        segments = []
                        start = previous = xs[0]
                        for x in xs[1:]:
                            if x > previous + 1:
                                segments.append(previous - start + 1)
                                start = x
                            previous = x
                        segments.append(previous - start + 1)
            self.assertEqual(len(segments), 2)
            for width in segments:
                self.assertAlmostEqual(width, 85.6 / 210 * 827, delta=3)
            self.assertAlmostEqual(row_count, 54 / 297 * 1169, delta=3)


if __name__ == "__main__":
    unittest.main()
