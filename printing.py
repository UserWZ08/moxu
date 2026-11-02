"""Office conversion and Qt/Windows driver based rendering."""

import hashlib
from pathlib import Path

from PySide6.QtCore import QRectF, QSizeF
from PySide6.QtGui import QImageReader, QPageLayout, QPageSize, QPainter
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

from catalog import paper_size


def installed_printers():
    return [p.printerName() for p in QPrinterInfo.availablePrinters()]


def read_image(path):
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    return reader.read()


def prepare(path, cache, office_engine="Microsoft Office 优先", session=None):
    source = Path(path)
    if not source.is_file():
        raise ValueError("文件不存在：" + str(source))
    suffix = source.suffix.lower()
    if suffix in [".tif", ".tiff"]:
        return prepare_tiff(source, Path(cache))
    if suffix in [".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"]:
        image = read_image(str(source))
        if image.isNull():
            raise ValueError("无法读取图片")
        return str(source), 1, "image"
    if suffix == ".pdf":
        output = source
    else:
        from office import engine_signature

        digest = hashlib.sha256(
            (
                str(source.resolve())
                + source.suffix.lower()
                + office_engine
                + engine_signature()
                + "cache-v6"
            ).encode()
        )
        with source.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        key = digest.hexdigest()
        folder = Path(cache) / key
        folder.mkdir(parents=True, exist_ok=True)
        output = folder / "converted.pdf"
        engine_file = folder / "engine.txt"
        if output.exists() and not engine_file.exists():
            output.unlink()
            engine_file.unlink(missing_ok=True)
        if not output.exists():
            from office import convert

            label = convert(source, folder, output, office_engine, session=session)
            (folder / "engine.txt").write_text(label, "utf-8")
    doc = QPdfDocument(None)
    if doc.load(str(output)) != QPdfDocument.Error.None_:
        raise ValueError("PDF 无法打开，可能已加密或损坏")
    count = doc.pageCount()
    doc.close()
    if not count:
        raise ValueError("文档没有可打印页面")
    return str(output), count, "pdf"


def prepare_tiff(source: Path, cache: Path) -> tuple:
    """Decode every TIFF frame to lossless cached pages or reject the whole input."""
    reader = QImageReader(str(source))
    reader.setAutoTransform(True)
    expected = reader.imageCount()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    directory = cache / ("tiff-" + digest)
    directory.mkdir(parents=True, exist_ok=True)
    frames = []
    while True:
        image = reader.read()
        if image.isNull():
            raise ValueError(
                f"TIFF 第 {len(frames) + 1} 页读取失败：{reader.errorString()}"
            )
        output = directory / f"page-{len(frames) + 1:06d}.png"
        if not image.save(str(output), "PNG"):
            raise OSError("无法写入 TIFF 页面缓存")
        frames.append(str(output))
        if not reader.jumpToNextImage():
            break
    if expected > 0 and len(frames) != expected:
        raise ValueError(
            f"TIFF 应有 {expected} 页，只读取到 {len(frames)} 页，已阻止导入"
        )
    if len(frames) == 1:
        return frames[0], 1, "image"
    return frames, len(frames), "images"


def make_printer(name, options, strict=True):
    info = QPrinterInfo.printerInfo(name)
    if info.isNull():
        raise RuntimeError("打印机已不可用：" + name)
    printer = QPrinter(info, QPrinter.PrinterMode.HighResolution)
    printer.setDocName("墨序")
    duplex = {
        "单面": QPrinter.DuplexMode.DuplexNone,
        "双面长边": QPrinter.DuplexMode.DuplexLongSide,
        "双面短边": QPrinter.DuplexMode.DuplexShortSide,
    }
    mm = paper_size(options["paper"], options)
    size = QPageSize(
        QSizeF(*mm),
        QPageSize.Unit.Millimeter,
        options["paper"],
        QPageSize.SizeMatchPolicy.ExactMatch,
    )
    wanted = size.size(QPageSize.Unit.Millimeter)
    for supported in info.supportedPageSizes():
        mm = supported.size(QPageSize.Unit.Millimeter)
        if (
            abs(mm.width() - wanted.width()) < 1
            and abs(mm.height() - wanted.height()) < 1
        ):
            size = supported
            break
    layout = printer.pageLayout()
    layout.setPageSize(size)
    layout.setOrientation(
        QPageLayout.Orientation.Landscape
        if options.get("landscape")
        else QPageLayout.Orientation.Portrait
    )
    layout.setMargins(layout.minimumMargins())
    if not printer.setPageLayout(layout) and strict:
        raise RuntimeError("驱动拒绝了纸张设置")
    printer.setResolution(options["dpi"])
    printer.setColorMode(
        QPrinter.ColorMode.Color
        if options["color"] == "彩色"
        else QPrinter.ColorMode.GrayScale
    )
    printer.setDuplex(duplex[options["duplex"]])
    printer.setCopyCount(1)  # explicit copies keep odd duplex documents isolated
    printer.setCollateCopies(True)
    if strict and printer.duplex() != duplex[options["duplex"]]:
        raise RuntimeError(
            "驱动没有接受单双面设置。请检查完整驱动、设备双面选件，或使用原生驱动对话框。"
        )
    requested_color = (
        QPrinter.ColorMode.Color
        if options["color"] == "彩色"
        else QPrinter.ColorMode.GrayScale
    )
    if strict and printer.colorMode() != requested_color:
        raise RuntimeError("驱动没有接受黑白/彩色设置")
    if strict and printer.resolution() != options["dpi"]:
        raise RuntimeError("驱动没有接受 DPI 设置，请修改配置或使用原生驱动")
    actual = printer.pageLayout().fullRect(QPageLayout.Unit.Millimeter)
    expected = list(paper_size(options["paper"], options))
    if options.get("landscape"):
        expected.reverse()
    if strict and any(
        abs(a - b) > 2 for a, b in zip([actual.width(), actual.height()], expected)
    ):
        raise RuntimeError("驱动纸张尺寸与订单不一致，已阻止提交")
    return printer


def render(item, printer, cancelled=lambda: False):
    from page_raster import Document

    document = Document(item)
    painter = QPainter()
    try:
        # Full-paper coordinates prevent printable-area origin and paper-size confusion.
        layout = printer.pageLayout()
        full = layout.fullRectPixels(printer.resolution())
        paint = layout.paintRectPixels(printer.resolution())
        mm = layout.fullRect(QPageLayout.Unit.Millimeter)
        scale_x = mm.width() / full.width()
        scale_y = mm.height() / full.height()
        margins = (
            paint.left() * scale_x,
            paint.top() * scale_y,
            (full.width() - paint.right() - 1) * scale_x,
            (full.height() - paint.bottom() - 1) * scale_y,
        )
        bands = iter(
            document.bands(
                item["selected"][0],
                printer.resolution(),
                margins=margins,
                pixel_size=(full.width(), full.height()),
            )
        )
        first_band = next(bands)
        printer.setFullPage(True)
        if not painter.begin(printer):
            raise RuntimeError("无法开始打印")
        painter.setRenderHint(QPainter.RenderHint.LosslessImageRendering)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        for n, page in enumerate(item["selected"]):
            if cancelled():
                raise RuntimeError("已停止；已提交的页面仍可能打印")
            if n and not printer.newPage():
                raise RuntimeError("驱动拒绝新页面")
            if n:
                bands = iter(
                    document.bands(
                        page,
                        printer.resolution(),
                        margins=margins,
                        pixel_size=(full.width(), full.height()),
                    )
                )
                first_band = next(bands)
            from itertools import chain

            painter.save()
            painter.setClipRect(QRectF(paint))
            try:
                for rect, image in chain([first_band], bands):
                    if cancelled():
                        raise RuntimeError("已停止；已提交的页面仍可能打印")
                    painter.drawImage(QRectF(rect.translated(full.topLeft())), image)
            finally:
                painter.restore()
    except Exception:
        printer.abort()
        raise
    finally:
        if painter.isActive():
            painter.end()
        document.close()


def preview_margins(item, config):
    from page_raster import resolved_options
    from quality import resolve

    options = resolved_options(item)
    quality = resolve(config, item["printer"], options)
    options["dpi"] = quality["dpi"]
    if quality["profile"]:
        from windows_driver import inspect_margins

        return inspect_margins(item["printer"], options, quality["profile"])
    printer = make_printer(item["printer"], options)
    m = printer.pageLayout().margins(QPageLayout.Unit.Millimeter)
    return m.left(), m.top(), m.right(), m.bottom()
