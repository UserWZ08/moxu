"""Qt table projection of print queue records. No routing or printer calls here."""

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from print_models import PrintItemRecord


class PrintQueueModel(QAbstractTableModel):
    HEADERS = ["文件名称", "页数", "打印设置", "分配打印机", "状态", "覆盖率估算"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.records: list[PrintItemRecord] = []

    def replace(self, records: list[PrintItemRecord]) -> None:
        self.beginResetModel()
        self.records = records
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.records)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return self.HEADERS[section]
            return str(section + 1)
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in (
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.ToolTipRole,
        ):
            return None
        item = self.records[index.row()]
        options = item["options"]
        name = Path(item["source"]).name
        if item.get("source_files"):
            name = f"图片组（{item['count']}页）：" + " / ".join(
                Path(path).name for path in item["source_files"]
            )
        coverage = item.get("coverage")
        values = [
            name,
            str(item["count"]),
            f"{options['paper']} · {options['color']} · {options['duplex']} · {options['copies']}份",
            item.get("printer", "未匹配"),
            item["status"],
            f"约 {coverage['area_percent']:.2f}%" if coverage else "未估算",
        ]
        if role == Qt.ItemDataRole.ToolTipRole:
            if index.column() == 0:
                return (
                    item["source"]
                    + "\n转换/渲染："
                    + item.get("engine", "Qt PDF / 图像")
                )
            if index.column() == 5 and coverage:
                return f"着色面积约 {coverage['area_percent']:.2f}%；平均灰度覆盖约 {coverage['tone_percent']:.2f}%；抽样 {coverage['sampled_pages']}/{coverage['selected_pages']} 页。\n{coverage['method']}"
        return values[index.column()]
