"""Pure page geometry shared by Qt printing, native printing and estimates."""

from catalog import DEFAULT_PAPERS

PAPER_MM = DEFAULT_PAPERS


def placement(
    image_width, image_height, width, height, kind, options, points=None, dpi=300
):
    if min(image_width, image_height, width, height) <= 0:
        raise ValueError("页面尺寸无效")
    if kind == "pdf" and points:
        natural_w, natural_h = points[0] * dpi / 72, points[1] * dpi / 72
        fit = min(width / natural_w, height / natural_h)
        mode = options.get("pdf_fit", "自适应纸张")
        ratio = (
            1
            if mode == "实际大小"
            else min(1, fit) if mode == "仅缩小超大页面" else fit
        )
        w, h = natural_w * ratio, natural_h * ratio
    else:
        fill = options.get("fit") == "填充裁切"
        ratio = (max if fill else min)(width / image_width, height / image_height)
        w, h = image_width * ratio, image_height * ratio
    return (width - w) / 2, (height - h) / 2, w, h
