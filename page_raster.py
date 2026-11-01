"""One opaque, physical paper layout for previews, measurement and both print backends."""
from copy import deepcopy
from math import sqrt
from PySide6.QtCore import QSize, QRectF, Qt
from PySide6.QtGui import QImage, QImageReader, QPainter, QTransform
from PySide6.QtPdf import QPdfDocument
from catalog import paper_size
from page_layout import placement


def opaque(image):
    if image.isNull():raise ValueError('页面图像为空')
    result=QImage(image.size(),QImage.Format.Format_RGB32);result.fill(Qt.GlobalColor.white)
    p=QPainter(result);p.drawImage(0,0,image);p.end()
    return result


class Document:
    def __init__(self,item):
        self.item=item;self.doc=None
        if item['kind']=='pdf':
            self.doc=QPdfDocument(None)
            if self.doc.load(item['prepared'])!=QPdfDocument.Error.None_:raise ValueError('PDF 无法打开')
    def close(self):
        if self.doc:self.doc.close();self.doc=None
    def image(self,page):
        path=self.item['prepared'][page] if self.item['kind']=='images' else self.item['prepared']
        reader=QImageReader(path);reader.setAutoTransform(True);image=reader.read()
        if image.isNull():raise ValueError('图片无法读取')
        return image
    def dimensions(self,page):
        if self.doc:
            s=self.doc.pagePointSize(page);return s.width(),s.height()
        image=self.image(page);return image.width(),image.height()
    def options(self):
        o=deepcopy(self.item['options'])
        if o.get('orientation','auto')=='auto':
            w,h=self.dimensions(self.item['selected'][0]);o['landscape']=w>h
        return o
    def sheet(self,page,dpi=110,margins=(0,0,0,0),maximum_pixels=24_000_000):
        o=self.options();mw,mh=paper_size(o['paper'],o)
        if o.get('landscape'):mw,mh=mh,mw
        dpi=min(dpi,sqrt(maximum_pixels/(mw*mh))*25.4)
        width,height=max(1,round(mw*dpi/25.4)),max(1,round(mh*dpi/25.4))
        sx,sy=width/mw,height/mh
        left,top,right,bottom=margins
        area=QRectF(left*sx,top*sy,width-(left+right)*sx,height-(top+bottom)*sy)
        if min(area.width(),area.height())<=0:raise ValueError('打印边距超过纸张尺寸')
        points=None
        if self.doc:
            points=self.dimensions(page)
            factor=min(dpi/72,sqrt(maximum_pixels/(points[0]*points[1])))
            image=self.doc.render(page,QSize(max(1,round(points[0]*factor)),max(1,round(points[1]*factor))))
        else:image=self.image(page)
        image=opaque(image)
        # Mixed orientation pages rotate as a whole; duplex binding never rotates content.
        if o.get('orientation','auto')=='auto' and ((image.width()>image.height()) != (area.width()>area.height())):
            image=image.transformed(QTransform().rotate(90))
            if points:points=points[::-1]
        target=QRectF(*placement(image.width(),image.height(),area.width(),area.height(),self.item['kind'],o,points,dpi));target.translate(area.topLeft())
        canvas=QImage(width,height,QImage.Format.Format_RGB32);canvas.fill(Qt.GlobalColor.white)
        p=QPainter(canvas);p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform);p.setClipRect(area);p.drawImage(target,image);p.end()
        if o['color']=='黑白':canvas=canvas.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(QImage.Format.Format_RGB32)
        return canvas


def resolved_options(item):
    document=Document(item)
    try:return document.options()
    finally:document.close()


def preview_sheet(item,page,dpi=90):
    document=Document(item)
    try:return document.sheet(page,dpi,item.get('preview_margins',(0,0,0,0)))
    finally:document.close()


def write_proof(item,path):
    """File-only output with the same physical layout; never creates a printer job."""
    from PySide6.QtGui import QPdfWriter,QPageSize,QPageLayout
    from PySide6.QtCore import QSizeF,QMarginsF
    document=Document(item);painter=QPainter();writer=None
    try:
        o=document.options();mw,mh=paper_size(o['paper'],o)
        writer=QPdfWriter(str(path));writer.setResolution(150);writer.setPageSize(QPageSize(QSizeF(mw,mh),QPageSize.Unit.Millimeter))
        writer.setPageOrientation(QPageLayout.Orientation.Landscape if o.get('landscape') else QPageLayout.Orientation.Portrait);writer.setPageMargins(QMarginsF(0,0,0,0))
        if not painter.begin(writer):raise RuntimeError('无法写入预览PDF')
        for n,page in enumerate(item['selected']):
            if n and not writer.newPage():raise RuntimeError('无法写入预览页')
            image=document.sheet(page,150,item.get('preview_margins',(0,0,0,0)));painter.drawImage(QRectF(writer.pageLayout().fullRectPixels(150)),image)
    finally:
        if painter.isActive():painter.end()
        document.close()
