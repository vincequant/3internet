"""Standalone floating panel for locally bound computer-opponent tests."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
import urllib.request

from quick_control_model import LABELS, KEYS, POLICIES, binding, wild_candidates, select_candidate, candidate_previews, candidate_label, require_available_action, probability_candidate, probability_previews, extension_plan, training_operand
from quick_control_instance import PanelInstance, watch_focus

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bridge'))
STATE_URL = 'http://127.0.0.1:8769/api/state'


def wine_argv(script):
    """Run a bridge script in the game's own Windows Python. Does not start the game."""
    script = Path(script)
    if sys.platform == 'win32':
        return [sys.executable, '-X', 'utf8', '-B', str(script)], dict(os.environ)
    if sys.platform != 'darwin':
        raise ValueError('支持 Mac Wine 和原生 Windows')
    cfg = json.loads((ROOT / 'connection.local.json').read_text(encoding='utf8'))
    runtime = cfg['wine_runtime']; wine = Path(runtime['wine']); prefix = Path(runtime['prefix'])
    python = ROOT / 'bridge/python/python.exe'
    if not wine.is_file() or not python.is_file() or not (prefix / 'system.reg').is_file():
        raise ValueError('找不到本机已有的 Wine/Python 环境')
    env = dict(os.environ, WINEPREFIX=str(prefix), WINEDEBUG='-all,err+all',
               LANG='zh_CN.UTF-8', LC_ALL='zh_CN.UTF-8', WINEDLLOVERRIDES='winegstreamer=d')
    for name in ('DYLD_LIBRARY_PATH','DYLD_FRAMEWORK_PATH','GST_PLUGIN_SYSTEM_PATH_1_0',
                 'GST_PLUGIN_SCANNER_1_0','CX_BOTTLE','CX_ROOT','WINESERVER','WINELOADER','WINEDLLPATH'):
        env.pop(name, None)
    if runtime.get('dependency_lib'):
        env['DYLD_FALLBACK_LIBRARY_PATH'] = runtime['dependency_lib']
    path = 'Z:' + str(script).replace('/', '\\')
    return [str(wine), str(python), '-X', 'utf8', '-B', path], env


def native_command(bound):
    argv, env = wine_argv(ROOT / 'bridge/quick_control_native.py')
    payload = json.dumps(bound, ensure_ascii=True)
    return argv + ['--binding', payload], env


class Panel:
    def __init__(self, root, smoke=False):
        self.root = root; self.proc = None; self.ready = False; self.busy = False
        self.bound = None; self.events = queue.Queue(); self.counter = 0; self.closed = False
        self.connecting = False; self.pending_id = None; self.pending_at = 0
        self.helper_epoch = 0
        self.selecting = False
        self.target_pending = False; self.selected_target = None
        self.pending_targets = {}; self.submitted_ids = set(); self.current_state = {}
        self.connection_error = None
        self.inspecting_id = None
        self.next_connect = 0; self.preview_loading = False
        self.previews = {}; self.preview_at = 0
        self.smoke = smoke
        self.marker_loading=False;self.marker_at=0
        root.title('三国志 · 快捷修改面板 1.8.7')
        root.geometry('560x420'); root.minsize(560, 420); root.attributes('-topmost', True)
        self.style_panel()
        rim = tk.Frame(root, bg='#af9050', padx=2, pady=2); rim.pack(fill='both',expand=True,padx=7,pady=7)
        box = ttk.Frame(rim, padding=10); box.pack(fill='both', expand=True)
        ttk.Label(box, text='三国志 Internet  ·  快捷军令', style='Title.TLabel').pack(anchor='w')
        ttk.Label(box, text='自动接入当前对局  ·  武将参考  ·  原版普通招揽', style='Muted.TLabel').pack(anchor='w', pady=(5,8))
        self.status = tk.StringVar(value='尚未连接游戏')
        ttk.Label(box, textvariable=self.status, wraplength=470, style='Muted.TLabel').pack(anchor='w')
        self.timer = tk.StringVar(value='游戏倒计时：—')
        ttk.Label(box, textvariable=self.timer, style='Timer.TLabel').pack(anchor='w', pady=8)
        row = ttk.Frame(box); row.pack(fill='x')
        self.connect_button = ttk.Button(row, text='重新连接', command=self.connect)
        self.connect_button.pack(side='left')
        self.refresh_button = ttk.Button(row, text='刷新状态', command=lambda:self.send('inspect'))
        self.refresh_button.pack(side='left', padx=8)
        self.buttons = {}
        self.buttons['extend'] = ttk.Button(row, text='回合 +10秒  F6', command=lambda:self.send('extend'))
        self.buttons['extend'].pack(side='left')
        root.bind('<Control-Alt-KeyPress-F6>', lambda e:self.key('extend'))
        self.extension_hint = tk.StringVar(value='加时：正在等待当前对局。')
        ttk.Label(box,textvariable=self.extension_hint,wraplength=510,style='Muted.TLabel').pack(anchor='w',pady=(5,0))
        self.automation = tk.BooleanVar(value=True)
        self.automation_switch = ttk.Checkbutton(box,text='启用辅助：补60秒／指令×3／WASD视角',
                                                variable=self.automation,command=self.settings)
        self.automation_switch.pack(anchor='w',pady=(6,2))
        self.auto_time_switch = self.automation_switch
        self.auto_time = tk.BooleanVar(value=False)
        self.auto_time_status = tk.StringVar(value='等待连接；正常倒数剩1秒补60秒，指令完成即结束。')
        ttk.Label(box,textvariable=self.auto_time_status,wraplength=510,style='Muted.TLabel').pack(anchor='w')
        self.buttons['focus_unit'] = ttk.Button(box, text='定位当前行动部队  ·  Ctrl+Alt+F7',
                                               command=lambda:self.send('focus_unit'))
        self.buttons['focus_unit'].pack(fill='x', pady=(10,0))
        root.bind('<Control-Alt-KeyPress-F7>', lambda e:self.key('focus_unit'))
        ttk.Button(box,text='武将名册  ·  在野／政治／本营，速查与招揽',command=self.officers).pack(fill='x',pady=(10,0))
        # The user explicitly wants built-in controls, without opt-in checkboxes.
        # Native settings remain false until an exact game binding is ready.
        self.test = tk.BooleanVar(value=True); self.allow_write = tk.BooleanVar(value=True)
        self.allow_target = tk.BooleanVar(value=True)
        ttk.Separator(box).pack(fill='x',pady=8)
        self.policy_hint = tk.StringVar()
        self.policy_buttons={}
        self.modifications_open = False
        self.fold_button = ttk.Button(box, text='▸ 修改功能／外挂（点击展开）', command=self.toggle_modifications)
        self.fold_button.pack(fill='x',pady=(0,6))
        self.modification_frame = ttk.Frame(box)
        self.auto_x3 = tk.BooleanVar(value=False)
        self.auto_status = tk.StringVar(value='指令×3：施舍／步骑弓训练；等待连接。')
        ttk.Label(self.modification_frame,textvariable=self.auto_status,wraplength=510,
                  style='Muted.TLabel').pack(anchor='w',pady=(0,6))
        common=ttk.Frame(self.modification_frame);common.pack(fill='x');common.columnconfigure((0,1),weight=1)
        for index, action in enumerate(('alms','infantry','cavalry','bow')):
            row, column = divmod(index, 2)
            label=LABELS[action]
            b = ttk.Button(common, text=f'{label}  {KEYS[action]}', command=lambda a=action:self.send(a))
            b.grid(row=row,column=column,sticky='ew',padx=2,pady=2); self.buttons[action] = b
            root.bind(f'<Control-Alt-KeyPress-{KEYS[action]}>', lambda e,a=action:self.key(a))
        self.training_hint = tk.StringVar(value='面板训练政治＝我方所属将最高政治×3；自动模式＝本次原版政治参数×3。\n施舍按原版随机加值×3，上限200。费用、次数和训练上限保持原版。\n加时、施舍、增强训练使用后标记我方，本局我方行动不用于训练。')
        ttk.Label(self.modification_frame, textvariable=self.training_hint,
                  wraplength=510, style='Muted.TLabel').pack(anchor='w', pady=6)
        self.modification_badge = tk.StringVar(value='修改使用标记按势力记录；对方行动仍可保留参考。')
        self.fold_anchor = ttk.Label(box, textvariable=self.modification_badge, wraplength=510, style='Muted.TLabel')
        self.fold_anchor.pack(anchor='w',pady=(0,5))
        ttk.Label(box,text='加时支持内政／军事输入；房主等待本机计时已由用户实测。',wraplength=510,style='Muted.TLabel').pack(anchor='w')
        self.hotkeys = tk.StringVar(value='全局快捷键：连接后检查')
        ttk.Label(box, textvariable=self.hotkeys, wraplength=470, style='Muted.TLabel').pack(anchor='w')
        self.map_keys = tk.StringVar(value='WASD视角：等待连接；游戏主地图置前时生效。')
        ttk.Label(box, textvariable=self.map_keys, wraplength=470, style='Muted.TLabel').pack(anchor='w')
        self.note = tk.StringVar(value='操作回执自动保存在本机 quick-control-records。')
        self.receipt_label=ttk.Label(box,textvariable=self.note,wraplength=470,style='Receipt.TLabel')
        self.receipt_label.pack(anchor='w',pady=4)
        self.log = None
        if not smoke:
            folder = ROOT / 'quick-control-records'; folder.mkdir(exist_ok=True)
            self.log = (folder / (datetime.now().strftime('%Y%m%d-%H%M%S-') + str(os.getpid()) + '.jsonl')).open('x', encoding='utf8')
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.update_buttons(); root.after(80, self.drain)
        root.after_idle(self.fit_height)
        root.bind('<F5>', lambda e:self.connect())
        if not smoke:
            root.after(250, self.connect)
            root.after(2000, self.heartbeat)

    def toggle_modifications(self):
        self.modifications_open = not self.modifications_open
        if self.modifications_open:
            self.modification_frame.pack(fill='x',before=self.fold_anchor)
        else:
            self.modification_frame.pack_forget()
        self.fold_button.configure(text=('▾' if self.modifications_open else '▸')+' 修改功能／外挂（点击'+('收起' if self.modifications_open else '展开')+'）')
        self.fit_height()

    def fit_height(self):
        self.root.update_idletasks()
        height=max(420,self.root.winfo_reqheight())
        if self.root.winfo_height()!=height:
            self.root.geometry(f'{max(560,self.root.winfo_width())}x{height}')

    def style_panel(self):
        """Classic jade, parchment and brass, with no additional dependencies."""
        font = 'SimSun' if sys.platform=='win32' else 'Songti SC'
        self.root.configure(bg='#173a31')
        style=ttk.Style(self.root);style.theme_use('clam')
        paper='#ede3c5';ink='#29382a';gold='#98702d'
        style.configure('.',font=(font,13),background=paper,foreground=ink)
        style.configure('TFrame',background=paper)
        style.configure('TLabel',background=paper,foreground=ink)
        style.configure('Title.TLabel',font=(font,18,'bold'),foreground='#335440')
        style.configure('Section.TLabel',font=(font,15,'bold'),foreground=gold)
        style.configure('Timer.TLabel',font=(font,15,'bold'),foreground='#675024')
        style.configure('Muted.TLabel',font=(font,10),foreground='#706651')
        style.configure('Hint.TLabel',font=(font,12),foreground='#6a5224')
        style.configure('Receipt.TLabel',font=(font,12,'bold'),foreground='#31543e')
        style.configure('Candidate.TLabel',font=(font,11,'bold'),foreground='#335440',
                        background='#e0d1a6',padding=(8,6),relief='solid',borderwidth=1)
        style.configure('TButton',background='#e0d1a6',foreground=ink,bordercolor='#aa9054',
                        lightcolor='#f7efda',darkcolor='#a68b4d',padding=(8,4),font=(font,11,'bold'))
        style.map('TButton',background=[('pressed','#cbb879'),('active','#f3e6b6'),('disabled','#dfd7c1')],
                  foreground=[('disabled','#8c8575')])
        for name,color in [('Politics','#805c22'),('Cavalry','#28513b'),('Bow','#2d5360'),('Raid','#68422e')]:
            style.configure(name+'.TButton',padding=(8,6),font=(font,13,'bold'),foreground=color)
        style.configure('Politics.TButton',font=(font,11,'bold'),padding=(6,3))
        style.configure('TSeparator',background='#b59b61')
        style.configure('Treeview',background='#f3ecd7',fieldbackground='#f3ecd7',rowheight=28)
        style.configure('Treeview.Heading',font=(font,12,'bold'))

    def clear_previews(self, waiting='等待当前对局'):
        self.previews = {}; self.preview_at = 0
        for policy, button in self.policy_buttons.items():
            button.configure(text=candidate_label(policy, waiting=waiting))
        if getattr(self, 'training_hint', None) is not None:
            self.show_training(None)

    def refresh_previews(self):
        if not self.policy_buttons or not self.ready or self.preview_loading:
            return
        self.preview_loading = True; bound = dict(self.bound); excluded = {r['city_id'] for r in self.pending_targets.values()}
        def worker():
            try:
                with urllib.request.urlopen(STATE_URL, timeout=8) as response:
                    payload = json.load(response)
                try:
                    training = training_operand(payload)
                except (ValueError, KeyError, TypeError):
                    training = None
                self.events.put(dict(kind='candidate_previews', bound=bound,
                                     excluded=list(excluded),previews=probability_previews(payload, bound, excluded),
                                     training=training,
                                     owned=[g['general_id_raw'] for g in payload['state']['entities']['generals']
                                            if type(g.get('owner_raw')) is int and g['owner_raw']!=65535]))
            except Exception as error:
                self.events.put(dict(kind='candidate_preview_error', bound=bound, note=str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def heartbeat(self):
        if self.closed or self.smoke:
            return
        if (self.ready or (self.proc and self.proc.poll() is None)) and not self.marker_loading and time.monotonic()-self.marker_at>=5:
            self.refresh_modification_label()
        if self.ready:
            if self.preview_at and time.monotonic() - self.preview_at > 10:
                self.clear_previews('候选已过期，正在刷新')
            if not self.busy and not self.selecting:
                self.refresh_previews()
                self.send('inspect', background=True)
        elif not self.connecting and time.monotonic() >= self.next_connect:
            self.connect()
        self.root.after(2000, self.heartbeat)

    def refresh_modification_label(self):
        self.marker_loading=True;bound=dict(self.bound)
        def worker():
            try:
                with urllib.request.urlopen(STATE_URL,timeout=8) as response:payload=json.load(response)
                if binding(payload)!=bound:
                    self.events.put(dict(kind='binding_changed',bound=bound,replacement=binding(payload),note='当前游戏实例已改变，正在重新连接'))
                    return
                from replay_modifications import current_label
                text=current_label(payload)
            except (OSError,ValueError,KeyError,TypeError) as error:
                text='修改标记状态等待确认：'+str(error)
            self.events.put(dict(kind='modification_label',bound=bound,note=text))
        threading.Thread(target=worker,daemon=True).start()

    def disconnect(self, note):
        """Stop the bound helper before retrying; never replay game commands."""
        self.ready = False; self.busy = False; self.selecting = False
        self.pending_id = None; self.inspecting_id = None
        self.current_state = {}
        self.clear_previews(); self.timer.set('游戏倒计时：—')
        self.connection_error = note
        self.status.set('等待当前对局，自动重连中…'); self.note.set(note)
        if self.proc and self.proc.poll() is None:
            try: self.write(dict(action='quit'))
            except (OSError, ValueError): pass

    def retire_stale_helper(self, replacement):
        """Only force-stop our helper after source confirms a different game.

        Old-game hooks cannot affect the newly bound instance. Never replay the
        timed-out request, kill the game, or force-stop a helper on the same game.
        """
        proc = self.proc
        force = (isinstance(replacement,dict)
                 and all(k in replacement and k in (self.bound or {}) for k in ('pid','created','image'))
                 and any(self.bound[k] != replacement[k] for k in ('pid','created','image')))
        self.helper_epoch = getattr(self,'helper_epoch',0) + 1
        def worker():
            if proc is not None:
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    if not force:
                        self.events.put(dict(kind='helper_retire_waiting',proc=proc))
                        return
                    proc.terminate()
                    try:proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=3)
                except (OSError,ValueError):pass
            self.events.put(dict(kind='stale_helper_retired',proc=proc))
        threading.Thread(target=worker,daemon=True).start()

    def record(self, event):
        if self.log:
            self.log.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(), **event), ensure_ascii=False)+'\n')
            self.log.flush()

    def officers(self):
        if not self.ready:
            self.note.set('先连接本机游戏，再读取在野将。'); return
        roster=getattr(self,'officer_roster',None)
        if roster and not roster.closed:
            roster.window.lift();roster.refresh();return
        from officer_roster import OfficerRoster
        self.officer_roster=OfficerRoster(self,STATE_URL)

    def key(self, action):
        self.send(action); return 'break'

    def select_policy(self, policy):
        if not self.ready or self.busy or self.selecting:return
        shown=self.previews.get(policy)
        if not shown or shown.get('error'):return
        self.selecting=True;bound=dict(self.bound);excluded={r['city_id'] for r in self.pending_targets.values()};self.update_buttons()
        self.note.set('正在核对概率候选及同城竞争，随后提交原版招揽…')
        def worker():
            try:
                with urllib.request.urlopen(STATE_URL,timeout=8) as response:payload=json.load(response)
                row=probability_candidate(payload,bound,policy,excluded)
                if any(row[k]!=shown[k] for k in ('id','city_id','attributes','pool_signature','prestige')):
                    raise ValueError('候选已变化，请看刷新后的姓名再点。')
                self.events.put(dict(kind='policy_selection',bound=bound,target=row))
            except Exception as error:self.events.put(dict(kind='policy_selection_error',note=str(error)))
        threading.Thread(target=worker,daemon=True).start()

    def recruit_officer(self,shown):
        if not self.ready or self.busy or self.selecting:return
        self.selecting=True;bound=dict(self.bound);self.update_buttons()
        excluded={r['city_id'] for r in self.pending_targets.values()}
        self.note.set('正在核对所选武将及同城竞争，随后提交普通招揽…')
        def worker():
            try:
                from quick_control_model import validate_roster_request
                with urllib.request.urlopen(STATE_URL,timeout=8) as response:payload=json.load(response)
                row=validate_roster_request(payload,bound,{'selection':shown},excluded)
                self.events.put(dict(kind='policy_selection',bound=bound,target=row))
            except Exception as error:self.events.put(dict(kind='policy_selection_error',note=str(error)))
        threading.Thread(target=worker,daemon=True).start()

    def update_buttons(self):
        used=self.current_state.get('orders_used',0)
        prestige=next((r['prestige'] for r in self.previews.values() if not r.get('error') and 'prestige' in r),None)
        self.policy_hint.set(f"采集民望 {prestige if prestige is not None else '—'}；概率优先，同率再比属性；原版结算。" if self.ready else '正在自动等待当前对局。')
        available = self.ready and not self.busy and not self.selecting and not self.current_state.get('effect_pending')
        menu_ready = (self.current_state.get('mode')==2 and self.current_state.get('phase')==1
                      and self.current_state.get('allowance')==1 and not self.current_state.get('modal'))
        extension_ready=False
        extension_reason='正在等待当前对局。' if not self.ready else '正在处理当前操作，请稍候。'
        if available:
            try:
                extension_plan(self.current_state,self.test.get(),self.allow_write.get());extension_ready=True
                extension_reason='内政／军事输入可用，每次 +10 秒（本机计时）。'
            except ValueError as error:extension_reason=str(error)
            except (KeyError,TypeError):extension_reason='计时状态未确认，等待刷新。'
        if getattr(self,'extension_hint',None) is not None:
            self.extension_hint.set('加时：'+extension_reason)
        for action, button in self.buttons.items():
            enabled = available and self.test.get() and (action != 'extend' or self.allow_write.get())
            if action=='focus_unit':
                from quick_unit_focus import require_focus_state
                try:require_focus_state(self.current_state)
                except ValueError:enabled=False
            if action not in ('extend','focus_unit') and used>=3:enabled=False
            if action not in ('extend','focus_unit') and not menu_ready:enabled=False
            if action=='extend' and not extension_ready:enabled=False
            if action in ('alms','infantry','cavalry','bow') and getattr(self,'auto_x3',None) is not None and self.auto_x3.get():enabled=False
            if self.target_pending and action=='recruit':enabled=False
            button.configure(state='normal' if enabled else 'disabled')
        fresh=self.preview_at and time.monotonic()-self.preview_at<=10
        for policy,button in self.policy_buttons.items():
            row=self.previews.get(policy)
            button.configure(state='normal' if available and menu_ready and used<3 and fresh and row and not row.get('error') else 'disabled')
        self.refresh_button.configure(state='normal' if self.ready and not self.busy and not self.selecting else 'disabled')
        self.connect_button.configure(state='disabled' if self.connecting or self.busy or self.selecting else 'normal')
        if getattr(self,'automation_switch',None) is not None:
            self.automation_switch.configure(state='normal')

    def connect(self):
        if self.connecting or self.busy or self.selecting:
            return
        if self.proc and self.proc.poll() is None:
            if self.ready: self.send('inspect', background=True)
            return
        if self.smoke:
            self.note.set('界面验证模式，不连接／输入游戏'); return
        self.connecting = True; self.ready = False; self.update_buttons()
        self.helper_epoch = getattr(self,'helper_epoch',0) + 1
        epoch = self.helper_epoch
        self.next_connect = time.monotonic() + 5
        self.connection_error = None
        self.status.set('正在核对本机游戏实例…')
        def worker():
            def emit(event):
                self.events.put(dict(event,helper_epoch=epoch))
            try:
                with urllib.request.urlopen(STATE_URL, timeout=8) as response:
                    payload = json.load(response)
                bound = binding(payload)
                from replay_modifications import current_label
                try:modification_label=current_label(payload)
                except (OSError,ValueError,KeyError,TypeError):modification_label='修改标记状态等待确认'
                cmd, env = native_command(bound)
                proc = subprocess.Popen(cmd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding='utf8', bufsize=1)
                emit(dict(kind='connected_process', bound=bound, proc=proc,
                                     modification_label=modification_label))
                def errors():
                    for line in proc.stderr:
                        if line.strip(): emit(dict(kind='helper_stderr', note=line.strip()[:500]))
                threading.Thread(target=errors, daemon=True).start()
                for line in proc.stdout:
                    try: emit(json.loads(line))
                    except ValueError: emit(dict(kind='helper_text', note=line.strip()[:500]))
                emit(dict(kind='exit', code=proc.wait()))
            except Exception as error:
                emit(dict(kind='connect_error', note=str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def settings(self):
        if not self.test.get():
            self.allow_write.set(False)
            self.allow_target.set(False)
        event = dict(action='settings', test_enabled=self.test.get(), allow_timer_write=self.allow_write.get(),allow_target_recruit=False,
                     automation_enabled=self.automation.get() if getattr(self,'automation',None) is not None else False)
        self.record(dict(kind='user_settings', **event))
        if self.ready:
            try: self.write(event)
            except Exception as error: self.note.set(str(error))
        self.update_buttons()

    def write(self, request):
        if not self.proc or self.proc.poll() is not None:
            raise ValueError('快捷指令辅助已退出，请重新连接')
        self.proc.stdin.write(json.dumps(request, ensure_ascii=True)+'\n'); self.proc.stdin.flush()

    def send(self, action, details=None, background=False):
        try: require_available_action(action)
        except ValueError as error:
            self.note.set(str(error)); return
        if not self.ready or self.busy or self.selecting:
            return
        if background and (action != 'inspect' or self.inspecting_id is not None):
            return
        if action != 'inspect' and not self.test.get():
            self.note.set('请先勾选「启用本局快捷修改」'); return
        if action == 'extend' and not self.allow_write.get():
            self.note.set('加时尚未启用'); return
        if self.target_pending and action == 'recruit':
            self.note.set('已有招揽尚待结算；可在名册选择其他城池继续招揽。');return
        self.counter += 1
        event = dict(action=action, request_id=self.counter,**(details or {}))
        self.record(dict(kind='automatic_inspect' if background else 'user_request', **event))
        try:
            self.write(event)
            if background:self.inspecting_id = self.counter
            else:
                self.pending_id = self.counter; self.pending_at = time.monotonic()
                self.busy = True; self.note.set('正在执行一次指令…')
        except Exception as error:
            self.note.set(str(error)); self.ready = False
        self.update_buttons()

    def show_training(self, row):
        titles = {'infantry': '步兵', 'cavalry': '骑兵', 'bow': '弓兵'}
        for action, title in titles.items():
            button = self.buttons.get(action)
            if button is None:
                continue
            text = '%s·政治%d' % (title, row['operand']) if row else LABELS[action]
            button.configure(text='%s  %s' % (text, KEYS[action]))
        if row:
            self.training_hint.set('训练政治＝%s %d×3＝%d。施舍按原版随机加值×3，上限200。\n沿用原版费用、次数和训练上限。\n加时、施舍、增强训练使用后标记我方，本局我方行动不用于训练。' % (
                row['name'], row['politics'], row['operand']))
        elif getattr(self, 'training_hint', None) is not None:
            self.training_hint.set('训练政治＝我方所属将最高政治×3。施舍按原版随机加值×3，上限200。\n沿用原版费用、次数和训练上限。\n加时、施舍、增强训练使用后标记我方，本局我方行动不用于训练。')

    def show_state(self, state):
        self.current_state = state
        remaining = state.get('remaining_ms')
        text = '阶段切换中／时间未知' if state.get('timer_known') is False else ('无限制' if remaining is None else f'{max(0,remaining)/1000:.1f} 秒')
        self.timer.set(f'游戏倒计时：{text}（读取值）')
        self.status.set(f'已绑定 {self.bound["source_id"]} · PID {self.bound["pid"]} · 阶段 {state["phase"]} · 已用指令 {state["orders_used"]}/3')

    def drain(self):
        if self.closed:
            return
        while True:
            try: event = self.events.get_nowait()
            except queue.Empty: break
            kind = event.get('kind')
            if event.get('helper_epoch',getattr(self,'helper_epoch',0)) != getattr(self,'helper_epoch',0):
                continue
            if kind == 'connected_process':
                self.proc = event['proc']; self.bound = event['bound']
                self.modification_badge.set(event.get('modification_label') or '本局暂无本程序修改标记；对方行动可保留参考。')
                self.record(dict(kind='bound', bound=self.bound)); continue
            self.record(event)
            if kind in ('candidate_previews', 'candidate_preview_error'):
                self.preview_loading = False
                if self.ready and self.bound == event['bound']:
                    if kind == 'candidate_previews':
                        if set(event['excluded'])!={r['city_id'] for r in self.pending_targets.values()}:
                            self.refresh_previews();continue
                        self.submitted_ids.difference_update(set(event['owned'])-self.pending_targets.keys())
                        self.previews = event['previews']; self.preview_at = time.monotonic()
                        self.show_training(event.get('training'))
                        for policy, row in self.previews.items():
                            self.policy_buttons[policy].configure(text=candidate_label(policy, row))
                    else:
                        self.clear_previews('候选读取失败，正在重试')
                        self.note.set('候选读取暂不可用，自动重试：'+event['note'])
            elif kind == 'policy_selection':
                self.selecting=False;row=event['target']
                if self.bound!=event['bound'] or not self.ready:
                    self.note.set('连接或开关已改变，未提交招揽。');continue
                self.selected_target=row
                self.send('recruit_roster' if row['policy']=='roster' else 'recruit_probability',dict(policy=row['policy'],general_id=row['id'],city_id=row['city_id'],selection=row,
                                               expected_attributes=row['attributes']))
                if self.busy:
                    self.note.set(f'已选 {row["name"]} · {row["city"]} · 统武 {row["blade"]}；正在提交。')
            elif kind == 'policy_selection_error':
                self.selecting=False;self.note.set(event['note']);self.refresh_previews()
            elif kind == 'ready':
                self.ready = True; self.connecting = False
                self.test.set(True);self.allow_write.set(True);self.allow_target.set(True)
                self.auto_x3.set(False)
                self.auto_time.set(False)
                self.show_state(event['state']); self.settings()
                registered = event['hotkeys']
                self.hotkeys.set('Ctrl + Alt + '+'、'.join(KEYS[a] for a in registered)+'（仅游戏置前；Mac用Control+Option）' if registered else '快捷键不可用，仍可点击按钮')
                self.note.set('已连接，点击按钮即可执行。')
                self.refresh_previews()
            elif kind == 'auto_time_status':
                self.auto_time.set(event['enabled']);self.auto_time_status.set(event['note'])
                result=event.get('result') or {}
                if result.get('after'):self.show_state(result['after'])
                if result and result.get('status')!='timer_field_verified':self.note.set(event['note'])
            elif kind == 'automation_status':
                self.automation.set(event['enabled']);self.note.set(event['note'])
                if not event['enabled']:
                    self.map_keys.set('画面移动：WASD已关闭。')
            elif kind in ('auto_x3_status','auto_x3_error','auto_x3_restore_error'):
                self.auto_x3.set(event.get('enabled',False))
                self.auto_status.set(event.get('note','自动×3状态待核对'))
                if kind!='auto_x3_status':self.note.set(event.get('note','自动×3发生错误'))
            elif kind=='auto_x3_operand':
                self.note.set(event['note'])
            elif kind == 'map_keys':
                active=event['active']
                if len(active)==4:
                    self.map_keys.set('画面移动：W上 A左 S下 D右（按住连续移动）')
                elif active:
                    self.map_keys.set('画面移动：'+ '、'.join(k.upper() for k in active)+'可用；其余键被占用')
                else:
                    self.map_keys.set('画面移动：WASD等待游戏主地图置前；输入框／弹窗时暂停'
                                      if self.automation.get() else '画面移动：WASD已关闭。')
            elif kind == 'modification_recorded':
                self.modification_badge.set(event['note'])
                self.marker_at=0
            elif kind == 'binding_changed':
                self.marker_loading=False;self.marker_at=time.monotonic()
                if event.get('bound')==self.bound:
                    self.disconnect(event['note']);self.retire_stale_helper(event.get('replacement'))
            elif kind == 'helper_retire_waiting':
                if self.proc is event['proc']:
                    self.note.set('正在等待辅助程序安全退出；未重发指令。')
            elif kind == 'stale_helper_retired':
                if self.proc is event['proc']:
                    self.proc=None;self.connecting=False;self.next_connect=0
            elif kind == 'modification_label':
                self.marker_loading=False;self.marker_at=time.monotonic()
                if event.get('bound')==self.bound:self.modification_badge.set(event['note'])
            elif kind == 'result':
                result = event['result']
                if event.get('request_id') == self.inspecting_id:
                    self.inspecting_id = None
                if event.get('request_id') == self.pending_id:
                    self.busy = False; self.pending_id = None
                note=result.get('note', '状态已刷新')
                if result.get('status')=='ordinary_recruit_queued':
                    self.target_pending=True
                    if self.selected_target:
                        self.pending_targets[self.selected_target['id']]=dict(self.selected_target)
                        self.submitted_ids.add(self.selected_target['id'])
                        row=self.selected_target
                        note=f'{row["name"]} · {row["city"]} · 统武 {row["blade"]}。'+note
                if event.get('action') != 'inspect':self.note.set(note)
                if result.get('status')=='ordinary_recruit_queued':
                    self.clear_previews('已提交，读取下一名…');self.refresh_previews()
                elif event.get('action')=='inspect' and result.get('status') == 'error':
                    if self.pending_targets:
                        # Do not cancel queued guarantees during a transient
                        # round transition. Retry reads without replaying input.
                        self.current_state={}
                        self.note.set('正在重试读取状态，保留已入队武将：'+note)
                    else:self.disconnect(note)
                if result.get('state'): self.show_state(result['state'])
                elif result.get('after'): self.show_state(result['after'])
            elif kind in ('fatal','connect_error','exit'):
                self.ready = False; self.busy = False; self.connecting = False; self.selecting=False
                self.inspecting_id = None
                self.target_pending=False; self.selected_target=None
                self.pending_targets.clear();self.submitted_ids.clear();self.current_state={}
                self.next_connect = time.monotonic() + 5
                self.clear_previews(); self.timer.set('游戏倒计时：—')
                if event.get('note'):self.connection_error=event['note']
                note=self.connection_error or '辅助程序已退出；游戏未关闭'
                if '当前尚未进入游戏' in note:note+='；进入对局后将自动连接。'
                self.status.set('等待当前对局，自动重连中…'); self.note.set(note)
            elif kind=='ordinary_recruit_round_finished':
                self.pending_targets.clear();self.submitted_ids.clear();self.target_pending=False
                self.note.set(event['note']);self.refresh_previews()
            elif kind in ('target_recruit_settled','target_recruit_failed','target_recruit_disarmed','recruit_restore_error'):
                if kind in ('target_recruit_settled','target_recruit_failed'):
                    self.pending_targets.pop(event['target']['general_id'],None)
                elif kind=='target_recruit_disarmed':self.pending_targets.clear()
                self.target_pending=bool(self.pending_targets)
                self.refresh_previews()
                self.note.set(event.get('note','指定招揽状态改变'))
            elif kind=='recruit_observation_error':
                self.note.set('招揽结果观察失败，结果未知：'+event.get('note','请核对游戏'))
            elif kind in ('effect_command_queued','effect_command_uncommitted','effect_observation_error','effect_restore_error','training_target_settled'):
                self.note.set(event.get('note','训练／施舍状态改变'))
                if kind in ('effect_command_queued','effect_command_uncommitted'):
                    state=dict(event['state'],effect_pending=False);self.show_state(state)
                    if kind=='effect_command_queued' and event.get('action') in ('infantry','cavalry','bow'):
                        self.note.set('训练指令已入队：政治参数'+str(event.get('operand',{}).get('after','未知'))+'；原版结算。')
        if self.busy and time.monotonic() - self.pending_at > 60:
            # Timeout never queues the same action again. Inspect only after a
            # late receipt returns or reopen/rebind after checking the game.
            self.record(dict(kind='receipt_timeout',request_id=self.pending_id,result_unknown=True,no_resend=True))
            self.disconnect('回执超时，结果未知；正在重新核对连接，不会重发指令。')
        self.update_buttons(); self.root.after(80, self.drain)
        self.root.after_idle(self.fit_height)

    def close(self):
        self.closed = True
        if self.proc and self.proc.poll() is None:
            try: self.write(dict(action='quit')); self.proc.stdin.close()
            except (OSError, ValueError): pass
        self.record(dict(kind='panel_closed'))
        if self.log: self.log.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--smoke-ui', action='store_true')
    args = parser.parse_args(); instance = None
    if not args.smoke_ui:
        instance = PanelInstance()
        if not instance.acquire():
            instance.request_focus()
            print('已唤回现有快捷修改面板。')
            return
    try:
        root = tk.Tk(); panel = Panel(root, args.smoke_ui)
        if os.environ.get('SGI_VERIFY_QUICK'):
            def verify():
                Path(os.environ['SGI_VERIFY_QUICK']).write_text(json.dumps(dict(
                    title=root.title(),viewable=bool(root.winfo_viewable()),bound=panel.bound,
                    ready=panel.ready,busy=panel.busy,connecting=panel.connecting,
                    status=panel.status.get(),note=panel.note.get(),
                    reconnect_state=str(panel.connect_button['state']),
                    refresh_state=str(panel.refresh_button['state']),
                    extend_state=str(panel.buttons['extend']['state']),
                    extension_hint=panel.extension_hint.get(),
                    auto_time_label=panel.auto_time_switch.cget('text'),auto_time_enabled=panel.auto_time.get(),
                    auto_time_state=str(panel.auto_time_switch['state']),auto_time_status=panel.auto_time_status.get(),
                    automation_label=panel.automation_switch.cget('text'),automation_enabled=panel.automation.get(),
                    auto_x3_enabled=panel.auto_x3.get(),map_keys=panel.map_keys.get(),
                    timer=panel.timer.get(),
                    helper_pid=panel.proc.pid if panel.proc else None),ensure_ascii=False,indent=2))
            root.after(8000,verify)
        from graceful_shutdown import install as install_shutdown
        install_shutdown(root,panel.close)
        if instance:
            root.after(250, lambda: watch_focus(root, instance))
        if args.smoke_ui:
            root.update()
            root.after(400,root.quit);root.mainloop();root.update_idletasks()
            print(json.dumps(dict(title=root.title(), buttons=list(panel.buttons),
                                 policies=list(panel.policy_buttons),
                                 width=root.winfo_width(), height=root.winfo_height(),
                                 input_disabled=all(str(b['state'])=='disabled' for b in panel.buttons.values()),
                                 candidate_input_disabled=all(str(b['state'])=='disabled' for b in panel.policy_buttons.values()),
                                 receipt_bounds=[panel.receipt_label.winfo_rooty()-root.winfo_rooty(),panel.receipt_label.winfo_height()],
                                 modifications_collapsed=not panel.modification_frame.winfo_ismapped(),
                                 timer_above_roster=panel.buttons['extend'].winfo_y(),
                                 candidates_readonly=[k for k,b in panel.policy_buttons.items() if isinstance(b,ttk.Label)]), ensure_ascii=False))
            root.after(1500, panel.close)
        root.mainloop()
    finally:
        if instance:
            instance.close()


if __name__ == '__main__':
    main()
