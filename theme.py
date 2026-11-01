from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor, QGuiApplication
from PySide6.QtWidgets import QApplication

def apply_theme(mode):
    dark=mode=='深色' or (mode=='跟随系统' and QGuiApplication.styleHints().colorScheme()==Qt.ColorScheme.Dark)
    bg,card,fg,border,alternate=('#141c29','#1e2939','#e7edf7','#354359','#253246') if dark else ('#f2f5fa','#ffffff','#21324b','#dbe3ee','#f7f9fc')
    app=QApplication.instance();palette=QPalette()
    roles={'Window':bg,'WindowText':fg,'Base':card,'AlternateBase':alternate,'Text':fg,'Button':card,'ButtonText':fg,'ToolTipBase':card,'ToolTipText':fg,'Highlight':'#307f73','HighlightedText':'#ffffff','PlaceholderText':'#93a1b5' if dark else '#687b94','Light':border,'Midlight':border,'Mid':border,'Dark':bg,'Shadow':bg}
    for name,color in roles.items():palette.setColor(getattr(QPalette.ColorRole,name),QColor(color))
    for role in [QPalette.ColorRole.Text,QPalette.ColorRole.WindowText,QPalette.ColorRole.ButtonText]:palette.setColor(QPalette.ColorGroup.Disabled,role,QColor('#8490a0'))
    app.setPalette(palette)
    app.setStyleSheet(f'''
      QWidget{{font-family:"Microsoft YaHei UI";font-size:13px;color:{fg};}}
      QMainWindow,QDialog,QMessageBox{{background:{bg};}}
      QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QPlainTextEdit,QTableView,QListView{{background:{card};color:{fg};border:1px solid {border};border-radius:8px;padding:7px;selection-background-color:#307f73;selection-color:white;alternate-background-color:{alternate};}}
      QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox{{min-height:20px;}}
      QScrollArea{{background:{bg};border:0;}}
      QScrollBar:vertical{{background:{bg};width:10px;}}
      QScrollBar::handle:vertical{{background:{border};border-radius:4px;min-height:28px;}}
      QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}
      QAbstractItemView{{background-color:{card};color:{fg};selection-background-color:#307f73;selection-color:white;}}
      QComboBox QAbstractItemView{{background-color:{card};color:{fg};border:1px solid {border};selection-background-color:#307f73;selection-color:white;outline:0;}}
      QComboBox QAbstractItemView::item{{min-height:28px;background-color:{card};color:{fg};}}
      QComboBox QAbstractItemView::item:selected{{background-color:#307f73;color:white;}}
      QHeaderView{{background-color:{card};color:{fg};padding:0;border:0;}}
      QHeaderView::section{{background-color:{card};color:{fg};padding:6px;border:0;}}
      QTableCornerButton::section{{background-color:{card};border:1px solid {border};}}
      QAbstractScrollArea::corner{{background:{card};}}
      QTableWidget{{gridline-color:{border};}}
      QTableView::item:selected{{background:{'#294c46' if dark else '#d9eee7'};color:{fg};}}
      QPushButton{{background:{card};border:1px solid {border};border-radius:9px;padding:10px 12px;}}
      QPushButton:hover{{border-color:#3d9688;}}
      QPushButton:disabled{{color:#8490a0;}}
      QPushButton#primary{{background:#307f73;color:white;border:0;font-weight:600;}}
      QTabWidget::pane{{border:1px solid {border};background:{bg};border-radius:8px;}}
      QTabBar::tab{{background:{card};color:{fg};padding:12px 18px;border:1px solid {border};}}
      QTabBar::tab:selected{{background:#307f73;color:white;}}
      QCheckBox::indicator{{width:17px;height:17px;border:1px solid {border};border-radius:4px;background:{card};}}
      QCheckBox::indicator:checked{{background:#307f73;border:2px solid #75cfb8;}}
      QTableView::indicator{{width:17px;height:17px;}}
      QSplitter::handle{{background:{border};width:1px;}}
      QMenu{{background:{card};color:{fg};border:1px solid {border};}}
      QMenu::item:selected{{background:#307f73;color:white;}}
      QLabel#title{{font-size:28px;font-weight:700;}}
      QLabel#total{{font-size:34px;font-weight:700;color:#42a38e;padding:10px;}}
      QLabel#preview{{background:#ffffff;color:#526174;border:1px solid #dbe2e8;border-radius:12px;}}
      QToolTip{{background:{card};color:{fg};border:1px solid {border};}}
    ''')
    return dark
