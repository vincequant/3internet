"""The complete native OmniWindow with an additional Fengye console."""
import json
import queue
import time
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox, filedialog

from omni_window import OmniWindow, DAMASK, PANEL, WELL, INK, GOLD, GOLD_HI, MUTED, WARN, BG
from fengye_source import FengyeSource, feed_items, control_ready, mode_text, validate_control


def wall_text(value):
    if not isinstance(value, (int, float)):
        return '—'
    try:
        return datetime.fromtimestamp(value).strftime('%m-%d %H:%M:%S')
    except (OSError, ValueError, OverflowError):
        return '—'


class FengyeWindow(OmniWindow):
    def __init__(self, root, source=None):
        self.source = source or FengyeSource()
        self.messages = queue.Queue()
        self.jobs = queue.Queue(maxsize=1)
        self.view = self.source.view
        self.feed_filter = tk.StringVar(root, value='全部')
        self.query = tk.StringVar(root)
        self.control_busy = False
        self.cooldown = 0
        self.pending_id = None
        self.pending_run = None
        self.pending_uncertain = False
        self.render_signature = None
        self.render_error = None
        super().__init__(root)
        root.title('風夜 · 全知情報 Hub 0.1.5')
        root.minsize(1120, 700)
        self.version_label.configure(text='風夜 0.1.5')
        top = self.version_label.master
        for w in top.winfo_children():
            if isinstance(w, tk.Label) and w.cget('text') == '全知情报':
                w.configure(text='風夜 · 全知情報')
        self.original_tabs = list(self.workspace.tabs())
        self.fengye_page = tk.Frame(self.workspace, bg=DAMASK)
        self.workspace.insert(0, self.fengye_page, text='風夜情報／操控台')
        self.fengye_book = ttk.Notebook(self.fengye_page)
        self.fengye_book.pack(fill='both', expand=True)
        self._build_intel()
        self._build_console()
        self._build_legacy()
        self._build_decoded()
        self.workspace.select(self.force_page)
        self.query.trace_add('write', lambda *_: self.render_feed())
        self.feed_filter.trace_add('write', lambda *_: self.render_feed())
        self.render_view(self.view)
        threading.Thread(target=self._fetch_fengye, daemon=True, name='fengye-evidence-reader').start()
        self.root.after(250, self._tick_fengye)

    def _page(self, title, index=None):
        page = tk.Frame(self.fengye_book, bg=DAMASK)
        if index is None:
            self.fengye_book.add(page, text=title)
        else:
            self.fengye_book.insert(index, page, text=title)
        return page

    def _text(self, parent, height=5):
        frame = tk.Frame(parent, bg=WELL)
        frame.pack(fill='both', expand=True, padx=8, pady=6)
        w = tk.Text(frame, height=height, bg=WELL, fg=INK, wrap='word', relief='flat',
                    font=(self.face, 11), state='disabled', padx=10, pady=8)
        scroll = ttk.Scrollbar(frame, command=w.yview)
        scroll.pack(side='right', fill='y')
        w.configure(yscrollcommand=scroll.set)
        w.pack(side='left', fill='both', expand=True)
        return w

    @staticmethod
    def _set_text(widget, text):
        if widget.get('1.0', 'end-1c') == text:
            return
        pos = widget.yview()[0]
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', text)
        widget.configure(state='disabled')
        widget.yview_moveto(pos)

    def _box(self, parent, title):
        return tk.LabelFrame(parent, text=title, bg=DAMASK, fg=GOLD, font=(self.face, 12, 'bold'))

    def _build_intel(self):
        self.intel_page = self._page('風夜情報', 0)
        bar = tk.Frame(self.intel_page, bg=PANEL)
        bar.pack(fill='x', padx=8, pady=8)
        self.mode_label = tk.Label(bar, bg=PANEL, fg=GOLD_HI, font=(self.face, 13, 'bold'), anchor='w')
        self.mode_label.pack(side='left', padx=12, pady=8)
        self.run_label = tk.Label(bar, bg=PANEL, fg='#eee3c5', font=(self.face, 11))
        self.run_label.pack(side='right', padx=12)
        self.target_label = tk.Label(self.intel_page, bg=DAMASK, fg=INK, font=(self.face, 11), anchor='w')
        self.target_label.pack(fill='x', padx=12)
        self.counter_label = tk.Label(self.intel_page, bg=DAMASK, fg=MUTED, font=(self.face, 10), anchor='w')
        self.counter_label.pack(fill='x', padx=12, pady=(4, 8))
        panes = tk.PanedWindow(self.intel_page, orient='horizontal', bg=DAMASK, sashwidth=9, bd=0)
        panes.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        left = tk.Frame(panes, bg=DAMASK)
        right = tk.Frame(panes, bg=DAMASK)
        panes.add(left, width=720, minsize=480, stretch='always')
        panes.add(right, width=400, minsize=320, stretch='always')
        tools = tk.Frame(left, bg=DAMASK)
        tools.pack(fill='x', pady=(0, 6))
        self.feed_count = tk.Label(tools, text='情報 0', bg=DAMASK, fg=GOLD, font=(self.face, 12, 'bold'))
        self.feed_count.pack(side='left', padx=4)
        ttk.Combobox(tools, textvariable=self.feed_filter, values=['全部', '訊框', '遊戲數據', '聊天', '控制'],
                     state='readonly', width=9).pack(side='left', padx=8)
        tk.Entry(tools, textvariable=self.query, bg=WELL, fg=INK, width=18).pack(side='left', fill='x', expand=True)
        tk.Button(tools, text='清除', bg=BG, command=lambda: self.query.set('')).pack(side='left', padx=4)
        self.feed_tree = self.tree(left, [('time', '時間', 112), ('kind', '分類', 76),
                                          ('label', '收到的情報', 260), ('detail', '摘要', 310)])
        self.feed_tree.tag_configure('data', foreground='#225e54')
        self.feed_tree.tag_configure('control', foreground='#8a3030')
        self.feed_tree.tag_configure('chat', foreground='#325f86')
        self.feed_tree.bind('<<TreeviewSelect>>', self.select_feed)
        self.feed_detail = self._text(left, 4)
        snapshot_box = self._box(right, '會話席位 · 快照時點')
        snapshot_box.pack(fill='both', expand=True)
        self.snapshot_note = tk.Label(snapshot_box, bg=DAMASK, fg=MUTED, anchor='w', font=(self.face, 10))
        self.snapshot_note.pack(fill='x', padx=8, pady=4)
        self.snapshot_tree = self.tree(snapshot_box, [('seat', '席', 38), ('name', '玩家', 90),
                                                     ('faction', '勢力', 80), ('state', '狀態', 58)])
        self.snapshot_tree.configure(height=8)
        self.snapshot_tree.tag_configure('fengye', background='#f4df96', foreground='#85291c')
        d8_box = self._box(right, '旁聽回執')
        d8_box.pack(fill='x', pady=(8, 0))
        self.d8_label = tk.Label(d8_box, bg=DAMASK, fg=INK, anchor='w', justify='left',
                                 wraplength=350, font=(self.face, 11))
        self.d8_label.pack(fill='x', padx=10, pady=10)
        chat_box = self._box(right, '收到的聊天')
        chat_box.pack(fill='both', expand=True, pady=(8, 0))
        self.chat_log = self._text(chat_box, 5)

    def _build_console(self):
        self.console_page = self._page('風夜操控台', 1)
        self.console_state = tk.Label(self.console_page, text='未就緒', bg=PANEL, fg=GOLD_HI,
                                      font=(self.face, 15, 'bold'), anchor='w', padx=16, pady=12)
        self.console_state.pack(fill='x', padx=12, pady=12)
        tk.Label(self.console_page, text='以風夜的名義發言', bg=DAMASK, fg=GOLD,
                 font=(self.face, 14, 'bold'), anchor='w').pack(fill='x', padx=18)
        self.chat_input = tk.Text(self.console_page, height=4, wrap='word', bg=WELL, fg=INK,
                                  font=(self.face, 13), padx=12, pady=10)
        self.chat_input.pack(fill='x', padx=16, pady=8)
        buttons = tk.Frame(self.console_page, bg=DAMASK)
        buttons.pack(fill='x', padx=16)
        self.chat_button = tk.Button(buttons, text='以風夜發言', bg=BG, fg=INK, command=self.send_chat)
        self.chat_button.pack(side='left')
        self.char_label = tk.Label(buttons, text='0 / 120 字 · GBK', bg=DAMASK, fg=MUTED)
        self.char_label.pack(side='left', padx=12)
        self.stop_button = tk.Button(buttons, text='讓風夜正常退出', bg='#ead4c6', fg=WARN, command=self.send_stop)
        self.stop_button.pack(side='right')
        self.chat_input.bind('<<Modified>>', self.input_changed)
        self.control_result = tk.Label(self.console_page, text='每條請求僅執行一次；失敗或結果未知時不自動重發。',
                                      bg=DAMASK, fg=MUTED, anchor='w', justify='left', wraplength=1050)
        self.control_result.pack(fill='x', padx=18, pady=10)
        panes = tk.PanedWindow(self.console_page, orient='horizontal', bg=DAMASK, sashwidth=9)
        panes.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        chats = self._box(panes, '聊天記錄')
        receipts = self._box(panes, '控制回執')
        panes.add(chats, minsize=360, stretch='always')
        panes.add(receipts, minsize=360, stretch='always')
        self.console_chat = self._text(chats, 10)
        self.control_log = self._text(receipts, 10)

    def _build_legacy(self):
        self.legacy_page = self._page('房間與來源記錄', 2)
        bar = tk.Frame(self.legacy_page, bg=DAMASK)
        bar.pack(fill='x', padx=12, pady=8)
        self.room_button = tk.Button(bar, text='讀取房間列表', bg=BG, command=lambda: self.request_refresh(search=True))
        self.room_button.pack(side='left')
        tk.Button(bar, text='開啟本地回放…', bg=BG, command=self.pick_replay).pack(side='left', padx=8)
        tk.Label(bar, text='查詢不入座；舊記錄保留原時間', bg=DAMASK, fg=MUTED).pack(side='left', padx=8)
        self.legacy_book = ttk.Notebook(self.legacy_page)
        self.legacy_book.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self.legacy_texts = {}
        for key, title in [('rooms', '房間'), ('members', '成員'), ('events', '事件'),
                           ('directory', '線路目錄'), ('source', '會話與採集來源')]:
            page = tk.Frame(self.legacy_book, bg=DAMASK)
            self.legacy_book.add(page, text=title)
            self.legacy_texts[key] = self._text(page, 14)

    def _build_decoded(self):
        self.decoded_page = self._page('風夜指令解讀')
        tk.Label(self.decoded_page, text='使用原版 Hub 的原生封包解析器。發送者 ID 與指令內勢力 ID 分開；未證明結算結果。',
                 bg=DAMASK, fg=MUTED, anchor='w', wraplength=1050).pack(fill='x', padx=12, pady=10)
        self.decoded_tree = self.tree(self.decoded_page, [('time', '收到時間', 140), ('round', '同步輪', 70),
                                     ('sender', '會話發送者', 130), ('force', '勢力 ID', 80),
                                     ('action', '指令', 140), ('value', '參數', 130), ('status', '解析狀態', 250)])
        self.decoded_note = tk.Label(self.decoded_page, text='', bg=DAMASK, fg=MUTED, anchor='w')
        self.decoded_note.pack(fill='x', padx=12, pady=8)

    # Keep the complete original polling/rendering path. Fengye has a separate
    # worker and queue, so an offline probe never replaces a valid world state.
    def _fetch_fengye(self):
        job = ('refresh', False)
        while not self.stop.is_set():
            try:
                op, payload = job
                if op == 'control':
                    try:
                        result = self.source.send(payload)
                    except Exception:
                        result = {'status': 'error', 'error': '控制結果未知；未重試'}
                    self.messages.put(('control', result))
                self.messages.put(('view', self.source.refresh(search=(op == 'refresh' and payload))))
            except Exception:
                self.messages.put(('error', '讀取失敗；保留最後記錄'))
            self.messages.put(('idle', None))
            while not self.stop.is_set():
                try:
                    job = self.jobs.get(timeout=.25)
                    break
                except queue.Empty:
                    if self.stop.wait(.25):
                        return
                    # Poll only while this native window exists.
                    if time.monotonic() - getattr(self, '_last_poll', 0) >= 5:
                        job = ('refresh', False)
                        break
            self._last_poll = time.monotonic()

    def request_refresh(self, search=False):
        if self.stop.is_set():
            return
        try:
            self.jobs.put_nowait(('refresh', search))
        except queue.Full:
            pass

    def _tick_fengye(self):
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == 'view':
                    self.view = value
                    self.render_view(value)
                elif kind == 'control':
                    self.control_busy = False
                    if value.get('status') == 'sent':
                        self.pending_id = value.get('id')
                        self.control_result.configure(text='請求已寫入 · {} · 等待探針回執，尚未確認執行'.format(self.pending_id))
                        if value.get('op') == 'chat':
                            self.chat_input.delete('1.0', 'end')
                    else:
                        self.pending_uncertain = True
                        self.control_result.configure(text='{} · 未自動重試；關閉或重新核實前不再送出。'.format(value.get('error') or value.get('status')))
                elif kind == 'error':
                    self.mode_label.configure(text=value)
                elif kind == 'idle':
                    self.reload_btn.configure(state='normal')
        except queue.Empty:
            pass
        except Exception as error:
            self.render_error = str(error)
            print('fengye-render', error, flush=True)
        self.update_control_state()
        if not self.stop.is_set():
            self.root.after(250, self._tick_fengye)

    def render_view(self, view):
        p = view.get('p34') or {}
        c = p.get('counters') or {}
        host = view.get('host') or {}
        self.mode_label.configure(text=mode_text(view))
        self.run_label.configure(text=p.get('run_name') or '尚無 run')
        self.target_label.configure(text='房間：{}　虛擬 IP：{}　線路：{}　最後資料：{}'.format(
            host.get('session') or '未知', host.get('virtual_ip') or '未知', view.get('line') or '未知', wall_text(c.get('last_packet_wall'))))
        self.counter_label.configure(text='收幀 {}　釋放 {}　錯誤 {}　同步 {} 輪　D8 後 {} 幀'.format(
            c.get('received', '—'), c.get('released', '—'), c.get('errors', '—'), c.get('rounds', '—'), c.get('received_after_d8', '—')))
        signature = json.dumps({k: view.get(k) for k in ('p34', 'host', 'members', 'events', 'directory', 'room_query', 'chain', 'source', 'ghost', 'collector')}, ensure_ascii=False, sort_keys=True)
        if signature != self.render_signature:
            self.render_feed()
            self.snapshot_tree.delete(*self.snapshot_tree.get_children())
            snapshots = p.get('snapshots') or {}
            block = snapshots.get('start') or snapshots.get('initial') or {}
            for r in block.get('rows') or []:
                name = r.get('name') or ('電腦' if r.get('state42') == 2 else '空席' if not r.get('id') else '未命名')
                self.snapshot_tree.insert('', 'end', values=(r.get('i', '—'), name, r.get('faction') or '—', r.get('state42', '—')),
                                          tags=('fengye',) if name in ('风夜', '風夜') else ())
            self.snapshot_note.configure(text='cmd{} · {} · 非即時'.format(block.get('cmd', '—'), wall_text(block.get('observed_at'))))
            chats = (p.get('chat') or {}).get('messages') or []
            chat_text = '\n\n'.join(wall_text(m.get('wall')) + '\n' + str(m.get('text') or '—') for m in chats) or '目前沒有可核實的聊天記錄。'
            self._set_text(self.chat_log, chat_text)
            self._set_text(self.console_chat, chat_text)
            events = (p.get('control') or {}).get('events') or []
            self._set_text(self.control_log, '\n\n'.join('{}　{}\n{}{}{}'.format(
                wall_text(e.get('wall')), e.get('ev') or '', e.get('text') or '',
                ' · rc=' + str(e['rc']) if e.get('rc') is not None else '',
                ' · ' + str(e['reason']) if e.get('reason') else '') for e in reversed(events)) or '尚無控制回執。')
            self.render_legacy(view)
            self.render_decoded(view)
            self.render_signature = signature
        d8 = p.get('d8') or {}
        effect = d8.get('effect') or {}
        row = effect.get('row_present')
        effect_text = '應用行仍在' if row is True else '觀測時應用行已消失' if row is False else '行消隱效果未知'
        w = p.get('window') or {}
        self.d8_label.configure(text='D8：{} · raw_rc={}\n{}\n原回執：{}\n觀察窗結束：{}'.format(
            '已發一次' if d8.get('sent_once') else '未證已發', d8.get('raw_rc', '—'), effect_text,
            wall_text(d8.get('sent_wall')), wall_text(w.get('end_wall'))))
        control = p.get('control') or {}
        last = control.get('last_result') or {}
        if self.pending_id and last.get('id') == self.pending_id:
            self.control_result.configure(text='已收到執行回執 · {} · rc={} · {}'.format(last.get('op'), last.get('rc'), wall_text(last.get('wall'))))
            self.pending_id = None
        if self.pending_run and p.get('run_name') != self.pending_run:
            self.pending_id = None
            self.pending_uncertain = False
            self.control_result.configure(text='已切換 run；先前請求不會重發。')
            self.pending_run = None
        self.update_control_state()

    def render_feed(self):
        if not hasattr(self, 'feed_tree'):
            return
        all_items = feed_items(self.view)
        kind = {'訊框': 'frame', '遊戲數據': 'data', '聊天': 'chat', '控制': 'control'}.get(self.feed_filter.get())
        query = self.query.get().strip().lower()
        items = [r for r in all_items if (not kind or r['kind'] == kind)
                 and (not query or query in (r['label'] + ' ' + r['detail']).lower())]
        selected = self.feed_tree.selection()
        old_key = self.feed_rows.get(selected[0]) if selected and hasattr(self, 'feed_rows') else None
        pos = self.feed_tree.yview()[0]
        self.feed_tree.delete(*self.feed_tree.get_children())
        self.feed_rows = {}
        names = {'frame': '訊框', 'data': '遊戲數據', 'chat': '聊天', 'control': '控制'}
        for i, row in enumerate(items):
            key = str(i)
            self.feed_rows[key] = row
            self.feed_tree.insert('', 'end', iid=key, values=(wall_text(row['wall']), names[row['kind']], row['label'], row['detail'].split('\n')[0]), tags=(row['kind'],))
            if row == old_key:
                self.feed_tree.selection_set(key)
        self.feed_tree.yview_moveto(pos)
        self.feed_count.configure(text='情報 {} / {}'.format(len(items), len(all_items)))
        if not self.feed_tree.selection():
            self._set_text(self.feed_detail, '選取一條情報查看細節。' if items else '此篩選沒有情報；未補入示範內容。')

    def select_feed(self, _=None):
        selected = self.feed_tree.selection()
        if selected:
            r = self.feed_rows.get(selected[0])
            if r:
                self._set_text(self.feed_detail, '{}　{}\n{}'.format(wall_text(r['wall']), r['label'], r['detail']))

    def render_legacy(self, v):
        q = v.get('room_query') or {}
        room_text = '狀態：{}　觀測：{}\n{}\n\n'.format(q.get('status', '未知'), wall_text(q.get('observed_at')), q.get('error') or '房間回覆不證明已開局。')
        room_text += '\n'.join('{}　{}　{}　{}/{}'.format(r.get('name') or '—', r.get('host') or '—', r.get('virtual_ip') or '—', r.get('current', '—'), r.get('maximum', '—')) for r in q.get('rooms') or []) or '尚無房間回覆；不作零房間判斷。'
        self._set_text(self.legacy_texts['rooms'], room_text)
        self._set_text(self.legacy_texts['members'], '主機 DLL 表觀測；與開局快照分開。\n\n' + ('\n'.join(
            '{}　ID {}　重連 {}　失敗 {}'.format(r.get('name') or '—', r.get('id', '—'), r.get('reconnecting', '—'), r.get('failed', '—')) for r in v.get('members') or []) or '尚無成員觀測。'))
        self._set_text(self.legacy_texts['events'], '\n'.join('{}　{}　{}'.format(wall_text(e.get('wall')), e.get('ev') or '', e.get('label') or '') for e in reversed(v.get('events') or [])) or '尚無事件。')
        directory = v.get('directory') or {}
        self._set_text(self.legacy_texts['directory'], '歷史目錄 · {}\n\n'.format(wall_text(directory.get('observed_at'))) + '\n'.join(
            '{}　{}:{}'.format(r.get('name') or '—', r.get('server') or '未知', r.get('port', '—')) for r in directory.get('lines') or []))
        # Render only public fields, never stringify raw backend dictionaries.
        source = v.get('source') or {}
        collector = v.get('collector') or {}
        ghost = v.get('ghost') or {}
        self._set_text(self.legacy_texts['source'], '模式：{}\nrun：{}\n來源觀測：{}\n採集：{}\n風夜：{}\n\n進程鏈\n{}\n\n僅讀風夜探針既有記錄；未啟動記憶體採集橋。'.format(
            mode_text(v), source.get('run_name') or '未知', wall_text(source.get('observed_at')),
            collector.get('mode') or '未知', ghost.get('state') or '未知',
            '\n'.join('{} · PID {}'.format(r.get('role') or '未知', r.get('pid', '—')) for r in v.get('chain') or []) or '未取得'))

    def input_changed(self, _=None):
        if not self.chat_input.edit_modified():
            return
        self.chat_input.edit_modified(False)
        text = self.chat_input.get('1.0', 'end-1c')
        try:
            text.encode('gbk')
            valid = len(text) <= 120
            suffix = 'GBK' if valid else '超過字數上限'
        except UnicodeEncodeError:
            valid = False
            suffix = '含 GBK 不支援字元'
        self.char_label.configure(text='{} / 120 字 · {}'.format(len(text), suffix), fg=MUTED if valid else WARN)
        self.update_control_state()

    def update_control_state(self):
        if not hasattr(self, 'console_state'):
            return
        ready = control_ready(self.view)
        p = self.view.get('p34') or {}
        pending = self.pending_id or (p.get('control') or {}).get('pending')
        enabled = ready and not self.control_busy and not pending and not self.pending_uncertain and time.monotonic() >= self.cooldown
        self.console_state.configure(text='就緒 · 風夜探針在線' if ready else '未就緒 · 回放／離線時不能操控')
        try:
            validate_control({'op': 'chat', 'text': self.chat_input.get('1.0', 'end-1c')})
            text_valid = True
        except ValueError:
            text_valid = False
        self.chat_button.configure(state='normal' if enabled and text_valid else 'disabled')
        self.stop_button.configure(state='normal' if enabled else 'disabled')
        transport = self.view.get('transport') or {}
        self.room_button.configure(state='normal' if transport.get('status') == 'online' and not self.source.sources.source_file else 'disabled')

    def send_control(self, payload):
        if not control_ready(self.view) or self.control_busy or self.pending_id or self.pending_uncertain or (self.view.get('p34') or {}).get('control', {}).get('pending') or time.monotonic() < self.cooldown:
            return
        try:
            payload = validate_control(payload)
        except ValueError as error:
            messagebox.showerror('無法送出', str(error), parent=self.root)
            return
        try:
            self.jobs.put_nowait(('control', payload))
        except queue.Full:
            self.control_result.configure(text='正在讀取狀態；本次未送出，請稍候。')
            return
        self.control_busy = True
        self.pending_run = (self.view.get('p34') or {}).get('run_name')
        self.cooldown = time.monotonic() + 2
        self.control_result.configure(text='送出單次請求中；不會自動重試。')
        self.update_control_state()

    def send_chat(self):
        self.send_control({'op': 'chat', 'text': self.chat_input.get('1.0', 'end-1c')})

    def send_stop(self):
        if not control_ready(self.view) or self.control_busy:
            return
        if messagebox.askokcancel('讓風夜正常退出', '確認讓風夜退出自己的會話？\n退出後需另行啟動探針。', parent=self.root):
            self.send_control({'op': 'stop'})

    def pick_replay(self):
        path = filedialog.askopenfilename(parent=self.root, title='開啟風夜觀測 JSON', filetypes=[('JSON', '*.json')])
        if path:
            # Open a separate viewer; do not replace a source under an in-flight
            # control request or lose the original view's pending receipt.
            import subprocess, sys
            from pathlib import Path
            subprocess.Popen([sys.executable, str(Path(__file__).with_name('run.py')), '--replay', path])

    def render_decoded(self, view):
        from fengye_source import decoded_commands
        self.decoded_tree.delete(*self.decoded_tree.get_children())
        rows = decoded_commands(view)
        for r in rows:
            self.decoded_tree.insert('', 'end', values=(wall_text(r.get('wall')), r.get('round', '—'),
                r.get('sender', '—'), r.get('actor_force_id', '—'), r.get('action', '未解碼'),
                r.get('value_raw', '—'), r.get('error') or '原始指令已解讀／結算未確認'))
        self.decoded_note.configure(text='{} 條同步記錄；使用原版解析器，不由指令推造兵力或資源。'.format(len(rows)))
