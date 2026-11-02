import json
import logging
import sys
import traceback
import uuid
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import (
    QItemSelection,
    QItemSelectionModel,
    QLibraryInfo,
    QLockFile,
    QSignalBlocker,
    QSize,
    Qt,
    QThread,
    QTimer,
    QTranslator,
    QUrl,
    Signal,
    qVersion,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

import customers
from catalog import configured_printers, paper_size
from core import (
    FORMATS,
    ServiceUnavailableError,
    Store,
    data_dir,
    new_order_id,
    order_quote,
    pages,
    route,
)
from customer_ui import CustomerEditor, CustomerManager
from page_raster import preview_sheet, resolved_options
from print_jobs import submit_order
from print_models import (
    OrderState,
    PrintItem,
    PrintItemRecord,
    SubmissionResult,
    SubmissionState,
)
from printing import installed_printers, make_printer, prepare, render
from quality import resolve as resolve_quality
from receipt import order_html, snapshot_template
from release_info import VERSION
from settings_ui import Settings
from theme import apply_theme
from workbench_ui import build_workbench

logger = logging.getLogger(__name__)


class Worker(QThread):
    ready = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.ready.emit(self.fn(self))
        except Exception as e:
            logger.exception("Background operation failed")
            self.failed.emit(str(e))


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.store = Store()
        self.items: list[PrintItemRecord] = []
        self.worker = None
        self.busy = False
        self._loading_options = False
        self._layout_cache = {}
        self.customer_record = {}
        self.completion_records = {}
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "moxu.ico")))
        self.setWindowTitle(f"墨序 {VERSION} · 打印工作台")
        self.resize(1380, 900)
        self.setMinimumSize(1050, 730)
        self.setAcceptDrops(True)
        build_workbench(self)
        if self.store.config.get("billing_review_required"):
            self.status.setText(
                "升级价格需要核对：请到后台“外观与功能”查看迁移提示；核对前暂停计价打印"
            )
            self.total.setToolTip(
                "\n".join(self.store.config.get("migration_notes", []))
            )

    def selection_changed(self):
        self._pending_option_error = ""
        rows = self.selected()
        if rows and rows[0] < len(self.items):
            o = self.items[rows[0]]["options"]
            self._loading_options = True
            try:
                for key, w in [
                    ("paper", self.paper),
                    ("color", self.color),
                    ("duplex", self.duplex),
                    ("fit", self.fit),
                    ("pdf_fit", self.pdf_fit),
                    ("printer", self.printer),
                    ("quality_level", self.quality),
                ]:
                    w.setCurrentText(
                        o.get(
                            key,
                            "标准打印" if key == "quality_level" else w.currentText(),
                        )
                    )
                self.copies.setValue(o["copies"])
                self.range.setText(o.get("range", ""))
                self.dpi.setCurrentText(str(o.get("dpi", 600)))
            finally:
                self._loading_options = False
            self.page.blockSignals(True)
            self.page.setValue(1)
            self.page.blockSignals(False)
        self.preview()
        self.sync_quality_controls()

    def live_apply(self, *args):
        if self._loading_options or self.busy:
            return
        mapping = {
            self.paper: "paper",
            self.color: "color",
            self.duplex: "duplex",
            self.fit: "fit",
            self.pdf_fit: "pdf_fit",
            self.quality: "quality_level",
            self.printer: "printer",
            self.copies: "copies",
            self.range: "range",
        }
        key = mapping.get(self.sender())
        if not key:
            return
        try:
            options = self.options()
            updates = []
            for row in self.selected():
                if not self.items[row]["count"]:
                    continue
                o = deepcopy(self.items[row]["options"])
                o[key] = options[key]
                o["orientation"] = "auto"
                if key == "paper":
                    o["paper_mm"] = options["paper_mm"]
                updates.append(
                    (row, o, pages(o.get("range", ""), self.items[row]["count"]))
                )
            for row, o, selected in updates:
                PrintItem(self.items[row]).apply_options(o, selected)
            self._pending_option_error = ""
            self.refresh()
        except Exception as error:
            self._pending_option_error = str(error)
            self.status.setText("设置尚未应用：" + str(error))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "preview_label"):
            QTimer.singleShot(0, self.preview)

    def initial_column_widths(self):
        available = max(600, self.table.viewport().width() - 4)
        for i, ratio in enumerate([0.31, 0.07, 0.23, 0.19, 0.10, 0.10]):
            self.table.setColumnWidth(i, max(45, int(available * ratio)))

    def theme(self, *args):
        apply_theme(self.store.config["theme"])

    def buildings(self):
        self.building.clear()
        self.building.addItems(
            self.store.config["communities"].get(self.community.currentText(), [])
        )

    def settings(self, quality=False):
        if self.busy:
            return
        dialog = Settings(self.store, self)
        if quality:
            dialog.tabs.setCurrentIndex(1)
        if dialog.exec():
            self.reload_settings_choices()

    def reload_settings_choices(self) -> None:
        """Keep existing selections; removed entries require a deliberate new choice."""
        config = self.store.config
        community = self.community.currentText()
        building = self.building.currentText()
        choices = [
            (self.paper, list(config["papers"])),
            (self.binding, [binding["name"] for binding in config["bindings"]]),
            (self.community, list(config["communities"])),
            (self.building, config["communities"].get(community, [])),
            (self.printer, ["自动分配"] + configured_printers(config)),
            (
                self.preset,
                ["选择常用预设"]
                + [preset["name"] for preset in config.get("presets", [])],
            ),
        ]
        self._loading_options = True
        try:
            with ExitStack() as blockers:
                for widget, values in choices:
                    blockers.enter_context(QSignalBlocker(widget))
                    previous = (
                        building if widget is self.building else widget.currentText()
                    )
                    widget.clear()
                    widget.addItems(values)
                    widget.setCurrentIndex(widget.findText(previous))
        finally:
            self._loading_options = False
        self._layout_cache.clear()
        self.theme()
        self.refresh()
        self.sync_quality_controls()
        if not self.community.currentText() or not self.building.currentText():
            self.status.setText("原小区或楼栋已移除，请重新选择地址后打印")

    def load_preset(self, index):
        if index <= 0:
            return
        p = self.store.config.get("presets", [])[index - 1]
        o = p["options"]
        self._loading_options = True
        if o.get("printer", "自动分配") not in ["自动分配"] + configured_printers(
            self.store.config
        ):
            self._loading_options = False
            self.error("预设中的打印机未在后台启用，请修改此预设")
            return
        for key, w in [
            ("paper", self.paper),
            ("color", self.color),
            ("duplex", self.duplex),
            ("fit", self.fit),
            ("dpi", self.dpi),
            ("printer", self.printer),
        ]:
            value = str(o[key])
            if w.findText(value) < 0:
                w.addItem(value)
            w.setCurrentText(value)
        self.copies.setValue(o["copies"])
        self.range.clear()
        self.quality.setCurrentText(
            o.get(
                "quality_level",
                "高质量打印" if o.get("dpi", 600) >= 1200 else "标准打印",
            )
        )
        self.pdf_fit.setCurrentText(o.get("pdf_fit", "自适应纸张"))
        self._loading_options = False
        self.apply(False, silent=True)
        self.status.setText("已载入预设「" + p["name"] + "」，已实时应用到选中文件")

    def reset_customer_identity(self, text):
        if text != self.customer_record.get("name"):
            self.customer_record.clear()

    def complete_customers(self, text):
        records = (
            customers.search(self.store.db, text, limit=5000) if text.strip() else []
        )
        self.completion_records = {
            f"{r['name']} · {r['community']} {r['building']} {r['room']} · {r['phone']} [{r['id'][:6]}]": r
            for r in records
        }
        self.customer_model.setStringList(list(self.completion_records))
        self.completer.setCompletionPrefix("")
        if records:
            desired = max(
                760,
                max(
                    self.fontMetrics().horizontalAdvance(text) + 60
                    for text in self.completion_records
                ),
            )
            self.completer.popup().setMinimumWidth(
                min(desired, self.screen().availableGeometry().width() - 60)
            )
            self.completer.complete()
            self.resize_customer_popup()
            QTimer.singleShot(0, self.resize_customer_popup)

    def resize_customer_popup(self):
        popup = self.completer.popup()
        count = self.customer_model.rowCount()
        if not count:
            return
        screen = self.screen().availableGeometry()
        origin = self.customer_search.mapToGlobal(
            self.customer_search.rect().bottomLeft()
        )
        desired = min(count, 12) * 38 + 18
        space_below = screen.bottom() - origin.y() - 12
        space_above = origin.y() - self.customer_search.height() - screen.top() - 12
        height = min(desired, max(space_below, space_above))
        height = max(40, height)
        popup.resize(popup.width(), height)
        if space_below < height:
            popup.move(popup.x(), origin.y() - self.customer_search.height() - height)

    def pick_customer(self, text):
        record = self.completion_records.get(text)
        if record:
            self.load_customer(record)

    def load_customer(self, record):
        self.customer_record = dict(record)
        self.customer.setText(record["name"])
        self.phone.setText(record.get("phone", ""))
        self.room.setText(record.get("room", ""))
        self.contact.setText(record.get("contact", ""))
        self.qq.setText(record.get("qq", ""))
        self.wechat.setText(record.get("wechat", ""))
        for combo_widget, key in [
            (self.community, "community"),
            (self.building, "building"),
        ]:
            value = record.get(key, "")
            if combo_widget.findText(value) < 0:
                combo_widget.addItem(value)
            combo_widget.setCurrentText(value)
        self.customer_search.setText(record["name"])
        self.status.setText("已载入客户档案；修改订单字段不会自动覆盖档案")

    def customer_manager(self):
        if self.busy:
            return
        dialog = CustomerManager(self.store, self)
        if dialog.exec() and dialog.selected_record:
            self.load_customer(dialog.selected_record)

    def save_customer(self):
        if self.busy:
            return
        data = dict(
            self.customer_record,
            name=self.customer.text(),
            community=self.community.currentText(),
            building=self.building.currentText(),
            room=self.room.text(),
            phone=self.phone.text(),
            contact=self.contact.text(),
            qq=self.qq.text(),
            wechat=self.wechat.text(),
        )
        dialog = CustomerEditor(self, self.store, data)
        if dialog.exec():
            try:
                self.load_customer(customers.upsert(self.store.db, dialog.result_value))
            except Exception as e:
                self.error(str(e))

    def photo_studio(self):
        if self.busy:
            return
        from photo_ui import PhotoStudio

        dialog = PhotoStudio(self.store, self)
        dialog.generated.connect(self.add_layout)
        dialog.exec()

    def add_layout(self, path, paper):
        self._loading_options = True
        self.paper.setCurrentText(paper)
        self.pdf_fit.setCurrentText("实际大小")
        self.range.clear()
        self.copies.setValue(1)
        self._loading_options = False
        self.add_files([path])

    def options(self):
        return {
            "paper": self.paper.currentText(),
            "color": self.color.currentText(),
            "duplex": self.duplex.currentText(),
            "fit": self.fit.currentText(),
            "dpi": int(self.dpi.currentText()),
            "copies": self.copies.value(),
            "range": self.range.text(),
            "printer": self.printer.currentText(),
            "landscape": False,
            "orientation": "auto",
            "pdf_fit": self.pdf_fit.currentText(),
            "paper_mm": list(
                paper_size(self.paper.currentText(), config=self.store.config)
            ),
            "quality_level": self.quality.currentText(),
        }

    def selected(self):
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.busy:
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_files([u.toLocalFile() for u in event.mimeData().urls()])

    def pick(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "添加打印文件",
            "",
            "可打印文件 (*.pdf *.doc *.docx *.xls *.xlsx *.ppt *.pptx *.jpg *.jpeg *.png *.bmp *.tif *.tiff)",
        )
        self.add_files(paths)

    def run(self, fn, done):
        self.busy = True
        self.printbtn.setEnabled(False)
        self.setAcceptDrops(False)
        self.edit_panel.setEnabled(False)
        self.table.setEnabled(False)
        self.worker = Worker(fn)
        self.worker.ready.connect(done, Qt.ConnectionType.QueuedConnection)
        self.worker.failed.connect(self.error)
        self.worker.progress.connect(self.status.setText)
        self.worker.finished.connect(self.idle)
        self.worker.start()

    def idle(self):
        self.busy = False
        self.printbtn.setEnabled(True)
        self.stop.setEnabled(False)
        self.setAcceptDrops(True)
        self.edit_panel.setEnabled(True)
        self.table.setEnabled(True)

    def error(self, msg):
        self.status.setText("操作失败：" + msg[:150])
        QMessageBox.warning(self, "操作未完成", msg)

    def add_files(self, paths):
        if self.busy or not paths:
            return
        options = self.options()
        office_engine = self.store.config.get("office_engine", "Microsoft Office 优先")
        existing = {s for i in self.items for s in i.get("source_files", [i["source"]])}
        paths = [
            str(Path(p).resolve())
            for p in paths
            if Path(p).suffix.lower() in FORMATS
            and str(Path(p).resolve()) not in existing
        ]
        if not paths:
            return

        def load(w):
            result = []
            from office import ConversionSession

            with ConversionSession() as session:
                for p in dict.fromkeys(paths):
                    w.progress.emit("正在解析：" + Path(p).name)
                    item = {
                        "source": p,
                        "options": deepcopy(options),
                        "status": "待打印",
                    }
                    try:
                        item["prepared"], item["count"], item["kind"] = prepare(
                            p, self.store.root / "cache", office_engine, session=session
                        )
                        item["selected"] = pages(options["range"], item["count"])
                        from office import engine_label

                        item["engine"] = engine_label(p, item["prepared"])
                    except Exception as e:
                        logger.exception(
                            "Document import failed (engine=%s)", office_engine
                        )
                        item.update(count=0, selected=[], status="解析失败：" + str(e))
                    result.append(item)
            return result

        def done(result):
            self.items.extend(result)
            self.refresh()
            engines = " / ".join(sorted({i.get("engine", "解析失败") for i in result}))
            self.status.setText(
                "解析完成 · 引擎：" + engines + "；请核对预览、打印机与价格"
            )

        self.run(load, done)

    def remove(self):
        if self.busy:
            return
        for row in reversed(self.selected()):
            del self.items[row]
        self.refresh()

    def merge_images(self):
        if self.busy:
            return
        try:
            rows = self.selected()
            if len(rows) < 2 or any(self.items[r].get("kind") != "image" for r in rows):
                raise ValueError(
                    "请按住 Ctrl 选择至少两张已解析的独立图片；按队列从上到下的顺序组成页面"
                )
            chosen = [self.items[r] for r in rows]
            o = deepcopy(chosen[0]["options"])
            o["range"] = ""
            o["duplex"] = "双面长边"
            item = {
                "source": chosen[0]["source"],
                "source_files": [i["source"] for i in chosen],
                "prepared": [i["prepared"] for i in chosen],
                "kind": "images",
                "count": len(chosen),
                "selected": list(range(len(chosen))),
                "options": o,
                "status": "待打印",
            }
            for r in reversed(rows):
                del self.items[r]
            if any(
                PrintItem(chosen_item).needs_repeat_confirmation
                for chosen_item in chosen
            ):
                item["submission_state"] = SubmissionState.UNCERTAIN.value
                item["status"] = "需核对 · 包含曾提交图片"
            self.items.insert(rows[0], item)
            self.refresh()
            self.status.setText(
                "图片已按队列顺序组成一个双面任务；请核对双面设置与预览"
            )
        except Exception as e:
            self.error(str(e))

    def apply(self, all_items, silent=False):
        if self.busy:
            return
        try:
            indices = list(range(len(self.items))) if all_items else self.selected()
            updates = [
                (i, pages(self.range.text(), self.items[i]["count"]))
                for i in indices
                if self.items[i]["count"]
            ]
            for i, selected in updates:
                PrintItem(self.items[i]).apply_options(self.options(), selected)
            self._pending_option_error = ""
            self.refresh()
        except Exception as e:
            if silent:
                self.status.setText("设置尚未应用：" + str(e))
            else:
                self.error(str(e))

    def refresh(self):
        selected_rows = self.selected()
        blocker = QSignalBlocker(self.table)
        selection_blocker = QSignalBlocker(self.table.selectionModel())
        installed = installed_printers()
        for row, item in enumerate(self.items):
            o = item["options"]
            try:
                item["printer"] = route(self.store.config, o, installed)
            except Exception:
                item["printer"] = "未匹配"
            item.pop("preview_margins", None)
            if item.get("count") and item["printer"] != "未匹配":
                try:
                    from printing import preview_margins

                    key = json.dumps(
                        [item["printer"], resolved_options(item)], sort_keys=True
                    )
                    if key not in self._layout_cache:
                        self._layout_cache[key] = preview_margins(
                            item, self.store.config
                        )
                    item["preview_margins"] = self._layout_cache[key]
                except Exception:
                    pass
        self.queue_model.replace(self.items)
        selection = QItemSelection()
        for row in selected_rows:
            if row < len(self.items):
                selection.select(
                    self.queue_model.index(row, 0),
                    self.queue_model.index(row, self.queue_model.columnCount() - 1),
                )
        self.table.selectionModel().select(
            selection, QItemSelectionModel.SelectionFlag.Select
        )
        del selection_blocker
        del blocker
        self.preview()
        self.sync_format_controls()
        try:
            if any(not i["count"] for i in self.items):
                raise ValueError("有文件未解析成功")
            q = order_quote(
                self.store.config,
                self.items,
                self.binding.currentText(),
                self.binding_quantity.value(),
            )
            self.total.setText("¥ " + q["total"] if q["enabled"] else "不计价")
            self.total.setToolTip("")
        except Exception as e:
            self.total.setText(
                "未提供所选服务"
                if isinstance(e, ServiceUnavailableError)
                else "价格待配置"
            )
            self.total.setToolTip(str(e))

    def preview(self):
        self.sync_format_controls()
        rows = self.selected()
        if not rows:
            return
        item = self.items[rows[0]]
        if not item["count"]:
            self.preview_label.setText(item["status"])
            return
        self.page.blockSignals(True)
        self.page.setMaximum(item["count"])
        self.page.blockSignals(False)
        try:
            image = preview_sheet(item, self.page.value() - 1)
            painter = QPainter(image)
            painter.setPen(QPen(QColor("#9aa7b6"), max(1, image.width() / 650)))
            painter.drawRect(image.rect().adjusted(1, 1, -2, -2))
            painter.end()
            pix = QPixmap.fromImage(image)
            self.preview_label.setPixmap(
                pix.scaled(
                    self.preview_label.size() - QSize(24, 24),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.preview_label.setToolTip(
                "所选纸张的整张预览 · "
                + item["options"]["paper"]
                + " · "
                + item["options"]["duplex"]
                + " · 白色区域均属于纸张；驱动边距以实际设备为准"
            )
        except Exception as error:
            self.preview_label.setText("预览失败：" + str(error))

    def sync_quality_controls(self, *args):
        if not hasattr(self, "quality_status"):
            return
        try:
            name = route(self.store.config, self.options(), installed_printers())
            quality = resolve_quality(self.store.config, name, self.options())
            self.quality_status.setText(name + "：" + quality["label"])
        except Exception as error:
            message = str(error)
            name = self.printer.currentText()
            if name != "自动分配":
                try:
                    resolve_quality(self.store.config, name, self.options())
                except Exception as detail:
                    message = str(detail)
            self.quality_status.setText("质量绑定提示：" + message)

    def sync_format_controls(self):
        if not hasattr(self, "option_form"):
            return
        rows = self.selected()
        relevant = (
            [self.items[i] for i in rows if i < len(self.items)] if rows else self.items
        )
        kinds = {i.get("kind") for i in relevant if i.get("count")}
        self.option_form.setRowVisible(self.fit, bool(kinds & {"image", "images"}))
        self.option_form.setRowVisible(self.pdf_fit, "pdf" in kinds)
        enabled = self.store.config.get("coverage_enabled", True)
        self.coverage_button.setVisible(enabled)
        self.table.setColumnHidden(5, not enabled)

    def calculate_coverage(self):
        if self.busy:
            return
        rows = self.selected() or list(range(len(self.items)))
        targets = [
            (r, deepcopy(self.items[r])) for r in rows if self.items[r].get("count")
        ]
        if not targets:
            self.error("请先导入可读取的文件")
            return

        def work(w):
            from coverage import estimate

            results = []
            for row, item in targets:
                w.progress.emit("正在估算覆盖率：" + Path(item["source"]).name)
                results.append((row, estimate(item)))
            return results

        def done(results):
            for row, result in results:
                self.items[row]["coverage"] = result
            self.refresh()
            self.status.setText(
                "覆盖率估算完成：按所选纸张与布局计算，非实际耗墨量；全部所选页面以150 DPI计算；面积和平均色调分别显示"
            )

        self.run(work, done)

    def open_source(self):
        if self.selected():
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(self.items[self.selected()[0]]["source"])
            )

    def export_proof(self):
        if self.busy:
            return
        try:
            rows = self.selected()
            if len(rows) != 1:
                raise ValueError(
                    "请选择一个已解析文件；导出所选页的单份排版，不提交打印"
                )
            item = self.items[rows[0]]
            if not item.get("count"):
                raise ValueError("文件尚未解析成功")
            path, _ = QFileDialog.getSaveFileName(
                self,
                "导出单份排版 · 不提交打印",
                str(self.store.root / "排版预览.pdf"),
                "PDF (*.pdf)",
            )
            if path:
                from page_raster import write_proof

                write_proof(item, path)
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as error:
            self.error(str(error))

    def payload(self, subset=None, for_print=True) -> dict:
        """Snapshot customer, pricing, file options and receipt settings for one order."""
        if for_print and self.store.config.get("configuration_review_required"):
            raise ValueError(
                "恢复后的设置尚未核对，请在后台确认地址、打印机和价格后保存"
            )
        for item in self.items:
            item.setdefault("queue_id", uuid.uuid4().hex)
        if getattr(self, "_pending_option_error", ""):
            raise ValueError("请先修正尚未应用的设置：" + self._pending_option_error)
        items = deepcopy(self.items if subset is None else subset)
        if not items or any(not i["count"] for i in items):
            raise ValueError("请添加文件，并移除解析失败的文件")
        communities = self.store.config["communities"]
        if self.building.currentText() not in communities.get(
            self.community.currentText(), []
        ):
            raise ValueError("请选择后台仍存在的小区和楼栋")
        for item in items:
            try:
                item["printer"] = route(
                    self.store.config, item["options"], installed_printers()
                )
                quality = resolve_quality(
                    self.store.config, item["printer"], item["options"]
                )
                item["options"]["dpi"] = quality["dpi"]
                item["quality_name"] = quality["label"]
            except Exception:
                if for_print:
                    raise
                item["printer"] = item["options"].get("printer", "自动分配")
                item["quality_name"] = "未校验（仅导出）"
            item["options"] = resolved_options(item)
            item["submitted_copies"] = 0
        payload = {
            "order_id": new_order_id(),
            "order_print": deepcopy(self.store.config.get("order_print", {})),
            "community": self.community.currentText(),
            "building": self.building.currentText(),
            "room": self.room.text(),
            "customer": self.customer.text(),
            "customer_id": self.customer_record.get("id", ""),
            "phone": self.phone.text(),
            "qq": self.qq.text(),
            "wechat": self.wechat.text(),
            "contact": self.contact.text(),
            "note": self.note.text(),
            "items": items,
            "quote": order_quote(
                self.store.config,
                items,
                self.binding.currentText(),
                self.binding_quantity.value(),
            ),
            "order_template": snapshot_template(self.store.config),
        }
        settings = payload["order_print"]
        settings["paper_mm"] = list(
            paper_size(settings.get("paper", "A4"), config=self.store.config)
        )
        if for_print:
            from order_pdf import receipt_item

            payload["receipt_item"] = receipt_item(
                self.store.config, payload, self.store.root, installed_printers()
            )
        return payload

    def export(self):
        if self.busy:
            return
        try:
            payload = self.payload(for_print=False)
            path, kind = QFileDialog.getSaveFileName(
                self,
                "保存订单页",
                str(self.store.root / ("订单-" + payload["order_id"] + ".pdf")),
                "订单PDF (*.pdf);;订单网页 (*.html)",
            )
            if path:
                oid = self.store.order(payload, payload["order_id"])
                if path.lower().endswith(".pdf") or (
                    "PDF" in kind and not path.lower().endswith(".html")
                ):
                    from order_pdf import write_order_pdf

                    if not path.lower().endswith(".pdf"):
                        path += ".pdf"
                    options = deepcopy(payload["order_print"])
                    write_order_pdf(path, oid, payload, "已创建", options)
                else:
                    Path(path).write_text(
                        order_html(oid, payload, "已创建"), encoding="utf-8"
                    )
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as e:
            self.error(str(e))

    def print_all(self):
        if self.busy:
            return
        try:
            payload = self.payload()
            if (
                any(PrintItem(item).needs_repeat_confirmation for item in self.items)
                and QMessageBox.question(
                    self,
                    "重复打印",
                    "队列中包含已提交或提交结果需核对的文件。修改设置不会撤回旧任务，请先核对系统打印队列。确定再次打印吗？",
                )
                != QMessageBox.StandardButton.Yes
            ):
                return
            if not self.confirm_print(payload):
                return
            self.dispatch(payload)
        except Exception as e:
            self.error(str(e))

    def confirmation_dialog(self, payload):
        dialog = QDialog(self)
        dialog.setWindowTitle("确认打印 · 核对客户与每个文件")
        dialog.resize(1080, 690)
        layout = QVBoxLayout(dialog)
        sides = sum(
            len(i["selected"]) * i["options"]["copies"] for i in payload["items"]
        )
        sheets = sum(
            (
                (len(i["selected"]) + 1) // 2
                if i["options"]["duplex"] != "单面"
                else len(i["selected"])
            )
            * i["options"]["copies"]
            for i in payload["items"]
        )
        customer = QLabel(
            f"{payload['community']} · {payload['building']} · 房号 {payload.get('room') or '未填'}\n"
            f"称呼：{payload.get('customer') or '未填'}    联系电话：{payload.get('phone') or '未填'}\n"
            f"QQ：{payload.get('qq') or '未填'}    微信：{payload.get('wechat') or '未填'}"
        )
        customer.setWordWrap(True)
        layout.addWidget(customer)
        summary = QLabel(
            f"{len(payload['items'])} 个文件 · 打印 {sides} 面 · 用纸 {sheets} 张（不含设备额外分隔页） · 金额 ¥{payload['quote']['total']}"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        table = QTableWidget(len(payload["items"]), 6)
        table.setHorizontalHeaderLabels(
            ["文件 / 页码", "份数", "用纸张数", "打印机", "打印参数", "质量"]
        )
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setWordWrap(True)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        for c, w in enumerate([240, 55, 75, 210, 245, 160]):
            table.setColumnWidth(c, w)
        for row, item in enumerate(payload["items"]):
            o = item["options"]
            n = len(item["selected"])
            sheet = ((n + 1) // 2 if o["duplex"] != "单面" else n) * o["copies"]
            scaling = (
                o.get("pdf_fit", "自适应纸张")
                if item["kind"] == "pdf"
                else o.get("fit", "完整留白")
            )
            values = [
                Path(item["source"]).name
                + " · "
                + str(n)
                + "页 · "
                + (o.get("range") or "全部页码"),
                str(o["copies"]),
                str(sheet),
                item["printer"],
                o["paper"]
                + " · "
                + o["color"]
                + " · "
                + o["duplex"]
                + " · "
                + ("横向" if o.get("landscape") else "纵向")
                + " · "
                + scaling,
                item.get("quality_name", ""),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                table.setItem(row, col, cell)
        table.resizeRowsToContents()
        layout.addWidget(table, 1)
        notice = QLabel(
            "长边 / 短边控制背面翻转。纸张方向自动匹配首张选中页面，混合方向页面自动旋转排入同一纸张。"
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        receipt = payload.get("receipt_item")
        if receipt:
            o = receipt["options"]
            extra = QLabel(
                f"另打印订单页：{receipt['count']}张 · 1份 · {o['paper']} · {o['color']} · 单面 · {receipt['printer']}（不计入文件价格）"
            )
            extra.setWordWrap(True)
            layout.addWidget(extra)
        else:
            layout.addWidget(QLabel("订单页随单打印：关闭"))
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("返回检查")
        cancel.clicked.connect(dialog.reject)
        buttons.addWidget(cancel)
        confirm = QPushButton("确认提交打印")
        confirm.setObjectName("primary")
        confirm.clicked.connect(dialog.accept)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)
        dialog.setProperty("sheets", sheets)
        dialog.setProperty("sides", sides)
        return dialog

    def confirm_print(self, payload):
        return self.confirmation_dialog(payload).exec() == QDialog.DialogCode.Accepted

    def dispatch(self, payload):
        oid = self.store.order(payload, payload.get("order_id"))
        self.store.status(oid, "正在提交")
        self.cancelled = False
        self.stop.setEnabled(True)
        configuration = deepcopy(self.store.config)

        def work(worker):
            return submit_order(
                payload,
                configuration,
                worker.progress.emit,
                lambda: self.cancelled,
                make_printer,
                render,
            )

        def done(result: SubmissionResult):
            data, status = result.payload, result.status
            self.store.status(oid, status, data)
            for submitted in data["items"]:
                for queued in self.items:
                    if queued.get("queue_id") != submitted.get("queue_id"):
                        continue
                    model = PrintItem(queued)
                    if result.state == OrderState.PREFLIGHT_FAILED:
                        continue  # Preflight cannot erase evidence from an earlier order.
                    state = (
                        SubmissionState.SUBMITTED
                        if submitted["submitted_copies"]
                        == submitted["options"]["copies"]
                        else SubmissionState.UNCERTAIN
                    )
                    model.finish_submission(oid, submitted["submitted_copies"], state)
            self.refresh()
            self.status.setText("订单 " + oid + " · " + status)
            if result.state == OrderState.PREFLIGHT_FAILED:
                QMessageBox.warning(self, "未提交打印", status)
            elif result.state != OrderState.SUBMITTED:
                QMessageBox.warning(
                    self,
                    "部分任务可能已打印",
                    status + "\n不要直接重打整单；请先核对打印队列和已提交份数。",
                )

        self.run(work, done)

    def cancel(self):
        self.cancelled = True
        self.status.setText("正在停止；已交给驱动的页面请在 Windows 打印队列中取消")

    def history(self):
        if self.busy:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("订单记录 · 最近500单")
        dialog.resize(1000, 620)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(
            ["订单号", "时间", "小区 / 楼栋", "金额", "状态"]
        )
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(table)
        records = self.store.history()
        table.setRowCount(len(records))
        for row, (oid, created, status, raw) in enumerate(records):
            p = json.loads(raw)
            for col, v in enumerate(
                [
                    oid,
                    created,
                    p["community"] + " / " + p["building"],
                    p["quote"]["total"],
                    status,
                ]
            ):
                table.setItem(row, col, QTableWidgetItem(v))

        def view():
            row = table.currentRow()
            if row < 0:
                return
            oid, _, status, raw = records[row]
            path = self.store.root / (oid + ".html")
            path.write_text(order_html(oid, json.loads(raw), status), "utf-8")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

        def save_pdf():
            row = table.currentRow()
            if row < 0:
                return
            oid, _, status, raw = records[row]
            data = json.loads(raw)
            options = deepcopy(
                data.get("order_print")
                or self.store.config.get(
                    "order_print", {"paper": "A4", "color": "黑白"}
                )
            )
            options["paper_mm"] = list(
                paper_size(options.get("paper", "A4"), options, self.store.config)
            )
            path, _ = QFileDialog.getSaveFileName(
                dialog,
                "导出历史订单PDF",
                str(self.store.root / (oid + ".pdf")),
                "PDF (*.pdf)",
            )
            if path:
                try:
                    from order_pdf import write_order_pdf

                    write_order_pdf(path, oid, data, status, options)
                    QDesktopServices.openUrl(QUrl.fromLocalFile(path))
                except Exception as error:
                    self.error(str(error))

        pdf_button = QPushButton("导出选中订单 PDF")
        pdf_button.clicked.connect(save_pdf)
        layout.addWidget(pdf_button)
        btn = QPushButton("查看选中订单 / 浏览器打印订单")
        btn.clicked.connect(view)
        layout.addWidget(btn)
        dialog.exec()

    def closeEvent(self, event):
        desktop = getattr(self, "desktop", None)
        if desktop is not None and desktop.intercept_close(event):
            return
        if self.busy:
            QMessageBox.information(
                self,
                "任务进行中",
                "请等待当前转换或打印提交完成；如需停止打印，请先点击停止后续提交。",
            )
            event.ignore()
        else:
            try:
                config = deepcopy(self.store.config)
                config["file_column_widths"] = [
                    self.table.columnWidth(i)
                    for i in range(self.queue_model.columnCount())
                ]
                self.store.save(config)
            except Exception:
                logger.exception("Column widths could not be saved while closing")
            event.accept()
            if desktop is not None:
                desktop.finish_exit()


def main():
    if "--capture-driver" in sys.argv:
        from driver_capture import main as capture_main

        capture_main(sys.argv[sys.argv.index("--capture-driver") + 1])
        return
    from diagnostics import configure_logging

    configure_logging(data_dir())
    app = QApplication(sys.argv)
    app.setApplicationName("墨序")
    app.setApplicationVersion(VERSION)
    logger.info(
        "Application startup version=%s Qt=%s Python=%s",
        VERSION,
        qVersion(),
        sys.version.split()[0],
    )
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "moxu.ico")))
    app.setStyle("Fusion")
    if "--feature-check" in sys.argv:
        from runtime_checks import run

        report = Path(sys.argv[sys.argv.index("--feature-check") + 1])
        try:
            report.write_text(json.dumps(run(), ensure_ascii=False), "utf-8")
        except Exception:
            report.write_text(
                json.dumps({"error": traceback.format_exc()}, ensure_ascii=False),
                "utf-8",
            )
            raise
        return
    translator = QTranslator(app)
    if translator.load(
        "qtbase_zh_CN", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    ):
        app.installTranslator(translator)
    try:
        lock = QLockFile(str(data_dir() / "session.lock"))
        # Long-running single-instance lock: dead local PIDs are still detected.
        # A timestamp timeout could steal a healthy application's long-held lock.
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            from desktop_lifecycle import activate_existing

            if activate_existing(data_dir()):
                return
            QMessageBox.information(
                None, "墨序已运行", "请使用已经打开的窗口，避免重复提交订单。"
            )
            return
        from desktop_lifecycle import DesktopLifecycle

        window = Window()
        window.desktop = DesktopLifecycle(window)
        app.setQuitOnLastWindowClosed(not window.desktop.tray_available())
        start_hidden = "--startup" in sys.argv and window.desktop.tray_available()
        if (
            not start_hidden
            or window.store.recovery_notice
            or window.store.config.get("billing_review_required")
        ):
            window.show()
        if window.store.recovery_notice:
            QTimer.singleShot(
                0,
                lambda: QMessageBox.warning(
                    window, "设置已恢复，请核对", window.store.recovery_notice
                ),
            )
        elif window.store.config.get("billing_review_required"):
            notice = "\n".join(window.store.config.get("migration_notes", []))
            notice += (
                "\n请到后台核对并补充价格，确认后保存；未确认前不会按不完整价格打印。"
            )
            QTimer.singleShot(
                0, lambda: QMessageBox.warning(window, "升级后请核对价格", notice)
            )
        if "--diagnostic" in sys.argv:
            target = Path(sys.argv[sys.argv.index("--diagnostic") + 1])

            def check():
                window.grab().save(str(target.with_suffix(".png")))
                target.write_text(
                    json.dumps(
                        {
                            "startup": "passed",
                            "version": VERSION,
                            "printers": installed_printers(),
                            "qt": qVersion(),
                            "python": sys.version,
                        },
                        ensure_ascii=False,
                    ),
                    "utf-8",
                )
                window.desktop.request_exit()

            QTimer.singleShot(1200, check)
        sys.exit(app.exec())
    except Exception:
        QMessageBox.critical(None, "启动失败", traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
