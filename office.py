"""Prefer the document's native Microsoft engine; only missing engines may fall back."""
import os,shutil,subprocess,json,base64,queue,threading
from pathlib import Path

POLICIES=['Microsoft Office 优先','仅 Microsoft Office','仅 LibreOffice']

def engine_signature():
    """Invalidate compatibility caches when an Office engine is installed/registered."""
    try:
        import winreg
        result=[]
        for name in ['Word.Application','Excel.Application','PowerPoint.Application']:
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,name+'\\CLSID') as k:clsid=winreg.QueryValue(k,None)
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,'CLSID\\'+clsid+'\\LocalServer32') as k:server=winreg.QueryValue(k,None)
                result.append(name+clsid+server)
            except OSError:result.append(name+':missing')
        return '|'.join(result)
    except ImportError:return 'non-windows'

SESSION_SCRIPT=r'''$ErrorActionPreference='Stop'
[Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$apps=@{}
try {
  while($null -ne ($line=[Console]::ReadLine())) {
    $doc=$null;$reply=@{code=0;error=''}
    try {
      $r=ConvertFrom-Json $line;$kind=$r.kind
      if(-not $apps.ContainsKey($kind)) {
        $prog=if($kind -eq 'word'){'Word.Application'}elseif($kind -eq 'excel'){'Excel.Application'}else{'PowerPoint.Application'}
        try {$app=New-Object -ComObject $prog} catch {
          if($_.Exception.ToString() -match '80040154|800401F3') {$reply.code=15};throw
        }
        $apps[$kind]=$app;$app.AutomationSecurity=3
        if($kind -ne 'ppt') {$app.Visible=$false;$app.DisplayAlerts=0}
        if($kind -eq 'word') {$app.ScreenUpdating=$false}
      }
      $app=$apps[$kind]
      if($kind -eq 'word') {$doc=$app.Documents.Open($r.source,$false,$true,$false);$doc.ExportAsFixedFormat($r.dest,17)}
      elseif($kind -eq 'excel') {$doc=$app.Workbooks.Open($r.source,0,$true);$doc.ExportAsFixedFormat(0,$r.dest)}
      else {$doc=$app.Presentations.Open($r.source,$true,$false,$false);$doc.SaveAs($r.dest,32)}
    } catch {if($reply.code -ne 15){$reply.code=1};$reply.error=$_.Exception.ToString()}
    finally {
      if($null -ne $doc){try {if($kind -eq 'word'){$doc.Close(0)}elseif($kind -eq 'excel'){$doc.Close($false)}else{$doc.Close()}} catch {$reply.code=1;$reply.error=$_.Exception.ToString()}}
    }
    [Console]::WriteLine((ConvertTo-Json -Compress $reply))
  }
} finally {foreach($app in $apps.Values){try {$app.Quit()} catch {}}}
'''

class ConversionSession:
    """Reuse one Word/Excel/PPT instance within an import batch, then close it."""
    def __init__(self):self.process=None;self.responses=queue.Queue()
    def __enter__(self):return self
    def native(self,source,output,kind):
        if self.process is None:
            encoded=base64.b64encode(SESSION_SCRIPT.encode('utf-16le')).decode('ascii')
            self.process=subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',creationflags=0x08000000)
            def read():
                for line in self.process.stdout:
                    try:self.responses.put(json.loads(line))
                    except ValueError:continue
                self.responses.put({'code':1,'error':'Office 转换进程意外退出'})
            threading.Thread(target=read,daemon=True).start()
        self.process.stdin.write(json.dumps({'source':str(source.resolve()),'dest':str(output.resolve()),'kind':kind})+'\n');self.process.stdin.flush()
        try:return self.responses.get(timeout=180)
        except queue.Empty:
            self.process.kill();raise RuntimeError('Office 转换超时；请检查文件和 Office 对话框')
    def __exit__(self,*args):
        if self.process:
            try:self.process.stdin.close()
            except OSError:pass
            try:self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
            self.process.stdout.close()

def libreoffice_path():
    found=shutil.which('soffice')
    if found:return found
    for base in [os.environ.get('ProgramFiles',''),os.environ.get('ProgramFiles(x86)','')]:
        p=Path(base)/'LibreOffice/program/soffice.exe'
        if p.exists():return str(p)
    return None

SCRIPT=r'''$ErrorActionPreference='Stop'
$s=$env:NP_SOURCE;$d=$env:NP_DEST;$kind=$env:NP_KIND;$app=$null;$doc=$null
try {
  $prog=if($kind -eq 'word'){'Word.Application'}elseif($kind -eq 'excel'){'Excel.Application'}else{'PowerPoint.Application'}
  try {$app=New-Object -ComObject $prog} catch {
    if($_.Exception.ToString() -match '80040154|800401F3') {Write-Output 'NP_ENGINE_MISSING';exit 15};throw
  }
  $app.AutomationSecurity=3
  if($kind -eq 'word') {$app.Visible=$false;$app.DisplayAlerts=0;$doc=$app.Documents.Open($s,$false,$true,$false);$doc.ExportAsFixedFormat($d,17)}
  elseif($kind -eq 'excel') {$app.Visible=$false;$app.DisplayAlerts=$false;$doc=$app.Workbooks.Open($s,0,$true);$doc.ExportAsFixedFormat(0,$d)}
  else {$doc=$app.Presentations.Open($s,$true,$false,$false);$doc.SaveAs($d,32)}
} finally {
  if($null -ne $doc){if($kind -eq 'word'){$doc.Close(0)}elseif($kind -eq 'excel'){$doc.Close($false)}else{$doc.Close()}}
  if($null -ne $app){$app.Quit()}
}
'''

def convert(source,folder,output,policy='Microsoft Office 优先',session=None):
    source=Path(source);folder=Path(folder);output=Path(output)
    if policy not in POLICIES:raise ValueError('Office 转换引擎设置无效')
    kind='word' if source.suffix.lower() in ['.doc','.docx'] else 'excel' if source.suffix.lower() in ['.xls','.xlsx'] else 'ppt'
    label={'word':'Microsoft Word','excel':'Microsoft Excel','ppt':'Microsoft PowerPoint'}[kind]
    if policy!='仅 LibreOffice':
        if session:
            result=session.native(source,output,kind)
            from types import SimpleNamespace
            proc=SimpleNamespace(returncode=result['code'],stdout=b'NP_ENGINE_MISSING' if result['code']==15 else b'',stderr=result.get('error','').encode('utf-8'))
        else:
            env=dict(os.environ,NP_SOURCE=str(source.resolve()),NP_DEST=str(output.resolve()),NP_KIND=kind)
            proc=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',SCRIPT],env=env,capture_output=True,timeout=180,creationflags=0x08000000)
        if proc.returncode==0 and output.exists():return label
        output.unlink(missing_ok=True)
        missing=proc.returncode==15 and b'NP_ENGINE_MISSING' in proc.stdout
        if not missing:raise RuntimeError(label+' 转换失败；为避免静默改变排版，没有切换其他引擎。\n'+proc.stderr.decode(errors='replace')[-650:])
        if policy=='仅 Microsoft Office':raise RuntimeError('没有安装对应的 '+label+'，请安装它或提交已确认的 PDF')
    executable=libreoffice_path()
    if not executable:raise RuntimeError('没有可用的 Office 转换引擎。请安装对应 Microsoft Office/LibreOffice，或先导出 PDF。')
    proc=subprocess.run([executable,'-env:UserInstallation='+(folder/'profile').resolve().as_uri(),'--headless','--convert-to','pdf','--outdir',str(folder),str(source.resolve())],capture_output=True,timeout=180,creationflags=0x08000000)
    converted=folder/(source.stem+'.pdf')
    if proc.returncode or not converted.exists():raise RuntimeError('LibreOffice 转换失败：'+proc.stderr.decode(errors='replace')[-650:])
    if converted.resolve()!=output.resolve():converted.replace(output)
    return 'LibreOffice（兼容转换，请核对排版）'

def engine_label(source,prepared):
    suffix=Path(source).suffix.lower()
    if suffix=='.pdf':return 'Qt PDF / PDFium'
    if suffix in ['.doc','.docx','.xls','.xlsx','.ppt','.pptx']:
        p=Path(prepared).parent/'engine.txt'
        return p.read_text('utf-8') if p.exists() else 'Office 转换'
    return 'Qt 图像模块'
