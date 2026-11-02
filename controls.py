from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
    QStyledItemDelegate,
)


class StepArrow(QAbstractButton):
    def __init__(self, up, parent):
        super().__init__(parent)
        self.up = up
        self.setAutoRepeat(True)
        self.setAutoRepeatDelay(350)
        self.setAutoRepeatInterval(80)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.underMouse() and self.isEnabled():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(100, 150, 140, 45))
            p.drawRoundedRect(QRectF(self.rect()), 4, 4)
        color = self.palette().color(QPalette.ColorRole.Text)
        if not self.isEnabled():
            color.setAlpha(65)
        p.setPen(
            QPen(
                color,
                1.6,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        p.setBrush(Qt.BrushStyle.NoBrush)
        x, y = self.width() / 2, self.height() / 2
        sign = -1 if self.up else 1
        path = QPainterPath()
        path.moveTo(x - 3.5, y - sign * 1.5)
        path.lineTo(x, y + sign * 1.5)
        path.lineTo(x + 3.5, y - sign * 1.5)
        p.drawPath(path)


class StepperMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.lineEdit().setTextMargins(0, 0, 28, 0)
        self.up_button = StepArrow(True, self)
        self.down_button = StepArrow(False, self)
        self.up_button.clicked.connect(self.stepUp)
        self.down_button.clicked.connect(self.stepDown)
        self.valueChanged.connect(self.refresh_arrows)
        self.refresh_arrows()

    def refresh_arrows(self, *args):
        flags = self.stepEnabled()
        self.up_button.setEnabled(
            not self.isReadOnly()
            and bool(flags & QAbstractSpinBox.StepEnabledFlag.StepUpEnabled)
        )
        self.down_button.setEnabled(
            not self.isReadOnly()
            and bool(flags & QAbstractSpinBox.StepEnabledFlag.StepDownEnabled)
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        h = max(10, (self.height() - 6) // 2)
        self.up_button.setGeometry(self.width() - 29, 3, 25, h)
        self.down_button.setGeometry(self.width() - 29, 3 + h, 25, h)
        self.refresh_arrows()

    def sizeHint(self):
        size = super().sizeHint()
        size.setWidth(size.width() + 28)
        return size


class NumberSpin(StepperMixin, QSpinBox):
    pass


class DecimalSpin(StepperMixin, QDoubleSpinBox):
    pass


class CleanCombo(QComboBox):
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(self.palette().color(QPalette.ColorRole.Mid), 1))
        p.setBrush(self.palette().color(QPalette.ColorRole.Base))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
        if not self.isEditable():
            p.setPen(self.palette().color(QPalette.ColorRole.Text))
            text = self.fontMetrics().elidedText(
                self.currentText(),
                Qt.TextElideMode.ElideRight,
                max(1, self.width() - 43),
            )
            p.drawText(
                self.rect().adjusted(12, 0, -31, 0), Qt.AlignmentFlag.AlignVCenter, text
            )
        x, y = self.width() - 18, self.height() / 2
        path = QPainterPath()
        path.moveTo(x - 4, y - 2)
        path.lineTo(x, y + 2)
        path.lineTo(x + 4, y - 2)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(
            QPen(
                self.palette().color(QPalette.ColorRole.Text),
                1.7,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        p.drawPath(path)

    def showPopup(self):
        width = max(
            [self.width()]
            + [
                self.fontMetrics().horizontalAdvance(self.itemText(i)) + 40
                for i in range(self.count())
            ]
        )
        screen = self.screen()
        self.view().setMinimumWidth(
            min(width, screen.availableGeometry().width() - 40) if screen else width
        )
        super().showPopup()


def draw_switch(painter, rect, checked, enabled=True, progress=None):
    t = float(checked) if progress is None else progress
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor("#34c77b" if checked else "#647184")
    if not enabled:
        color.setAlpha(95)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
    diameter = rect.height() - 6
    x = rect.left() + 3 + t * (rect.width() - diameter - 6)
    painter.setBrush(QColor("#ffffff" if enabled else "#b4bdc8"))
    painter.drawEllipse(QRectF(x, rect.top() + 3, diameter, diameter))


class Switch(QCheckBox):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._position = 0.0
        self.animation = QPropertyAnimation(self, b"position", self)
        self.animation.setDuration(150)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self.animate)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(30)

    def get_position(self):
        return self._position

    def set_position(self, value):
        self._position = value
        self.update()

    position = Property(float, get_position, set_position)

    def animate(self, checked):
        if not self.isVisible():
            self.set_position(float(checked))
            return
        self.animation.stop()
        self.animation.setStartValue(self._position)
        self.animation.setEndValue(float(checked))
        self.animation.start()

    def sizeHint(self):
        return QSize(60 + self.fontMetrics().horizontalAdvance(self.text()), 32)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        p = QPainter(self)
        rect = QRectF(1, (self.height() - 26) / 2, 46, 26)
        draw_switch(p, rect, self.isChecked(), self.isEnabled(), self._position)
        p.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        p.drawText(
            self.rect().adjusted(57, 0, 0, 0),
            Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )
        if self.hasFocus():
            p.setPen(QColor("#75cfb8"))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 14, 14)


class SwitchDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        painter.fillRect(option.rect, option.palette.color(QPalette.ColorRole.Base))
        rect = QRectF(
            option.rect.center().x() - 23, option.rect.center().y() - 13, 46, 26
        )
        state = index.data(Qt.ItemDataRole.CheckStateRole)
        draw_switch(
            painter,
            rect,
            state in [Qt.CheckState.Checked, Qt.CheckState.Checked.value],
            bool(index.flags() & Qt.ItemFlag.ItemIsEnabled),
        )
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if not (index.flags() & Qt.ItemFlag.ItemIsEnabled):
            return False
        from PySide6.QtCore import QEvent

        activate = (
            event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
        )
        activate = activate or (
            event.type() == QEvent.Type.KeyPress
            and event.key() in [Qt.Key.Key_Space, Qt.Key.Key_Select]
        )
        if activate:
            old = index.data(Qt.ItemDataRole.CheckStateRole)
            return model.setData(
                index,
                0 if old in [Qt.CheckState.Checked, Qt.CheckState.Checked.value] else 2,
                Qt.ItemDataRole.CheckStateRole,
            )
        return False


class SegmentedChoice(QComboBox):
    """QComboBox-compatible segmented selector with an animated sliding pill."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slide = 0.0
        self.anim = QPropertyAnimation(self, b"slide", self)
        self.anim.setDuration(150)
        self.anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.currentIndexChanged.connect(self.move_pill)
        self.setMinimumHeight(38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def get_slide(self):
        return self._slide

    def set_slide(self, value):
        self._slide = value
        self.update()

    slide = Property(float, get_slide, set_slide)

    def move_pill(self, index):
        if not self.isVisible():
            self.set_slide(float(max(0, index)))
            return
        self.anim.stop()
        self.anim.setStartValue(self._slide)
        self.anim.setEndValue(float(index))
        self.anim.start()

    def sizeHint(self):
        return QSize(
            max(
                120,
                sum(
                    self.fontMetrics().horizontalAdvance(self.itemText(i)) + 24
                    for i in range(self.count())
                ),
            ),
            38,
        )

    def paintEvent(self, event):
        if not self.count():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.palette().color(QPalette.ColorRole.Base))
        p.drawRoundedRect(QRectF(self.rect()), 11, 11)
        width = (self.width() - 6) / self.count()
        p.setBrush(QColor("#307f73"))
        p.drawRoundedRect(
            QRectF(3 + self._slide * width, 3, width, self.height() - 6), 9, 9
        )
        for i in range(self.count()):
            p.setPen(
                QColor("white")
                if i == self.currentIndex()
                else self.palette().color(QPalette.ColorRole.Text)
            )
            p.drawText(
                QRectF(3 + i * width, 0, width, self.height()),
                Qt.AlignmentFlag.AlignCenter,
                self.itemText(i),
            )

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.count():
            self.setCurrentIndex(
                min(
                    self.count() - 1,
                    max(0, int(event.position().x() * self.count() / self.width())),
                )
            )
            event.accept()

    def mousePressEvent(self, event):
        event.accept()

    def keyPressEvent(self, event):
        if event.key() in [Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Space]:
            self.setCurrentIndex(
                (self.currentIndex() + (1 if event.key() != Qt.Key.Key_Left else -1))
                % max(1, self.count())
            )
            return
        super().keyPressEvent(event)


class CustomerResultDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(38)
        return size
