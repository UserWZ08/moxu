import unittest,tempfile,ctypes as C
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
from PySide6.QtCore import Qt,QSize,QRectF,QMarginsF
from PySide6.QtGui import QImage,QPainter,QPdfWriter,QPageSize
from PySide6.QtWidgets import QApplication
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPrintSupport import QPrinter
from page_raster import Document,opaque,resolved_options,preview_sheet,write_proof
from coverage import pixel_metrics,estimate
from printing import render,prepare
from test_rendering import sample_profile
import windows_driver as native
APP=QApplication.instance() or QApplication([])

def fixture(path,landscape=False):
    writer=QPdfWriter(str(path));writer.setResolution(72);writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    if landscape:
        from PySide6.QtGui import QPageLayout
        writer.setPageOrientation(QPageLayout.Orientation.Landscape)
    painter=QPainter(writer);painter.fillRect(QRectF(60,60,80,80),Qt.GlobalColor.black);painter.end()

def item(path,paper='A3',fit='自适应纸张'):
    return {'source':str(path),'prepared':str(path),'kind':'pdf','count':1,'selected':[0],'options':{'paper':paper,'color':'黑白','duplex':'双面短边','copies':1,'dpi':150,'pdf_fit':fit,'orientation':'auto'}}

class PrintSafetyTests(unittest.TestCase):
    def test_transparent_pdf_regression_and_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.pdf';fixture(path);document=Document(item(path))
            raw=document.doc.render(0,QSize(595,842))
            self.assertEqual(raw.pixelColor(590,830).alpha(),0)
            self.assertEqual(raw.convertToFormat(QImage.Format.Format_Grayscale8).pixelColor(590,830).red(),0)
            sheet=document.sheet(0,150);document.close()
            self.assertEqual(sheet.pixelColor(sheet.width()-5,sheet.height()-5).getRgb(),(255,255,255,255))
            self.assertAlmostEqual(pixel_metrics(sheet)['area_percent'],80*80/(595*842)*100,delta=.2)
            metrics=estimate(item(path));self.assertLess(metrics['area_percent'],2);self.assertEqual(metrics['sampled_pages'],1)
    def test_transparent_png_is_white_in_both_color_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            image=QImage(200,300,QImage.Format.Format_ARGB32);image.fill(Qt.GlobalColor.transparent);path=Path(tmp)/'transparent.png';image.save(str(path))
            for color in ['黑白','彩色']:
                obj=item(path);obj.update(kind='image');obj['options']['color']=color
                sheet=preview_sheet(obj,0);self.assertEqual(pixel_metrics(sheet)['area_percent'],0)
    def test_actual_a4_on_a3_and_fit_physical_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.pdf';fixture(path)
            # Full black A4 has half the area of A3 at actual size.
            writer=QPdfWriter(str(path));writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4));writer.setPageMargins(QMarginsF(0,0,0,0));p=QPainter(writer);p.fillRect(writer.pageLayout().fullRectPixels(writer.resolution()),Qt.GlobalColor.black);p.end();del writer
            for mode,expected in [('实际大小',50),('自适应纸张',100)]:
                sheet=preview_sheet(item(path,fit=mode),0,150);self.assertAlmostEqual(sheet.width()/sheet.height(),297/420,delta=.001)
                self.assertAlmostEqual(pixel_metrics(sheet)['area_percent'],expected,delta=.6)
    def test_auto_orientation_independent_of_duplex(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'wide.pdf';fixture(path,True);obj=item(path);self.assertTrue(resolved_options(obj)['landscape'])
            images=[]
            for mode in ['单面','双面长边','双面短边']:
                obj['options']['duplex']=mode;sheet=preview_sheet(obj,0);self.assertGreater(sheet.width(),sheet.height());images.append(bytes(sheet.constBits()))
            self.assertEqual(images[0],images[1]);self.assertEqual(images[1],images[2])
    def test_qt_output_a3_pdf_and_white_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source.pdf';output=Path(tmp)/'printed.pdf';fixture(source);printer=QPrinter();printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat);printer.setOutputFileName(str(output));printer.setResolution(150);printer.setPageSize(QPageSize(QPageSize.PageSizeId.A3));render(item(source),printer);del printer
            doc=QPdfDocument();self.assertEqual(doc.load(str(output)),QPdfDocument.Error.None_);size=doc.pagePointSize(0);self.assertAlmostEqual(size.width()*25.4/72,297,delta=.2);self.assertAlmostEqual(size.height()*25.4/72,420,delta=.2)
            self.assertLess(pixel_metrics(doc.render(0,QSize(595,842)))['area_percent'],3);doc.close();del doc
    def test_native_a3_short_edge_raster_is_white_and_full_paper(self):
        captured=[];profile=sample_profile()
        class Spool:
            def DocumentPropertiesW(self,hwnd,h,name,dest,source,flags):
                if flags==0:return 228
                C.memmove(dest,source,228);return 1
            def ClosePrinter(self,h):pass
        class Gdi:
            def CreateDCW(self,*args):return 9
            def GetDeviceCaps(self,dc,key):return {8:1724,10:2450,88:150,90:150,110:1754,111:2480,112:15,113:15}[key]
            def StretchDIBits(self,dc,x,y,w,h,sx,sy,sw,sh,pixels,header,*rest):
                raw=C.string_at(pixels,sw*sh*4);captured.append((x,y,w,h,raw[-4:]));return sh
            def __getattr__(self,name):return lambda *args:1
        class Fake:
            spool=Spool();gdi=Gdi()
            def open(self,name):return 1
            def fingerprint(self,h):return profile['driver']
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.pdf';fixture(path);obj=item(path);obj['printer']='TEST'
            with patch('windows_driver.API',return_value=Fake()):native.print_item(obj,profile)
        self.assertEqual(captured,[(-15,-15,1754,2480,b'\xff\xff\xff\xff')])
    def test_cache_reuses_unchanged_content_and_invalidates_changed_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'test.docx';source.write_bytes(b'one');calls=[]
            def convert(source,folder,output,*args,**kwargs):calls.append(1);fixture(output);return 'Microsoft Word'
            with patch('office.convert',side_effect=convert):
                a=prepare(source,Path(tmp)/'cache');source.touch();b=prepare(source,Path(tmp)/'cache');self.assertEqual(a,b);self.assertEqual(len(calls),1)
                source.write_bytes(b'two');self.assertNotEqual(a[0],prepare(source,Path(tmp)/'cache')[0]);self.assertEqual(len(calls),2)
    def test_file_only_proof_has_a3_dimensions_and_white_background(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source.pdf';fixture(source);output=Path(tmp)/'proof.pdf';write_proof(item(source),output);doc=QPdfDocument();self.assertEqual(doc.load(str(output)),QPdfDocument.Error.None_);size=doc.pagePointSize(0);self.assertAlmostEqual(size.width()*25.4/72,297,delta=.2);self.assertAlmostEqual(size.height()*25.4/72,420,delta=.2);self.assertLess(pixel_metrics(doc.render(0,QSize(595,842)))['area_percent'],3);doc.close();del doc
    def test_conversion_batch_reuses_single_helper_and_preserves_missing_engine_code(self):
        import io
        from office import ConversionSession
        class Fake:
            stdin=io.StringIO();stdout=io.StringIO('{"code":0,"error":""}\n{"code":15,"error":"missing"}\n')
            def wait(self,timeout):return 0
        with patch('office.subprocess.Popen',return_value=Fake()) as launch:
            with ConversionSession() as session:
                self.assertEqual(session.native(Path('a.docx'),Path('a.pdf'),'word')['code'],0)
                self.assertEqual(session.native(Path('b.docx'),Path('b.pdf'),'word')['code'],15)
                self.assertEqual(launch.call_count,1)

if __name__=='__main__':unittest.main()
