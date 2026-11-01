"""Offline millimetre-accurate layouts. No external project code or AI models."""
import math
from PySide6.QtCore import Qt,QRectF,QSizeF,QMarginsF
from PySide6.QtGui import QImage,QPainter,QPdfWriter,QPageSize,QPageLayout,QPen,QColor

def center_crop(width,height,aspect):
    if width/height>aspect:
        w=height*aspect/width;return ((1-w)/2,0,w,1)
    h=width/aspect/height;return (0,(1-h)/2,1,h)

def cropped(image,rect):
    x,y,w,h=rect;x=max(0,min(.999,x));y=max(0,min(.999,y));w=max(.001,min(1-x,w));h=max(.001,min(1-y,h))
    return image.copy(round(x*image.width()),round(y*image.height()),max(1,round(w*image.width())),max(1,round(h*image.height())))

def layout_rects(paper,item,quantity,margin=5,gap=2):
    pw,ph=paper;iw,ih=item
    if min(pw,ph,iw,ih)<=0 or margin<0 or gap<0:raise ValueError('尺寸或间距无效')
    cols=math.floor((pw-2*margin+gap)/(iw+gap));rows=math.floor((ph-2*margin+gap)/(ih+gap))
    if cols<1 or rows<1:raise ValueError('所选纸张放不下该尺寸，请减小边距或更换纸张')
    capacity=cols*rows;quantity=capacity if quantity==0 else quantity
    if not 1<=quantity<=1000:raise ValueError('排版数量应为1–1000，或选择自动排满')
    x0=(pw-(cols*iw+(cols-1)*gap))/2;y0=(ph-(rows*ih+(rows-1)*gap))/2
    return [[(x0+(j%cols)*(iw+gap),y0+(j//cols)*(ih+gap),iw,ih) for j in range(min(capacity,quantity-start))] for start in range(0,quantity,capacity)]

def write_pdf(path,paper,item,images,quantity=0,margin=5,gap=2,cut_marks=True,repeat=True):
    """images are prepared QImages; repeat fills with the first, otherwise each appears once."""
    if not images:raise ValueError('请先选择图片')
    pages=layout_rects(paper,item,quantity if repeat else len(images),margin,gap)
    writer=QPdfWriter(str(path));writer.setResolution(300);writer.setPageLayout(QPageLayout(QPageSize(QSizeF(*paper),QPageSize.Unit.Millimeter,'排版纸张',QPageSize.SizeMatchPolicy.ExactMatch),QPageLayout.Orientation.Portrait,QMarginsF(0,0,0,0)));writer.setTitle('墨序 · 原尺寸照片排版')
    painter=QPainter(writer)
    if not painter.isActive():raise ValueError('无法创建 PDF 文件')
    scale=300/25.4;number=0
    try:
        for page_number,rects in enumerate(pages):
            if page_number and not writer.newPage():raise RuntimeError('无法创建新 PDF 页面')
            for x,y,w,h in rects:
                image=images[0] if repeat else images[number];number+=1
                painter.drawImage(QRectF(x*scale,y*scale,w*scale,h*scale),image)
                if cut_marks:
                    painter.setPen(QPen(QColor('#606060'),.1*scale))
                    for cx,cy in [(x,y),(x+w,y),(x,y+h),(x+w,y+h)]:
                        painter.drawLine(QRectF((cx-.8)*scale,cy*scale,1.6*scale,0).topLeft(),QRectF((cx-.8)*scale,cy*scale,1.6*scale,0).topRight())
                        painter.drawLine(QRectF(cx*scale,(cy-.8)*scale,0,1.6*scale).topLeft(),QRectF(cx*scale,(cy-.8)*scale,0,1.6*scale).bottomLeft())
    finally:painter.end()
    return len(pages)
