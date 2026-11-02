"""Coverage of the same opaque paper raster used for printing. Not ink consumption."""

from collections import Counter

from PySide6.QtGui import QImage

from page_raster import Document, opaque


def pixel_metrics(image):
    rgb = opaque(image)
    raw = bytes(rgb.constBits())
    stride = rgb.bytesPerLine()
    packed = b"".join(
        raw[y * stride : y * stride + rgb.width() * 4] for y in range(rgb.height())
    )
    # RGB32 is BGRA on supported Windows x64. Count white pixels without Python pixel loops.
    white = bytes(1 if n >= 245 else 0 for n in range(256))
    b = packed[0::4].translate(white)
    g = packed[1::4].translate(white)
    r = packed[2::4].translate(white)
    # Big integer bitwise AND processes three channel masks in C, including yellow/cyan.
    blank = (
        int.from_bytes(b, "little")
        & int.from_bytes(g, "little")
        & int.from_bytes(r, "little")
    ).bit_count()
    gray = rgb.convertToFormat(QImage.Format.Format_Grayscale8)
    raw = bytes(gray.constBits())
    stride = gray.bytesPerLine()
    histogram = Counter(
        b"".join(
            raw[y * stride : y * stride + gray.width()] for y in range(gray.height())
        )
    )
    total = rgb.width() * rgb.height()
    return {
        "area_percent": round(100 * (total - blank) / total, 2),
        "tone_percent": round(
            100
            * sum((255 - v) * count for v, count in histogram.items())
            / (255 * total),
            2,
        ),
    }


def estimate(item, maximum_pages=None):
    selected = item["selected"]
    if not selected:
        raise ValueError("没有选中的页面")
    document = Document(item)
    results = []
    try:
        for index in selected:
            results.append(
                pixel_metrics(
                    document.sheet(
                        index, 150, item.get("preview_margins", (0, 0, 0, 0))
                    )
                )
            )
    finally:
        document.close()
    return {
        "area_percent": round(
            sum(r["area_percent"] for r in results) / len(results), 2
        ),
        "tone_percent": round(
            sum(r["tone_percent"] for r in results) / len(results), 2
        ),
        "sampled_pages": len(results),
        "selected_pages": len(selected),
        "method": "全部所选页面，150 DPI；先合成白底，再按实际布局与黑白/彩色计算；任一RGB通道低于245视为着色。面积与平均色调是两项指标，均非耗墨量。未连接设备时不计驱动边距。",
    }
