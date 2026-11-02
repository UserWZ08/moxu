from copy import deepcopy
from decimal import Decimal

DEFAULT_PAPERS = {
    "A4": [210, 297],
    "A3": [297, 420],
    "A5": [148, 210],
    "B5": [182, 257],
    "6寸相纸": [101.6, 152.4],
    "5寸相纸": [88.9, 127],
}
DEFAULT_BINDINGS = [
    {"name": "不装订", "price": "0.00"},
    {"name": "订书钉", "price": "0.00"},
    {"name": "回形针", "price": "0.00"},
    {"name": "胶装", "price": "0.00"},
]


def ensure_catalog(config):
    config.setdefault("close_behavior", "ask")
    config.setdefault("autostart", False)
    config.setdefault("papers", deepcopy(DEFAULT_PAPERS))
    config.setdefault("bindings", deepcopy(DEFAULT_BINDINGS))
    config.setdefault("office_engine", "Microsoft Office 优先")
    config.pop("light_background_enabled", None)
    config.pop("background_choice_initialized", None)
    config.setdefault(
        "order_template",
        {
            "title": "墨序 · 订单",
            "header_text": "",
            "footer_text": "",
            "image_path": "",
            "image_width_mm": 35,
            "image_position": "顶部",
            "show_contact": True,
        },
    )
    config.setdefault("document_templates", {"户口本内页": [143, 105]})
    config.setdefault(
        "order_print",
        {"enabled": False, "paper": "A4", "color": "黑白", "printer": "自动分配"},
    )
    return config


def paper_size(name, options=None, config=None):
    if options and options.get("paper_mm"):
        return tuple(options["paper_mm"])
    return tuple((config or {}).get("papers", DEFAULT_PAPERS)[name])


def configured_printers(config, enabled_only=True):
    return [
        p["name"]
        for p in config.get("printers", [])
        if p.get("enabled", True) or not enabled_only
    ]


def binding_charge(config, name, quantity=1):
    if type(quantity) is not int or not 1 <= quantity <= 999:
        raise ValueError("装订份数应为1–999")
    found = next(
        (p for p in config.get("bindings", DEFAULT_BINDINGS) if p["name"] == name), None
    )
    if found is None:
        raise ValueError("装订方式已失效，请重新选择")
    amount = Decimal(found["price"]) * quantity
    return {
        "name": name,
        "quantity": quantity,
        "unit_price": format(Decimal(found["price"]), ".2f"),
        "total": format(amount, ".2f"),
    }


def validate_catalog(c):
    if c.get("office_engine", "Microsoft Office 优先") not in [
        "Microsoft Office 优先",
        "仅 Microsoft Office",
        "仅 LibreOffice",
    ]:
        raise ValueError("Office 转换引擎设置无效")
    papers = c.get("papers", DEFAULT_PAPERS)
    if not isinstance(papers, dict) or not papers:
        raise ValueError("至少配置一种纸张")
    for name, mm in papers.items():
        if (
            not name.strip()
            or len(mm) != 2
            or any(type(v) not in [int, float] or not 10 <= v <= 2000 for v in mm)
        ):
            raise ValueError("纸张宽高应为10–2000毫米")
    names = set()
    for item in c.get("bindings", DEFAULT_BINDINGS):
        if not item["name"].strip() or item["name"] in names:
            raise ValueError("装订方式名称为空或重复")
        names.add(item["name"])
        price = Decimal(str(item["price"]))
        if (
            not price.is_finite()
            or price < 0
            or price != price.quantize(Decimal(".01"))
        ):
            raise ValueError("装订单价最多两位小数，且应为非负数")
    if not names:
        raise ValueError("至少保留一种装订方式，可以设置“不装订”")
    for name, mm in c.get("document_templates", {}).items():
        if (
            not name.strip()
            or len(mm) != 2
            or any(not 10 <= float(v) <= 1000 for v in mm)
        ):
            raise ValueError("证件模板尺寸无效")
    template = c.get("order_template", {})
    order = c.get(
        "order_print",
        {"enabled": False, "paper": "A4", "color": "黑白", "printer": "自动分配"},
    )
    if (
        type(order.get("enabled")) is not bool
        or order.get("paper") not in papers
        or order.get("color") not in ["黑白", "彩色"]
        or not isinstance(order.get("printer"), str)
        or not order["printer"]
    ):
        raise ValueError("订单随单打印设置无效")
    for key in ["title", "header_text", "footer_text"]:
        if (
            not isinstance(template.get(key, ""), str)
            or len(template.get(key, "")) > 20000
        ):
            raise ValueError("订单自定义文字无效或过长")
    images = template.get("images", [])
    if len(images) > 4:
        raise ValueError("订单最多设置4张自定义图片")
    for image in images:
        if (
            not isinstance(image.get("path"), str)
            or not 10 <= float(image.get("width_mm", 35)) <= 180
            or image.get("position", "顶部") not in ["顶部", "底部"]
        ):
            raise ValueError("订单图片设置无效")
    return papers
