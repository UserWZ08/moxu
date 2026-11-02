import base64
import html
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from string import Template


@lru_cache(maxsize=2)
def load_template(name: str) -> Template:
    """Load bundled markup; callers escape user text before substitution."""
    return Template((Path(__file__).parent / "assets" / name).read_text("utf-8"))


def snapshot_template(config):
    from PySide6.QtCore import QBuffer, QIODevice, Qt
    from PySide6.QtGui import QImageReader

    template = deepcopy(config.get("order_template", {}))
    template["images"] = []
    source = config.get("order_template", {})
    images = source.get("images", [])
    if source.get("image_path"):
        images = images + [
            {
                "path": source["image_path"],
                "width_mm": source.get("image_width_mm", 35),
                "position": source.get("image_position", "顶部"),
            }
        ]
    for item in images[:4]:
        reader = QImageReader(item["path"])
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            raise ValueError("订单自定义图片无法读取，请到后台重新选择")
        image = image.scaled(
            1200,
            1200,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buf, "PNG")
        template["images"].append(
            {
                "data": base64.b64encode(bytes(buf.data())).decode(),
                "width_mm": item.get("width_mm", 35),
                "position": item.get("position", "顶部"),
            }
        )
    template.pop("image_path", None)
    return template


def order_html(oid, payload, status):
    def escape(value):
        return html.escape(str(value))

    template = payload.get("order_template", {})
    title = template.get("title", "墨序 · 订单")

    def images(position):
        return "".join(
            '<img alt="订单自定义图片" style="display:inline-block;max-width:100%;margin:4mm 4mm 4mm 0;width:'
            + str(max(10, min(180, float(i.get("width_mm", 35)))))
            + 'mm" src="data:image/png;base64,'
            + escape(i["data"])
            + '">'
            for i in template.get("images", [])
            if i.get("position", "顶部") == position
        )

    rows = "".join(
        "<tr>"
        + "".join(
            "<td>" + escape(v) + "</td>"
            for v in [
                " / ".join(Path(s).name for s in i.get("source_files", [i["source"]])),
                len(i["selected"]),
                i["options"]["copies"],
                i["options"]["paper"],
                i["options"]["color"],
                i["options"]["duplex"],
                i.get("printer", ""),
                i.get("submitted_copies", 0),
            ]
        )
        + "</tr>"
        for i in payload["items"]
    )
    groups = "".join(
        "<tr>"
        + "".join(
            "<td>" + escape(v) + "</td>"
            for v in [
                g["rule"]["paper"]
                + " "
                + g["rule"]["color"]
                + " "
                + g["rule"]["duplex"],
                str(g["quantity"]) + g["rule"]["unit"],
                "满量优惠" if g.get("mode") == "volume" else "分段优惠",
                "¥" + g["amount"],
            ]
        )
        + "</tr>"
        for g in payload["quote"].get("groups", [])
    )
    binding = payload["quote"].get("binding", {})
    binding_text = f"{binding.get('name','不装订')} × {binding.get('quantity',1)}，费用 ¥{payload['quote'].get('binding_total','0.00')}"
    contact = ""
    if template.get("show_contact", True):
        details = [
            label + str(payload.get(key, ""))
            for key, label in [
                ("phone", "手机："),
                ("qq", "QQ："),
                ("wechat", "微信："),
                ("contact", "其他："),
            ]
            if payload.get(key)
        ]
        contact = "<p>" + escape("　".join(details)) + "</p>"
    total_text = (
        "合计 ¥ " + escape(payload["quote"]["total"])
        if payload["quote"]["enabled"]
        else "本单不计价"
    )
    return load_template("order_browser.html").substitute(
        title=escape(title),
        order_id=escape(oid),
        status=escape(status),
        top_images=images("顶部"),
        bottom_images=images("底部"),
        header_text=escape(template.get("header_text", "")),
        footer_text=escape(template.get("footer_text", "")),
        address=escape(
            " · ".join(
                payload.get(key, "") for key in ("community", "building", "room")
            )
        ),
        customer=escape(payload.get("customer", "")),
        contact_html=contact,
        note=escape(payload.get("note", "")),
        file_rows=rows,
        price_rows=groups,
        binding_text=escape(binding_text),
        total_text=total_text,
    )
