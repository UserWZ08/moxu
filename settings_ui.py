"""Graphical editors; all changes stay in the application configuration."""
import json,sys,tempfile,uuid
from copy import deepcopy
from pathlib import Path
from PySide6.QtCore import Qt,QProcess,QTimer
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QPushButton,QComboBox,QLineEdit,QSpinBox,QDoubleSpinBox,QCheckBox,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QTabWidget,QMessageBox,QFileDialog,QListWidget,QListWidgetItem,QDialogButtonBox,QScrollArea,QLayout)
from core import validate,migrate_config,data_dir
from catalog import ensure_catalog,configured_printers
from office import POLICIES
from pricing import enrich,effective,validate_discounts,summary
from quality import LEVELS,bindings as printer_quality_bindings
from controls import Switch as QCheckBox,SwitchDelegate,SegmentedChoice,CleanCombo,NumberSpin as QSpinBox,DecimalSpin as QDoubleSpinBox
from printing import installed_printers

PAPERS=['A4','A3','A5','B5']
COLORS=['黑白','彩色']
DUPLEX=['单面','双面长边','双面短边']

def choice(values,current=None):
    w=SegmentedChoice() if list(values) in [COLORS,DUPLEX,['单面','双面'],LEVELS] else CleanCombo();w.addItems([str(v) for v in values])
    if current is not None:w.setCurrentText(str(current))
    return w

def integer(value=1,maximum=999):
    w=QSpinBox();w.setRange(1,maximum);w.setValue(value);return w

def button(text,action,primary=False):
    w=QPushButton(text);w.clicked.connect(action)
    if primary:w.setObjectName('primary')
    return w

def table(headers):
    w=QTableWidget(0,len(headers));w.setHorizontalHeaderLabels(headers);w.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);w.horizontalHeader().setFixedHeight(46);w.verticalHeader().setDefaultSectionSize(40);w.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);w.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);w.verticalHeader().setVisible(False);w.setAlternatingRowColors(True);return w

def populate(w,rows):
    w.setRowCount(len(rows))
    for r,row in enumerate(rows):
        for c,value in enumerate(row):
            cell=QTableWidgetItem(str(value));cell.setToolTip(str(value));w.setItem(r,c,cell)

class Editor(QDialog):
    def __init__(self,title,parent):
        super().__init__(parent);self.setWindowTitle(title);self.resize(660,540);self.outer=QVBoxLayout(self);self.content=QWidget();self.body=QVBoxLayout(self.content);self.body.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize);self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setWidget(self.content);self.outer.addWidget(self.scroll,1);self.form=QFormLayout();self.body.addLayout(self.form)
    def finish(self):
        bar=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);bar.button(QDialogButtonBox.StandardButton.Save).setText('保存');bar.button(QDialogButtonBox.StandardButton.Cancel).setText('取消');bar.accepted.connect(self.submit);bar.rejected.connect(self.reject);self.outer.addWidget(bar)
    def submit(self):
        try:self.result_value=self.value();self.accept()
        except Exception as e:QMessageBox.warning(self,'请检查设置',str(e))

class CommunityEditor(Editor):
    def __init__(self,parent,name='',buildings=None):
        super().__init__('编辑小区与楼栋',parent);self.name=QLineEdit(name);self.form.addRow('小区名称',self.name)
        self.buildings=QListWidget();self.buildings.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);self.body.addWidget(QLabel('楼栋列表 · 双击名称可修改，按住 Ctrl 可多选删除'))
        self.body.addWidget(self.buildings)
        for name in buildings or []:self.add_name(name)
        bar=QHBoxLayout();self.new_name=QLineEdit();self.new_name.setPlaceholderText('例如：商业楼、东区1栋');bar.addWidget(self.new_name);bar.addWidget(button('添加楼栋',self.add_one));bar.addWidget(button('删除选中',self.delete));self.body.addLayout(bar)
        bar=QHBoxLayout();self.start=integer(1,9999);self.end=integer(10,9999);self.suffix=QLineEdit('栋');self.suffix.setMaximumWidth(90)
        for w in [QLabel('批量生成'),self.start,QLabel('至'),self.end,QLabel('后缀'),self.suffix,button('生成楼栋',self.generate)]:bar.addWidget(w)
        self.body.addLayout(bar);self.finish()
    def add_name(self,name):
        if name not in [self.buildings.item(i).text() for i in range(self.buildings.count())]:
            item=QListWidgetItem(name);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsEditable);self.buildings.addItem(item)
    def add_one(self):
        if self.new_name.text().strip():self.add_name(self.new_name.text().strip());self.new_name.clear()
    def delete(self):
        for item in self.buildings.selectedItems():self.buildings.takeItem(self.buildings.row(item))
    def generate(self):
        if self.end.value()<self.start.value():QMessageBox.warning(self,'范围无效','结束楼栋号应不小于起始号');return
        if self.end.value()-self.start.value()>1000:QMessageBox.warning(self,'范围过大','一次最多生成 1001 栋');return
        for n in range(self.start.value(),self.end.value()+1):self.add_name(str(n)+self.suffix.text())
    def value(self):
        name=self.name.text().strip();buildings=[self.buildings.item(i).text().strip() for i in range(self.buildings.count())]
        if not name or not buildings or any(not b for b in buildings):raise ValueError('请输入小区名称并添加至少一栋楼')
        if len(buildings)!=len(set(buildings)):raise ValueError('楼栋名称不能重复')
        return name,buildings

class PrinterEditor(Editor):
    def __init__(self,parent,profile=None):
        super().__init__('打印机能力与分配规则',parent);self.resize(850,650);p=profile or {};names=installed_printers()
        if p.get('name') and p['name'] not in names:names.append(p['name'])
        self.name=choice(names,p.get('name'));self.form.addRow('系统打印机',self.name)
        self.enabled=QCheckBox('参与自动分配');self.enabled.setChecked(p.get('enabled',True));self.form.addRow('启用',self.enabled)
        self.priority=integer(p.get('priority',10),9999);self.form.addRow('优先级（越小越优先）',self.priority)
        row=QWidget();bar=QHBoxLayout(row);bar.setContentsMargins(0,0,0,0);self.resolutions={}
        for dpi in sorted(set([300,600,1200]+p.get('dpi',[]))):
            cb=QCheckBox(str(dpi));cb.setChecked(dpi in p.get('dpi',[600]));bar.addWidget(cb);self.resolutions[dpi]=cb
        self.form.addRow('允许的 DPI',row)
        self.body.addWidget(QLabel('勾选此打印机允许接收的组合。这里只保存软件规则，不修改 Windows 驱动默认值。'))
        self.matrix=QTableWidget(len(PAPERS),6);self.matrix.setVerticalHeaderLabels(PAPERS);self.matrix.setHorizontalHeaderLabels([c+'\n'+d for c in COLORS for d in DUPLEX]);self.matrix.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.matrix.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.matrix.setItemDelegate(SwitchDelegate(self.matrix));self.matrix.horizontalHeader().setFixedHeight(64);self.matrix.verticalHeader().setFixedWidth(min(150,max(60,max(self.fontMetrics().horizontalAdvance(p) for p in PAPERS)+16)));self.matrix.setMinimumHeight(min(400,len(PAPERS)*38+80))
        rules=p.get('rules',[{'paper':'A4','color':'黑白','duplex':'单面'}])
        for r,paper in enumerate(PAPERS):
            for col,(color,duplex) in enumerate((c,d) for c in COLORS for d in DUPLEX):
                item=QTableWidgetItem();item.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Checked if {'paper':paper,'color':color,'duplex':duplex} in rules else Qt.CheckState.Unchecked);self.matrix.setItem(r,col,item)
        self.body.addWidget(self.matrix);self.body.addWidget(QLabel('B5 为 182 × 257 mm。硬件支持情况请以厂商驱动为准。'))
        self.original=deepcopy(p);self.quality_profiles=deepcopy(p.get('quality_profiles',[]));self.capture_process=None
        self.quality_choice=choice([v['name'] for v in self.quality_profiles],p.get('active_quality'));self.form.addRow('已保存厂商预设',self.quality_choice)
        self.quality_name=QLineEdit();self.quality_name.setPlaceholderText('例如：标准 / 高 / 照片');self.form.addRow('捕获预设名称',self.quality_name)
        bar=QHBoxLayout();self.capture_button=button('打开厂商窗口并捕获质量',self.capture_quality);bar.addWidget(self.capture_button);bar.addWidget(button('删除选中质量',self.remove_quality));self.body.addLayout(bar)
        self.binding_widgets={}
        for level in LEVELS:
            widget=choice([]);self.binding_widgets[level]=widget;self.form.addRow(level+'绑定',widget)
        self.refresh_bindings()
        self.name.currentTextChanged.connect(lambda *args:self.refresh_bindings(True))
        named_widget=QWidget();named=QHBoxLayout(named_widget);named.setContentsMargins(0,0,0,0);named.addWidget(button('捕获标准档',lambda:self.capture_named('标准')));named.addWidget(button('捕获高质量档',lambda:self.capture_named('高')));self.form.addRow('厂商质量捕获',named_widget)
        self.capture_status=QLabel('惠普可绑定600/1200 DPI；爱普生分别捕获“标准”“高”，再绑定到两档。\n厂商模式还需在“外观与功能”中开启。这里只保存到墨序，不修改系统默认值。');self.capture_status.setWordWrap(True);self.body.addWidget(self.capture_status);self.finish()
    def capture_named(self,name):self.quality_name.setText(name);self.capture_quality()
    def refresh_bindings(self,reset=False):
        source=dict(self.original,name=self.name.currentText(),quality_profiles=[p for p in self.quality_profiles if p.get('printer')==self.name.currentText()])
        if source['name']!=self.original.get('name'):source.pop('quality_bindings',None)
        defaults=printer_quality_bindings(source)
        for level,widget in self.binding_widgets.items():
            previous=defaults[level] if reset else widget.currentData() or defaults[level];widget.clear();widget.addItem('未配置',{'mode':'unconfigured'})
            for dpi in sorted(self.resolutions):widget.addItem(str(dpi)+' DPI',{'mode':'dpi','dpi':dpi})
            for profile in self.quality_profiles:widget.addItem('厂商预设：'+profile['name'],{'mode':'native','profile':profile['name']})
            index=next((i for i in range(widget.count()) if widget.itemData(i)==previous),-1)
            if index<0:widget.addItem('待捕获：'+previous.get('profile','未配置'),previous);index=widget.count()-1
            widget.setCurrentIndex(index)
    def remove_quality(self):
        i=self.quality_choice.currentIndex()
        if i>=0:del self.quality_profiles[i];self.quality_choice.removeItem(i);self.refresh_bindings()
    def capture_quality(self):
        if self.capture_process is not None:return
        name=self.quality_name.text().strip() or self.quality_choice.currentText()
        if not name:QMessageBox.warning(self,'填写名称','请先填写质量预设名称，例如“标准”或“高”');return
        printer=self.name.currentText()
        if not printer:return
        folder=data_dir()/'driver-capture';folder.mkdir(exist_ok=True);key=uuid.uuid4().hex;request=folder/(key+'.json');result=folder/(key+'-result.json')
        previous=next((v for v in self.quality_profiles if v['name']==name and v.get('printer')==printer),None)
        request.write_text(json.dumps({'printer':printer,'previous':previous,'output':str(result)},ensure_ascii=False),'utf-8')
        process=QProcess(self);self.capture_process=process;self.capture_button.setEnabled(False);self.capture_status.setText('请在厂商窗口选择标准/高、纸张材质等质量设置，然后确定。此操作不打印。')
        if getattr(sys,'frozen',False):process.setProgram(sys.executable);process.setArguments(['--capture-driver',str(request)])
        else:process.setProgram(sys.executable);process.setArguments([str(Path(__file__).with_name('driver_capture.py')),str(request)])
        def finished(*args):
            self.capture_process=None;self.capture_button.setEnabled(True)
            try:
                if not result.exists():raise RuntimeError('驱动窗口异常退出、未能启动或已超时，没有保存任何质量设置')
                data=json.loads(result.read_text('utf-8'))
                if data.get('error'):raise RuntimeError(data['error'])
                if data.get('cancelled'):self.capture_status.setText('已取消捕获，原预设没有改变');return
                profile=dict(data['profile'],name=name)
                old=next((i for i,v in enumerate(self.quality_profiles) if v['name']==name),None)
                if old is None:self.quality_profiles.append(profile)
                else:self.quality_profiles[old]=profile
                self.quality_choice.clear();self.quality_choice.addItems([v['name'] for v in self.quality_profiles]);self.quality_choice.setCurrentText(name);self.refresh_bindings();self.capture_status.setText('已捕获“'+name+'”。请核对两档绑定，保存打印机和全部设置后生效。')
            except Exception as e:self.capture_status.setText('捕获未完成：'+str(e))
            finally:request.unlink(missing_ok=True);result.unlink(missing_ok=True)
        process.finished.connect(finished)
        process.errorOccurred.connect(lambda error: finished() if error==QProcess.ProcessError.FailedToStart else None)
        timer=QTimer(process);timer.setSingleShot(True);timer.setInterval(180000);timer.timeout.connect(process.kill);process.finished.connect(timer.stop);process.start();timer.start()
    def reject(self):
        if self.capture_process is not None:self.capture_process.kill();self.capture_process.waitForFinished(1000)
        super().reject()
    def value(self):
        rules=[{'paper':paper,'color':color,'duplex':duplex} for r,paper in enumerate(PAPERS) for col,(color,duplex) in enumerate((c,d) for c in COLORS for d in DUPLEX) if self.matrix.item(r,col).checkState()==Qt.CheckState.Checked]
        dpi=[d for d,cb in self.resolutions.items() if cb.isChecked()]
        if not self.name.currentText():raise ValueError('没有可绑定的系统打印机，请先在 Windows 中安装')
        if not dpi or not rules:raise ValueError('至少选择一个 DPI 和一个打印组合')
        if self.capture_process is not None:raise ValueError('请先在厂商窗口完成或取消质量捕获')
        result=dict(self.original,name=self.name.currentText(),enabled=self.enabled.isChecked(),priority=self.priority.value(),dpi=dpi,rules=rules)
        profiles=[v for v in self.quality_profiles if v.get('printer')==self.name.currentText()]
        result.update(quality_profiles=profiles,active_quality=self.quality_choice.currentText(),quality_bindings={level:widget.currentData() for level,widget in self.binding_widgets.items()});return result

class PresetEditor(Editor):
    def __init__(self,parent,preset=None):
        super().__init__('编辑打印预设',parent);p=preset or {};o=deepcopy(p.get('options',{}));o.setdefault('quality_level','高质量打印' if o.get('dpi',600)>=1200 else '标准打印')
        self.name=QLineEdit(p.get('name',''));self.form.addRow('预设名称',self.name);self.fields={}
        for k,label,values,default in [('paper','纸张',PAPERS,'A4'),('color','颜色',COLORS,'黑白'),('duplex','单双面',DUPLEX,'单面'),('fit','图片缩放',['完整留白','填充裁切'],'完整留白'),('pdf_fit','文档缩放',['自适应纸张','仅缩小超大页面','实际大小'],'自适应纸张'),('quality_level','打印质量',LEVELS,'标准打印'),('printer','打印机',['自动分配']+configured_printers(parent.config),'自动分配')]:
            values=list(values)
            if o.get(k,default) not in values and k!='printer':values.append(o[k])
            self.fields[k]=choice(values,o.get(k,default));self.form.addRow(label,self.fields[k])
        self.copies=integer(o.get('copies',1));self.form.addRow('份数',self.copies);self.landscape=QCheckBox('横向');self.landscape.hide();self.form.addRow('纸张方向',QLabel('自动匹配文件内容'))
        self.body.addWidget(QLabel('预设可在主界面一键载入，再应用到选中或全部文件。\n标准/高质量会按每台打印机的绑定转换为 DPI 或厂商预设。'));self.finish()
    def value(self):
        name=self.name.text().strip()
        if not name:raise ValueError('请输入预设名称')
        o={k:w.currentText() for k,w in self.fields.items()};o.update(dpi=600,copies=self.copies.value(),landscape=False,orientation='auto',range='')
        return {'name':name,'options':o}

class PriceEditor(Editor):
    def __init__(self,parent,rule=None):
        super().__init__('标价与量大优惠',parent);p=enrich(rule or {'tiers':[[None,'0.20']],'mode':'progressive'});self.resize(760,640)
        self.paper=choice(PAPERS,p.get('paper','A4'));self.color=choice(COLORS,p.get('color','黑白'));self.duplex=choice(['单面','双面'],p.get('duplex','单面'));self.unit=choice(['面','张'],p.get('unit','面'));self.base=QDoubleSpinBox();self.base.setRange(0,100000);self.base.setDecimals(2);self.base.setSingleStep(.01);self.base.setValue(float(p['base_price']))
        for label,w in [('纸张',self.paper),('颜色',self.color),('打印方式',self.duplex),('计价单位',self.unit),('标价（元/单位）',self.base)]:self.form.addRow(label,w)
        self.discount=QCheckBox('启用量大优惠');self.discount.setChecked(p.get('discount_enabled',False));self.form.addRow(self.discount)
        self.mode=SegmentedChoice();self.mode.addItems(['分段优惠','满量优惠']);self.mode.setCurrentIndex(1 if p.get('mode')=='volume' else 0);self.form.addRow('优惠计算方式',self.mode)
        self.explanation=QLabel();self.explanation.setWordWrap(True);self.body.addWidget(self.explanation);self.tiers=table(['优惠从多少单位开始（含）','优惠单价（元）']);self.body.addWidget(self.tiers)
        for minimum,price in p.get('discounts',[]):self.add_tier(minimum,price)
        self.actions=QWidget();bar=QHBoxLayout(self.actions);bar.setContentsMargins(0,0,0,0);bar.addWidget(button('添加优惠档位',self.insert_tier));bar.addWidget(button('删除选中档位',self.remove_tier));self.body.addWidget(self.actions)
        self.discount.toggled.connect(self.describe);self.mode.currentIndexChanged.connect(self.describe);self.base.valueChanged.connect(self.describe);self.unit.currentTextChanged.connect(self.describe);self.describe();self.finish()
    @property
    def mode_key(self):return 'volume' if self.mode.currentIndex()==1 else 'progressive'
    def describe(self,*args):
        enabled=self.discount.isChecked();self.form.setRowVisible(self.mode,enabled);self.tiers.setVisible(enabled);self.actions.setVisible(enabled)
        if not enabled:self.explanation.setText('未启用优惠，全部数量按标价计算。');return
        self.explanation.setText('从门槛单位开始按优惠价计费，之前仍按标价。例如标价0.20，第21张起0.15，25张合计4.75元。' if self.mode_key=='progressive' else '达到门槛后，该打印类别的全部数量统一按优惠价计费。例如标价0.20，满20张0.15，25张合计3.75元。')
    def add_tier(self,minimum,price):
        row=self.tiers.rowCount();self.tiers.insertRow(row);quantity=integer(minimum,1000000);quantity.setMinimum(2);self.tiers.setCellWidget(row,0,quantity);money=QDoubleSpinBox();money.setRange(0,100000);money.setDecimals(2);money.setSingleStep(.01);money.setValue(float(price));self.tiers.setCellWidget(row,1,money)
    def insert_tier(self):
        count=self.tiers.rowCount();self.add_tier(self.tiers.cellWidget(count-1,0).value()+20 if count else 20,format(self.base.value(),'.2f'))
    def remove_tier(self):
        row=self.tiers.currentRow()
        if row>=0:self.tiers.removeRow(row)
    def value(self):
        rule={'paper':self.paper.currentText(),'color':self.color.currentText(),'duplex':self.duplex.currentText(),'unit':self.unit.currentText(),'mode':self.mode_key,'base_price':format(self.base.value(),'.2f'),'discount_enabled':self.discount.isChecked(),'discounts':[[self.tiers.cellWidget(r,0).value(),format(self.tiers.cellWidget(r,1).value(),'.2f')] for r in range(self.tiers.rowCount())]}
        validate_discounts(rule);rule=effective(rule)
        config={'theme':'浅色','billing':True,'communities':{'临时':['1栋']},'printers':[],'prices':[rule]}
        if hasattr(self.parent(),'config'):config['papers']=self.parent().config['papers']
        validate(config);return rule

class Settings(QDialog):
    def __init__(self,store,parent):
        super().__init__(parent);self.store=store;self.config=ensure_catalog(migrate_config(store.config));self.config.setdefault('presets',[]);PAPERS[:]=list(self.config['papers']);self.setWindowTitle('墨序 · 设置中心');self.resize(1080,760);self.body=QVBoxLayout(self);self.tabs=QTabWidget();self.body.addWidget(self.tabs)
        self.tables={}
        for key,title,headers in [('communities','小区与楼栋',['小区名称','楼栋数量','楼栋']),('printers','打印机',['系统打印机','启用','优先级','DPI','允许组合数']),('presets','打印预设',['名称','纸张','颜色','单双面','打印机']),('prices','价格与阶梯',['纸张','颜色','打印方式','单位','阶梯模式 / 价格'])]:
            page=QWidget();layout=QVBoxLayout(page);bar=QHBoxLayout();bar.addWidget(button('＋ 添加',lambda checked=False,k=key:self.edit(k)));bar.addWidget(button('编辑选中',lambda checked=False,k=key:self.edit(k,self.tables[k].currentRow())));bar.addWidget(button('删除选中',lambda checked=False,k=key:self.delete(k)));bar.addStretch();layout.addLayout(bar)
            if key=='printers':layout.addWidget(QLabel('勾选能力组合，设置自动分配优先级。此处不会打开厂商首选项，也不会修改系统默认配置。'))
            if key=='presets':layout.addWidget(QLabel('保存常用纸张、颜色、单双面、打印机及 DPI，在主界面一键载入。'))
            if key=='prices':layout.addWidget(QLabel('支持按面 / 张收费和多段阶梯。所有金额均可在表单中修改。'))
            t=table(headers);self.tables[key]=t;t.cellDoubleClicked.connect(lambda row,col,k=key:self.edit(k,row));layout.addWidget(t);self.tabs.addTab(page,title)
        page=QWidget();form=QFormLayout(page);self.theme=choice(['跟随系统','浅色','深色'],self.config['theme']);self.billing=QCheckBox('启用订单计价');self.billing.setChecked(self.config['billing']);form.addRow('外观模式',self.theme);self.office_engine=choice(POLICIES,self.config.get('office_engine',POLICIES[0]));form.addRow('Office转换引擎',self.office_engine);form.addRow('计价',self.billing);self.coverage=QCheckBox('显示覆盖率估算工具');self.coverage.setChecked(self.config.get('coverage_enabled',True));form.addRow('覆盖率',self.coverage);self.native_quality=QCheckBox('启用后台捕获的厂商质量预设');self.native_quality.setChecked(self.config.get('native_quality_enabled',False));form.addRow('打印质量',self.native_quality);form.addRow(QLabel('开启后，有已保存质量预设的打印机使用其当前预设；无预设的设备仍使用通用 DPI。'));self.review=QCheckBox('我已核对迁移后的单双面价格');self.review.setVisible(bool(self.config.get('billing_review_required')));form.addRow(self.review);form.addRow(QLabel('\n'.join(self.config.get('migration_notes',[]))));form.addRow(QLabel('设置保存在本机。保存后立即生效；取消不会修改原配置。'));self.tabs.addTab(page,'外观与功能')
        from business_settings import CatalogPage,OrderTemplatePage
        self.catalog_pages=[]
        for key,title in [('papers','纸张尺寸'),('bindings','装订服务'),('document_templates','证件模板')]:
            page=CatalogPage(self,key);self.catalog_pages.append(page);self.tabs.addTab(page,title)
        self.order_page=OrderTemplatePage(self);self.tabs.addTab(self.order_page,'订单页')
        bar=QHBoxLayout();bar.addWidget(button('导入配置',self.import_config));bar.addWidget(button('导出配置',self.export_config));bar.addStretch();bar.addWidget(button('取消',self.reject));bar.addWidget(button('保存全部设置',self.save,True));self.body.addLayout(bar);self.refresh()
    def refresh(self):
        c=self.config;PAPERS[:]=list(c['papers'])
        for page in getattr(self,'catalog_pages',[]):page.refresh()
        populate(self.tables['communities'],[(name,len(bs),'、'.join(bs)) for name,bs in c['communities'].items()])
        populate(self.tables['printers'],[(p['name'],'是' if p.get('enabled',True) else '否',p.get('priority',10),' / '.join(map(str,p['dpi'])),len(p['rules'])) for p in c['printers']])
        populate(self.tables['presets'],[(p['name'],p['options']['paper'],p['options']['color'],p['options']['duplex'],p['options'].get('printer','自动分配')) for p in c['presets']])
        populate(self.tables['prices'],[(p['paper'],p['color'],p['duplex'],p['unit'],summary(p)) for p in c['prices']])
    def edit(self,key,row=None):
        if row is not None and row<0:return
        data=self.config[key];old=None
        if key=='communities':
            names=list(data);old=names[row] if row is not None else None;editor=CommunityEditor(self,old or '',data[old] if old else [])
        else:
            old=data[row] if row is not None else None;editor={'printers':PrinterEditor,'presets':PresetEditor,'prices':PriceEditor}[key](self,old)
        if editor.exec()!=QDialog.DialogCode.Accepted:return
        value=editor.result_value
        if key=='communities':
            name,buildings=value
            if name!=old and name in data:QMessageBox.warning(self,'名称重复','此小区已存在');return
            if old is not None:del data[old]
            data[name]=buildings
        else:
            candidate=deepcopy(data)
            if row is None:candidate.append(value)
            else:candidate[row]=value
            temp=deepcopy(self.config);temp[key]=candidate
            try:validate(temp)
            except Exception as e:QMessageBox.warning(self,'无法保存此项',str(e));return
            self.config[key]=candidate
        self.refresh()
    def delete(self,key):
        row=self.tables[key].currentRow()
        if row<0:return
        if QMessageBox.question(self,'删除配置','删除选中项目？保存全部设置后生效。')!=QMessageBox.StandardButton.Yes:return
        data=self.config[key]
        if isinstance(data,dict):del data[list(data)[row]]
        else:del data[row]
        self.refresh()
    def current(self):
        c=deepcopy(self.config);c['theme']=self.theme.currentText();c['billing']=self.billing.isChecked();c['coverage_enabled']=self.coverage.isChecked();c['native_quality_enabled']=self.native_quality.isChecked();c['office_engine']=self.office_engine.currentText();c['order_template']=self.order_page.value();
        if c.get('billing_review_required') and self.review.isChecked():c['billing_review_required']=False;c.pop('migration_notes',None)
        return validate(c)
    def save(self):
        try:
            from business_settings import materialize_images
            c=self.current();materialize_images(c,self.store.root);self.store.save(c);self.accept()
        except Exception as e:QMessageBox.warning(self,'设置未保存',str(e))
    def import_config(self):
        path,_=QFileDialog.getOpenFileName(self,'导入配置','','配置文件 (*.json)')
        if not path:return
        try:
            c=validate(ensure_catalog(migrate_config(json.loads(Path(path).read_text('utf-8')))));c.setdefault('presets',[]);self.config=c;self.theme.setCurrentText(c['theme']);self.billing.setChecked(c['billing']);self.coverage.setChecked(c.get('coverage_enabled',True));self.native_quality.setChecked(c.get('native_quality_enabled',False));self.review.setVisible(bool(c.get('billing_review_required')));self.review.setChecked(False);self.office_engine.setCurrentText(c.get('office_engine',POLICIES[0]));self.order_page.reload();self.refresh()
        except Exception as e:QMessageBox.warning(self,'导入失败',str(e))
    def export_config(self):
        try:
            c=self.current();path,_=QFileDialog.getSaveFileName(self,'导出配置','墨序配置.json','配置文件 (*.json)')
            if path:Path(path).write_text(json.dumps(c,ensure_ascii=False,indent=2),'utf-8')
        except Exception as e:QMessageBox.warning(self,'导出失败',str(e))
