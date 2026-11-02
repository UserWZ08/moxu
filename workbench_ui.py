"""Workbench widget construction, split by screen area; no submission logic."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app import Window

from PySide6.QtCore import (
    QStringListModel,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QGuiApplication,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from catalog import configured_printers
from controls import (
    CleanCombo,
    NumberSpin,
    SegmentedChoice,
)
from quality import LEVELS
from queue_model import PrintQueueModel


def combo(values):
    c = (
        SegmentedChoice()
        if list(values) in [["黑白", "彩色"], ["单面", "双面长边", "双面短边"], LEVELS]
        else CleanCombo()
    )
    c.addItems(values)
    return c


def build_workbench(window: Window) -> None:
    root = QWidget()
    window.setCentralWidget(root)
    layout = QVBoxLayout(root)
    layout.setContentsMargins(28, 22, 28, 22)
    layout.setSpacing(16)
    _build_header(window, layout)
    _build_customer_fields(window, layout)
    split = QSplitter()
    layout.addWidget(split, 1)
    _build_file_panel(window, split)
    _build_print_panel(window, split)
    window.status = QLabel("就绪 · 数据保存在本机，不会自动上传文件")
    layout.addWidget(window.status)
    _connect_controls(window)


def _build_header(window: Window, layout: QVBoxLayout) -> None:
    head = QHBoxLayout()
    title = QLabel("墨序")
    title.setObjectName("title")
    head.addWidget(title)
    head.addWidget(QLabel("文件放进来，订单交出去"))
    head.addStretch()
    photos = QPushButton("照片 / 证件排版")
    photos.clicked.connect(window.photo_studio)
    head.addWidget(photos)
    clients = QPushButton("客户档案")
    clients.clicked.connect(window.customer_manager)
    head.addWidget(clients)
    settings = QPushButton("⚙  后台设置")
    settings.clicked.connect(window.settings)
    head.addWidget(settings)
    history = QPushButton("订单记录")
    history.clicked.connect(window.history)
    head.addWidget(history)
    layout.addLayout(head)


def _build_customer_fields(window: Window, layout: QVBoxLayout) -> None:
    customer = QHBoxLayout()
    window.community = combo(list(window.store.config["communities"]))
    window.building = combo([])
    window.community.currentTextChanged.connect(window.buildings)
    window.buildings()
    window.customer = QLineEdit()
    window.customer.setPlaceholderText("称呼（选填）")
    window.customer.setMaximumWidth(150)
    window.customer.textEdited.connect(window.reset_customer_identity)
    window.room = QLineEdit()
    window.room.setPlaceholderText("房号")
    window.room.setMaximumWidth(90)
    window.note = QLineEdit()
    window.note.setPlaceholderText("订单备注（选填）")
    for label, w in [
        ("小区", window.community),
        ("楼栋", window.building),
        ("房号", window.room),
        ("称呼", window.customer),
        ("备注", window.note),
    ]:
        customer.addWidget(QLabel(label))
        customer.addWidget(w)
    window.community.setMinimumWidth(145)
    window.building.setMinimumWidth(115)
    window.building.setMinimumContentsLength(8)
    window.building.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    layout.addLayout(customer)
    contact_bar = QHBoxLayout()
    window.customer_search = QLineEdit()
    window.customer_search.setPlaceholderText("搜索姓名 / 拼音 / 手机 / QQ / 微信")
    window.customer_search.setMinimumWidth(180)
    window.customer_search.setMaximumWidth(280)
    contact_bar.addWidget(window.customer_search)
    window.customer_model = QStringListModel(window)
    window.completer = QCompleter(window.customer_model, window)
    window.completer.setCompletionMode(
        QCompleter.CompletionMode.UnfilteredPopupCompletion
    )
    window.completer.setMaxVisibleItems(12)
    window.customer_search.setCompleter(window.completer)
    window.customer_search.textEdited.connect(window.complete_customers)
    window.completer.activated[str].connect(window.pick_customer)
    from controls import CustomerResultDelegate

    window.completer.popup().setItemDelegate(
        CustomerResultDelegate(window.completer.popup())
    )
    window.completer.popup().setVerticalScrollMode(
        QAbstractItemView.ScrollMode.ScrollPerPixel
    )
    window.completer.popup().setVerticalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    window.phone = QLineEdit()
    window.phone.setPlaceholderText("手机号")
    window.phone.setMaximumWidth(150)
    window.qq = QLineEdit()
    window.qq.setPlaceholderText("QQ号")
    window.wechat = QLineEdit()
    window.wechat.setPlaceholderText("微信号")
    window.contact = QLineEdit()
    window.contact.setPlaceholderText("其他联系方式")
    window.contact.setMaximumWidth(160)
    for label, w in [
        ("手机", window.phone),
        ("QQ", window.qq),
        ("微信", window.wechat),
        ("其他", window.contact),
    ]:
        contact_bar.addWidget(QLabel(label))
        contact_bar.addWidget(w)
    save_customer = QPushButton("保存客户")
    save_customer.clicked.connect(window.save_customer)
    contact_bar.addWidget(save_customer)
    layout.addLayout(contact_bar)


def _build_file_panel(window: Window, split: QSplitter) -> None:
    left = QWidget()
    ll = QVBoxLayout(left)
    ll.setContentsMargins(0, 0, 12, 0)
    split.addWidget(left)
    actions = QHBoxLayout()
    add = QPushButton("＋ 添加文件 / 拖放到窗口")
    add.setObjectName("primary")
    add.clicked.connect(window.pick)
    actions.addWidget(add)
    remove = QPushButton("移除选中")
    remove.clicked.connect(window.remove)
    actions.addWidget(remove)
    merge = QPushButton("选中图片合为双面页组")
    merge.clicked.connect(window.merge_images)
    actions.addWidget(merge)
    window.coverage_button = QPushButton("估算覆盖率")
    window.coverage_button.clicked.connect(window.calculate_coverage)
    actions.addWidget(window.coverage_button)
    actions.addStretch()
    ll.addLayout(actions)
    window.table = QTableView()
    window.queue_model = PrintQueueModel(window.table)
    window.table.setModel(window.queue_model)
    window.table.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.Interactive
    )
    window.table.horizontalHeader().setMinimumSectionSize(45)
    widths = window.store.config.get(
        "file_column_widths", [350, 70, 245, 210, 105, 125]
    )
    for i, width in enumerate(widths[:6]):
        window.table.setColumnWidth(i, max(45, min(1600, int(width))))
    if not window.store.config.get("file_column_widths"):
        QTimer.singleShot(0, window.initial_column_widths)
    window.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    window.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    window.table.selectionModel().selectionChanged.connect(window.selection_changed)
    ll.addWidget(window.table, 1)
    window.preview_label = QLabel(
        "拖入 Word、Excel、PPT、PDF 或图片\n转换后可在这里预览"
    )
    window.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    window.preview_label.setMinimumHeight(230)
    window.preview_label.setObjectName("preview")
    ll.addWidget(window.preview_label)
    pbar = QHBoxLayout()
    window.page = NumberSpin()
    window.page.setRange(1, 1)
    window.page.setPrefix("预览页 ")
    window.page.valueChanged.connect(window.preview)
    pbar.addWidget(window.page)
    openfile = QPushButton("用默认程序打开原文件")
    openfile.clicked.connect(window.open_source)
    pbar.addWidget(openfile)
    proof = QPushButton("导出当前文件排版 PDF")
    proof.clicked.connect(window.export_proof)
    pbar.addWidget(proof)
    pbar.addStretch()
    ll.addLayout(pbar)


def _build_print_panel(window: Window, split: QSplitter) -> None:
    right = QWidget()
    right.setMaximumWidth(340)
    rr = QVBoxLayout(right)
    form = QFormLayout()
    window.option_form = form
    rr.addLayout(form)
    window.paper = combo(list(window.store.config["papers"]))
    window.color = combo(["黑白", "彩色"])
    window.duplex = combo(["单面", "双面长边", "双面短边"])
    window.fit = combo(["完整留白", "填充裁切"])
    window.pdf_fit = combo(["自适应纸张", "仅缩小超大页面", "实际大小"])
    window.quality = combo(LEVELS)
    window.dpi = combo(["300", "600", "1200"])
    window.dpi.setCurrentText("600")
    window.printer = combo(["自动分配"] + configured_printers(window.store.config))
    window.copies = NumberSpin()
    window.copies.setRange(1, 999)
    window.range = QLineEdit()
    window.range.setPlaceholderText("全部，或 1-3,5")
    for label, w in [
        ("纸张", window.paper),
        ("颜色", window.color),
        ("单双面", window.duplex),
        ("图片缩放", window.fit),
        ("文档缩放", window.pdf_fit),
        ("打印质量", window.quality),
        ("打印机", window.printer),
        ("份数", window.copies),
        ("页码", window.range),
    ]:
        form.addRow(label, w)
    window.quality_status = QLabel()
    window.quality_status.setWordWrap(True)
    form.addRow(window.quality_status)
    window.preset = combo(
        ["选择常用预设"] + [p["name"] for p in window.store.config.get("presets", [])]
    )
    window.preset.currentIndexChanged.connect(window.load_preset)
    form.insertRow(0, "常用预设", window.preset)
    live = QLabel("选中文件后，修改设置立即生效")
    live.setWordWrap(True)
    rr.addWidget(live)
    allbtn = QPushButton("应用到全部文件")
    allbtn.clicked.connect(lambda: window.apply(True))
    rr.addWidget(allbtn)
    orientation_tip = QLabel("纸张方向自动匹配内容；长边 / 短边仅控制背面翻转。")
    orientation_tip.setWordWrap(True)
    rr.addWidget(orientation_tip)
    driver = QPushButton("后台设置打印质量")
    driver.clicked.connect(lambda: window.settings(True))
    rr.addWidget(driver)
    tip = QLabel(
        "厂商质量可在后台捕获并启用。\n覆盖率是页面着色面积估算，不等于实际耗墨量。\n价格按纸张、颜色、单/双面分别累计。"
    )
    tip.setWordWrap(True)
    rr.addWidget(tip)
    rr.addStretch()
    window.binding = combo([b["name"] for b in window.store.config["bindings"]])
    window.binding_quantity = NumberSpin()
    window.binding_quantity.setRange(1, 999)
    form.addRow("装订方式", window.binding)
    form.addRow("装订份数", window.binding_quantity)
    window.binding.currentTextChanged.connect(window.refresh)
    window.binding_quantity.valueChanged.connect(window.refresh)
    window.total = QLabel("¥ 0.00")
    window.total.setObjectName("total")
    rr.addWidget(window.total)
    export = QPushButton("生成订单页")
    export.clicked.connect(window.export)
    rr.addWidget(export)
    window.printbtn = QPushButton("确认并批量打印")
    window.printbtn.setObjectName("primary")
    window.printbtn.clicked.connect(window.print_all)
    rr.addWidget(window.printbtn)
    window.stop = QPushButton("停止后续提交")
    window.stop.clicked.connect(window.cancel)
    window.stop.setEnabled(False)
    rr.addWidget(window.stop)
    rr.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
    rr.setSpacing(8)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidget(right)
    panel = QWidget()
    panel.setMinimumWidth(350)
    panel.setMaximumWidth(380)
    panel_layout = QVBoxLayout(panel)
    panel_layout.setContentsMargins(0, 0, 0, 0)
    panel_layout.addWidget(scroll, 1)
    for w in [window.total, export, window.printbtn, window.stop]:
        rr.removeWidget(w)
        panel_layout.addWidget(w)
    split.addWidget(panel)
    split.setStretchFactor(0, 1)
    window.edit_panel = right


def _connect_controls(window: Window) -> None:
    QGuiApplication.styleHints().colorSchemeChanged.connect(window.theme)
    window.theme()
    window.sync_format_controls()
    for field in [
        window.paper,
        window.color,
        window.duplex,
        window.printer,
        window.quality,
    ]:
        field.currentIndexChanged.connect(window.sync_quality_controls)
    window.sync_quality_controls()
    window.option_widgets = [
        window.paper,
        window.color,
        window.duplex,
        window.fit,
        window.pdf_fit,
        window.quality,
        window.printer,
        window.copies,
        window.range,
    ]
    for field in window.option_widgets:
        signal = (
            field.textChanged
            if field is window.range
            else (
                field.valueChanged
                if field is window.copies
                else field.currentIndexChanged
            )
        )
        signal.connect(window.live_apply)
