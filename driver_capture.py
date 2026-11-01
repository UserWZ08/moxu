"""Isolate vendor UI so a failing driver does not crash the workbench."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))

def main(request_path):
    request_file=Path(request_path);request=json.loads(request_file.read_text('utf-8'));output=Path(request['output'])
    try:
        from windows_driver import capture
        profile=capture(request['printer'],request.get('previous'))
        result={'cancelled':profile is None,'profile':profile}
    except Exception as e:result={'error':str(e)}
    output.write_text(json.dumps(result,ensure_ascii=False),'utf-8')

if __name__=='__main__':main(sys.argv[1])
