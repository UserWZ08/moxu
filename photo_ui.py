from pathlib import Path
import uuid
from PySide6.QtCore import Qt,QRectF,QPointF,Signal,QThread
from PySide6.QtGui import QPainter,QColor,QPen,QTransform
from PySide6.QtWidgets import QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QPushButton,QFileDialog,QMessageBox,QTabWidget,QListWidget,QDoubleSpinBox,QSpinBox,QLineEdit,QScrollArea,QLayout,QFrame
from controls import CleanCombo,Switch,NumberSpin as QSpinBox,DecimalSpin as QDoubleSpinBox
from printing import read_image
from catalog import paper_size
from photo_layout import center_crop,cropped,layout_rects,write_pdf

class LazyImages:
    def __init__(self,records,make):self.records=records;self.make=make
    def __len__(self):return len(self.records)
    def __getitem__(self,index):return self.make(self.records[index])

class CropView(QWidget):
    changed=Signal(object)
    def __init__(self):super().__init__();self.image=None;self.crop=(0,0,1,1);self.aspect=1;self.start=None;self.setMinimumSize(360,280);self.setCursor(Qt.CursorShape.CrossCursor)
    def set_image(self,image,aspect,rect=None):
        self.image=image;self.aspect=aspect;self.crop=tuple(rect) if rect else center_crop(image.width(),image.height(),aspect);self.update()
    def image_rect(self):
        scale=min((self.width()-20)/self.image.width(),(self.height()-20)/self.image.height());return QRectF((self.width()-self.image.width()*scale)/2,(self.height()-self.image.height()*scale)/2,self.image.width()*scale,self.image.height()*scale)
    def point(self,p):
        r=self.image_rect();return QPointF(max(0,min(1,(p.x()-r.x())/r.width())),max(0,min(1,(p.y()-r.y())/r.height())))
    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor('#f1f3f6'))
        if self.image is None:p.setPen(QColor('#546273'));p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,'拖入图片或点击导入，然后拖动框选需要保留的区域');return
        r=self.image_rect();p.drawImage(r,self.image);x,y,w,h=self.crop;c=QRectF(r.x()+x*r.width(),r.y()+y*r.height(),w*r.width(),h*r.height());p.setBrush(QColor(0,0,0,100));p.setPen(Qt.PenStyle.NoPen)
        for mask in [QRectF(r.left(),r.top(),r.width(),c.top()-r.top()),QRectF(r.left(),c.bottom(),r.width(),r.bottom()-c.bottom()),QRectF(r.left(),c.top(),c.left()-r.left(),c.height()),QRectF(c.right(),c.top(),r.right()-c.right(),c.height())]:p.drawRect(mask)
        p.setPen(QPen(QColor('#ff9c45'),2));p.setBrush(Qt.BrushStyle.NoBrush);p.drawRect(c)
    def mousePressEvent(self,e):
        if self.image is not None:self.start=self.point(e.position())
    def mouseMoveEvent(self,e):
        if self.start is None:return
        point=self.point(e.position());dx=point.x()-self.start.x();dy=point.y()-self.start.y();width=abs(dx);height=abs(dy);ratio=self.aspect*self.image.height()/self.image.width()
        if width/max(height,.0001)>ratio:width=height*ratio
        else:height=width/ratio
        if min(width,height)>.005:
            self.crop=(self.start.x()-width if dx<0 else self.start.x(),self.start.y()-height if dy<0 else self.start.y(),width,height);self.update();self.changed.emit(self.crop)
    def mouseReleaseEvent(self,e):self.start=None

class PhotoPanel(QWidget):
    queued=Signal(str,str)
    def __init__(self,store,documents=False):
        super().__init__();self.store=store;self.documents=documents;self.records=[];self.current=-1;self.setAcceptDrops(True);layout=QHBoxLayout(self);left=QVBoxLayout();layout.addLayout(left,1);self.view=CropView();left.addWidget(self.view,1);self.view.changed.connect(self.crop_changed)
        bar=QHBoxLayout();add=QPushButton('导入图片');add.clicked.connect(self.load);bar.addWidget(add);rotate=QPushButton('旋转 90°');rotate.clicked.connect(self.rotate);bar.addWidget(rotate);reset=QPushButton('重置裁切');reset.clicked.connect(self.reset_crop);bar.addWidget(reset);remove=QPushButton('移除当前');remove.clicked.connect(self.remove_current);bar.addWidget(remove);left.addLayout(bar)
        self.list=QListWidget();self.list.setMaximumHeight(105);self.list.currentRowChanged.connect(self.show_record);left.addWidget(self.list)
        side=QWidget();side.setMinimumWidth(310);side.setMaximumWidth(365);side_layout=QVBoxLayout(side);side_layout.setContentsMargins(0,0,0,0);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame);content=QWidget();right=QVBoxLayout(content);right.setContentsMargins(0,0,8,0);right.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize);scroll.setWidget(content);side_layout.addWidget(scroll,1);layout.addWidget(side);form=QFormLayout();right.addLayout(form)
        self.template=CleanCombo();self.templates={'身份证正反面':[85.6,54],'户口本内页':[143,105],'自定义':[85.6,54]} if documents else {'一寸':[25,35],'二寸':[35,49],'护照照片':[33,48],'自定义':[25,35]}
        if documents:self.templates.update(store.config.get('document_templates',{}))
        self.template.addItems(self.templates);form.addRow('排版模板',self.template)
        self.width=QDoubleSpinBox();self.height=QDoubleSpinBox()
        for name,spin in [('成品宽 mm',self.width),('成品高 mm',self.height)]:spin.setRange(10,1000);spin.setDecimals(2);form.addRow(name,spin)
        self.paper=CleanCombo();self.paper.addItems(store.config['papers']);self.paper.setCurrentText('A4' if documents else '6寸相纸');form.addRow('输出纸张',self.paper)
        self.margin=QDoubleSpinBox();self.margin.setRange(0,100);self.margin.setValue(10 if documents else 4);form.addRow('边距 mm',self.margin)
        self.gap=QDoubleSpinBox();self.gap.setRange(0,100);self.gap.setValue(8 if documents else 2);form.addRow('间距 mm',self.gap)
        self.quantity=QSpinBox();self.quantity.setRange(0,100);self.quantity.setSpecialValueText('自动排满');form.addRow('照片数量',self.quantity);self.quantity.setVisible(not documents);form.labelForField(self.quantity).setVisible(not documents)
        self.marks=Switch('显示裁切标记');self.marks.setChecked(True);form.addRow(self.marks)
        self.info=QLabel();self.info.setWordWrap(True);right.addWidget(self.info)
        if not documents:
            note=QLabel('模板控制成品尺寸；头部比例及办理要求请另行核对。');note.setWordWrap(True);right.addWidget(note)
        if documents:
            note=QLabel('请裁到证件边缘并拍正；当前不自动校正透视。\n户口本默认143×105 mm，可修改。');note.setWordWrap(True);right.addWidget(note)
        right.addStretch();save=QPushButton('导出原尺寸 PDF');save.clicked.connect(lambda:self.export(False));side_layout.addWidget(save);queue=QPushButton('生成并加入打印队列');queue.setObjectName('primary');queue.clicked.connect(lambda:self.export(True));side_layout.addWidget(queue)
        self.template.currentTextChanged.connect(self.apply_template)
        for spin in [self.width,self.height]:spin.valueChanged.connect(self.dimension_changed)
        for w in [self.margin,self.gap,self.quantity]:w.valueChanged.connect(self.describe)
        self.paper.currentTextChanged.connect(self.describe);self.apply_template();self.describe()
    def apply_template(self,*args):
        w,h=self.templates[self.template.currentText()];self.width.blockSignals(True);self.height.blockSignals(True);self.width.setValue(w);self.height.setValue(h);self.width.blockSignals(False);self.height.blockSignals(False);self.dimension_changed()
    def dimension_changed(self,*args):
        if self.current>=0:self.reset_crop()
        self.describe()
    def describe(self,*args):
        try:
            count=len(self.records) if self.documents else self.quantity.value();pages=layout_rects(paper_size(self.paper.currentText(),config=self.store.config),(self.width.value(),self.height.value()),max(1,count) if self.documents else count,self.margin.value(),self.gap.value());self.info.setText(f'成品 {self.width.value():g} × {self.height.value():g} mm\n预计 {len(pages)} 页，首张 {len(pages[0])} 个。\n加入队列后将使用“实际大小”，请核对纸张。')
        except Exception as e:self.info.setText(str(e))
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and any(Path(u.toLocalFile()).suffix.lower() in ['.jpg','.jpeg','.png','.bmp'] for u in event.mimeData().urls()):event.acceptProposedAction()
    def dropEvent(self,event):
        self.add_paths([u.toLocalFile() for u in event.mimeData().urls()]);event.acceptProposedAction()
    def load(self):
        paths,_=QFileDialog.getOpenFileNames(self,'导入照片或证件图片','','图片 (*.jpg *.jpeg *.png *.bmp)');self.add_paths(paths)
    def add_paths(self,paths):
        for path in paths:
            if len(self.records)>=100:break
            if not Path(path).is_file() or Path(path).suffix.lower() not in ['.jpg','.jpeg','.png','.bmp']:continue
            if read_image(path).isNull():continue
            self.records.append({'path':path,'rotation':0,'crop':None});self.list.addItem(Path(path).name)
        if self.records:self.list.setCurrentRow(len(self.records)-1)
        self.describe()
    def image(self,record):
        image=read_image(record['path'])
        return image.transformed(QTransform().rotate(record['rotation'])) if record['rotation'] else image
    def show_record(self,index):
        if not 0<=index<len(self.records):return
        self.current=index;record=self.records[index];image=self.image(record)
        if image.isNull():QMessageBox.warning(self,'无法打开','图片损坏或格式不支持');return
        self.view.set_image(image,self.width.value()/self.height.value(),record['crop']);record['crop']=self.view.crop
    def crop_changed(self,crop):
        if self.current>=0:self.records[self.current]['crop']=crop
    def reset_crop(self):
        if self.current>=0:self.records[self.current]['crop']=None;self.show_record(self.current)
    def rotate(self):
        if self.current>=0:r=self.records[self.current];r['rotation']=(r['rotation']+90)%360;r['crop']=None;self.show_record(self.current)
    def remove_current(self):
        if self.current<0:return
        index=self.current;self.list.blockSignals(True);self.list.takeItem(index);self.records.pop(index);self.list.blockSignals(False)
        if self.records:self.list.setCurrentRow(min(index,len(self.records)-1));self.show_record(min(index,len(self.records)-1))
        else:self.current=-1;self.view.image=None;self.view.update()
        self.describe()
    def export(self,queue):
        try:
            if not self.records:raise ValueError('请先导入图片')
            records=self.records if self.documents else [self.records[self.current]]
            def make(record):
                image=self.image(record)
                if image.isNull():raise ValueError('图片无法读取')
                rect=record['crop'] or center_crop(image.width(),image.height(),self.width.value()/self.height.value());return cropped(image,rect)
            images=LazyImages(records,make)
            if queue:
                directory=self.store.root/'generated';directory.mkdir(exist_ok=True);path=str(directory/('排版-'+uuid.uuid4().hex[:12]+'.pdf'))
            else:path,_=QFileDialog.getSaveFileName(self,'保存原尺寸排版','证件排版.pdf','PDF (*.pdf)')
            if not path:return
            temp=Path(path).with_name(Path(path).name+'.partial')
            try:
                write_pdf(temp,paper_size(self.paper.currentText(),config=self.store.config),(self.width.value(),self.height.value()),images,self.quantity.value(),self.margin.value(),self.gap.value(),self.marks.isChecked(),not self.documents);temp.replace(path)
            except Exception:temp.unlink(missing_ok=True);raise
            if queue:self.queued.emit(path,self.paper.currentText())
            else:QMessageBox.information(self,'已生成','PDF已保存。打印时选择“实际大小”，不要再次适应纸张。')
        except Exception as e:QMessageBox.warning(self,'未能排版',str(e))

class PhotoStudio(QDialog):
    generated=Signal(str,str)
    def __init__(self,store,parent):
        super().__init__(parent);self.setAcceptDrops(True);self.setWindowTitle('墨序 · 照片与证件排版');screen=self.screen().availableGeometry();self.resize(min(1120,screen.width()-50),min(820,screen.height()-65));self.setMinimumSize(840,550);layout=QVBoxLayout(self);tabs=QTabWidget();self.tabs=tabs;layout.addWidget(tabs);self.panels=[]
        for documents,title in [(False,'证件照排版'),(True,'身份证 / 户口本原尺寸')]:
            panel=PhotoPanel(store,documents);self.panels.append(panel);tabs.addTab(panel,title);panel.queued.connect(self.queued)
    def queued(self,path,paper):self.generated.emit(path,paper);self.accept()
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and any(Path(u.toLocalFile()).suffix.lower() in ['.jpg','.jpeg','.png','.bmp'] for u in event.mimeData().urls()):event.acceptProposedAction()
    def dropEvent(self,event):self.tabs.currentWidget().add_paths([u.toLocalFile() for u in event.mimeData().urls()]);event.acceptProposedAction()
    def reject(self):super().reject()
