"""Optional local one-shot pool read, preserving an older active collector."""
import json,os,subprocess,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def request_for(state,health,config,review=False):
 if review or config.get('mode')!='local':raise ValueError('回放与远端仅使用所选帧记录的卡池')
 if health.get('service')!='sgi-crossover-bridge-1' or health.get('phase')!='live' or not health.get('fresh'):raise ValueError('本机实时采集尚未就绪')
 expected=config.get('expected_source') or config.get('label')
 if not expected or health.get('source_id')!=expected:raise ValueError('当前数据源不属于本机')
 identity=(state or {}).get('identity') or {}
 if any(identity.get(k)!=(health.get('identity') or {}).get(k) for k in ('pid','path','creation_filetime')):raise ValueError('当前画面与实时游戏实例不符')
 if state.get('core_address')!=health.get('core_address'):raise ValueError('当前游戏核心已改变')
 return dict(identity=identity,core_address=state['core_address'],build_sha256=state['build_sha256'],clock_raw_hex=(state.get('clock_candidates') or {}).get('raw_hex'))
def fetch(state,review=False,kind='card_pool'):
 from connection import load_config
 config=load_config()
 if review or config['mode']!='local':raise ValueError('回放与远端仅使用所选帧记录的卡池')
 op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 health=json.load(op.open('http://127.0.0.1:'+str(config['port'])+'/health',timeout=5));request=request_for(state,health,config,review)
 request['kind']=kind
 script=ROOT/'bridge/read_card_pool.py'
 if sys.platform=='win32':cmd=[sys.executable,'-X','utf8','-B',str(script)];env=dict(os.environ)
 elif sys.platform=='darwin':
  cfg=json.loads((ROOT/'connection.local.json').read_text(encoding='utf8'));runtime=cfg['wine_runtime']
  cmd=[runtime['wine'],str(ROOT/'bridge/python/python.exe'),'-X','utf8','-B','Z:'+str(script).replace('/','\\')]
  env=dict(os.environ,WINEPREFIX=runtime['prefix'],WINEDEBUG='-all',WINEDLLOVERRIDES='winegstreamer=d')
  for n in ('DYLD_LIBRARY_PATH','DYLD_FRAMEWORK_PATH','GST_PLUGIN_SYSTEM_PATH_1_0','GST_PLUGIN_SCANNER_1_0','CX_BOTTLE','CX_ROOT','WINESERVER','WINELOADER','WINEDLLPATH'):env.pop(n,None)
  if runtime.get('dependency_lib'):env['DYLD_FALLBACK_LIBRARY_PATH']=runtime['dependency_lib']
 else:raise ValueError('仅支持Mac Wine与Windows')
 p=subprocess.run(cmd,input=json.dumps(request),capture_output=True,text=True,encoding='utf8',env=env,timeout=20)
 try:result=json.loads(p.stdout)
 except ValueError:raise ValueError('只读卡池辅助未返回有效结果')
 if p.returncode or result.get('error'):raise ValueError(result.get('error','只读卡池读取失败'))
 return result
