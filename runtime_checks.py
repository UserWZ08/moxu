"""Explicit offline smoke check for packaged distributions; never submits print jobs."""

import tempfile
from pathlib import Path


def run():
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtPdf import QPdfDocument

    from core import Store
    from customers import export_xlsx, import_xlsx, search, upsert
    from office import POLICIES
    from photo_layout import write_pdf
    from release_info import VERSION

    result = {"version": VERSION}
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        store = Store(directory / "a")
        record = upsert(
            store.db,
            {
                "name": "张三",
                "phone": "013800000001",
                "qq": "001234",
                "building": "12栋",
            },
        )
        assert search(store.db, "zs")[0]["id"] == record["id"]
        assert search(store.db, "zhangsan")[0]["phone"] == "013800000001"
        result["customer_search"] = "passed"
        workbook = directory / "customers.xlsx"
        export_xlsx(store.db, workbook)
        other = Store(directory / "b")
        assert import_xlsx(other.db, workbook) == 1
        assert search(other.db, "001234")[0]["qq"] == "001234"
        result["excel_round_trip"] = "passed"
        store.db.close()
        other.db.close()
        image = QImage(100, 80, QImage.Format.Format_RGB32)
        image.fill(QColor("#ef7b28"))
        pdf = directory / "layout.pdf"
        write_pdf(pdf, (210, 297), (85.6, 54), [image], 2, 10, 8, False)
        doc = QPdfDocument(None)
        assert doc.load(str(pdf)) == QPdfDocument.Error.None_
        assert doc.pageCount() == 1
        assert abs(doc.pagePointSize(0).width() * 25.4 / 72 - 210) < 0.2
        doc.close()
        del doc
        result["document_layout"] = "passed"
        from coverage import pixel_metrics
        from page_raster import preview_sheet, write_proof

        obj = {
            "source": str(pdf),
            "prepared": str(pdf),
            "kind": "pdf",
            "selected": [0],
            "options": {
                "paper": "A3",
                "color": "黑白",
                "duplex": "双面短边",
                "copies": 1,
                "pdf_fit": "自适应纸张",
                "orientation": "auto",
            },
        }
        sheet = preview_sheet(obj, 0)
        assert sheet.pixelColor(sheet.width() - 2, sheet.height() - 2).red() == 255
        assert pixel_metrics(sheet)["area_percent"] < 80
        result["opaque_pdf_background"] = "passed"
        from page_raster import Document

        document = Document(obj)
        try:
            plan = document.plan(0, 1200)
            assert plan["size"].width() == round(297 * 1200 / 25.4)
            bands = document.bands(0, 1200)
            rect, tile = next(bands)
            assert tile.width() * tile.height() <= 4_000_000
            assert rect.width() == plan["size"].width()
            bands.close()
            result["full_resolution_bands"] = "passed"
        finally:
            document.close()
        proof = directory / "proof.pdf"
        write_proof(obj, proof)
        check = QPdfDocument()
        assert check.load(str(proof)) == QPdfDocument.Error.None_
        assert abs(check.pagePointSize(0).width() * 25.4 / 72 - 297) < 0.2
        check.close()
        del check
        result["a3_file_only_proof"] = "passed"
        from order_pdf import write_order_pdf

        order = directory / "order.pdf"
        order_data = {
            "items": [dict(obj, source="demo.pdf", printer="测试打印机")],
            "quote": {"enabled": False, "total": "0.00"},
            "community": "测试小区",
            "customer": "测试客户",
            "order_template": {},
        }
        write_order_pdf(
            order, "OFFLINE-CHECK", order_data, "自检", {"paper": "A5", "color": "黑白"}
        )
        check = QPdfDocument()
        assert check.load(str(order)) == QPdfDocument.Error.None_
        assert abs(check.pagePointSize(0).width() * 25.4 / 72 - 148) < 0.2
        assert "测试客户" in check.getAllText(0).text()
        check.close()
        del check
        result["order_pdf_a5"] = "passed"
        assert (Path(__file__).parent / "assets" / "moxu.ico").is_file()
        result["icon_assets"] = "passed"
        result["office_policy"] = POLICIES[0]
    result["physical_print_jobs_submitted"] = 0
    from copy import deepcopy

    from core import DEFAULT, quote
    from quality import resolve

    config = deepcopy(DEFAULT)
    config["prices"] = [
        {
            "paper": "A4",
            "color": "黑白",
            "duplex": "单面",
            "unit": "面",
            "base_price": "0.20",
            "discount_enabled": True,
            "mode": "volume",
            "discounts": [[20, "0.15"]],
        }
    ]
    item = {
        "selected": list(range(25)),
        "options": {"paper": "A4", "color": "黑白", "duplex": "单面", "copies": 1},
    }
    assert quote(config, [item])["total"] == "3.75"
    result["list_price_discounts"] = "passed"
    config["printers"] = [{"name": "HP M403", "dpi": [600, 1200]}]
    assert resolve(config, "HP M403", {"quality_level": "标准打印"})["dpi"] == 600
    assert resolve(config, "HP M403", {"quality_level": "高质量打印"})["dpi"] == 1200
    result["device_quality_binding"] = "passed"
    config["printers"] = [{"name": "EPSON L15158", "dpi": [600]}]
    assert (
        resolve(config, "EPSON L15158", {"quality_level": "高质量打印"})["dpi"] == 600
    )
    result["new_printer_quality_fallback"] = "passed"
    from print_models import PrintItem

    record = {"status": "已提交", "options": {}, "selected": [0]}
    model = PrintItem(record)
    model.apply_options({"copies": 2}, [0])
    assert model.needs_repeat_confirmation
    result["submission_evidence"] = "passed"
    from PySide6.QtGui import QImageReader

    assert b"tiff" in [bytes(value) for value in QImageReader.supportedImageFormats()]
    result["tiff_plugin"] = "passed"
    with tempfile.TemporaryDirectory() as temporary:
        store = Store(temporary)
        store.save(store.config)
        store.db.close()
        store.path.write_bytes(b'{"truncated":')
        recovered = Store(temporary)
        assert recovered.config["configuration_review_required"]
        assert "settings-last-good.json" in recovered.recovery_notice
        recovered.db.close()
    result["damaged_configuration_recovery"] = "passed"
    from core import migrate_config

    previous = deepcopy(DEFAULT)
    previous.update(
        schema_version=4,
        migration_notes=["6寸相纸 彩色：缺少双面价格，请补充或确认不提供该服务。"],
        billing_review_required=True,
    )
    assert not migrate_config(previous).get("billing_review_required")
    result["obsolete_price_notice_removed"] = "passed"
    from desktop_lifecycle import CloseChoiceDialog

    dialog = CloseChoiceDialog(None, False, False)
    assert not dialog.background_button.isEnabled() and dialog.exit_button.isEnabled()
    dialog.reject()
    from desktop_settings import PROJECT_URL, DesktopSettingsPage

    settings = DesktopSettingsPage({"close_behavior": "tray", "autostart": False})
    assert settings.value() == {"close_behavior": "tray", "autostart": False}
    settings.close()
    assert PROJECT_URL == "https://github.com/UserWZ08/moxu"
    result["desktop_preferences_and_project"] = "passed"
    from autostart import startup_command

    assert "--startup" in startup_command()
    result["startup_command_only_no_registration"] = "passed"
    return result
