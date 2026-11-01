"""Domain model, routing, graduated prices and durable order ledger."""
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import json, os, sqlite3, uuid,sys
from copy import deepcopy
from datetime import datetime
from catalog import ensure_catalog,validate_catalog,binding_charge
from pricing import enrich,effective,validate_discounts

FORMATS = {'.pdf', '.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'}
DEFAULT = {
    'schema_version':3,'native_quality_enabled':False,'coverage_enabled':True,
    'theme': '跟随系统', 'billing': True,
    'communities': {'示例小区': ['1栋', '2栋', '3栋']},
    'printers': [],
    'presets': [],
    'prices': [
        {'paper': 'A4', 'color': '黑白', 'duplex': '*', 'unit': '面', 'tiers': [[20, '0.20'], [100, '0.15'], [None, '0.10']]},
        {'paper': 'A4', 'color': '彩色', 'duplex': '*', 'unit': '面', 'tiers': [[None, '1.00']]},
        {'paper': 'A3', 'color': '黑白', 'duplex': '*', 'unit': '面', 'tiers': [[None, '0.40']]},
        {'paper': 'A3', 'color': '彩色', 'duplex': '*', 'unit': '面', 'tiers': [[None, '2.00']]}
    ]
}
DEFAULT['prices']=[dict(r,duplex=side,mode='progressive') for r in DEFAULT['prices'] for side in ['单面','双面']]
ensure_catalog(DEFAULT)

def billing_side(duplex):return '单面' if duplex=='单面' else '双面'

def active_quality(config,printer):
    if not config.get('native_quality_enabled'):return None
    p=next((p for p in config['printers'] if p['name']==printer),{})
    profiles=p.get('quality_profiles',[])
    return next((v for v in profiles if v['name']==p.get('active_quality')),profiles[0] if profiles else None)

def migrate_config(config):
    c=deepcopy(config)
    if c.get('schema_version',0)>=3:return c
    notes=list(c.get('migration_notes',[]));converted=[]
    for paper,color in dict.fromkeys((r['paper'],r['color']) for r in c.get('prices',[])):
        rules=[r for r in c['prices'] if (r['paper'],r['color'])==(paper,color)]
        def find(side):
            exact=next((r for r in rules if r['duplex']==side),None)
            return exact or next((r for r in rules if r['duplex']=='*'),None)
        simple=find('单面');long=find('双面长边');short=find('双面短边');double=next((r for r in rules if r['duplex']=='双面'),None) or long or short
        if long and short and (long['tiers']!=short['tiers'] or long['unit']!=short['unit']):notes.append(f'{paper} {color}：旧长边/短边价格不同，双面暂按长边迁移，请核对。')
        for side,r in [('单面',simple),('双面',double)]:
            if r:
                r=deepcopy(r);r['duplex']=side;r.setdefault('mode','progressive')
                for tier in r['tiers']:
                    d=Decimal(str(tier[1]));rounded=d.quantize(Decimal('.01'),rounding=ROUND_HALF_UP) if d.is_finite() else d
                    if d.is_finite() and d!=rounded:notes.append(f'{paper} {color} {side}：单价已取两位小数，请核对。')
                    tier[1]=str(rounded)
                converted.append(r)
    c.update(schema_version=3,prices=converted)
    c.setdefault('native_quality_enabled',False);c.setdefault('coverage_enabled',True)
    if notes:c.update(migration_notes=list(dict.fromkeys(notes)),billing_review_required=True)
    return c

def data_dir():
    if getattr(sys,'frozen',False) and (Path(sys.executable).parent/'portable.flag').exists():
        p=Path(sys.executable).parent/'data';p.mkdir(parents=True,exist_ok=True);return p
    p = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'NeighbourPrint'
    p.mkdir(parents=True, exist_ok=True)
    return p

def validate(c):
    papers=validate_catalog(c)
    for key in ['native_quality_enabled','coverage_enabled']:
        if key in c and type(c[key]) is not bool:raise ValueError('功能开关必须为布尔值')
    if c.get('theme') not in ['跟随系统', '浅色', '深色']: raise ValueError('主题只能是跟随系统、浅色、深色')
    if not isinstance(c.get('billing'), bool): raise ValueError('billing 必须为 true 或 false')
    if not isinstance(c.get('communities'), dict) or not c['communities']: raise ValueError('至少配置一个小区')
    for name, buildings in c['communities'].items():
        if not name.strip() or not isinstance(buildings, list) or not buildings or any(not isinstance(b, str) or not b.strip() for b in buildings): raise ValueError('小区名和楼栋不能为空')
    names = set()
    for p in c.get('printers', []):
        if not p.get('name') or p['name'] in names: raise ValueError('打印机名称不能为空或重复')
        names.add(p['name'])
        for level,binding in p.get('quality_bindings',{}).items():
            if level not in ['标准打印','高质量打印'] or binding.get('mode') not in ['dpi','native','unconfigured']:raise ValueError('打印机质量绑定无效')
            if binding['mode']=='dpi' and (type(binding.get('dpi')) is not int or not 72<=binding['dpi']<=2400):raise ValueError('质量绑定DPI无效')
            if binding['mode']=='native' and not binding.get('profile'):raise ValueError('请选择厂商质量预设')
        for r in p['rules']:
            if r['paper'] not in papers or r['color'] not in ['黑白','彩色'] or r['duplex'] not in ['单面','双面长边','双面短边']: raise ValueError('打印机规则无效')
        if not p.get('dpi') or any(type(d) is not int or d < 72 or d > 2400 for d in p['dpi']): raise ValueError('dpi 应为 72–2400 的整数列表')
        quality_names=set()
        for q in p.get('quality_profiles',[]):
            from windows_driver import validated_blob
            if not q.get('name') or q['name'] in quality_names or q.get('printer')!=p['name']:raise ValueError('厂商质量名称无效、重复或属于另一台打印机')
            quality_names.add(q['name']);validated_blob(q)
    preset_names=set()
    if not isinstance(c.get('presets',[]),list):raise ValueError('预设配置必须为列表')
    for p in c.get('presets',[]):
        name=p.get('name','').strip()
        if not name or name in preset_names:raise ValueError('预设名称不能为空或重复')
        preset_names.add(name);o=p['options']
        if o['paper'] not in papers or o['color'] not in ['黑白','彩色'] or o['duplex'] not in ['单面','双面长边','双面短边']:raise ValueError('预设打印组合无效')
        if type(o['dpi']) is not int or not 72<=o['dpi']<=2400 or type(o['copies']) is not int or not 1<=o['copies']<=999:raise ValueError('预设 DPI 或份数无效')
        if o.get('fit') not in ['完整留白','填充裁切'] or type(o.get('landscape')) is not bool or not isinstance(o.get('printer'),str) or not o['printer']:raise ValueError('预设缩放、方向或打印机设置无效')
        if o.get('pdf_fit','自适应纸张') not in ['自适应纸张','仅缩小超大页面','实际大小']:raise ValueError('文档缩放预设无效')
        if o.get('quality_level','标准打印') not in ['标准打印','高质量打印']:raise ValueError('打印预设质量档位无效')
    keys = set()
    for raw in c.get('prices', []):
        validate_discounts(raw);r=effective(raw) if 'base_price' in raw else raw
        key = (r['paper'], r['color'], r['duplex'])
        if key in keys: raise ValueError('重复计价规则')
        keys.add(key)
        if r['paper'] not in papers or r['color'] not in ['黑白','彩色'] or r['duplex'] not in ['单面','双面']: raise ValueError('计价条件应按纸张、颜色、单面/双面分别设置')
        mode=r.get('mode','progressive')
        if mode not in ['progressive','volume']:raise ValueError('阶梯模式无效')
        if r['unit'] not in ['面','张'] or not r['tiers']: raise ValueError('计价单位为面/张，至少配置一个单价')
        if mode=='progressive' and r['tiers'][-1][0] is not None:raise ValueError('分段累进的最后阶梯上限必须为不限')
        if mode=='volume' and r['tiers'][0][0]!=1:raise ValueError('满量降价第一档应从 1 开始')
        prev = 0
        for i, (limit, price) in enumerate(r['tiers']):
            d = Decimal(str(price))
            if not d.is_finite() or d < 0 or d!=d.quantize(Decimal('.01')): raise ValueError('单价必须为非负数，最多两位小数')
            if limit is None:
                if mode!='progressive' or i != len(r['tiers'])-1: raise ValueError('无限阶梯只能在分段累进的最后')
            elif type(limit) is not int or limit <= prev: raise ValueError('阶梯上限应递增')
            else: prev = limit
    return c

class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root else data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'settings.json'
        original = json.loads(self.path.read_text('utf-8')) if self.path.exists() else deepcopy(DEFAULT)
        self.config = ensure_catalog(migrate_config(original))
        self.config['prices']=[enrich(r) for r in self.config['prices']]
        if self.path.exists() and original!=self.config:
            backup=self.root/('settings-before-v5.json' if original.get('schema_version',0)>=3 else 'settings-before-v3.json')
            if not backup.exists():backup.write_text(json.dumps(original,ensure_ascii=False,indent=2),'utf-8')
        self.config.setdefault('presets',[])
        validate(self.config)
        self.db = sqlite3.connect(self.root / 'orders.sqlite')
        self.db.execute('CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, created TEXT, status TEXT, payload TEXT)')
        # A terminated process cannot prove whether its last spool submission succeeded.
        self.db.execute("UPDATE orders SET status='中断，需核对打印队列' WHERE status='正在提交'")
        self.db.commit()
        from customers import init_table
        init_table(self.db)
    def save(self, config):
        validate(config)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), 'utf-8')
        tmp.replace(self.path)
        self.config = config
    def order(self, payload):
        oid = datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
        self.db.execute('INSERT INTO orders VALUES (?,?,?,?)', (oid, datetime.now().isoformat(timespec='seconds'), '已创建', json.dumps(payload, ensure_ascii=False)))
        self.db.commit()
        return oid
    def status(self, oid, status, payload=None):
        if payload is None: self.db.execute('UPDATE orders SET status=? WHERE id=?', (status,oid))
        else: self.db.execute('UPDATE orders SET status=?,payload=? WHERE id=?', (status,json.dumps(payload,ensure_ascii=False),oid))
        self.db.commit()
    def history(self):
        return self.db.execute('SELECT id,created,status,payload FROM orders ORDER BY created DESC LIMIT 500').fetchall()

def pages(spec, count):
    if not spec.strip(): return list(range(count))
    result = set()
    for part in spec.replace('，', ',').split(','):
        parts = part.strip().split('-')
        if len(parts) > 2: raise ValueError('页码示例：1-3,5')
        a = int(parts[0]); b = int(parts[-1])
        if not 1 <= a <= b <= count: raise ValueError(f'页码范围应在 1–{count} 内')
        result.update(range(a-1,b))
    return sorted(result)

def route(config, options, installed):
    candidates=[];failures=[];manual=options.get('printer','自动分配')
    for p in config['printers']:
        if p['name'] not in installed or not p.get('enabled',True) or (manual!='自动分配' and p['name']!=manual):continue
        if not any(all(r[k]==options[k] for k in ['paper','color','duplex']) for r in p['rules']):continue
        if options.get('quality_level'):
            from quality import resolve
            try:resolve(config,p['name'],options)
            except ValueError as error:failures.append(str(error));continue
        else:
            native=config.get('native_quality_enabled') and p.get('quality_profiles')
            if not native and options['dpi'] not in p['dpi']:continue
        candidates.append(p)
    if not candidates:
        if failures:raise ValueError('打印质量尚未就绪：'+'；'.join(failures[:3]))
        raise ValueError('没有匹配的可用打印机。请检查后台纸张、颜色、单双面能力及设备状态。')
    return sorted(candidates,key=lambda p:p.get('priority',100))[0]['name']


def quote(config, items):
    if not config['billing']: return {'total':'0.00','groups':[], 'enabled':False}
    if config.get('billing_review_required'):raise ValueError('升级后的旧价格存在差异，请到后台核对并确认迁移价格')
    groups = {}
    for item in items:
        o = item['options']
        matches = [r for r in config['prices'] if r['paper']==o['paper'] and r['color']==o['color'] and r['duplex']==billing_side(o['duplex'])]
        if not matches: raise ValueError(f"未配置 {o['paper']} / {o['color']} / {o['duplex']} 的价格")
        rule = effective(matches[0])
        n = len(item['selected'])
        qty = (n if rule['unit']=='面' or o['duplex']=='单面' else (n+1)//2) * o['copies']
        key = json.dumps(rule,sort_keys=True)
        if key not in groups: groups[key] = {'rule':rule, 'quantity':0}
        groups[key]['quantity'] += qty
    total = Decimal(0)
    for g in groups.values():
        n = g['quantity']; prev = 0; subtotal = Decimal(0)
        mode=g['rule'].get('mode','progressive')
        if mode=='volume':
            price=next(price for minimum,price in reversed(g['rule']['tiers']) if n>=minimum) if n else '0.00'
            subtotal=n*Decimal(str(price));g['applied_unit_price']=str(Decimal(str(price)).quantize(Decimal('.01')))
        else:
            for limit, price in g['rule']['tiers']:
                take = max(0, min(n, limit if limit is not None else n)-prev)
                subtotal += take * Decimal(str(price))
                if limit is None or n <= limit: break
                prev = limit
        g['mode']=mode
        g['amount'] = str(subtotal.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)); total += Decimal(g['amount'])
    return {'total':str(total.quantize(Decimal('.01'))),'groups':list(groups.values()), 'enabled':True}


def order_quote(config,items,binding_name,quantity=1):
    result=quote(config,items);binding=binding_charge(config,binding_name,quantity)
    result['print_total']=result['total'];result['binding']=binding
    result['binding_total']=binding['total'] if result['enabled'] else '0.00'
    result['total']=format(Decimal(result['print_total'])+Decimal(result['binding_total']),'.2f')
    return result
