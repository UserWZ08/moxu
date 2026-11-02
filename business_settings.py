import hashlib
import shutil
from copy import deepcopy
from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from controls import DecimalSpin, Switch
from settings_ui import Editor, button, choice, populate, table


class SizeEditor(Editor):
    def __init__(self, parent, name="", size=(100, 150)):
        super().__init__("纸张 / 证件模板尺寸", parent)
        self.name = QLineEdit(name)
        self.width = DecimalSpin()
        self.height = DecimalSpin()
        self.form.addRow("名称", self.name)
        for label, w, v in [
            ("宽度 mm", self.width, size[0]),
            ("高度 mm", self.height, size[1]),
        ]:
            w.setRange(10, 2000)
            w.setDecimals(2)
            w.setValue(v)
            self.form.addRow(label, w)
        self.body.addWidget(
            QLabel("纸张尺寸仍需打印机及驱动支持；证件模板为成品实际尺寸。")
        )
        self.finish()

    def value(self):
        if not self.name.text().strip():
            raise ValueError("名称不能为空")
        return self.name.text().strip(), [self.width.value(), self.height.value()]


class BindingEditor(Editor):
    def __init__(self, parent, item=None):
        super().__init__("装订方式与价格", parent)
        item = item or {}
        self.name = QLineEdit(item.get("name", ""))
        self.price = DecimalSpin()
        self.price.setRange(0, 100000)
        self.price.setDecimals(2)
        self.price.setValue(float(item.get("price", "0.00")))
        self.form.addRow("装订方式", self.name)
        self.form.addRow("每份价格（元）", self.price)
        self.body.addWidget(
            QLabel("例如订书钉、回形针、胶装或其他服务。订单中单独填写装订份数。")
        )
        self.finish()

    def value(self):
        if not self.name.text().strip():
            raise ValueError("名称不能为空")
        return {
            "name": self.name.text().strip(),
            "price": format(self.price.value(), ".2f"),
        }


class CatalogPage(QWidget):
    def __init__(self, settings, key):
        super().__init__(settings)
        self.settings = settings
        self.key = key
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(button("添加", lambda: self.edit()))
        bar.addWidget(button("编辑选中", lambda: self.edit(self.grid.currentRow())))
        bar.addWidget(button("删除选中", self.remove))
        bar.addStretch()
        layout.addLayout(bar)
        layout.addWidget(
            QLabel(
                "尺寸单位为毫米。纸张能力和价格可在对应页面单独配置。"
                if key == "papers"
                else (
                    "装订按份数单独计价；历史订单保留原来的方式和金额。"
                    if key == "bindings"
                    else "身份证预置85.6×54 mm；户口本采用143×105 mm，可在此新增或修改模板。"
                )
            )
        )
        self.grid = table(
            ["名称", "单价（元/份）"]
            if key == "bindings"
            else ["名称", "宽度 mm", "高度 mm"]
        )
        layout.addWidget(self.grid)
        self.grid.cellDoubleClicked.connect(lambda r, c: self.edit(r))
        self.refresh()

    def refresh(self):
        data = self.settings.config[self.key]
        populate(
            self.grid,
            (
                [[r["name"], format(float(r["price"]), ".2f")] for r in data]
                if isinstance(data, list)
                else [[name, f"{mm[0]:g}", f"{mm[1]:g}"] for name, mm in data.items()]
            ),
        )

    def edit(self, row=None):
        if row is not None and row < 0:
            return
        data = self.settings.config[self.key]
        if self.key == "bindings":
            old = data[row] if row is not None else None
            dlg = BindingEditor(self, old)
            if not dlg.exec():
                return
            value = dlg.result_value
            if any(r["name"] == value["name"] and i != row for i, r in enumerate(data)):
                QMessageBox.warning(self, "重复名称", "此装订方式已存在")
                return
            if row is None:
                data.append(value)
            else:
                data[row] = value
        else:
            old = list(data)[row] if row is not None else None
            dlg = SizeEditor(self, old or "", data[old] if old else (100, 150))
            if not dlg.exec():
                return
            name, mm = dlg.result_value
            if name != old and name in data:
                QMessageBox.warning(self, "重复名称", "此名称已存在")
                return
            if old is not None:
                del data[old]
            data[name] = mm
            if self.key == "papers" and old and old != name:
                for p in self.settings.config["printers"]:
                    for rule in p["rules"]:
                        if rule["paper"] == old:
                            rule["paper"] = name
                for rule in self.settings.config["prices"]:
                    if rule["paper"] == old:
                        rule["paper"] = name
                for preset in self.settings.config["presets"]:
                    if preset["options"]["paper"] == old:
                        preset["options"]["paper"] = name
        self.settings.refresh()

    def remove(self):
        row = self.grid.currentRow()
        if row < 0:
            return
        data = self.settings.config[self.key]
        if len(data) <= 1:
            QMessageBox.warning(self, "无法删除", "请至少保留一个选项")
            return
        if self.key == "papers":
            name = list(data)[row]
            c = self.settings.config
            if (
                any(r["paper"] == name for p in c["printers"] for r in p["rules"])
                or any(r["paper"] == name for r in c["prices"])
                or any(p["options"]["paper"] == name for p in c["presets"])
            ):
                QMessageBox.warning(
                    self, "正在使用", "请先移除打印机、价格或预设中对此纸张的引用"
                )
                return
        if (
            QMessageBox.question(self, "删除选项", "删除此选项？保存全部设置后生效。")
            != QMessageBox.StandardButton.Yes
        ):
            return
        if isinstance(data, list):
            del data[row]
        else:
            del data[list(data)[row]]
        self.settings.refresh()


class OrderTemplatePage(QWidget):
    def __init__(self, settings):
        super().__init__(settings)
        self.settings = settings
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.title = QLineEdit()
        self.header = QPlainTextEdit()
        self.footer = QPlainTextEdit()
        self.header.setMaximumHeight(100)
        self.footer.setMaximumHeight(100)
        self.contact = Switch("订单显示客户联系方式")
        for label, w in [
            ("订单标题", self.title),
            ("顶部自定义文字", self.header),
            ("底部自定义文字", self.footer),
            ("", self.contact),
        ]:
            form.addRow(label, w)
        self.auto_print = Switch("文件提交成功后自动打印订单页")
        self.print_paper = choice(list(settings.config["papers"]))
        self.print_color = choice(["黑白", "彩色"])
        from catalog import configured_printers

        self.print_printer = choice(["自动分配"] + configured_printers(settings.config))
        for label, w in [
            ("随单打印", self.auto_print),
            ("订单纸张", self.print_paper),
            ("订单颜色", self.print_color),
            ("订单打印机", self.print_printer),
        ]:
            form.addRow(label, w)
        note = QLabel(
            "订单独立单面打印1份，不插入文件背面；不计入文件价格。纸张与颜色也用于订单PDF导出。"
        )
        note.setWordWrap(True)
        form.addRow(note)
        self.list = QListWidget()
        layout.addWidget(self.list)
        bar = QHBoxLayout()
        bar.addWidget(button("添加图片 / 二维码", self.add))
        bar.addWidget(button("删除图片", self.remove))
        layout.addLayout(bar)
        bar = QHBoxLayout()
        self.position = choice(["顶部", "底部"])
        self.width = DecimalSpin()
        self.width.setRange(10, 180)
        self.width.setValue(35)
        bar.addWidget(QLabel("图片位置"))
        bar.addWidget(self.position)
        bar.addWidget(QLabel("打印宽度 mm"))
        bar.addWidget(self.width)
        layout.addLayout(bar)
        layout.addWidget(
            QLabel(
                "最多4张图片；生成订单时内嵌图片，订单HTML可离线打开和打印。文字按纯文本处理。"
            )
        )
        self.list.currentRowChanged.connect(self.select)
        self.width.valueChanged.connect(self.change)
        self.position.currentTextChanged.connect(self.change)
        self.reload()

    def reload(self):
        o = self.settings.config.get("order_print", {})
        self.auto_print.setChecked(o.get("enabled", False))
        self.print_paper.setCurrentText(o.get("paper", "A4"))
        self.print_color.setCurrentText(o.get("color", "黑白"))
        self.print_printer.setCurrentText(o.get("printer", "自动分配"))
        t = self.settings.config.get("order_template", {})
        self.title.setText(t.get("title", "墨序 · 订单"))
        self.header.setPlainText(t.get("header_text", ""))
        self.footer.setPlainText(t.get("footer_text", ""))
        self.contact.setChecked(t.get("show_contact", True))
        self.images = deepcopy(t.get("images", []))
        self.refresh_list()

    def refresh_choices(self):
        from catalog import configured_printers

        for widget, values in [
            (self.print_paper, list(self.settings.config["papers"])),
            (
                self.print_printer,
                ["自动分配"] + configured_printers(self.settings.config),
            ),
        ]:
            old = widget.currentText()
            widget.clear()
            widget.addItems(values)
            if old in values:
                widget.setCurrentText(old)

    def refresh_list(self):
        self.list.clear()
        self.list.addItems([Path(i["path"]).name for i in self.images])

    def select(self, row):
        if not 0 <= row < len(self.images):
            return
        self.position.blockSignals(True)
        self.width.blockSignals(True)
        self.position.setCurrentText(self.images[row].get("position", "顶部"))
        self.width.setValue(self.images[row].get("width_mm", 35))
        self.position.blockSignals(False)
        self.width.blockSignals(False)

    def change(self, *args):
        row = self.list.currentRow()
        if 0 <= row < len(self.images):
            self.images[row].update(
                position=self.position.currentText(), width_mm=self.width.value()
            )

    def add(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择订单图片", "", "图片 (*.png *.jpg *.jpeg *.bmp)"
        )
        for path in paths:
            if len(self.images) >= 4:
                break
            self.images.append({"path": path, "width_mm": 35, "position": "顶部"})
        self.refresh_list()

    def remove(self):
        row = self.list.currentRow()
        if row >= 0:
            del self.images[row]
            self.refresh_list()

    def value(self):
        return {
            "title": self.title.text().strip() or "墨序 · 订单",
            "header_text": self.header.toPlainText(),
            "footer_text": self.footer.toPlainText(),
            "show_contact": self.contact.isChecked(),
            "images": deepcopy(self.images),
        }

    def print_value(self):
        return {
            "enabled": self.auto_print.isChecked(),
            "paper": self.print_paper.currentText(),
            "color": self.print_color.currentText(),
            "printer": self.print_printer.currentText(),
        }


def materialize_images(config, root):
    from PySide6.QtGui import QImageReader

    for image in config.get("order_template", {}).get("images", []):
        p = Path(image["path"])
        if not p.is_file() or p.stat().st_size > 15_000_000:
            raise ValueError("订单图片不存在或大于15MB")
        if QImageReader(str(p)).read().isNull():
            raise ValueError("无法读取订单图片：" + p.name)
        directory = root / "assets"
        directory.mkdir(exist_ok=True)
        dest = directory / (
            hashlib.sha256(p.read_bytes()).hexdigest()[:24] + p.suffix.lower()
        )
        if p.resolve() != dest.resolve() and not dest.exists():
            shutil.copy2(p, dest)
        image["path"] = str(dest)
