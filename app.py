import sys, os, json, html, traceback
from contextlib import ExitStack
from PySide6.QtCore import QSignalBlocker
from page_raster import preview_sheet,resolved_options
from pathlib import Path
from copy import deepcopy
from PySide6.QtCore import Qt, QThread, Signal, QSize, QTimer, QUrl, QLockFile, qVersion, QTranslator, QLibraryInfo, QStringListModel
from PySide6.QtGui import QDesktopServices, QPixmap, QGuiApplication, QTextDocument, QPageSize, QIcon,QPainter,QColor,QPen
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QSpinBox,QLineEdit,QTableWidget,QTableWidgetItem,QHeaderView,QFileDialog,QMessageBox,QDialog,QPlainTextEdit,QTabWidget,QFormLayout,QCheckBox,QSplitter,QAbstractItemView,QScrollArea,QFrame,QLayout,QCompleter)
from PySide6.QtPrintSupport import QPrinter,QPrintDialog
from PySide6.QtPdf import QPdfDocument
from core import Store, FORMATS, pages, route, quote, data_dir,active_quality,order_quote
from printing import prepare, installed_printers, make_printer, render, read_image
from settings_ui import Settings
from theme import apply_theme
from catalog import configured_printers,paper_size
from quality import LEVELS,resolve as resolve_quality
from customer_ui import CustomerManager,CustomerEditor
import customers
from receipt import order_html,snapshot_template
from controls import Switch as QCheckBox,SegmentedChoice,CleanCombo,NumberSpin as QSpinBox

class Worker(QThread):
    ready = Signal(object)
    failed = Signal(str)
    progress = Signal(str)
    def __init__(self, fn): super().__init__(); self.fn=fn
    def run(self):
        try: self.ready.emit(self.fn(self))
        except Exception as e: self.failed.emit(str(e))

def combo(values):
    c=SegmentedChoice() if list(values) in [['黑白','彩色'],['单面','双面长边','双面短边'],LEVELS] else CleanCombo(); c.addItems(values); return c

class Window(QMainWindow):
    def __init__(self):
        super().__init__(); self.store=Store(); self.items=[]; self.worker=None; self.busy=False; self.oid=None;self._loading_options=False
        self._layout_cache={};self.customer_record={};self.completion_records={};self.setWindowIcon(QIcon(str(Path(__file__).parent/'assets'/'moxu.ico')));self.setWindowTitle('墨序 · 打印工作台'); self.resize(1380,900); self.setMinimumSize(1050,730); self.setAcceptDrops(True)
        root=QWidget(); self.setCentralWidget(root); layout=QVBoxLayout(root); layout.setContentsMargins(28,22,28,22); layout.setSpacing(16)
        head=QHBoxLayout(); title=QLabel('墨序'); title.setObjectName('title'); head.addWidget(title); head.addWidget(QLabel('文件放进来，订单交出去')); head.addStretch()
        photos=QPushButton('照片 / 证件排版');photos.clicked.connect(self.photo_studio);head.addWidget(photos);clients=QPushButton('客户档案');clients.clicked.connect(self.customer_manager);head.addWidget(clients)
        settings=QPushButton('⚙  后台设置'); settings.clicked.connect(self.settings); head.addWidget(settings); history=QPushButton('订单记录'); history.clicked.connect(self.history); head.addWidget(history); layout.addLayout(head)
        customer=QHBoxLayout();self.community=combo(list(self.store.config['communities']));self.building=combo([]);self.community.currentTextChanged.connect(self.buildings);self.buildings()
        self.customer=QLineEdit();self.customer.setPlaceholderText('称呼（选填）');self.customer.setMaximumWidth(150);self.customer.textEdited.connect(self.reset_customer_identity)
        self.room=QLineEdit();self.room.setPlaceholderText('房号');self.room.setMaximumWidth(90)
        self.note=QLineEdit();self.note.setPlaceholderText('订单备注（选填）')
        for label,w in [('小区',self.community),('楼栋',self.building),('房号',self.room),('称呼',self.customer),('备注',self.note)]:customer.addWidget(QLabel(label));customer.addWidget(w)
        self.community.setMinimumWidth(145);self.building.setMinimumWidth(115);self.building.setMinimumContentsLength(8);self.building.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents);layout.addLayout(customer)
        contact_bar=QHBoxLayout();self.customer_search=QLineEdit();self.customer_search.setPlaceholderText('搜索姓名 / 拼音 / 手机 / QQ / 微信');self.customer_search.setMinimumWidth(180);self.customer_search.setMaximumWidth(280);contact_bar.addWidget(self.customer_search)
        self.customer_model=QStringListModel(self);self.completer=QCompleter(self.customer_model,self);self.completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion);self.completer.setMaxVisibleItems(12);self.customer_search.setCompleter(self.completer);self.customer_search.textEdited.connect(self.complete_customers);self.completer.activated[str].connect(self.pick_customer)
        from controls import CustomerResultDelegate
        self.completer.popup().setItemDelegate(CustomerResultDelegate(self.completer.popup()));self.completer.popup().setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel);self.completer.popup().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.phone=QLineEdit();self.phone.setPlaceholderText('手机号');self.phone.setMaximumWidth(150)
        self.qq=QLineEdit();self.qq.setPlaceholderText('QQ号');self.wechat=QLineEdit();self.wechat.setPlaceholderText('微信号');self.contact=QLineEdit();self.contact.setPlaceholderText('其他联系方式');self.contact.setMaximumWidth(160)
        for label,w in [('手机',self.phone),('QQ',self.qq),('微信',self.wechat),('其他',self.contact)]:contact_bar.addWidget(QLabel(label));contact_bar.addWidget(w)
        save_customer=QPushButton('保存客户');save_customer.clicked.connect(self.save_customer);contact_bar.addWidget(save_customer);layout.addLayout(contact_bar)
        split=QSplitter(); layout.addWidget(split,1); left=QWidget(); ll=QVBoxLayout(left); ll.setContentsMargins(0,0,12,0); split.addWidget(left)
        actions=QHBoxLayout(); add=QPushButton('＋ 添加文件 / 拖放到窗口'); add.setObjectName('primary'); add.clicked.connect(self.pick); actions.addWidget(add); remove=QPushButton('移除选中'); remove.clicked.connect(self.remove); actions.addWidget(remove); merge=QPushButton('选中图片合为双面页组'); merge.clicked.connect(self.merge_images); actions.addWidget(merge); self.coverage_button=QPushButton('估算覆盖率'); self.coverage_button.clicked.connect(self.calculate_coverage); actions.addWidget(self.coverage_button); actions.addStretch(); ll.addLayout(actions)
        self.table=QTableWidget(0,6); self.table.setHorizontalHeaderLabels(['文件名称','页数','打印设置','分配打印机','状态','覆盖率估算']); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive);self.table.horizontalHeader().setMinimumSectionSize(45);
        widths=self.store.config.get('file_column_widths',[350,70,245,210,105,125]);
        for i,width in enumerate(widths[:6]):self.table.setColumnWidth(i,max(45,min(1600,int(width))))
        if not self.store.config.get('file_column_widths'):QTimer.singleShot(0,self.initial_column_widths)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.itemSelectionChanged.connect(self.selection_changed); ll.addWidget(self.table,1)
        self.preview_label=QLabel('拖入 Word、Excel、PPT、PDF 或图片\n转换后可在这里预览'); self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter); self.preview_label.setMinimumHeight(230); self.preview_label.setObjectName('preview'); ll.addWidget(self.preview_label)
        pbar=QHBoxLayout(); self.page=QSpinBox(); self.page.setRange(1,1); self.page.setPrefix('预览页 '); self.page.valueChanged.connect(self.preview); pbar.addWidget(self.page); openfile=QPushButton('用默认程序打开原文件'); openfile.clicked.connect(self.open_source); pbar.addWidget(openfile);proof=QPushButton('导出当前文件排版 PDF');proof.clicked.connect(self.export_proof);pbar.addWidget(proof);pbar.addStretch(); ll.addLayout(pbar)
        right=QWidget(); right.setMaximumWidth(340); rr=QVBoxLayout(right); form=QFormLayout(); self.option_form=form; rr.addLayout(form)
        self.paper=combo(list(self.store.config['papers'])); self.color=combo(['黑白','彩色']); self.duplex=combo(['单面','双面长边','双面短边']); self.fit=combo(['完整留白','填充裁切']); self.pdf_fit=combo(['自适应纸张','仅缩小超大页面','实际大小']); self.quality=combo(LEVELS);self.dpi=combo(['300','600','1200']); self.dpi.setCurrentText('600'); self.printer=combo(['自动分配']+configured_printers(self.store.config)); self.copies=QSpinBox(); self.copies.setRange(1,999); self.range=QLineEdit(); self.range.setPlaceholderText('全部，或 1-3,5'); self.landscape=QCheckBox('横向纸张');self.landscape.hide()
        for label,w in [('纸张',self.paper),('颜色',self.color),('单双面',self.duplex),('图片缩放',self.fit),('文档缩放',self.pdf_fit),('打印质量',self.quality),('打印机',self.printer),('份数',self.copies),('页码',self.range)]: form.addRow(label,w)
        self.quality_status=QLabel(); self.quality_status.setWordWrap(True); form.addRow(self.quality_status)
        self.preset=combo(['选择常用预设']+[p['name'] for p in self.store.config.get('presets',[])]); self.preset.currentIndexChanged.connect(self.load_preset); form.insertRow(0,'常用预设',self.preset)
        live=QLabel('选中文件后，修改设置立即生效');live.setWordWrap(True);rr.addWidget(live);allbtn=QPushButton('应用到全部文件');allbtn.clicked.connect(lambda:self.apply(True));rr.addWidget(allbtn)
        orientation_tip=QLabel('纸张方向自动匹配内容；长边 / 短边仅控制背面翻转。');orientation_tip.setWordWrap(True);rr.addWidget(orientation_tip)
        driver=QPushButton('后台设置打印质量'); driver.clicked.connect(lambda:self.settings(True)); rr.addWidget(driver)
        tip=QLabel('厂商质量可在后台捕获并启用。\n覆盖率是页面着色面积估算，不等于实际耗墨量。\n价格按纸张、颜色、单/双面分别累计。'); tip.setWordWrap(True); rr.addWidget(tip); rr.addStretch()
        self.binding=combo([b['name'] for b in self.store.config['bindings']]);self.binding_quantity=QSpinBox();self.binding_quantity.setRange(1,999);form.addRow('装订方式',self.binding);form.addRow('装订份数',self.binding_quantity);self.binding.currentTextChanged.connect(self.refresh);self.binding_quantity.valueChanged.connect(self.refresh)
        self.total=QLabel('¥ 0.00'); self.total.setObjectName('total'); rr.addWidget(self.total)
        export=QPushButton('生成订单页'); export.clicked.connect(self.export); rr.addWidget(export)
        self.printbtn=QPushButton('确认并批量打印'); self.printbtn.setObjectName('primary'); self.printbtn.clicked.connect(self.print_all); rr.addWidget(self.printbtn)
        self.stop=QPushButton('停止后续提交'); self.stop.clicked.connect(self.cancel); self.stop.setEnabled(False); rr.addWidget(self.stop)
        rr.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize);rr.setSpacing(8)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame);scroll.setWidget(right)
        panel=QWidget();panel.setMinimumWidth(350);panel.setMaximumWidth(380);panel_layout=QVBoxLayout(panel);panel_layout.setContentsMargins(0,0,0,0);panel_layout.addWidget(scroll,1)
        for w in [self.total,export,self.printbtn,self.stop]:rr.removeWidget(w);panel_layout.addWidget(w)
        split.addWidget(panel);split.setStretchFactor(0,1)
        self.status=QLabel('就绪 · 数据保存在本机，不会自动上传文件'); layout.addWidget(self.status)
        QGuiApplication.styleHints().colorSchemeChanged.connect(self.theme); self.theme(); self.sync_format_controls()
        for field in [self.paper,self.color,self.duplex,self.printer,self.quality]:field.currentIndexChanged.connect(self.sync_quality_controls)
        self.sync_quality_controls()
        self.option_widgets=[self.paper,self.color,self.duplex,self.fit,self.pdf_fit,self.quality,self.printer,self.copies,self.range]
        for field in self.option_widgets:
            signal=field.textChanged if field is self.range else field.valueChanged if field is self.copies else field.currentIndexChanged
            signal.connect(self.live_apply)
        self.edit_panel=right
    def selection_changed(self):
        self._pending_option_error=''
        rows=self.selected()
        if rows and rows[0]<len(self.items):
            o=self.items[rows[0]]['options'];self._loading_options=True
            try:
                for key,w in [('paper',self.paper),('color',self.color),('duplex',self.duplex),('fit',self.fit),('pdf_fit',self.pdf_fit),('printer',self.printer),('quality_level',self.quality)]:
                    w.setCurrentText(o.get(key,'标准打印' if key=='quality_level' else w.currentText()))
                self.copies.setValue(o['copies']);self.range.setText(o.get('range',''));self.dpi.setCurrentText(str(o.get('dpi',600)))
            finally:self._loading_options=False
            self.page.blockSignals(True);self.page.setValue(1);self.page.blockSignals(False)
        self.preview();self.sync_quality_controls()
    def live_apply(self,*args):
        if self._loading_options or self.busy:return
        mapping={self.paper:'paper',self.color:'color',self.duplex:'duplex',self.fit:'fit',self.pdf_fit:'pdf_fit',self.quality:'quality_level',self.printer:'printer',self.copies:'copies',self.range:'range'}
        key=mapping.get(self.sender())
        if not key:return
        try:
            options=self.options();updates=[]
            for row in self.selected():
                if not self.items[row]['count']:continue
                o=deepcopy(self.items[row]['options']);o[key]=options[key];o['orientation']='auto'
                if key=='paper':o['paper_mm']=options['paper_mm']
                updates.append((row,o,pages(o.get('range',''),self.items[row]['count'])))
            for row,o,selected in updates:
                self.items[row].update(options=o,selected=selected,status='待打印');self.items[row].pop('coverage',None)
            self._pending_option_error='';self.refresh()
        except Exception as error:
            self._pending_option_error=str(error);self.status.setText('设置尚未应用：'+str(error))
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'preview_label'):QTimer.singleShot(0,self.preview)
    def initial_column_widths(self):
        available=max(600,self.table.viewport().width()-4)
        for i,ratio in enumerate([.31,.07,.23,.19,.10,.10]):self.table.setColumnWidth(i,max(45,int(available*ratio)))
    def theme(self,*args):
        apply_theme(self.store.config['theme'])
    def buildings(self):
        self.building.clear(); self.building.addItems(self.store.config['communities'].get(self.community.currentText(),[]))
    def settings(self,quality=False):
        if self.busy: return
        dialog=Settings(self.store,self)
        if quality:dialog.tabs.setCurrentIndex(1)
        if dialog.exec():
            self._layout_cache.clear();self._loading_options=True
            previous_paper=self.paper.currentText();self.paper.clear();self.paper.addItems(list(self.store.config['papers']));self.paper.setCurrentText(previous_paper)
            self.binding.blockSignals(True);self.binding.clear();self.binding.addItems([b['name'] for b in self.store.config['bindings']]);self.binding.blockSignals(False)
            self.community.clear(); self.community.addItems(list(self.store.config['communities'])); self.printer.clear(); self.printer.addItems(['自动分配']+configured_printers(self.store.config)); self.preset.blockSignals(True); self.preset.clear(); self.preset.addItems(['选择常用预设']+[p['name'] for p in self.store.config.get('presets',[])]); self.preset.blockSignals(False); self._loading_options=False;self.theme(); self.refresh(); self.sync_quality_controls()
    def load_preset(self,index):
        if index<=0:return
        p=self.store.config.get('presets',[])[index-1];o=p['options'];self._loading_options=True
        if o.get('printer','自动分配') not in ['自动分配']+configured_printers(self.store.config):self._loading_options=False;self.error('预设中的打印机未在后台启用，请修改此预设');return
        for key,w in [('paper',self.paper),('color',self.color),('duplex',self.duplex),('fit',self.fit),('dpi',self.dpi),('printer',self.printer)]:
            value=str(o[key])
            if w.findText(value)<0:w.addItem(value)
            w.setCurrentText(value)
        self.copies.setValue(o['copies']);self.landscape.setChecked(o['landscape']);self.range.clear();self.quality.setCurrentText(o.get('quality_level','高质量打印' if o.get('dpi',600)>=1200 else '标准打印'));self.pdf_fit.setCurrentText(o.get('pdf_fit','自适应纸张'))
        self._loading_options=False;self.apply(False,silent=True);self.status.setText('已载入预设「'+p['name']+'」，已实时应用到选中文件')
    def reset_customer_identity(self,text):
        if text!=self.customer_record.get('name'):
            self.customer_record.clear()

    def complete_customers(self,text):
        records=customers.search(self.store.db,text,limit=5000) if text.strip() else []
        self.completion_records={f"{r['name']} · {r['community']} {r['building']} {r['room']} · {r['phone']} [{r['id'][:6]}]":r for r in records}
        self.customer_model.setStringList(list(self.completion_records));self.completer.setCompletionPrefix('')
        if records:
            desired=max(760,max(self.fontMetrics().horizontalAdvance(text)+60 for text in self.completion_records));self.completer.popup().setMinimumWidth(min(desired,self.screen().availableGeometry().width()-60));self.completer.complete();self.resize_customer_popup();QTimer.singleShot(0,self.resize_customer_popup)
    def resize_customer_popup(self):
        popup=self.completer.popup();count=self.customer_model.rowCount()
        if not count:return
        screen=self.screen().availableGeometry();origin=self.customer_search.mapToGlobal(self.customer_search.rect().bottomLeft())
        desired=min(count,12)*38+18;space_below=screen.bottom()-origin.y()-12;space_above=origin.y()-self.customer_search.height()-screen.top()-12
        height=min(desired,max(space_below,space_above));height=max(40,height)
        popup.resize(popup.width(),height)
        if space_below<height:popup.move(popup.x(),origin.y()-self.customer_search.height()-height)
    def pick_customer(self,text):
        record=self.completion_records.get(text)
        if record:self.load_customer(record)
    def load_customer(self,record):
        self.customer_record=dict(record);self.customer.setText(record['name']);self.phone.setText(record.get('phone',''));self.room.setText(record.get('room',''));self.contact.setText(record.get('contact',''));self.qq.setText(record.get('qq',''));self.wechat.setText(record.get('wechat',''))
        for combo_widget,key in [(self.community,'community'),(self.building,'building')]:
            value=record.get(key,'')
            if combo_widget.findText(value)<0:combo_widget.addItem(value)
            combo_widget.setCurrentText(value)
        self.customer_search.setText(record['name']);self.status.setText('已载入客户档案；修改订单字段不会自动覆盖档案')
    def customer_manager(self):
        if self.busy:return
        dialog=CustomerManager(self.store,self)
        if dialog.exec() and dialog.selected_record:self.load_customer(dialog.selected_record)
    def save_customer(self):
        if self.busy:return
        data=dict(self.customer_record,name=self.customer.text(),community=self.community.currentText(),building=self.building.currentText(),room=self.room.text(),phone=self.phone.text(),contact=self.contact.text(),qq=self.qq.text(),wechat=self.wechat.text())
        dialog=CustomerEditor(self,self.store,data)
        if dialog.exec():
            try:self.load_customer(customers.upsert(self.store.db,dialog.result_value))
            except Exception as e:self.error(str(e))
    def photo_studio(self):
        if self.busy:return
        from photo_ui import PhotoStudio
        dialog=PhotoStudio(self.store,self);dialog.generated.connect(self.add_layout);dialog.exec()
    def add_layout(self,path,paper):
        self._loading_options=True;self.paper.setCurrentText(paper);self.pdf_fit.setCurrentText('实际大小');self.range.clear();self.copies.setValue(1);self._loading_options=False;self.add_files([path])
    def options(self):
        return {'paper':self.paper.currentText(),'color':self.color.currentText(),'duplex':self.duplex.currentText(),'fit':self.fit.currentText(),'dpi':int(self.dpi.currentText()),'copies':self.copies.value(),'range':self.range.text(),'printer':self.printer.currentText(),'landscape':False,'orientation':'auto','pdf_fit':self.pdf_fit.currentText(),'paper_mm':list(paper_size(self.paper.currentText(),config=self.store.config)),'quality_level':self.quality.currentText()}
    def selected(self): return sorted({i.row() for i in self.table.selectedIndexes()})
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and not self.busy: event.acceptProposedAction()
    def dropEvent(self,event): self.add_files([u.toLocalFile() for u in event.mimeData().urls()])
    def pick(self):
        paths,_=QFileDialog.getOpenFileNames(self,'添加打印文件','','可打印文件 (*.pdf *.doc *.docx *.xls *.xlsx *.ppt *.pptx *.jpg *.jpeg *.png *.bmp *.tif *.tiff)'); self.add_files(paths)
    def run(self,fn,done):
        self.busy=True; self.printbtn.setEnabled(False); self.setAcceptDrops(False);self.edit_panel.setEnabled(False);self.table.setEnabled(False)
        self.worker=Worker(fn); self.worker.ready.connect(done); self.worker.failed.connect(self.error); self.worker.progress.connect(self.status.setText); self.worker.finished.connect(self.idle); self.worker.start()
    def idle(self): self.busy=False; self.printbtn.setEnabled(True); self.stop.setEnabled(False); self.setAcceptDrops(True);self.edit_panel.setEnabled(True);self.table.setEnabled(True)
    def error(self,msg): self.status.setText('操作失败：'+msg[:150]); QMessageBox.warning(self,'操作未完成',msg)
    def add_files(self,paths):
        if self.busy or not paths: return
        options=self.options();office_engine=self.store.config.get('office_engine','Microsoft Office 优先'); existing={s for i in self.items for s in i.get('source_files',[i['source']])}
        paths=[str(Path(p).resolve()) for p in paths if Path(p).suffix.lower() in FORMATS and str(Path(p).resolve()) not in existing]
        if not paths: return
        def load(w):
            result=[]
            from office import ConversionSession
            with ConversionSession() as session:
                for p in dict.fromkeys(paths):
                    w.progress.emit('正在解析：'+Path(p).name)
                    item={'source':p,'options':deepcopy(options),'status':'待打印'}
                    try:
                        item['prepared'],item['count'],item['kind']=prepare(p,self.store.root/'cache',office_engine,session=session); item['selected']=pages(options['range'],item['count']);from office import engine_label;item['engine']=engine_label(p,item['prepared'])
                    except Exception as e: item.update(count=0,selected=[],status='解析失败：'+str(e))
                    result.append(item)
            return result
        def done(result):
            self.items.extend(result);self.refresh();engines=' / '.join(sorted({i.get('engine','解析失败') for i in result}));self.status.setText('解析完成 · 引擎：'+engines+'；请核对预览、打印机与价格')
        self.run(load,done)
    def remove(self):
        if self.busy:return
        for row in reversed(self.selected()): del self.items[row]
        self.refresh()
    def merge_images(self):
        if self.busy:return
        try:
            rows=self.selected()
            if len(rows)<2 or any(self.items[r].get('kind')!='image' for r in rows):raise ValueError('请按住 Ctrl 选择至少两张已解析的独立图片；按队列从上到下的顺序组成页面')
            chosen=[self.items[r] for r in rows];o=deepcopy(chosen[0]['options']);o['range']='';o['duplex']='双面长边'
            item={'source':chosen[0]['source'],'source_files':[i['source'] for i in chosen],'prepared':[i['prepared'] for i in chosen],'kind':'images','count':len(chosen),'selected':list(range(len(chosen))),'options':o,'status':'待打印'}
            for r in reversed(rows):del self.items[r]
            self.items.insert(rows[0],item);self.refresh();self.status.setText('图片已按队列顺序组成一个双面任务；请核对双面设置与预览')
        except Exception as e:self.error(str(e))
    def apply(self,all_items,silent=False):
        if self.busy:return
        try:
            indices=list(range(len(self.items))) if all_items else self.selected()
            updates=[(i,pages(self.range.text(),self.items[i]['count'])) for i in indices if self.items[i]['count']]
            for i,selected in updates: self.items[i]['options']=deepcopy(self.options()); self.items[i]['selected']=selected; self.items[i]['status']='待打印'; self.items[i].pop('coverage',None)
            self._pending_option_error=''
            self.refresh()
        except Exception as e:
            if silent:self.status.setText('设置尚未应用：'+str(e))
            else:self.error(str(e))
    def refresh(self):
        selected_rows=self.selected();blocker=QSignalBlocker(self.table);self.table.setRowCount(len(self.items)); installed=installed_printers()
        for row,item in enumerate(self.items):
            o=item['options']
            try:item['printer']=route(self.store.config,o,installed)
            except Exception:item['printer']='未匹配'
            item.pop('preview_margins',None)
            if item.get('count') and item['printer']!='未匹配':
                try:
                    from printing import preview_margins
                    key=json.dumps([item['printer'],resolved_options(item)],sort_keys=True)
                    if key not in self._layout_cache:self._layout_cache[key]=preview_margins(item,self.store.config)
                    item['preview_margins']=self._layout_cache[key]
                except Exception:pass
            name=f"图片组（{item['count']}页）："+' / '.join(Path(s).name for s in item['source_files']) if item.get('source_files') else Path(item['source']).name
            for col,v in enumerate([name,str(item['count']),f"{o['paper']} · {o['color']} · {o['duplex']} · {o['copies']}份",item['printer'],item['status'],('约 %.2f%%'%item['coverage']['area_percent']) if item.get('coverage') else '未估算']):
                cell=QTableWidgetItem(v); cell.setToolTip(str(v)); self.table.setItem(row,col,cell)
                if col==0:cell.setToolTip(item['source']+'\n转换/渲染：'+item.get('engine','Qt PDF / 图像'))
                if col==5 and item.get('coverage'):
                    c=item['coverage'];cell.setToolTip(f"着色面积约 {c['area_percent']:.2f}%；平均灰度覆盖约 {c['tone_percent']:.2f}%；抽样 {c['sampled_pages']}/{c['selected_pages']} 页。\n{c['method']}")
        for row in selected_rows:
            if row<len(self.items):
                for column in range(self.table.columnCount()):self.table.item(row,column).setSelected(True)
        del blocker
        self.preview();self.sync_format_controls()
        try:
            if any(not i['count'] for i in self.items):raise ValueError('有文件未解析成功')
            q=order_quote(self.store.config,self.items,self.binding.currentText(),self.binding_quantity.value()); self.total.setText('¥ '+q['total'] if q['enabled'] else '不计价')
        except Exception as e:self.total.setText('价格待配置'); self.total.setToolTip(str(e))
    def preview(self):
        self.sync_format_controls()
        rows=self.selected()
        if not rows:return
        item=self.items[rows[0]]
        if not item['count']:self.preview_label.setText(item['status']);return
        self.page.blockSignals(True); self.page.setMaximum(item['count']); self.page.blockSignals(False)
        try:
            image=preview_sheet(item,self.page.value()-1);painter=QPainter(image);painter.setPen(QPen(QColor('#9aa7b6'),max(1,image.width()/650)));painter.drawRect(image.rect().adjusted(1,1,-2,-2));painter.end();pix=QPixmap.fromImage(image)
            self.preview_label.setPixmap(pix.scaled(self.preview_label.size()-QSize(24,24),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            self.preview_label.setToolTip('所选纸张的整张预览 · '+item['options']['paper']+' · '+item['options']['duplex']+' · 白色区域均属于纸张；驱动边距以实际设备为准')
        except Exception as error:self.preview_label.setText('预览失败：'+str(error))
    def sync_quality_controls(self,*args):
        if not hasattr(self,'quality_status'):return
        try:
            name=route(self.store.config,self.options(),installed_printers());quality=resolve_quality(self.store.config,name,self.options());self.quality_status.setText(name+'：'+quality['label'])
        except Exception as error:
            name=self.printer.currentText()
            if name!='自动分配':
                try:resolve_quality(self.store.config,name,self.options())
                except Exception as detail:error=detail
            self.quality_status.setText('质量绑定提示：'+str(error))
    def sync_format_controls(self):
        if not hasattr(self,'option_form'):return
        rows=self.selected();relevant=[self.items[i] for i in rows if i<len(self.items)] if rows else self.items
        kinds={i.get('kind') for i in relevant if i.get('count')}
        self.option_form.setRowVisible(self.fit,bool(kinds&{'image','images'}));self.option_form.setRowVisible(self.pdf_fit,'pdf' in kinds)
        enabled=self.store.config.get('coverage_enabled',True);self.coverage_button.setVisible(enabled);self.table.setColumnHidden(5,not enabled)
    def calculate_coverage(self):
        if self.busy:return
        rows=self.selected() or list(range(len(self.items)));targets=[(r,deepcopy(self.items[r])) for r in rows if self.items[r].get('count')]
        if not targets:self.error('请先导入可读取的文件');return
        def work(w):
            from coverage import estimate
            results=[]
            for row,item in targets:
                w.progress.emit('正在估算覆盖率：'+Path(item['source']).name)
                results.append((row,estimate(item)))
            return results
        def done(results):
            for row,result in results:self.items[row]['coverage']=result
            self.refresh();self.status.setText('覆盖率估算完成：按所选纸张与布局计算，非实际耗墨量；全部所选页面以150 DPI计算；面积和平均色调分别显示')
        self.run(work,done)
    def open_source(self):
        if self.selected(): QDesktopServices.openUrl(QUrl.fromLocalFile(self.items[self.selected()[0]]['source']))
    def export_proof(self):
        if self.busy:return
        try:
            rows=self.selected()
            if len(rows)!=1:raise ValueError('请选择一个已解析文件；导出所选页的单份排版，不提交打印')
            item=self.items[rows[0]]
            if not item.get('count'):raise ValueError('文件尚未解析成功')
            path,_=QFileDialog.getSaveFileName(self,'导出单份排版 · 不提交打印',str(self.store.root/'排版预览.pdf'),'PDF (*.pdf)')
            if path:
                from page_raster import write_proof
                write_proof(item,path);QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as error:self.error(str(error))
    def payload(self,subset=None):
        if getattr(self,'_pending_option_error',''):raise ValueError('请先修正尚未应用的设置：'+self._pending_option_error)
        items=deepcopy(self.items if subset is None else subset)
        if not items or any(not i['count'] for i in items):raise ValueError('请添加文件，并移除解析失败的文件')
        if not self.community.currentText() or not self.building.currentText():raise ValueError('请选择小区和楼栋')
        for item in items:
            item['printer']=route(self.store.config,item['options'],installed_printers());quality=resolve_quality(self.store.config,item['printer'],item['options']);item['options']['dpi']=quality['dpi'];item['options']=resolved_options(item);item['quality_name']=quality['label'];item['submitted_copies']=0
        return {'community':self.community.currentText(),'building':self.building.currentText(),'room':self.room.text(),'customer':self.customer.text(),'customer_id':self.customer_record.get('id',''),'phone':self.phone.text(),'qq':self.qq.text(),'wechat':self.wechat.text(),'contact':self.contact.text(),'note':self.note.text(),'items':items,'quote':order_quote(self.store.config,items,self.binding.currentText(),self.binding_quantity.value()),'order_template':snapshot_template(self.store.config)}
    def export(self):
        if self.busy:return
        try:
            payload=self.payload(); oid=self.store.order(payload); path,_=QFileDialog.getSaveFileName(self,'保存订单页',str(Path.home()/'Documents'/f'订单-{oid}.html'),'订单网页 (*.html)')
            if path:Path(path).write_text(order_html(oid,payload,'已创建'),encoding='utf-8');QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as e:self.error(str(e))
    def print_all(self):
        if self.busy:return
        try:
            payload=self.payload()
            if any(i['status']=='已提交' for i in self.items) and QMessageBox.question(self,'重复打印','队列中包含已提交文件。确定要再次打印吗？')!=QMessageBox.StandardButton.Yes:return
            if not self.confirm_print(payload):return
            self.dispatch(payload)
        except Exception as e:self.error(str(e))
    def confirmation_dialog(self,payload):
        dialog=QDialog(self);dialog.setWindowTitle('确认打印 · 核对客户与每个文件');dialog.resize(1080,690);layout=QVBoxLayout(dialog)
        sides=sum(len(i['selected'])*i['options']['copies'] for i in payload['items'])
        sheets=sum(((len(i['selected'])+1)//2 if i['options']['duplex']!='单面' else len(i['selected']))*i['options']['copies'] for i in payload['items'])
        customer=QLabel(f"{payload['community']} · {payload['building']} · 房号 {payload.get('room') or '未填'}\n称呼：{payload.get('customer') or '未填'}    联系电话：{payload.get('phone') or '未填'}\nQQ：{payload.get('qq') or '未填'}    微信：{payload.get('wechat') or '未填'}")
        customer.setWordWrap(True);layout.addWidget(customer)
        summary=QLabel(f"{len(payload['items'])} 个文件 · 打印 {sides} 面 · 用纸 {sheets} 张（不含设备额外分隔页） · 金额 ¥{payload['quote']['total']}");summary.setWordWrap(True);layout.addWidget(summary)
        table=QTableWidget(len(payload['items']),6);table.setHorizontalHeaderLabels(['文件 / 页码','份数','用纸张数','打印机','打印参数','质量']);table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);table.setWordWrap(True);table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for c,w in enumerate([240,55,75,210,245,160]):table.setColumnWidth(c,w)
        for row,item in enumerate(payload['items']):
            o=item['options'];n=len(item['selected']);sheet=((n+1)//2 if o['duplex']!='单面' else n)*o['copies']
            scaling=o.get('pdf_fit','自适应纸张') if item['kind']=='pdf' else o.get('fit','完整留白')
            values=[Path(item['source']).name+' · '+str(n)+'页 · '+(o.get('range') or '全部页码'),str(o['copies']),str(sheet),item['printer'],o['paper']+' · '+o['color']+' · '+o['duplex']+' · '+('横向' if o.get('landscape') else '纵向')+' · '+scaling,item.get('quality_name','')]
            for col,value in enumerate(values):cell=QTableWidgetItem(value);cell.setToolTip(value);table.setItem(row,col,cell)
        table.resizeRowsToContents();layout.addWidget(table,1);notice=QLabel('长边 / 短边控制背面翻转。纸张方向自动匹配首张选中页面，混合方向页面自动旋转排入同一纸张。');notice.setWordWrap(True);layout.addWidget(notice)
        buttons=QHBoxLayout();buttons.addStretch();cancel=QPushButton('返回检查');cancel.clicked.connect(dialog.reject);buttons.addWidget(cancel);confirm=QPushButton('确认提交打印');confirm.setObjectName('primary');confirm.clicked.connect(dialog.accept);buttons.addWidget(confirm);layout.addLayout(buttons)
        dialog.setProperty('sheets',sheets);dialog.setProperty('sides',sides);return dialog
    def confirm_print(self,payload):return self.confirmation_dialog(payload).exec()==QDialog.DialogCode.Accepted
    def dispatch(self,payload,native=None):
        oid=self.store.order(payload);self.oid=oid;self.store.status(oid,'正在提交');self.cancelled=False;self.stop.setEnabled(True)
        configuration=deepcopy(self.store.config)
        def work(w):
            try:
                for item in payload['items']:
                    for copy in range(item['options']['copies']):
                        if self.cancelled:raise RuntimeError('已停止后续提交，请核对系统打印队列')
                        w.progress.emit(f"正在提交 {Path(item['source']).name} · 第{copy+1}份")
                        quality=resolve_quality(configuration,item['printer'],item['options']);saved=quality['profile'];item['options']['dpi']=quality['dpi'];item['quality_name']=quality['label']
                        if native is None and saved:
                            from windows_driver import print_item
                            print_item(item,saved,lambda:self.cancelled)
                        else:
                            printer=native if native is not None else make_printer(item['printer'],item['options'])
                            render(item,printer,lambda:self.cancelled)
                        item['submitted_copies']+=1
                return payload,'已提交'
            except Exception as e:return payload,'需核对：'+str(e)
        def done(result):
            data,status=result;self.store.status(oid,status,data)
            for source in data['items']:
                for i in self.items:
                    if i['source']==source['source']:i['status']='已提交' if source['submitted_copies']==source['options']['copies'] else '需核对'
            self.refresh();self.status.setText('订单 '+oid+' · '+status)
            if status!='已提交':QMessageBox.warning(self,'部分任务可能已打印',status+'\n不要直接重打整单；请先核对打印队列和已提交份数。')
        self.run(work,done)
    def cancel(self):self.cancelled=True;self.status.setText('正在停止；已交给驱动的页面请在 Windows 打印队列中取消')
    def native_print(self):
        if self.busy:return
        try:
            rows=self.selected()
            if len(rows)!=1:raise ValueError('请选择一个文件')
            payload=self.payload([self.items[rows[0]]]); item=payload['items'][0]
            if item['options']['copies']!=1:raise ValueError('原生驱动模式请将此文件份数设为 1；批量份数请用标准流程')
            printer=make_printer(item['printer'],item['options'],strict=False);dialog=QPrintDialog(printer,self);dialog.setWindowTitle('原生驱动设置 · 确认后立即提交当前文件')
            if dialog.exec()!=QDialog.DialogCode.Accepted:return
            # Record generic settings actually returned by the driver dialog.
            o=item['options']; o['dpi']=printer.resolution();o['color']='彩色' if printer.colorMode()==QPrinter.ColorMode.Color else '黑白'
            o['duplex']={QPrinter.DuplexMode.DuplexNone:'单面',QPrinter.DuplexMode.DuplexLongSide:'双面长边',QPrinter.DuplexMode.DuplexShortSide:'双面短边'}.get(printer.duplex(),'双面长边')
            sz=printer.pageLayout().pageSize().size(QPageSize.Unit.Millimeter)
            dims=sorted([sz.width(),sz.height()]);paper=next((name for name,w,h in [('A3',297,420),('A4',210,297),('A5',148,210),('B5',182,257)] if abs(dims[0]-w)<1 and abs(dims[1]-h)<1),None)
            if paper is None:raise ValueError('原生模式仅支持 A3/A4/A5/B5(JIS)；请重新选择纸张')
            o['paper']=paper;o['copies']=printer.copyCount();o['printer']=printer.printerName();item['printer']=route(self.store.config,o,installed_printers());payload['quote']=quote(self.store.config,payload['items']);printer.setCopyCount(1)
            if QMessageBox.question(self,'确认驱动打印',f"以驱动返回的设置打印 {o['copies']} 份，金额 ¥{payload['quote']['total']}。\n原生对话框中的页码范围不生效，以文件列表已应用的页码为准。\n是否提交？")!=QMessageBox.StandardButton.Yes:return
            self.dispatch(payload,printer)
        except Exception as e:self.error(str(e))
    def history(self):
        if self.busy:return
        dialog=QDialog(self);dialog.setWindowTitle('订单记录 · 最近500单');dialog.resize(1000,620);layout=QVBoxLayout(dialog);table=QTableWidget(0,5);table.setHorizontalHeaderLabels(['订单号','时间','小区 / 楼栋','金额','状态']);table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);layout.addWidget(table);records=self.store.history();table.setRowCount(len(records))
        for row,(oid,created,status,raw) in enumerate(records):
            p=json.loads(raw)
            for col,v in enumerate([oid,created,p['community']+' / '+p['building'],p['quote']['total'],status]):table.setItem(row,col,QTableWidgetItem(v))
        def view():
            row=table.currentRow()
            if row<0:return
            oid,_,status,raw=records[row];path=self.store.root/(oid+'.html');path.write_text(order_html(oid,json.loads(raw),status),'utf-8');QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        btn=QPushButton('查看选中订单 / 浏览器打印订单');btn.clicked.connect(view);layout.addWidget(btn);dialog.exec()
    def closeEvent(self,event):
        if self.busy:QMessageBox.information(self,'任务进行中','请等待当前转换或打印提交完成；如需停止打印，请先点击停止后续提交。');event.ignore()
        else:
            try:
                config=deepcopy(self.store.config);config['file_column_widths']=[self.table.columnWidth(i) for i in range(self.table.columnCount())];self.store.save(config)
            except OSError:pass
            event.accept()

def main():
    if '--capture-driver' in sys.argv:
        from driver_capture import main as capture_main
        capture_main(sys.argv[sys.argv.index('--capture-driver')+1]);return
    app=QApplication(sys.argv);app.setApplicationName('墨序');app.setApplicationVersion('0.6.0');app.setWindowIcon(QIcon(str(Path(__file__).parent/'assets'/'moxu.ico')));app.setStyle('Fusion')
    if '--feature-check' in sys.argv:
        from runtime_checks import run
        report=Path(sys.argv[sys.argv.index('--feature-check')+1])
        try:report.write_text(json.dumps(run(),ensure_ascii=False),'utf-8')
        except Exception:report.write_text(json.dumps({'error':traceback.format_exc()},ensure_ascii=False),'utf-8');raise
        return
    translator=QTranslator(app)
    if translator.load('qtbase_zh_CN',QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):app.installTranslator(translator)
    try:
        lock=QLockFile(str(data_dir()/'session.lock'));lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            QMessageBox.information(None,'墨序已运行','请使用已经打开的窗口，避免重复提交订单。');return
        window=Window();window.show()
        if '--diagnostic' in sys.argv:
            target=Path(sys.argv[sys.argv.index('--diagnostic')+1])
            def check():
                window.grab().save(str(target.with_suffix('.png')))
                target.write_text(json.dumps({'startup':'passed','printers':installed_printers(),'qt':qVersion(),'python':sys.version},ensure_ascii=False),'utf-8');window.close();app.quit()
            QTimer.singleShot(1200,check)
        sys.exit(app.exec())
    except Exception:
        QMessageBox.critical(None,'启动失败',traceback.format_exc());raise

if __name__=='__main__':main()
