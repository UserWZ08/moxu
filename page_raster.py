"""One opaque, physical paper layout for previews, measurement and both print backends."""

from copy import deepcopy
from math import sqrt
from typing import Iterator, TypedDict

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QPainter, QTransform
from PySide6.QtPdf import QPdfDocument, QPdfDocumentRenderOptions

from catalog import paper_size

MM_PER_INCH = 25.4
PDF_POINTS_PER_INCH = 72
PRINT_BAND_PIXELS = 4_000_000
SCREEN_PAGE_PIXELS = 24_000_000


class RasterPlan(TypedDict):
    """Pixel coordinates on the full physical sheet, plus device margins."""

    size: QSize
    target: QRect
    area: QRectF
    rotate: bool
    options: dict
    dpi: tuple[float, float]


def opaque(image):
    if image.isNull():
        raise ValueError("页面图像为空")
    result = QImage(image.size(), QImage.Format.Format_RGB32)
    result.fill(Qt.GlobalColor.white)
    p = QPainter(result)
    p.drawImage(0, 0, image)
    p.end()
    return result


class Document:
    """One decoded input, with shared physical geometry for preview and output."""

    def __init__(self, item: dict):
        self.item = item
        self.doc = None
        self._image = None
        self._image_page = None
        self._options = None
        if item["kind"] == "pdf":
            self.doc = QPdfDocument(None)
            if self.doc.load(item["prepared"]) != QPdfDocument.Error.None_:
                raise ValueError("PDF 无法打开")

    def close(self) -> None:
        if self.doc:
            self.doc.close()
            self.doc = None
        self._image = None

    def image(self, page: int) -> QImage:
        if self._image_page == page and self._image is not None:
            return self._image
        path = (
            self.item["prepared"][page]
            if self.item["kind"] == "images"
            else self.item["prepared"]
        )
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            raise ValueError("图片无法读取")
        self._image = image
        self._image_page = page
        return image

    def dimensions(self, page: int) -> tuple[float, float]:
        if self.doc:
            s = self.doc.pagePointSize(page)
            return s.width(), s.height()
        image = self.image(page)
        return image.width(), image.height()

    def options(self) -> dict:
        if self._options is not None:
            return deepcopy(self._options)
        o = deepcopy(self.item["options"])
        if o.get("orientation", "auto") == "auto":
            w, h = self.dimensions(self.item["selected"][0])
            o["landscape"] = w > h
        self._options = o
        return deepcopy(o)

    def plan(
        self,
        page: int,
        xdpi: float,
        ydpi: float | None = None,
        margins=(0, 0, 0, 0),
        pixel_size: tuple[int, int] | None = None,
    ) -> RasterPlan:
        """Geometry at the output device's full resolution. No whole-page pixel cap."""
        ydpi = xdpi if ydpi is None else ydpi
        if min(xdpi, ydpi) <= 0:
            raise ValueError("输出分辨率无效")
        o = self.options()
        mw, mh = paper_size(o["paper"], o)
        if o.get("landscape"):
            mw, mh = mh, mw
        width, height = pixel_size or (
            round(mw * xdpi / MM_PER_INCH),
            round(mh * ydpi / MM_PER_INCH),
        )
        if min(width, height) <= 0:
            raise ValueError("输出页面尺寸无效")
        sx, sy = width / mw, height / mh
        left, top, right, bottom = margins
        aw, ah = mw - left - right, mh - top - bottom
        if min(aw, ah) <= 0:
            raise ValueError("打印边距超过纸张尺寸")
        iw, ih = self.dimensions(page)
        rotate = o.get("orientation", "auto") == "auto" and ((iw > ih) != (aw > ah))
        if rotate:
            iw, ih = ih, iw
        if self.doc:
            nw, nh = (
                iw * MM_PER_INCH / PDF_POINTS_PER_INCH,
                ih * MM_PER_INCH / PDF_POINTS_PER_INCH,
            )
            fit = min(aw / nw, ah / nh)
            mode = o.get("pdf_fit", "自适应纸张")
            if mode == "实际大小":
                ratio = 1
            elif mode == "仅缩小超大页面":
                ratio = min(1, fit)
            else:
                ratio = fit
            tw, th = nw * ratio, nh * ratio
        else:
            ratio = (max if o.get("fit") == "填充裁切" else min)(aw / iw, ah / ih)
            tw, th = iw * ratio, ih * ratio
        target = QRect(
            round((left + (aw - tw) / 2) * sx),
            round((top + (ah - th) / 2) * sy),
            max(1, round(tw * sx)),
            max(1, round(th * sy)),
        )
        area = QRectF(left * sx, top * sy, aw * sx, ah * sy)
        return {
            "size": QSize(width, height),
            "target": target,
            "area": area,
            "rotate": rotate,
            "options": o,
            "dpi": (xdpi, ydpi),
        }

    def bands(
        self,
        page,
        xdpi,
        ydpi=None,
        margins=(0, 0, 0, 0),
        pixel_size=None,
        maximum_band_pixels=PRINT_BAND_PIXELS,
    ) -> Iterator[tuple[QRect, QImage]]:
        """Render directly at final scale, in bounded strips; never enlarge a PDF raster."""
        plan = self.plan(page, xdpi, ydpi, margins, pixel_size)
        size = plan["size"]
        target = plan["target"]
        area = plan["area"]
        o = plan["options"]
        step = max(1, min(size.height(), maximum_band_pixels // size.width()))
        source = None
        if not self.doc:
            source = self.image(page)
            if plan["rotate"]:
                source = source.transformed(QTransform().rotate(90))
        for y in range(0, size.height(), step):
            rect = QRect(0, y, size.width(), min(step, size.height() - y))
            canvas = QImage(rect.size(), QImage.Format.Format_RGB32)
            canvas.fill(Qt.GlobalColor.white)
            painter = QPainter(canvas)
            painter.translate(0, -y)
            painter.setClipRect(area)
            try:
                if self.doc:
                    visible = rect.intersected(target).intersected(area.toAlignedRect())
                    if not visible.isEmpty():
                        image = self._render_pdf_tile(
                            page, target, visible, plan["rotate"]
                        )
                        # Alpha is composited onto white before any grayscale conversion.
                        painter.drawImage(visible.topLeft(), image)
                else:
                    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                    painter.drawImage(QRectF(target), source)
            finally:
                painter.end()
            if o["color"] == "黑白":
                canvas = canvas.convertToFormat(
                    QImage.Format.Format_Grayscale8
                ).convertToFormat(QImage.Format.Format_RGB32)
            yield rect, canvas

    def _render_pdf_tile(
        self, page: int, target: QRect, visible: QRect, rotate: bool
    ) -> QImage:
        """Isolate the Qt 6.8.3 clip/rotation compatibility workaround.

        Qt ignores rotation for scaled clips and uses inclusive QRect endpoints
        in the PDFium transform. Revalidate test_resolution before upgrading Qt.
        """
        clip = visible.translated(-target.x(), -target.y())
        scaled_size = target.size()
        if rotate:
            clip = QRect(
                clip.y(),
                target.width() - clip.x() - clip.width(),
                clip.height(),
                clip.width(),
            )
            scaled_size = QSize(target.height(), target.width())
        settings = QPdfDocumentRenderOptions()
        settings.setScaledSize(scaled_size)
        # An extra edge pixel cancels the implementation's (N-1)/N shrink.
        settings.setScaledClipRect(
            QRect(clip.x(), clip.y(), clip.width() + 1, clip.height() + 1)
        )
        image = self.doc.render(page, clip.size(), settings)
        if image.isNull():
            raise RuntimeError("PDF分块渲染失败")
        if rotate:
            image = image.transformed(QTransform().rotate(90))
        return image

    def sheet(
        self, page, dpi=110, margins=(0, 0, 0, 0), maximum_pixels=SCREEN_PAGE_PIXELS
    ) -> QImage:
        """Bounded screen/coverage raster only. Physical output must use bands()."""
        o = self.options()
        mw, mh = paper_size(o["paper"], o)
        if o.get("landscape"):
            mw, mh = mh, mw
        dpi = min(dpi, sqrt(maximum_pixels / (mw * mh)) * MM_PER_INCH)
        return next(
            self.bands(
                page, dpi, margins=margins, maximum_band_pixels=maximum_pixels + 100_000
            )
        )[1]


def resolved_options(item: dict) -> dict:
    document = Document(item)
    try:
        return document.options()
    finally:
        document.close()


def preview_sheet(item: dict, page: int, dpi: float = 90) -> QImage:
    document = Document(item)
    try:
        return document.sheet(page, dpi, item.get("preview_margins", (0, 0, 0, 0)))
    finally:
        document.close()


def write_proof(item: dict, path, dpi: int = 600) -> None:
    """File-only output with the same physical layout; never creates a printer job."""
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter

    document = Document(item)
    painter = QPainter()
    writer = None
    try:
        o = document.options()
        mw, mh = paper_size(o["paper"], o)
        writer = QPdfWriter(str(path))
        writer.setResolution(dpi)
        writer.setPageSize(QPageSize(QSizeF(mw, mh), QPageSize.Unit.Millimeter))
        writer.setPageOrientation(
            QPageLayout.Orientation.Landscape
            if o.get("landscape")
            else QPageLayout.Orientation.Portrait
        )
        writer.setPageMargins(QMarginsF(0, 0, 0, 0))
        if not painter.begin(writer):
            raise RuntimeError("无法写入预览PDF")
        painter.setRenderHint(QPainter.RenderHint.LosslessImageRendering)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        for n, page in enumerate(item["selected"]):
            if n and not writer.newPage():
                raise RuntimeError("无法写入预览页")
            full = writer.pageLayout().fullRectPixels(dpi)
            for rect, image in document.bands(
                page,
                dpi,
                margins=item.get("preview_margins", (0, 0, 0, 0)),
                pixel_size=(full.width(), full.height()),
            ):
                painter.drawImage(QRectF(rect), image)
    finally:
        if painter.isActive():
            painter.end()
        document.close()
