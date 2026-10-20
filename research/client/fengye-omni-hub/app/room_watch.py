"""Local-only room observer UI, Windows or macOS Wine; never joins a game."""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'app'))
sys.path.insert(0,str(ROOT/'bridge'))
from room_list_model import AlertState
from room_watch_audio import read_play_bgm, resolve_setting_ini, write_play_bgm
from room_watch_audio import sanpk_running, sanguo_running, should_restore_audio_on_exit, waiting_status
from room_watch_focus import adopt_resume, apply_nonactivating_window, capture_frontmost, is_self_or_wine, restore_frontmost, resume_from_env
from dock_icon import apply as apply_dock_icon
from room_watch_settings import load as load_settings, save as save_settings, read_file, update as update_settings

SCHEME='保留游戏的后台观察（不是仅大厅查询）'
SCHEME_QUIET_WAIT='安静等待：启动前关闭背景乐再开游戏（仍要开 SANPK，不是仅大厅查询）'
ALERT_SOUND=Path('/System/Library/Sounds/Ping.aiff')

KEEP_WAITING = (
    '已离开游戏选择',
    '无法唯一识别房间列表对象',
    '列表刷新中',
    '未出现已核验的搜索确认框',
    '游戏搜索尚未完成',
    '无法只读访问游戏进程',
    '观察进程超时',
    '观察进程退出',
    '未收到有效的房间数据',
    '窗口已变化',
)
PROBE_TIMEOUT = 45


def auto_refresh_keep(running):
    """Pause follows the checkbox. quiet-wait must not ignore an explicit uncheck."""
    return bool(running)


def should_keep_waiting(status, message='', quiet_wait=False):
    if status=='waiting_lobby':
        return True
    if not quiet_wait or status!='unavailable':
        return False
    text=message or ''
    return any(marker in text for marker in KEEP_WAITING)


def should_apply_mute_after(snapshot, restored=False, muted=False):
    return bool(snapshot.get('quiet') and snapshot.get('status')=='fresh'
                and not restored and not muted)


def snapshot_for_alerts(snapshot):
    if snapshot.get('ui_listbox')=='mismatch':
        value=dict(snapshot)
        value['status']='cached'
        return value
    box=snapshot.get('ui_listbox')
    if snapshot.get('ui_list')=='mismatch' and box not in ('rooms_agree','count_agree','empty_agree'):
        value=dict(snapshot)
        value['status']='cached'
        return value
    return snapshot


def snapshot_without_game(reveal=False, lobby_alive=False):
    message=waiting_status(False,lobby_alive)
    if reveal:
        message='游戏未运行，未探窗口、不抢焦点。'+(message or '')
    return {'status':'waiting_lobby','rooms':[],'observed_at':time.time(),
            'message':message,'scheme':'sanpk_background'}


def next_poll_delay(status, message='', quiet_wait=False):
    if should_keep_waiting(status, message, quiet_wait):
        return 2.0
    return 20.0

def should_log_snapshot(status, message='', last_status=None, last_message=None, elapsed=0):
    if status!='waiting_lobby':
        return True
    if last_status!=status or last_message!=message:
        return True
    return elapsed>=60

def ring(root=None, resume=None):
    if root is not None and sys.platform!='darwin':
        root.bell()
    if sys.platform=='darwin' and ALERT_SOUND.is_file():
        subprocess.Popen(['afplay',str(ALERT_SOUND)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    restore_frontmost(resume)

def wine_prefix():
    try:
        from connection import local_config
        runtime=(local_config() or {}).get('wine_runtime') or {}
        prefix=runtime.get('prefix')
        return prefix
    except Exception:
        return None

def command(refresh, quiet=False, reveal=False, inspect=False, prefix=None, pid=None, exe=None):
    sys.path.insert(0,str(ROOT/'bridge'))
    from room_list_probe import probe_command
    return probe_command(ROOT, refresh, quiet, reveal, inspect,
                         prefix=prefix if prefix is not None else wine_prefix(),
                         pid=pid, exe=exe)

def kill_probe(proc):
    if sys.platform=='win32':
        proc.kill()
    else:
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            proc.kill()
    try:
        proc.communicate(timeout=3)
    except Exception:
        pass


def probe(refresh=False, quiet=False, reveal=False):
    cmd,env=command(refresh, quiet=quiet, reveal=reveal)
    kwargs=dict(args=cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace')
    if sys.platform=='win32':
        kwargs['creationflags']=0x08000000 | 0x00000200
    else:
        kwargs['start_new_session']=True
    proc=subprocess.Popen(**kwargs)
    try:
        stdout, _stderr = proc.communicate(timeout=PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        kill_probe(proc)
        raise RuntimeError('观察进程超时，本轮未标为实时')
    if proc.returncode:raise RuntimeError('观察进程退出；游戏进程未被终止')
    for line in reversed((stdout or '').splitlines()):
        try:
            value=json.loads(line)
            if isinstance(value,dict) and 'status' in value:return value
        except ValueError:pass
    raise RuntimeError('未收到有效的房间数据')

def acquire_lock(path=None):
    path=Path(path) if path is not None else ROOT/'logs/room-watch.lock'
    path.parent.mkdir(exist_ok=True)
    stream=path.open('a+b')
    try:
        if sys.platform=='win32':
            import msvcrt
            stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except Exception:
        stream.close()
        raise
    return stream

def setting_ini(exe=None):
    return resolve_setting_ini(exe, wine_prefix())

def mute_bgm(settings_path, exe=None):
    ini=setting_ini(exe)
    current,_,_=read_play_bgm(ini)
    stored=read_file(settings_path)
    if stored.get('audio_original') not in (0,1):
        update_settings(settings_path,audio_original=current)
    write_play_bgm(ini,0)
    update_settings(settings_path,audio_muted=True)
    return current

def restore_bgm(settings_path, exe=None):
    stored=read_file(settings_path)
    original=stored.get('audio_original')
    if original not in (0,1):
        raise RuntimeError('没有已保存的原音频设置，未改写')
    write_play_bgm(setting_ini(exe),original)
    update_settings(settings_path,audio_muted=False,quiet_launch=False,
                    audio_restore_written=True,audio_restore_heard=False)
    return original

def main():
    settings_path=ROOT/'room-watch.local.json'
    threshold,minutes=load_settings(settings_path)
    alerts=AlertState(threshold,minutes)
    quiet_wait='--quiet-wait' in sys.argv
    try:lock=acquire_lock()
    except OSError:
        print('本机已有一个观察窗口，请使用原窗口。',file=sys.stderr)
        try:
            from quiet_wait_launch import notify_already_running
            notify_already_running()
        except Exception:
            pass
        return
    resume=resume_from_env() or capture_frontmost()
    root=tk.Tk();apply_dock_icon(root,'wine');root.withdraw()
    root.title(f'房间人数观察 · 本机 · 大于 {threshold} 人提示')
    root.attributes('-topmost', False)
    apply_nonactivating_window(root)
    root.deiconify()
    root.after(80, lambda: restore_frontmost(resume))
    root.after(400, lambda: restore_frontmost(resume))
    from mac_light_theme import apply_light_defaults
    apply_light_defaults(root)
    root.geometry('700x480');root.minsize(640,420)
    logger=logging.getLogger('room-watch');logger.setLevel(logging.INFO)
    handler=RotatingFileHandler(ROOT/'logs/room-watch.jsonl',maxBytes=1024*1024,backupCount=3,encoding='utf-8')
    logger.addHandler(handler)
    frame=ttk.Frame(root,padding=12);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text=SCHEME_QUIET_WAIT if quiet_wait else SCHEME).pack(anchor='w')
    status=tk.StringVar(value=('启动前已关 PlayBGM，进入游戏选择后开始后台观察。'
                              if quiet_wait else
                              '正在读取列表缓存… 关闭本窗会停止观察并恢复游戏显示/原音频设置。'))
    ttk.Label(frame,textvariable=status,wraplength=660).pack(anchor='w',pady=8)
    tree=ttk.Treeview(frame,columns=('name','count','state'),show='headings',height=6)
    for name,title,width in [('name','房间',285),('count','连接人数 / 上限',125),('state','进场参考',180)]:
        tree.heading(name,text=title);tree.column(name,width=width,minwidth=80)
    tree.tag_configure('ready',background='#d5f1d5',foreground='#153b15');tree.pack(fill='both',expand=True)
    bar=ttk.Frame(frame);bar.pack(fill='x',pady=8)
    running=tk.BooleanVar(value='--watch' in sys.argv or quiet_wait)
    sound=tk.BooleanVar(value=True)
    background=tk.BooleanVar(value=True)
    ttk.Checkbutton(bar,text='自动刷新（后台，不弹窗）',variable=running).pack(side='left')
    ttk.Checkbutton(bar,text='达到条件时响铃',variable=sound).pack(side='left',padx=8)
    settings_bar=ttk.Frame(frame);settings_bar.pack(fill='x',pady=(0,8))
    x_var=tk.StringVar(value=str(threshold));y_var=tk.StringVar(value=f'{minutes:g}')
    ttk.Label(settings_bar,text='有房间大于').pack(side='left')
    ttk.Spinbox(settings_bar,from_=0,to=63,textvariable=x_var,width=4).pack(side='left',padx=4)
    ttk.Label(settings_bar,text='人，每').pack(side='left')
    ttk.Spinbox(settings_bar,from_=.1,to=1440,increment=.5,textvariable=y_var,width=6).pack(side='left',padx=4)
    ttk.Label(settings_bar,text='分钟最多响一次').pack(side='left')
    hint=tk.StringVar()
    def update_hint():
        hint.set(f'当前生效：人数 >{alerts.threshold}（至少 {alerts.threshold+1} 人），每 {alerts.minutes:g} 分钟可响一次。\n'
                 '含房主；多人达标合并警报。不会自动加入。大厅本身不能查人数。'
                 '后台刷新只藏搜寻确认框，不藏游戏选择房间列表。'
                 '已在播的循环乐不会因中途改 ini 停下；要无音乐请用「安静等待」在启动前关 PlayBGM。'
                 '进场恢复只写回原值，正在跑的游戏不一定马上出声，请用耳朵确认。'
                 '关窗停止观察；安静等待且游戏未开时保持 PlayBGM=0。再开用 Wine 导航或 Start-Room-Watch / Start-Quiet-Wait。')
    def apply_settings():
        try:x,y=save_settings(settings_path,x_var.get(),y_var.get())
        except (OSError,ValueError,TypeError) as error:
            messagebox.showerror('警报设置未保存',str(error));return
        alerts.configure(x,y);x_var.set(str(x));y_var.set(f'{y:g}');update_hint()
        root.title(f'房间人数观察 · 本机 · 大于 {x} 人提示')
        status.set('警报设置已保存；在下一次有效刷新时按新设置判断')
    ttk.Button(settings_bar,text='保存设置',command=apply_settings).pack(side='right')
    update_hint();ttk.Label(frame,textvariable=hint,wraplength=660).pack(anchor='w')
    inbox=queue.Queue();state={'busy':False,'next':0,'closed':False,'exe':None,'restored':False,
                               'muted':bool(quiet_wait and read_file(settings_path).get('audio_muted')),
                               'resume':resume}
    def start(refresh=True, reveal=False):
        if state['busy'] or state['closed']:return
        if not sanpk_running():
            inbox.put(snapshot_without_game(reveal,sanguo_running()))
            return
        state['busy']=True
        quiet=background.get() and refresh and not reveal
        if reveal:status.set('正在恢复游戏窗口…')
        elif refresh:status.set('正在后台刷新房间列表（不抢焦点）…')
        else:status.set('读取现有列表（缓存，不报警）…')
        def work():
            try:result=probe(refresh=refresh and not reveal, quiet=quiet, reveal=reveal)
            except Exception as error:result={'status':'unavailable','rooms':[],'message':str(error),'observed_at':time.time()}
            inbox.put(result)
        threading.Thread(target=work,daemon=True).start()
    def apply_mute():
        try:
            original=mute_bgm(settings_path,state.get('exe'))
            stored=read_file(settings_path)
            if stored.get('quiet_launch'):
                status.set('启动前已关闭 PlayBGM，等待中不应再开新曲。观察器警报仍可响。进场前请恢复声音。')
            else:
                status.set(f'已把 Setting.ini 的 PlayBGM 从 {original} 改为 0，只阻止下一首。'
                           '已经在循环的背景乐仍会响。要无音乐请退出后用「安静等待」启动。'
                           '未改系统音量。观察器响铃不受影响。')
        except Exception as error:
            status.set('游戏静音未生效：'+str(error))
    def restore_game():
        try:
            original=restore_bgm(settings_path,state.get('exe'));state['muted']=False
            status.set(f'已把 PlayBGM 写回 {original}。正在运行的游戏不一定马上出声，请用耳朵确认；'
                       '听不到就从大厅再进一次游戏。未自动入场。')
        except Exception as error:
            status.set('原音频未恢复：'+str(error)+'；仍尝试显示窗口')
        start(refresh=False, reveal=True)
    def exit_watch():
        if state['closed']:
            close_window();return
        if state['restored']:
            if not state['busy']:close_window()
            return
        state['restored']=True
        running.set(False)
        keep_quiet=not should_restore_audio_on_exit(read_file(settings_path),sanpk_running())
        if keep_quiet:
            close_window();return
        try:restore_bgm(settings_path,state.get('exe'));state['muted']=False
        except Exception:
            pass
        def finish(tries=0):
            if state['closed']:return
            if state['busy'] and tries<50:
                root.after(200,lambda:finish(tries+1));return
            if tries==0 or state['busy'] is False:
                start(refresh=False, reveal=True)
                root.after(2500,close_window)
        finish()
    actions=ttk.Frame(frame);actions.pack(fill='x',pady=6)
    ttk.Button(actions,text='立即后台刷新',command=lambda:start(True)).pack(side='left')
    ttk.Button(actions,text='恢复游戏显示和声音',command=restore_game).pack(side='left',padx=8)
    ttk.Button(actions,text='退出观察',command=exit_watch).pack(side='right')
    def tick():
        if state['closed']:return
        try:
            value=inbox.get_nowait()
            state['busy']=False
            keep=auto_refresh_keep(running.get())
            state['next']=time.monotonic()+next_poll_delay(value.get('status'),value.get('message') or '',keep)
            if value.get('exe'):state['exe']=value['exe']
            now=time.monotonic()
            if should_log_snapshot(value.get('status'),value.get('message') or '',
                                   state.get('log_status'),state.get('log_message'),
                                   now-state.get('log_at',0)):
                logger.info(json.dumps(value,ensure_ascii=False))
                state['log_status']=value.get('status')
                state['log_message']=value.get('message') or ''
                state['log_at']=now
            tree.delete(*tree.get_children())
            fresh=value['status']=='fresh'
            for r in value.get('rooms',[]):
                ready=fresh and r['current']>alerts.threshold
                tree.insert('', 'end',values=(r['name'],f"{r['current']} / {r['maximum']}"+('（缓存）' if not fresh else ''),
                    f'已超过 {alerts.threshold} 人' if ready else (f'等待人数 >{alerts.threshold}' if fresh else '未验证更新时间')),tags=('ready',) if ready else ())
            stamp=time.strftime('%H:%M:%S',time.localtime(value['observed_at']))
            events=alerts.update(snapshot_for_alerts(value),enabled=sound.get())
            if fresh:
                status.set('最近成功查询 '+stamp+' · '+value.get('message',''))
            else:
                status.set(value.get('message') or '读取未成功；未用旧人数报警')
            if fresh and not value['rooms']:
                extra=''
                if value.get('ui_list')=='empty_agree':
                    extra='；游戏列表也显示看不到主机'
                elif value.get('ui_hints'):
                    extra='；游戏列表：'+value['ui_hints'][0]
                status.set('已搜索 '+stamp+' · 当前未发现房间（不代表房间为 0 人）'+extra)
            if value.get('ui_list')=='mismatch' and value.get('ui_listbox') not in ('rooms_agree','count_agree'):
                status.set('读到房间但游戏仍显示看不到主机；未用该结果报警')
            if value.get('ui_listbox')=='mismatch':
                status.set('读到房间但游戏列表人数不一致；未用该结果报警')
            if value.get('rooms') and value.get('ui_listbox_items'):
                extra='；列表原文：'+'、'.join(str(item) for item in value['ui_listbox_items'][:8])
                current=status.get() or ''
                if extra not in current:
                    status.set(current+extra)
            if value.get('confirm_first_visible'):
                current=status.get() or ''
                note='；搜寻确认框曾短暂可见'
                if note not in current:
                    status.set(current+note)
            if events:
                status.set(f'人数已超过 {alerts.threshold}：'+'、'.join(f"{r['name']} {r['current']} 人" for r in events))
                root.title(f'≥{alerts.threshold+1} 人 · 可以考虑进场 · 房间观察')
                if sound.get():ring(root, state.get('resume'))
            elif fresh:root.title(f'房间人数观察 · 本机 · 大于 {alerts.threshold} 人提示')
            if value['status']=='waiting_lobby':
                if keep:running.set(True)
                status.set(value.get('message') or '等待进入游戏选择')
            elif value['status']=='unavailable':
                if should_keep_waiting(value['status'], value.get('message') or '', keep):
                    running.set(True)
                    status.set((value.get('message') or '等待游戏选择')+'；继续等待，不会用旧人数报警')
                else:
                    running.set(False);status.set(value['message']+'；已暂停，不会用过期人数报警')
            if value.get('status')!='waiting_lobby':
                restore_frontmost(state.get('resume'), stolen_by=is_self_or_wine)
            if should_apply_mute_after(value, state['restored'], state['muted']):
                apply_mute();state['muted']=True
        except queue.Empty:pass
        state['resume']=adopt_resume(state.get('resume'))
        if running.get() and not state['busy'] and time.monotonic()>=state['next']:start()
        root.after(200,tick)
    def close_window():
        state['closed']=True
        root.destroy()
    def close():
        if not state['restored']:
            exit_watch()
            return
        close_window()
    root.protocol('WM_DELETE_WINDOW',close)
    start(running.get());root.after(200,tick);root.mainloop()
    lock.close()

if __name__=='__main__':
    try:
        main()
    except Exception:
        logging.basicConfig(filename=str(ROOT/'logs/room-watch-ui.log'),level=logging.ERROR)
        logging.exception('room_watch failed')
        raise
