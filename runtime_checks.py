"""Explicit offline smoke check for packaged distributions; never submits print jobs."""
import tempfile,json
from pathlib import Path

def run():
    from PySide6.QtGui import QImage,QColor
    from PySide6.QtPdf import QPdfDocument
    from core import Store
    from customers import upsert,search,export_xlsx,import_xlsx
    from photo_layout import write_pdf
    from office import POLICIES
    result={}
    with tempfile.TemporaryDirectory() as tmp:
        directory=Path(tmp);store=Store(directory/'a');record=upsert(store.db,{'name':'张三','phone':'013800000001','qq':'001234','building':'12栋'});assert search(store.db,'zs')[0]['id']==record['id'];assert search(store.db,'zhangsan')[0]['phone']=='013800000001';result['customer_search']='passed'
        workbook=directory/'customers.xlsx';export_xlsx(store.db,workbook);other=Store(directory/'b');assert import_xlsx(other.db,workbook)==1;assert search(other.db,'001234')[0]['qq']=='001234';result['excel_round_trip']='passed';store.db.close();other.db.close()
        image=QImage(100,80,QImage.Format.Format_RGB32);image.fill(QColor('#ef7b28'));pdf=directory/'layout.pdf';write_pdf(pdf,(210,297),(85.6,54),[image],2,10,8,False);doc=QPdfDocument(None);assert doc.load(str(pdf))==QPdfDocument.Error.None_;assert doc.pageCount()==1;assert abs(doc.pagePointSize(0).width()*25.4/72-210)<.2;doc.close();del doc;result['document_layout']='passed'
        from page_raster import preview_sheet,write_proof
        from coverage import pixel_metrics
        obj={'source':str(pdf),'prepared':str(pdf),'kind':'pdf','selected':[0],'options':{'paper':'A3','color':'黑白','duplex':'双面短边','copies':1,'pdf_fit':'自适应纸张','orientation':'auto'}}
        sheet=preview_sheet(obj,0);assert sheet.pixelColor(sheet.width()-2,sheet.height()-2).red()==255;assert pixel_metrics(sheet)['area_percent']<80;result['opaque_pdf_background']='passed'
        proof=directory/'proof.pdf';write_proof(obj,proof);check=QPdfDocument();assert check.load(str(proof))==QPdfDocument.Error.None_;assert abs(check.pagePointSize(0).width()*25.4/72-297)<.2;check.close();del check;result['a3_file_only_proof']='passed'
        assert (Path(__file__).parent/'assets'/'moxu.ico').is_file();result['icon_assets']='passed';result['office_policy']=POLICIES[0]
    result['physical_print_jobs_submitted']=0
    from copy import deepcopy
    from core import DEFAULT,quote
    from quality import resolve
    config=deepcopy(DEFAULT);config['prices']=[{'paper':'A4','color':'黑白','duplex':'单面','unit':'面','base_price':'0.20','discount_enabled':True,'mode':'volume','discounts':[[20,'0.15']]}]
    item={'selected':list(range(25)),'options':{'paper':'A4','color':'黑白','duplex':'单面','copies':1}}
    assert quote(config,[item])['total']=='3.75';result['list_price_discounts']='passed'
    config['printers']=[{'name':'HP M403','dpi':[600,1200]}]
    assert resolve(config,'HP M403',{'quality_level':'标准打印'})['dpi']==600;assert resolve(config,'HP M403',{'quality_level':'高质量打印'})['dpi']==1200;result['device_quality_binding']='passed'
    return result
