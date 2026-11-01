import sys,os,tempfile,gc
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from PySide6.QtWidgets import QApplication,QPushButton,QHeaderView,QAbstractSpinBox
from PySide6.QtCore import Qt,QPoint,QPointF,QMimeData,QUrl,QCoreApplication
from PySide6.QtGui import QImage,QColor,QDragEnterEvent,QDropEvent
from PySide6.QtTest import QTest
from copy import deepcopy
from app import Window
from core import Store,DEFAULT
from settings_ui import Settings,PriceEditor,PrinterEditor
from photo_ui import PhotoStudio
from controls import NumberSpin,DecimalSpin
from printing import prepare
import customers
def run():
    app=QApplication.instance() or QApplication([]);output=Path(tempfile.mkdtemp(prefix='moxu-v6-previews-'))
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['LOCALAPPDATA']=tmp;seed=Store();c=deepcopy(DEFAULT);c['theme']='深色';c['communities']={'星河花园':['12栋']};c['printers']=[{'name':'HP LaserJet Pro M403d','enabled':True,'dpi':[600,1200],'rules':[{'paper':'A4','color':'黑白','duplex':'单面'}]}];seed.save(c);customer=customers.upsert(seed.db,{'name':'张三','community':'星河花园','building':'12栋','phone':'13800000000'});seed.db.close()
        with patch('app.installed_printers',return_value=['HP LaserJet Pro M403d']):
            win=Window();win.show();app.processEvents();win.load_customer(customer);win.complete_customers('zs');app.processEvents();assert win.customer_search.width()<=280;assert not hasattr(win,'customer_community');assert win.room.x()<win.customer.x();assert win.customer.width()<=150;assert win.qq.isVisible() and win.wechat.isVisible();assert win.completer.popup().height()>=50;assert win.completer.popup().minimumWidth()>=760;win.completer.popup().hide();assert win.table.horizontalHeader().sectionResizeMode(0)==QHeaderView.ResizeMode.Interactive;win.table.setColumnWidth(0,360);win.table.setColumnWidth(1,85)
            assert isinstance(win.copies,NumberSpin);assert win.copies.buttonSymbols()==QAbstractSpinBox.ButtonSymbols.NoButtons;QTest.mouseClick(win.copies.up_button,Qt.MouseButton.LeftButton);assert win.copies.value()==2;win.copies.setValue(1)
            image=QImage(210,297,QImage.Format.Format_RGB32);image.fill(QColor('white'));path=str(Path(tmp)/'sample.png');image.save(path);prepared,count,kind=prepare(path,Path(tmp)/'cache');win.items=[{'source':path,'prepared':prepared,'count':count,'kind':kind,'selected':[0],'options':win.options(),'status':'待打印'}];win.refresh();win.table.selectRow(0);app.processEvents();assert win.table.columnWidth(0)==360 and win.table.columnWidth(1)==85;assert win.preview_label.grab().toImage().pixelColor(20,20).lightness()>240
            win.quality.setCurrentText('高质量打印');assert win.items[0]['options']['quality_level']=='高质量打印';payload=win.payload();assert payload['items'][0]['options']['dpi']==1200;QTest.qWait(180);win.grab().save(str(output/'打印界面.png'))
            win.copies.setValue(3);assert win.items[0]['options']['copies']==3
            win.paper.setCurrentText('A3');assert win.items[0]['options']['paper']=='A3'
            pix=win.preview_label.pixmap();assert abs(pix.width()/pix.height()-297/420)<.015
            win.items.append(deepcopy(win.items[0]));win.items[1]['options']['paper']='A4';win.items[1]['options']['paper_mm']=[210,297];win.items[1]['options']['copies']=1;win.refresh()
            win.table.clearSelection()
            for row in range(2):
                for col in range(win.table.columnCount()):win.table.item(row,col).setSelected(True)
            win.duplex.setCurrentText('双面短边');assert win.items[0]['options']['copies']==3 and win.items[1]['options']['copies']==1;assert win.items[1]['options']['paper']=='A4'
            for row in range(25):customers.upsert(win.store.db,{'name':'张测试'+str(row),'community':'星河花园'})
            win.complete_customers('张');app.processEvents();assert win.completer.popup().height()>300;assert win.completer.popup().verticalScrollBar().maximum()>0
            win.completer.popup().grab().save(str(output/'客户搜索.png'));win.completer.popup().hide()
            win.table.clearSelection();win.table.selectRow(0);win.paper.setCurrentText('A4');win.duplex.setCurrentText('单面');win.items=win.items[:1];win.refresh();win.table.selectRow(0);win.load_customer(customer);win.room.setText('1201');win.qq.setText('123456');win.wechat.setText('test_wechat')
            dialog=win.confirmation_dialog(win.payload());dialog.show();app.processEvents();assert dialog.property('sheets')==3;assert dialog.property('sides')==3;assert dialog.width()>=1000;dialog.grab().save(str(output/'确认打印.png'));dialog.close()
            settings=Settings(win.store,win);settings.show();app.processEvents();price=PriceEditor(settings,{'paper':'A4','color':'黑白','duplex':'单面','unit':'面','mode':'progressive','tiers':[[None,'0.20']]});price.show();app.processEvents();assert isinstance(price.base,DecimalSpin);old=price.base.value();QTest.mouseClick(price.base.up_button,Qt.MouseButton.LeftButton);assert abs(price.base.value()-old-.01)<.00001;price.base.setValue(.2);assert not price.discount.isChecked();price.discount.setChecked(True);price.insert_tier();price.tiers.cellWidget(0,0).setValue(21);price.tiers.cellWidget(0,1).setValue(.15);assert price.value()['tiers']==[[20,'0.20'],[None,'0.15']];QTest.qWait(180);price.grab().save(str(output/'标价与优惠.png'));price.close()
            printer=PrinterEditor(settings,c['printers'][0]);printer.show();app.processEvents();assert printer.binding_widgets['标准打印'].currentData()=={'mode':'dpi','dpi':600};assert printer.binding_widgets['高质量打印'].currentData()=={'mode':'dpi','dpi':1200};printer.grab().save(str(output/'质量绑定.png'));printer.close();settings.close()
            studio=PhotoStudio(win.store,win);studio.show();app.processEvents();mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(path)]);enter=QDragEnterEvent(QPoint(50,50),Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier);QCoreApplication.sendEvent(studio,enter);assert enter.isAccepted();drop=QDropEvent(QPointF(50,50),Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier);QCoreApplication.sendEvent(studio,drop);assert len(studio.panels[0].records)==1;assert not any('换底' in button.text() for button in studio.findChildren(QPushButton));studio.grab().save(str(output/'证件照拖放.png'));studio.close()
            win.close();assert win.store.config['file_column_widths'][0]==360;win.store.db.close();del win,settings,price,printer,studio;gc.collect();app.processEvents()
    print('PASS: realtime options, multi-selection preserves other fields, paper preview ratio, customer layout, tall scrolling results, detailed confirmation; previous UI checks passed')

if __name__=='__main__':run()
