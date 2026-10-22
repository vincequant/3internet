import json,urllib.request
from pathlib import Path
from functools import lru_cache
from connection import CONNECTION
URL=CONNECTION.base_url+'/api/state'

@lru_cache(maxsize=1)
def viewer_version():
 try:return json.loads((Path(__file__).resolve().parents[1]/'RELEASE.json').read_text(encoding='utf8'))['version']
 except (OSError,ValueError,KeyError):return None

def snapshot_age_text(age):
 if age is None:return '无快照'
 try:return f'{int(age)}秒'
 except (TypeError,ValueError):return '无快照'

def recording_text(payload):
 """Describe reported recorder state; a lobby is not a recorded match."""
 p=payload or {}; archive=p.get('replay_archive')
 if not isinstance(archive,dict):return '记录状态未确认'
 if archive.get('write_error'):return '回放写入异常'
 native=p.get('native_payload_observations') or {}
 fault=native.get('enabled') and native.get('phase') in ('backoff','stopped','stopping')
 if archive.get('recording') and archive.get('open'):
  seq=archive.get('seq'); suffix=f' {seq}帧' if type(seq) is int else ''
  return '回放记录中'+suffix+(' · 指令采集异常' if fault else '')
 if fault:
  return '指令采集异常 · 回放待开局'
 return '记录监控已启动 · 回放待开局'

def _status_text(payload,doc=None):
 p=payload or {}
 doc=doc if doc is not None else p.get('state')
 age=p.get('snapshot_age_s')
 if age is None and doc and doc.get('capture_end'):
  from datetime import datetime,timezone
  try:age=(datetime.now(timezone.utc)-datetime.fromisoformat(doc['capture_end'])).total_seconds()
  except (TypeError,ValueError):age=None
 age_txt=snapshot_age_text(age)
 phase=p.get('phase') or ''
 if p.get('fresh') and not p.get('error') and doc:
  ms=(doc.get('timing') or {}).get('capture_ms')
  snap=doc.get('snapshot_id') or ''
  if isinstance(p.get('replay_archive'),dict):return '采集实时 · '+recording_text(p),'#d2edb9'
  recording=''
  if isinstance(ms,(int,float)):return f'采集实时 · {ms:.1f} ms · {snap}'+recording,'#d2edb9'
  return f'采集实时 · {snap}'+recording,'#d2edb9'
 if phase=='waiting_for_player':
  return '已连接游戏 · 等待开局 · '+recording_text(p),'#ffd08a'
 if phase=='waiting_for_game':
  return '等待游戏启动 · 记录待连接','#ffd08a'
 if phase=='map_not_ready':
  return '等待地图就绪 · 旧快照 '+age_txt,'#ffd08a'
 if phase=='recovering':
  return '恢复中 · 旧快照 '+age_txt,'#ffd08a'
 return '采集断开 · 旧快照 '+age_txt,'#ffc0a0'

def poll(app):
 from native_input_evidence import InputEvidenceReader
 from native_command_evidence import CommandEvidenceReader
 from command_view_store import CommandViewStore
 inputs=InputEvidenceReader()
 commands=CommandEvidenceReader()
 command_views=CommandViewStore()
 from command_peer import CommandPeer
 peer=CommandPeer()
 from sortie_observations import SortieObservations
 sorties=SortieObservations()
 while not app.stop.is_set():
  try:
   CONNECTION.ensure()
   with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(URL,timeout=6) as response:p=json.load(response)
   CONNECTION.validate(p)
   if p.get('service')!='sgi-crossover-bridge-1':raise ValueError('不是本测试包的采集桥')
   if p.get('fresh') is not True:p['fresh']=False
  except Exception as error:p={'fresh':False,'error':str(error),'state':None,'phase':'error'}
  p['source_label']=CONNECTION.cfg['label']
  p['remote']=CONNECTION.remote
  if p.get('state'):
   # Pure display derivation from this exact snapshot, including an older
   # collector kept running to preserve the current match's archive stream.
   # Never rewrite history or pretend missing new collector fields were read.
   from unit_combat import enrich_unit_combat
   enrich_unit_combat(p['state'])
   if not CONNECTION.remote:p=sorties.attach(p)
   evidence=commands.read(p,remote=CONNECTION.remote)
   if not CONNECTION.remote:
    try:evidence=command_views.remember(p,evidence)
    except (OSError,ValueError) as error:print('指令日期保存失败：'+str(error),flush=True)
   evidence=peer.attach(p,evidence)
   p['state']=dict(p['state'],local_input_evidence=inputs.read(p,remote=CONNECTION.remote),
                   native_command_evidence=evidence)
   p['state'].pop('native_command_transfer',None)
  if p.get('fresh') is not True:
   source=CONNECTION.cfg.get('expected_source') or CONNECTION.cfg['label']
   if CONNECTION.remote:
    from command_transport import import_retained
    p['retained_command_view']=import_retained(p)
   else:p['retained_command_view']=command_views.load(source)
  try:app.inbox.put_nowait(p)
  except Exception:pass
  app.stop.wait(1)
 peer.close()


def confirm_player(doc,force_id):
 if CONNECTION.remote:raise ValueError('远端只读查看；我方身份由游戏所在电脑自动识别')
 payload={'session_id':(doc.get('player_identity') or {}).get('session_id'),'force_id':force_id}
 request=urllib.request.Request(CONNECTION.base_url+'/api/player',data=json.dumps(payload).encode('utf8'),headers={'Content-Type':'application/json'},method='POST')
 try:
  with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=3) as response:return json.load(response)
 except urllib.error.HTTPError as error:
  raise ValueError(json.loads(error.read()).get('error','确认失败')) from error


def invalidate_player(doc):
 from command_display import retain_calendars
 out=dict(doc);out['player_force_id']=None
 if doc.get('native_command_evidence'):
  out['native_command_evidence']=retain_calendars(doc['native_command_evidence'],doc.get('history'),doc.get('snapshot_id'))
 out['player_identity']=dict(doc.get('player_identity') or {},force_id=None,status='unknown',source='unknown')
 out['current_local_projection']=dict(doc.get('current_local_projection') or {},player_force_id=None)
 out.pop('history',None);out['core_projection_divergence']={}
 return out


def status_text(payload,doc=None):
 text,color=_status_text(payload,doc)
 p=payload or {}
 if (p.get('fresh') and p.get('phase')=='live' and p.get('release_version')
     and viewer_version() and p['release_version']!=viewer_version()):
  text+=' · 采集器更新待本局结束'
 label=p.get('source_label',CONNECTION.cfg['label'])
 return ('远端 · ' if p.get('remote',CONNECTION.remote) else '本机 · ')+label+' · '+text,color
