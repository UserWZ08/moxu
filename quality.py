"""User-facing quality names, resolved against each printer's own binding."""
LEVELS=['标准打印','高质量打印']

def default_bindings(printer):
    names=[q['name'] for q in printer.get('quality_profiles',[])]
    manufacturer=printer.get('name','').casefold()
    if 'epson' in manufacturer or '爱普生' in manufacturer:
        standard=next((n for n in names if n in ['标准','标准打印','standard']), '标准')
        high=next((n for n in names if n in ['高','高质量','高质量打印','high']), '高')
        return {LEVELS[0]:{'mode':'native','profile':standard},LEVELS[1]:{'mode':'native','profile':high}}
    dpi=printer.get('dpi',[600]);return {LEVELS[0]:{'mode':'dpi','dpi':600 if 600 in dpi else min(dpi)},LEVELS[1]:{'mode':'dpi','dpi':1200}}

def bindings(printer):return printer.get('quality_bindings') or default_bindings(printer)

def resolve(config,printer_name,options):
    printer=next((p for p in config.get('printers',[]) if p['name']==printer_name),None)
    if printer is None:raise ValueError('打印机未在后台添加')
    level=options.get('quality_level')
    if not level:
        from core import active_quality
        profile=active_quality(config,printer_name)
        return {'dpi':options.get('dpi',600),'profile':profile,'label':profile['name'] if profile else '通用 DPI'}
    if level not in LEVELS:raise ValueError('打印质量选项无效')
    binding=bindings(printer).get(level)
    if not binding:raise ValueError(printer_name+' 尚未绑定“'+level+'”')
    if binding.get('mode')=='unconfigured':raise ValueError(printer_name+' 尚未绑定“'+level+'”')
    if binding['mode']=='dpi':
        dpi=binding['dpi']
        if dpi not in printer.get('dpi',[]):raise ValueError(printer_name+' 不支持已绑定的 DPI')
        return {'dpi':dpi,'profile':None,'label':level+' · '+str(dpi)+' DPI'}
    if not config.get('native_quality_enabled'):raise ValueError('请在后台开启厂商质量预设，再使用此设备的质量档位')
    profile=next((q for q in printer.get('quality_profiles',[]) if q['name']==binding['profile']),None)
    if profile is None:raise ValueError(printer_name+' 的“'+level+'”需要先捕获并绑定厂商预设“'+binding['profile']+'”')
    return {'dpi':options.get('dpi',600),'profile':profile,'label':level+' · 厂商预设：'+profile['name']}
