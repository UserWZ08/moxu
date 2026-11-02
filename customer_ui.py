from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

import customers
from controls import CleanCombo
from settings_ui import Editor, button, populate, table


class CustomerEditor(Editor):
    def __init__(self, parent, store, record=None):
        super().__init__("客户档案", parent)
        self.store = store
        self.record = record or {}
        self.fields = {}
        self.resize(650, 650)
        labels = dict(zip(customers.FIELDS, customers.HEADERS[1:]))
        for key in customers.FIELDS:
            if key in ["community", "building"]:
                w = CleanCombo()
                w.setEditable(True)
                if key == "community":
                    w.addItems(list(store.config["communities"]))
                else:
                    w.addItems(
                        store.config["communities"].get(
                            self.record.get("community", ""), []
                        )
                    )
                w.setCurrentText(self.record.get(key, ""))
            else:
                w = QLineEdit(self.record.get(key, ""))
            self.fields[key] = w
            self.form.addRow(labels[key], w)
        self.fields["community"].currentTextChanged.connect(self.buildings)
        self.fields["alias"].setPlaceholderText("可填写其他读音、昵称或常用简称")
        self.body.addWidget(
            QLabel("手机号、QQ、微信均按文本保存。客户档案与订单快照分别保存。")
        )
        self.finish()

    def buildings(self, community):
        current = self.fields["building"].currentText()
        self.fields["building"].clear()
        self.fields["building"].addItems(
            self.store.config["communities"].get(community, [])
        )
        self.fields["building"].setCurrentText(current)

    def value(self):
        r = {
            key: (w.currentText() if isinstance(w, QComboBox) else w.text()).strip()
            for key, w in self.fields.items()
        }
        r["id"] = self.record.get("id", "")
        if not r["name"]:
            raise ValueError("请输入客户姓名")
        return r


class CustomerManager(QDialog):
    def __init__(self, store, parent, initial_search=""):
        super().__init__(parent)
        self.store = store
        self.selected_record = None
        self.setWindowTitle("墨序 · 客户档案")
        self.resize(1200, 680)
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.query = QLineEdit(initial_search)
        self.query.setPlaceholderText(
            "姓名 / 拼音 / 首字母 / 手机号 / QQ / 微信 / 小区 / 房号"
        )
        bar.addWidget(self.query)
        bar.addWidget(button("添加客户", self.add))
        bar.addWidget(button("编辑选中", self.edit))
        bar.addWidget(button("删除选中", self.remove))
        layout.addLayout(bar)
        self.grid = table(customers.HEADERS[1:])
        layout.addWidget(self.grid)
        layout.addWidget(
            QLabel(
                "列表最多显示2000条；输入关键字可搜索全部档案，Excel导出包含全部客户。"
            )
        )
        self.grid.cellDoubleClicked.connect(lambda *args: self.choose())
        self.query.textChanged.connect(self.refresh)
        bar = QHBoxLayout()
        bar.addWidget(button("导入 Excel", self.import_sheet))
        bar.addWidget(button("导出 Excel / 空白模板", self.export_sheet))
        bar.addStretch()
        bar.addWidget(button("使用选中客户", self.choose, True))
        layout.addLayout(bar)
        self.refresh()

    def refresh(self):
        self.records = customers.search(self.store.db, self.query.text(), limit=2000)
        populate(self.grid, [[r[k] for k in customers.FIELDS] for r in self.records])

    def current(self):
        row = self.grid.currentRow()
        return self.records[row] if 0 <= row < len(self.records) else None

    def add(self):
        self.edit(new=True)

    def edit(self, new=False):
        record = None if new else self.current()
        if not new and record is None:
            return
        dlg = CustomerEditor(self, self.store, record)
        if dlg.exec():
            try:
                customers.upsert(self.store.db, dlg.result_value)
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "保存失败", str(e))

    def remove(self):
        record = self.current()
        if not record:
            return
        if (
            QMessageBox.question(
                self, "删除客户", "删除此客户档案？历史订单中的客户快照仍会保留。"
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.store.db.execute("DELETE FROM customers WHERE id=?", (record["id"],))
        self.store.db.commit()
        self.refresh()

    def choose(self):
        if self.current():
            self.selected_record = self.current()
            self.accept()

    def export_sheet(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出客户档案", "客户档案.xlsx", "Excel (*.xlsx)"
        )
        if not path:
            return
        try:
            n = customers.export_xlsx(self.store.db, path)
            QMessageBox.information(
                self, "已导出", f"已导出 {n} 条客户记录。电话和账号列已设为文本。"
            )
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def import_sheet(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入客户档案", "", "Excel (*.xlsx)"
        )
        if not path:
            return
        try:
            n = customers.import_xlsx(self.store.db, path)
            self.refresh()
            QMessageBox.information(
                self,
                "已导入",
                f"已处理 {n} 条客户记录。已有编号与姓名一致时仅更新非空字段，缺列和空白不会清除原资料；相同姓名/地址/手机号会合并。",
            )
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))
