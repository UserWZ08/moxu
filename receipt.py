import html,base64
from pathlib import Path
from copy import deepcopy

def snapshot_template(config):
    from PySide6.QtGui import QImageReader
    from PySide6.QtCore import QBuffer,QIODevice,Qt
    template=deepcopy(config.get('order_template',{}));template['images']=[]
    source=config.get('order_template',{});images=source.get('images',[])
    if source.get('image_path'):images=images+[{'path':source['image_path'],'width_mm':source.get('image_width_mm',35),'position':source.get('image_position','顶部')}]
    for item in images[:4]:
        reader=QImageReader(item['path']);reader.setAutoTransform(True);image=reader.read()
        if image.isNull():raise ValueError('订单自定义图片无法读取，请到后台重新选择')
        image=image.scaled(1200,1200,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        buf=QBuffer();buf.open(QIODevice.OpenModeFlag.WriteOnly);image.save(buf,'PNG')
        template['images'].append({'data':base64.b64encode(bytes(buf.data())).decode(),'width_mm':item.get('width_mm',35),'position':item.get('position','顶部')})
    template.pop('image_path',None);return template

def order_html(oid,payload,status):
    e=lambda v:html.escape(str(v));template=payload.get('order_template',{});title=template.get('title','墨序 · 订单')
    def images(position):return ''.join('<img alt="订单自定义图片" style="display:inline-block;max-width:100%;margin:4mm 4mm 4mm 0;width:'+str(max(10,min(180,float(i.get('width_mm',35)))))+'mm" src="data:image/png;base64,'+e(i['data'])+'">' for i in template.get('images',[]) if i.get('position','顶部')==position)
    rows=''.join('<tr>'+''.join('<td>'+e(v)+'</td>' for v in [' / '.join(Path(s).name for s in i.get('source_files',[i['source']])),len(i['selected']),i['options']['copies'],i['options']['paper'],i['options']['color'],i['options']['duplex'],i.get('printer',''),i.get('submitted_copies',0)])+'</tr>' for i in payload['items'])
    groups=''.join('<tr>'+''.join('<td>'+e(v)+'</td>' for v in [g['rule']['paper']+' '+g['rule']['color']+' '+g['rule']['duplex'],str(g['quantity'])+g['rule']['unit'],'满量优惠' if g.get('mode')=='volume' else '分段优惠','¥'+g['amount']])+'</tr>' for g in payload['quote'].get('groups',[]))
    binding=payload['quote'].get('binding',{});binding_text=f"{binding.get('name','不装订')} × {binding.get('quantity',1)}，费用 ¥{payload['quote'].get('binding_total','0.00')}"
    contact=''
    if template.get('show_contact',True):
        details=[label+str(payload.get(key,'')) for key,label in [('phone','手机：'),('qq','QQ：'),('wechat','微信：'),('contact','其他：')] if payload.get(key)]
        contact='<p>'+e('　'.join(details))+'</p>'
    return f'''<!doctype html><meta charset="utf-8"><title>{e(title)} {e(oid)}</title><style>body{{font:14px 'Microsoft YaHei',sans-serif;margin:35px;color:#263345}}h1{{color:#e77826}}table{{border-collapse:collapse;width:100%;margin:4mm 0}}th,td{{padding:8px;border-bottom:1px solid #dce2e8;text-align:left;word-break:break-word}}.custom{{white-space:pre-wrap}}.total{{font-size:28px;color:#d66d1f}}@media print{{body{{margin:10mm}}tr,img{{break-inside:avoid}}}}</style>{images('顶部')}<h1>{e(title)}</h1><div class="custom">{e(template.get('header_text',''))}</div><p>订单号：{e(oid)}　状态：{e(status)}</p><h2>{e(payload.get('community',''))} · {e(payload.get('building',''))} · {e(payload.get('room',''))}</h2><p>客户：{e(payload.get('customer',''))}</p>{contact}<p>备注：{e(payload.get('note',''))}</p><table><tr><th>文件</th><th>页数</th><th>份数</th><th>纸张</th><th>颜色</th><th>单双面</th><th>打印机</th><th>已提交份数</th></tr>{rows}</table><table><tr><th>计价类别</th><th>数量</th><th>模式</th><th>金额</th></tr>{groups}</table><p>装订：{e(binding_text)}</p><p class="total">{'合计 ¥ '+e(payload['quote']['total']) if payload['quote']['enabled'] else '本单不计价'}</p>{images('底部')}<div class="custom">{e(template.get('footer_text',''))}</div><p>已提交表示交给系统打印队列，不代表纸张已经输出。</p>'''
