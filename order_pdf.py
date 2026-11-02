"""File-only, paginated order documents. Physical output uses the normal job pipeline."""

import base64
import html
import re
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPageSize,
    QPainter,
    QPdfWriter,
    QTextDocument,
    QTextOption,
)
from PySide6.QtPdf import QPdfDocument

from catalog import paper_size
from receipt import load_template


def pdf_html(oid, payload, status, options):
    def escape(value):
        return html.escape(str(value))

    template = payload.get("order_template", {})
    mono = options.get("color", "黑白") == "黑白"
    accent = "#222222" if mono else "#d5681c"
    width = paper_size(options["paper"], options)[0] - 16

    def images(position):
        parts = []
        for record in template.get("images", []):
            if record.get("position", "顶部") != position:
                continue
            image = QImage.fromData(base64.b64decode(record["data"]))
            if image.isNull():
                raise ValueError("订单图片损坏")
            from page_raster import opaque

            image = opaque(image)
            if mono:
                image = image.convertToFormat(QImage.Format.Format_Grayscale8)
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            data = base64.b64encode(bytes(buffer.data())).decode()
            w = min(width, float(record.get("width_mm", 35))) * 72 / 25.4
            h = w * image.height() / image.width()
            maximum_height = (paper_size(options["paper"], options)[1] - 32) * 72 / 25.4
            if h > maximum_height:
                w *= maximum_height / h
                h = maximum_height
            parts.append(
                f'<p><img src="data:image/png;base64,{data}" width="{w:.0f}" height="{h:.0f}"></p>'
            )
        return "".join(parts)

    def text(value):
        return escape(value).replace("\n", "<br>")

    rows = []
    for i in payload["items"]:
        o = i["options"]
        name = " / ".join(Path(s).name for s in i.get("source_files", [i["source"]]))
        # Word-boundary wrapping alone cannot break many long Latin filenames.
        name = "\u200b".join(name[n : n + 14] for n in range(0, len(name), 14))
        params = o["paper"] + " / " + o["color"] + " / " + o["duplex"]
        rows.append(
            "<tr>"
            + "".join(
                "<td>" + text(v) + "</td>"
                for v in [
                    name,
                    params,
                    f"{len(i['selected'])}页 × {o['copies']}份",
                    i.get("printer", ""),
                ]
            )
            + "</tr>"
        )
    contact = ""
    if template.get("show_contact", True):
        contact = (
            "<p>"
            + text(
                "    ".join(
                    label + str(payload[key])
                    for key, label in [
                        ("phone", "电话："),
                        ("qq", "QQ："),
                        ("wechat", "微信："),
                        ("contact", "其他："),
                    ]
                    if payload.get(key)
                )
            )
            + "</p>"
        )
    sides = sum(len(i["selected"]) * i["options"]["copies"] for i in payload["items"])
    sheets = sum(
        (
            (len(i["selected"]) + 1) // 2
            if i["options"]["duplex"] != "单面"
            else len(i["selected"])
        )
        * i["options"]["copies"]
        for i in payload["items"]
    )
    quote = payload["quote"]
    binding = quote.get("binding", {})
    total = "合计 ¥ " + quote["total"] if quote.get("enabled") else "本单不计价"
    binding_text = f"{binding.get('name', '不装订')} × {binding.get('quantity', 1)}，¥{quote.get('binding_total', '0.00')}"
    return (
        load_template("order_pdf.html")
        .substitute(
            accent=accent,
            title=text(template.get("title", "墨序 · 订单")),
            order_id=escape(oid),
            status=escape(status),
            top_images=images("顶部"),
            bottom_images=images("底部"),
            header_text=text(template.get("header_text", "")),
            footer_text=text(template.get("footer_text", "")),
            address=text(
                " / ".join(
                    payload.get(key, "") for key in ("community", "building", "room")
                )
            ),
            customer=text(payload.get("customer", "")),
            contact_html=contact,
            note=text(payload.get("note", "")),
            file_rows="".join(rows),
            sides=sides,
            sheets=sheets,
            binding_text=text(binding_text),
            total_text=escape(total),
        )
        .strip()
    )


def write_order_pdf(path, oid, payload, status, options):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = QPdfWriter(str(path))
    writer.setResolution(72)
    writer.setTitle("墨序订单 " + oid)
    writer.setPageSize(
        QPageSize(
            QSizeF(*paper_size(options["paper"], options)), QPageSize.Unit.Millimeter
        )
    )
    writer.setPageMargins(QMarginsF(0, 0, 0, 0))
    full = writer.pageLayout().fullRectPoints()
    margin = 8 * 72 / 25.4
    width = full.width() - 2 * margin
    height = full.height() - 2 * margin - 18
    raw = pdf_html(oid, payload, status, options)
    prefix, body = raw.split("<body>", 1)
    body = body.removesuffix("</body></html>")
    before, table = body.split("<table ", 1)
    table, after = table.split("</table>", 1)
    head, rows = table.split("</thead>", 1)
    header = "<table " + head + "</thead></table>"
    rows = re.findall(r"<tr>.*?</tr>", rows, re.S)
    painter = QPainter(writer)
    page = 1
    y = 0

    def document(markup):
        doc = QTextDocument()
        doc.setDefaultFont(QFont("Microsoft YaHei", 10))
        doc.setDocumentMargin(0)
        setting = doc.defaultTextOption()
        setting.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        doc.setDefaultTextOption(setting)
        doc.setHtml(prefix + "<body>" + markup + "</body></html>")
        doc.setTextWidth(width)
        return doc

    def footer():
        painter.setPen(QColor("#444444"))
        painter.setFont(QFont("Microsoft YaHei", 9))
        painter.drawText(
            QRectF(margin, full.height() - margin - 12, width, 12),
            Qt.AlignmentFlag.AlignRight,
            str(page),
        )

    def next_page():
        nonlocal page, y
        footer()
        if not writer.newPage():
            raise RuntimeError("订单PDF分页失败")
        page += 1
        y = 0

    def draw(doc, offset=0, limit=None):
        nonlocal y
        h = doc.size().height() if limit is None else limit
        painter.save()
        painter.translate(margin, margin + y - offset)
        painter.setClipRect(QRectF(0, offset, width, h))
        doc.drawContents(painter, QRectF(0, offset, width, h))
        painter.restore()
        y += h

    def chunk(markup):
        doc = document(markup)
        h = doc.size().height()
        if h <= height:
            if y + h > height:
                next_page()
            draw(doc)
        else:
            if y:
                next_page()
            doc.setPageSize(QSizeF(width, height))
            for n in range(doc.pageCount()):
                if n:
                    next_page()
                draw(doc, n * height, height)

    try:
        chunk(before)
        header_doc = document(header)
        header_height = header_doc.size().height()
        table_started = False
        for row in rows:
            widths = iter([33, 27, 14, 26])
            row = re.sub(r"<td>", lambda _: f'<td width="{next(widths)}%">', row)
            doc = document(
                '<table width="100%" cellspacing="0" cellpadding="4">'
                + row
                + "</table>"
            )
            h = doc.size().height()
            if y + h + (0 if table_started else header_height) > height:
                next_page()
                table_started = False
            if not table_started:
                draw(header_doc)
                table_started = True
            if h > height - header_height:
                chunk(
                    '<table width="100%" cellspacing="0" cellpadding="4">'
                    + row
                    + "</table>"
                )
            else:
                draw(doc)
        chunk(after)
        footer()
    finally:
        painter.end()
    writer = None  # Release the file before reopening it for verification.
    check = QPdfDocument()
    try:
        if check.load(str(path)) != QPdfDocument.Error.None_ or check.pageCount() < 1:
            raise RuntimeError("订单PDF生成失败")
        return check.pageCount()
    finally:
        check.close()


def receipt_item(config, payload, root, installed):
    from core import route
    from page_raster import resolved_options
    from quality import LEVELS, resolve

    settings = payload.get("order_print", config.get("order_print", {}))
    if not settings.get("enabled"):
        return None
    options = {
        "paper": settings.get("paper", "A4"),
        "color": settings.get("color", "黑白"),
        "printer": settings.get("printer", "自动分配"),
        "duplex": "单面",
        "copies": 1,
        "range": "",
        "pdf_fit": "实际大小",
        "fit": "完整留白",
        "dpi": 600,
        "orientation": "portrait",
        "landscape": False,
        "quality_level": LEVELS[0],
    }
    options["paper_mm"] = list(paper_size(options["paper"], config=config))
    printer = route(config, options, installed)
    quality = resolve(config, printer, options)
    options["dpi"] = quality["dpi"]
    path = Path(root) / "generated" / "orders" / (payload["order_id"] + ".pdf")
    count = write_order_pdf(
        path, payload["order_id"], payload, "随单订单（不代表文件已出纸）", options
    )
    item = {
        "source": str(path),
        "prepared": str(path),
        "kind": "pdf",
        "count": count,
        "selected": list(range(count)),
        "options": options,
        "printer": printer,
        "submitted_copies": 0,
        "status": "待打印",
        "quality_name": quality["label"],
        "is_receipt": True,
    }
    item["options"] = resolved_options(item)
    return item
