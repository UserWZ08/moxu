"""List price first, optional discount thresholds; compatibility with older tiers."""
from copy import deepcopy
from decimal import Decimal

def enrich(rule):
    r=deepcopy(rule)
    if 'base_price' not in r:
        tiers=r['tiers'];r['base_price']=str(Decimal(str(tiers[0][1])));r['discounts']=[]
        if r.get('mode','progressive')=='volume':r['discounts']=[list(t) for t in tiers[1:]]
        else:r['discounts']=[[tiers[i-1][0]+1,str(price)] for i,(_,price) in enumerate(tiers) if i]
        r['discount_enabled']=bool(r['discounts'])
    return r

def effective(rule):
    r=enrich(rule);base=r['base_price'];discounts=r.get('discounts',[]) if r.get('discount_enabled',False) else []
    if not discounts:r['tiers']=[[1,base]] if r.get('mode')=='volume' else [[None,base]]
    elif r.get('mode')=='volume':r['tiers']=[[1,base]]+[list(d) for d in discounts]
    else:
        tiers=[];price=base
        for minimum,next_price in discounts:tiers.append([minimum-1,price]);price=next_price
        tiers.append([None,price]);r['tiers']=tiers
    return r

def validate_discounts(rule):
    if 'base_price' not in rule:return
    d=Decimal(str(rule['base_price']))
    if not d.is_finite() or d<0 or d!=d.quantize(Decimal('.01')):raise ValueError('标价必须为非负数，最多两位小数')
    previous=1;previous_price=d
    if type(rule.get('discount_enabled',False)) is not bool:raise ValueError('优惠开关无效')
    if rule.get('discount_enabled',False) and not rule.get('discounts'):raise ValueError('请添加优惠档位，或关闭量大优惠')
    for minimum,price in rule.get('discounts',[]) if rule.get('discount_enabled',False) else []:
        if type(minimum) is not int or minimum<=previous:raise ValueError('优惠数量应从2开始且递增')
        amount=Decimal(str(price))
        if not amount.is_finite() or amount<0 or amount!=amount.quantize(Decimal('.01')) or amount>previous_price:raise ValueError('优惠单价应为两位小数，不能高于标价或上一档优惠价')
        previous=minimum;previous_price=amount

def summary(rule):
    r=enrich(rule);base='标价 ¥'+format(Decimal(str(r['base_price'])),'.2f')
    if not r.get('discount_enabled'):return base+'；不启用优惠'
    mode='分段优惠' if r.get('mode','progressive')=='progressive' else '满量优惠'
    return base+'；'+mode+'：'+'；'.join(str(n)+'起 ¥'+format(Decimal(str(p)),'.2f') for n,p in r.get('discounts',[]))
