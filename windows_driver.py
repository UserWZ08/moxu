"""Job-local Windows DEVMODE capture and GDI output. Never calls SetPrinter/DM_UPDATE."""
import base64,ctypes as C,struct,os
from catalog import paper_size
from ctypes import wintypes as W

DM_OUT_BUFFER=2;DM_IN_PROMPT=4;DM_IN_BUFFER=8

def validated_blob(profile):
    try:raw=base64.b64decode(profile['devmode'],validate=True)
    except Exception as e:raise ValueError('质量预设数据损坏，请重新捕获') from e
    if not 220<=len(raw)<=1_000_000:raise ValueError('质量预设长度无效')
    size,extra=struct.unpack_from('<HH',raw,68)
    if size<220 or size+extra>len(raw):raise ValueError('质量预设结构无效')
    return raw

def job_blob(profile,options):
    raw=bytearray(validated_blob(profile))
    fields=struct.unpack_from('<I',raw,72)[0]
    # Leave print quality and every vendor-private byte unchanged.
    custom=options['paper'] not in ['A3','A4','A5','B5']
    fields=(fields&~(4|8|0x10000))|1|2|0x10|0x100|0x800|0x1000|0x8000
    if custom:fields|=4|8
    if custom:
        w,h=paper_size(options['paper'],options);struct.pack_into('<hh',raw,80,round(h*10),round(w*10))
    struct.pack_into('<I',raw,72,fields)
    for offset,value in [(76,2 if options.get('landscape') else 1),(78,{'A3':8,'A4':9,'A5':11,'B5':13}.get(options['paper'],256)),(84,100),(86,1),(92,2 if options['color']=='彩色' else 1),(94,{'单面':1,'双面长边':2,'双面短边':3}[options['duplex']]),(100,1)]:struct.pack_into('<h',raw,offset,value)
    return bytes(raw)

class DRIVER_INFO_2(C.Structure):
    _fields_=[('version',W.DWORD),('name',W.LPWSTR),('environment',W.LPWSTR),('path',W.LPWSTR),('data',W.LPWSTR),('config',W.LPWSTR)]

class DOCINFO(C.Structure):
    _fields_=[('size',C.c_int),('name',W.LPCWSTR),('output',W.LPCWSTR),('datatype',W.LPCWSTR),('flags',W.DWORD)]

class BITMAPINFOHEADER(C.Structure):
    _fields_=[('size',W.DWORD),('width',W.LONG),('height',W.LONG),('planes',W.WORD),('bits',W.WORD),('compression',W.DWORD),('image_size',W.DWORD),('xppm',W.LONG),('yppm',W.LONG),('used',W.DWORD),('important',W.DWORD)]

class API:
    def __init__(self):
        if os.name!='nt':raise RuntimeError('厂商质量预设仅支持 Windows')
        self.spool=C.WinDLL('winspool.drv',use_last_error=True);self.gdi=C.WinDLL('gdi32',use_last_error=True)
        definitions=[(self.spool,'OpenPrinterW',[W.LPWSTR,C.POINTER(W.HANDLE),C.c_void_p],W.BOOL),(self.spool,'ClosePrinter',[W.HANDLE],W.BOOL),(self.spool,'DocumentPropertiesW',[W.HWND,W.HANDLE,W.LPWSTR,C.c_void_p,C.c_void_p,W.DWORD],W.LONG),(self.spool,'GetPrinterDriverW',[W.HANDLE,W.LPWSTR,W.DWORD,C.c_void_p,W.DWORD,C.POINTER(W.DWORD)],W.BOOL),(self.gdi,'CreateDCW',[W.LPCWSTR,W.LPCWSTR,W.LPCWSTR,C.c_void_p],W.HDC),(self.gdi,'DeleteDC',[W.HDC],W.BOOL),(self.gdi,'StartDocW',[W.HDC,C.POINTER(DOCINFO)],C.c_int),(self.gdi,'StartPage',[W.HDC],C.c_int),(self.gdi,'EndPage',[W.HDC],C.c_int),(self.gdi,'EndDoc',[W.HDC],C.c_int),(self.gdi,'AbortDoc',[W.HDC],C.c_int),(self.gdi,'GetDeviceCaps',[W.HDC,C.c_int],C.c_int),(self.gdi,'SetStretchBltMode',[W.HDC,C.c_int],C.c_int),(self.gdi,'SetBrushOrgEx',[W.HDC,C.c_int,C.c_int,C.c_void_p],W.BOOL),(self.gdi,'IntersectClipRect',[W.HDC,C.c_int,C.c_int,C.c_int,C.c_int],C.c_int),(self.gdi,'StretchDIBits',[W.HDC]+[C.c_int]*8+[C.c_void_p,C.c_void_p,W.UINT,W.DWORD],C.c_int)]
        for dll,name,args,result in definitions:
            fn=getattr(dll,name);fn.argtypes=args;fn.restype=result
    def open(self,name):
        h=W.HANDLE()
        if not self.spool.OpenPrinterW(name,C.byref(h),None):raise C.WinError(C.get_last_error())
        return h
    def fingerprint(self,h):
        needed=W.DWORD();self.spool.GetPrinterDriverW(h,None,2,None,0,C.byref(needed))
        if not 0<needed.value<=1_000_000:raise RuntimeError('无法读取打印驱动信息')
        buf=C.create_string_buffer(needed.value)
        if not self.spool.GetPrinterDriverW(h,None,2,buf,needed.value,C.byref(needed)):raise C.WinError(C.get_last_error())
        info=C.cast(buf,C.POINTER(DRIVER_INFO_2)).contents
        result={'name':info.name,'environment':info.environment,'version':info.version,'config':info.config}
        try:
            stat=os.stat(info.config);result.update(file_size=stat.st_size,file_mtime=stat.st_mtime_ns)
        except OSError:pass
        return result

def capture(name,old=None):
    api=API();h=api.open(name)
    try:
        size=api.spool.DocumentPropertiesW(None,h,name,None,None,0)
        if not 220<=size<=1_000_000:raise RuntimeError('驱动没有提供有效的设置缓冲区')
        out=C.create_string_buffer(size)
        if api.spool.DocumentPropertiesW(None,h,name,out,None,DM_OUT_BUFFER)!=1:raise RuntimeError('无法读取当前驱动设置')
        if old:
            if old.get('printer')!=name:raise ValueError('质量预设属于另一台打印机')
            if old.get('driver')!=api.fingerprint(h):raise ValueError('驱动已变化，请新建质量预设')
            raw=validated_blob(old)
            if len(raw)==size:out=C.create_string_buffer(raw,size)
        # This dialog edits only the returned buffer. DM_UPDATE is deliberately absent.
        result=api.spool.DocumentPropertiesW(None,h,name,out,out,DM_OUT_BUFFER|DM_IN_BUFFER|DM_IN_PROMPT)
        if result==2:return None
        if result!=1:raise RuntimeError('厂商设置窗口无法完成操作，请先修复 Windows 中的打印首选项')
        raw=out.raw
        profile={'printer':name,'driver':api.fingerprint(h),'devmode':base64.b64encode(raw).decode('ascii')};validated_blob(profile);return profile
    finally:api.spool.ClosePrinter(h)

def normalized_job(api,h,name,profile,options):
    if profile.get('printer')!=name or profile.get('driver')!=api.fingerprint(h):raise RuntimeError('打印机或驱动与已保存质量预设不一致，请到后台重新捕获')
    raw=job_blob(profile,options)
    needed=api.spool.DocumentPropertiesW(None,h,name,None,None,0)
    if needed!=len(raw):raise RuntimeError('驱动设置缓冲区尺寸已变化，请重新捕获质量预设')
    source=C.create_string_buffer(raw,len(raw));dest=C.create_string_buffer(len(raw))
    if api.spool.DocumentPropertiesW(None,h,name,dest,source,DM_IN_BUFFER|DM_OUT_BUFFER)!=1:raise RuntimeError('驱动拒绝了质量预设与当前纸张/单双面组合')
    expected={76:2 if options.get('landscape') else 1,78:{'A3':8,'A4':9,'A5':11,'B5':13}.get(options['paper'],256),86:1,92:2 if options['color']=='彩色' else 1,94:{'单面':1,'双面长边':2,'双面短边':3}[options['duplex']]}
    if options['paper'] not in ['A3','A4','A5','B5']:expected.pop(78,None)
    for offset,value in expected.items():
        if struct.unpack_from('<h',dest.raw,offset)[0]!=value:raise RuntimeError('驱动更改了纸张、颜色、份数或单双面设置，已阻止提交')
    return dest

def inspect_margins(name,options,profile):
    """Create/query a device context only. Does not call StartDoc or print anything."""
    api=API();h=api.open(name);dc=None
    try:
        mode=normalized_job(api,h,name,profile,options);dc=api.gdi.CreateDCW('WINSPOOL',name,None,mode)
        if not dc:raise RuntimeError('无法读取设备页面布局')
        caps={key:api.gdi.GetDeviceCaps(dc,key) for key in [8,10,88,90,110,111,112,113]}
        if min(caps[k] for k in [8,10,88,90,110,111])<=0:raise RuntimeError('设备页面尺寸无效')
        return (caps[112]*25.4/caps[88],caps[113]*25.4/caps[90],(caps[110]-caps[8]-caps[112])*25.4/caps[88],(caps[111]-caps[10]-caps[113])*25.4/caps[90])
    finally:
        if dc:api.gdi.DeleteDC(dc)
        api.spool.ClosePrinter(h)

def print_item(item,profile,cancelled=lambda:False):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QImage
    from PySide6.QtPdf import QPdfDocument
    from printing import read_image
    from page_raster import Document
    document=Document(item);item=dict(item,options=document.options());api=API();name=item['printer'];h=api.open(name);dc=None;started=False;doc=None
    try:
        devmode=normalized_job(api,h,name,profile,item['options'])
        dc=api.gdi.CreateDCW('WINSPOOL',name,None,devmode)
        if not dc:raise C.WinError(C.get_last_error())
        width,height=api.gdi.GetDeviceCaps(dc,8),api.gdi.GetDeviceCaps(dc,10)
        xdpi,ydpi=api.gdi.GetDeviceCaps(dc,88),api.gdi.GetDeviceCaps(dc,90)
        if min(width,height,xdpi,ydpi)<=0:raise RuntimeError('驱动返回了无效的页面尺寸')
        actual=[api.gdi.GetDeviceCaps(dc,110)*25.4/xdpi,api.gdi.GetDeviceCaps(dc,111)*25.4/ydpi]
        desired=list(paper_size(item['options']['paper'],item['options']))
        if item['options'].get('landscape'):desired.reverse()
        if any(abs(a-b)>4 for a,b in zip(actual,desired)):raise RuntimeError('驱动返回的物理纸张尺寸与订单不一致')
        physical_width=api.gdi.GetDeviceCaps(dc,110);physical_height=api.gdi.GetDeviceCaps(dc,111)
        offset_x=api.gdi.GetDeviceCaps(dc,112);offset_y=api.gdi.GetDeviceCaps(dc,113)
        margins=(offset_x*25.4/xdpi,offset_y*25.4/ydpi,(physical_width-width-offset_x)*25.4/xdpi,(physical_height-height-offset_y)*25.4/ydpi)
        first_image=document.sheet(item['selected'][0],max(xdpi,ydpi),margins)
        info=DOCINFO(C.sizeof(DOCINFO),'墨序',None,None,0)
        if cancelled():raise RuntimeError('已停止后续提交')
        if api.gdi.StartDocW(dc,C.byref(info))<=0:raise RuntimeError('无法创建系统打印任务')
        started=True
        for n,page in enumerate(item['selected']):
            if cancelled():raise RuntimeError('已停止；已进入打印队列的页面仍可能输出')
            image=first_image if n==0 else document.sheet(page,max(xdpi,ydpi),margins)
            x,y,w,hh=-offset_x,-offset_y,physical_width,physical_height
            pixels=bytes(image.constBits());buf=C.create_string_buffer(pixels,len(pixels));bitmap=BITMAPINFOHEADER(C.sizeof(BITMAPINFOHEADER),image.width(),-image.height(),1,32,0,len(pixels),0,0,0,0)
            if api.gdi.StartPage(dc)<=0:raise RuntimeError('无法开始打印页面')
            api.gdi.IntersectClipRect(dc,0,0,width,height);api.gdi.SetStretchBltMode(dc,4);api.gdi.SetBrushOrgEx(dc,0,0,None)
            result=api.gdi.StretchDIBits(dc,round(x),round(y),round(w),round(hh),0,0,image.width(),image.height(),buf,C.byref(bitmap),0,0x00CC0020)
            if result in [0,-1] or api.gdi.EndPage(dc)<=0:raise RuntimeError('驱动拒绝页面图像')
        if api.gdi.EndDoc(dc)<=0:raise RuntimeError('驱动未确认打印任务提交')
        started=False
    finally:
        if started and dc:api.gdi.AbortDoc(dc)
        document.close()
        if dc:api.gdi.DeleteDC(dc)
        api.spool.ClosePrinter(h)
