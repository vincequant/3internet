"""Two phase timelines combining labeled packet and state observations."""
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from officer_reference import hire_command_text, officer_event_text

INFER_TAB = '推测指令'
INFER_NOTE = '完整原始指令流尚未捕获。已解码的封包及本机输入见「原始指令」；下面按状态变化整理，不能当成原始指令，也不能据此判断没有下令。'
INPUT_NOTE = '已捕获的本机原版输入参数；入队／结算未确认。仅覆盖开启自动×3时的训练／施舍，不代表完整指令流。'
COMMAND_NOTE = '封包＋观察合并显示；编号不代表已结算次数。'
OBS_BANNER = '状态变化／推断，非原始指令'
HIRES_BANNER = '录用状态观察，非原始指令'
OBS_EMPTY = '此窗口未观察到相关变化；不代表没有下令'


def compact_action_text(text):
    for note in ('（观测）', '（观察）', '，观测', '，观察', '观测净值：'):
        text = str(text).replace(note, '')
    return text


class QuarterOpsPanel(tk.Frame):
    def __init__(self, parent, app=None, *, hires_only=False):
        super().__init__(parent, bg='#f7f4ea')
        self.app = app
        self.busy = False
        self.hires_only = hires_only
        self.log = None
        self.military_log = None
        self.rows = None
        self.lane_book = None
        self.raw_page = None
        self.input_page = None
        self.input_log = None
        self.civil_page = None
        self.military_page = None
        self.raw_log = None
        self.civil_labels = []
        self.military_labels = []
        self._shown_force = None
        self._paint_sig = None
        self._input_details = ''
        self._expanded_additions = set()
        self.details_window = None
        self.details_log = None
        self.scout_window = None
        self.construction_window = None
        face = getattr(app, 'face', 'PingFang SC') if app is not None else 'PingFang SC'
        hint = '点将看招募将领的属性' if hires_only else '点城名看建设位置，点侦察看范围，点将看属性，双击出征看周边'
        tk.Label(self, text=hint, bg='#f7f4ea', fg='#786e56',
                 anchor='w', font=(face, 11)).pack(fill='x', padx=8, pady=(6, 2))
        if hires_only:
            tk.Label(self, text=HIRES_BANNER, bg='#f7f4ea', fg='#6b5420',
                     anchor='w', font=(face, 11, 'bold')).pack(fill='x', padx=8, pady=(0, 2))
            self.log = self._make_log(self)
        else:
            self.lane_book = ttk.Notebook(self)
            self.lane_book.pack(fill='both', expand=True, padx=8, pady=(0, 8))
            self.input_page = tk.Frame(self.lane_book, bg='#f7f4ea')
            self.civil_page = self.input_page
            self.military_page = tk.Frame(self.lane_book, bg='#f7f4ea')
            self.lane_book.add(self.civil_page, text='内政阶段')
            self.lane_book.add(self.military_page, text='军事阶段')
            for page in (self.civil_page, self.military_page):
                tools = tk.Frame(page, bg='#f7f4ea')
                tools.pack(fill='x', padx=8, pady=(4, 0))
                ttk.Button(tools, text='详情', command=self._show_input_details).pack(side='right')
            self.input_log = self._make_log(self.civil_page)
            self.log = self.input_log
            self.raw_log = self.input_log  # Compatibility for existing diagnostics.
            self.military_log = self._make_log(self.military_page)
            self._view_entities = {}
            self._paint_inputs({},None,0)
            self.lane_book.select(self.civil_page)
        self.rows = self.log

    def _make_log(self, parent):
        shell = tk.Frame(parent, bg='#f7f4ea')
        shell.pack(fill='both', expand=True)
        widget = tk.Text(shell, wrap='word', bg='#f7f4ea', fg='#302c22',
                         font=self._face(11), relief='flat', borderwidth=0,
                         highlightthickness=0, padx=8, pady=6, cursor='arrow',
                         takefocus=False)
        scroll = ttk.Scrollbar(shell, command=widget.yview)
        scroll.pack(side='right', fill='y')
        widget.pack(side='left', fill='both', expand=True)
        widget.configure(yscrollcommand=scroll.set)
        widget.tag_configure('quarter', background='#e8d6a8', foreground='#6b5420', font=self._face(11, 'bold'))
        widget.tag_configure('empty', foreground='#8a8474')
        widget.tag_configure('source', foreground='#6b5420', font=self._face(11, 'bold'))
        widget.tag_configure('action', foreground='#1e3f6e', underline=True)
        widget.tag_configure('cheat', foreground='#b11a1a', font=self._face(10, 'bold'))
        widget.bind('<Key>', lambda _e=None: 'break')
        return widget

    def _write_infer_placeholder(self, widget):
        self._open_log(widget)
        widget.insert('end', INFER_TAB + '\n', 'source')
        widget.insert('end', INFER_NOTE + '\n', 'empty')
        widget.insert('end', OBS_EMPTY + '\n', 'empty')

    def update_force(self, force, state=None):
        self._fill_ops(state, (force or {}).get('force_id'))

    def _face(self, size=10, weight='normal'):
        face = getattr(self.app, 'face', None) if self.app is not None else None
        return (face or 'PingFang SC', size, weight)

    def _open_log(self, widget):
        for name in list(widget.tag_names()):
            if str(name).startswith('command_'):
                widget.tag_delete(name)
        widget.delete('1.0', 'end')

    def _close_log(self, widget, anchor):
        widget.yview_moveto(anchor)

    def _quarter_line(self, widget, label):
        widget.insert('end', str(label or '—') + '\n', 'quarter')

    def _chip(self, frame, text, action=None, kind='plain'):
        if not self.hires_only:
            text = compact_action_text(text)
        # Inline text keeps each quarter compact and wraps without clipping commands.
        tags = [kind]
        if action:
            tag = 'command_' + str(len(frame.tag_names()))
            tags.extend(('action', tag))
            event = '<Double-1>' if kind == 'unit' else '<Button-1>'
            frame.tag_bind(tag, event, lambda _e=None: action())
            frame.tag_bind(tag, '<Enter>', lambda _e=None: frame.configure(cursor='hand2'))
            frame.tag_bind(tag, '<Leave>', lambda _e=None: frame.configure(cursor='arrow'))
        frame.insert('end', str(text), tuple(tags))
        frame.insert('end', '\n' if kind in ('empty', 'slot') else '  ')

    def _fill_ops(self, state, force_id):
        bridge = str(Path(__file__).resolve().parent.parent / 'bridge')
        if bridge not in sys.path:
            sys.path.append(bridge)
        from state_history import calendar_label, hire_quarter_lanes, military_chip_text, split_quarter_lanes
        self.busy = True
        try:
            if self.hires_only:
                self._fill_hires(state, force_id, hire_quarter_lanes, calendar_label)
                return
            lanes = split_quarter_lanes((state or {}).get('history') or {}, force_id, None)
            inputs = (state or {}).get('local_input_evidence') or {}
            commands = (state or {}).get('native_command_evidence') or {}
            generals = ((state or {}).get('entities') or {}).get('generals', [])
            from command_display import command_groups
            groups = command_groups([r for r in commands.get('rows', []) if r.get('actor_force_id') == force_id],
                                    (state or {}).get('history'))
            calendar_sig = tuple((g['lane'], g['calendar']) for g in groups)
            sig = (force_id, False, repr(lanes), repr(inputs), repr(commands), calendar_sig,
                   repr(((state or {}).get('entities') or {}).get('lords') or []),
                   tuple((g.get('general_id_raw'),g.get('name')) for g in generals))
            if sig == self._paint_sig:
                return
            input_anchor = self._anchor(self.input_log, force_id)
            self._shown_force = force_id
            self._paint_sig = sig
            self._view_entities = (state or {}).get('entities') or {}
            self._paint_inputs(inputs,force_id,input_anchor,commands,(state or {}).get('history'),generals)
        finally:
            self.busy = False

    def _paint_inputs(self, evidence, force_id, anchor, commands=None, history=None, generals=()):
        from native_input_evidence import input_line
        from native_command_evidence import command_line
        from command_display import short_command, display_rows
        from action_timeline import timeline_groups, diplomacy_text, sortie_text, observation_text
        entities = getattr(self, '_view_entities', {})
        view_state = {'entities': entities}
        military_anchor = self.military_log.yview()[0]
        body=self.input_log
        from command_effects import retain_effects, effect_text, anomaly_reason, badge_text
        from command_phase_values import retain_phase_values, phase_summaries
        from scout_location import scout, location_text, valid_reference
        from command_construction import construction, valid_construction
        commands=retain_effects(commands or {}, history)
        commands=retain_phase_values(commands, history)
        raw_rows=[r for r in display_rows(commands) if r.get('actor_force_id')==force_id]
        groups = timeline_groups(raw_rows, history, force_id, entities)
        def toggle(key):
            if key in self._expanded_additions:self._expanded_additions.remove(key)
            else:self._expanded_additions.add(key)
            self._paint_inputs(evidence,force_id,body.yview()[0],commands,history,generals)
        for lane, title, body in (('civil', '内政指令', self.input_log), ('military', '军事指令', self.military_log)):
            self._open_log(body)
            body.insert('end',title+'\n','source')
            shown = [group for group in groups if group['lane'] == lane]
            labels=[]
            for group in shown:
                labels.append(group['label'])
                self._quarter_line(body,group['label'])
                added = [e['raw'] for e in group['entries'] if e['raw'] and e['raw'].get('native_type')==20 and e['raw'].get('subtype')==5]
                painted_additions = False
                number = 0
                for entry in group['entries']:
                    row, observed = entry['raw'], entry['observation']
                    if row and row.get('native_type')==20 and row.get('subtype')==5:
                        if painted_additions:continue
                        painted_additions=True
                        number += 1
                        key=(force_id,group['calendar'])
                        opened=key in self._expanded_additions
                        targets=list(dict.fromkeys(item.get('target_raw') for item in added))
                        self._chip(body,f'{number}. '+('▼' if opened else '▶')+f' 加增（{len(targets)}名武将）',
                                   action=lambda key=key:toggle(key),kind='slot')
                        if opened:
                            from command_display import general_name
                            for target in targets:self._chip(body,'    '+general_name(target,generals),kind='slot')
                        continue
                    number += 1
                    if row is None:
                        self._chip(body,f'{number}. '+observation_text(observed, view_state),
                                   action=(lambda it=observed:self.locate_op(it)) if observed.get('target') else None,
                                   kind='unit' if observed.get('field')=='出征' else 'slot')
                        if observed.get('field')=='出征':body.insert('end','\n')
                        continue
                    special=diplomacy_text(row,entities) if row.get('native_type')==19 else None
                    if row.get('native_type')==16:
                        text=observation_text(observed, view_state) if observed else sortie_text(row,entities)
                        self._chip(body,f'{number}. '+text,
                                   action=(lambda it=observed:self.locate_op(it)) if observed else None,kind='unit')
                        body.insert('end','\n')
                        continue
                    text=f'{number}. '+compact_action_text(special or effect_text(row,generals))
                    if scout(row):
                        binding=row.get('display_binding') or commands.get('binding') or {}
                        text=f'{number}. 侦察 '+location_text(row,binding)
                        action=(lambda row=row,binding=binding:self.open_scout(row,binding)) if valid_reference(row,row.get('scout_reference'),binding) else None
                        self._chip(body,text,action=action,kind='slot')
                    elif construction(row) and valid_construction(row,row.get('construction_reference'),row.get('display_binding') or commands.get('binding') or {}):
                        binding=row.get('display_binding') or commands['binding']
                        body.insert('end',f'{number}. '+row['action']+' ')
                        self._chip(body,row['construction_reference']['city']['name'],action=lambda row=row,binding=binding:self.open_construction(row,binding))
                        body.insert('end',compact_action_text(effect_text(row,generals)[len(short_command(row,generals)):])+'\n')
                    elif anomaly_reason(row):
                        body.insert('end',text+'  ');body.insert('end','['+badge_text(row)+']','cheat')
                        body.insert('end','\n')
                    else:self._chip(body,text,kind='slot')
                for entry in group['responses']:
                    self._chip(body,(diplomacy_text(entry['raw'],entities) or '外交回应'),kind='slot')
                if group['automatic_joins']:
                    from command_display import general_name
                    names=[]
                    for entry in group['automatic_joins']:
                        name=general_name(entry['raw']['target_raw'],generals) if entry['raw'] else str(entry['observation'].get('after') or '')
                        if name not in names:names.append(name)
                    self._chip(body,'自动加入：'+'、'.join(names),kind='slot')
                for item in group['notes']:
                    self._chip(body,observation_text(item, view_state),kind='empty')
                packet_rows=[e['raw'] for e in group['entries'] if e['raw']]
                for summary in phase_summaries(packet_rows,commands.get('binding') or {}):
                    self._chip(body,'  '+summary,kind='empty')
                body.insert('end','\n')
            if lane=='civil':self.civil_labels=labels
            else:self.military_labels=labels
            if not shown:self._chip(body,'暂无记录',kind='empty')
            self._close_log(body,anchor if lane=='civil' else military_anchor)
        body=self.input_log
        details = ['原始封包详情', COMMAND_NOTE,
                   '按指令类型分内政／军事。日期仅为首次采样与游戏历史的时间对照，不是下令日期或局次绑定。',
                   '重复观测已合并，执行次数及结算未确认；采样有漏项，未解码类型不由状态变化补造。',
                   '同一采样年季的加增只合并显示，展开列武将；不代表只执行一次。',
                   '接纳仕官按季度自动加入展示，不占回合指令编号；原始封包仍保留。',
                   '侦察中心来自原始封包；城名／归属按同来源对照快照，不是封包自带或下令时刻确认。附近为四邻距离≤5格的唯一最近城，与侦察范围不同。小地图黄色范围为原版四邻4格规则，执行／结果未确认。',
                   '箭头数值为同一短采样间隔的唯一状态对照，非已验证结算；缺失、跨季、多个候选不配对。',
                   '结算期净值来自同一内政输入→处理阶段的内存前后值，同类多笔只显示一次；含耗粮、费用、上限和其他来源，不作为每条指令的收益或外挂判断。录用城名来自同源状态，箭头武将仅配对同城同输入窗口唯一的待录用状态；未观察到结果不等于失败。',
                   '红色外挂标签表示封包参数超出原版保守范围，不指认具体工具。只有观测增幅超单次上限时标疑似外挂；可能漏采连续指令。季节净增不参与判断。', '']
        details.extend(('显示来源：[封包]为原始队列字节；[观察]为状态变化推断，不能当成原始指令；合并显示不改变原始证据。',
                        '出征的攻击为网站公式参考值，训练为部队本级0–100值；冻结于出现时，不能当成实际伤害。',
                        '外交回应、自动加入、部队消失与得失城观察不计入三次内政指令。',
                        '外交使用卡来自flags_raw；cards_raw为随封包携带的手牌，不能当成已使用卡。'))
        for row in reversed(raw_rows):
            details.append(command_line(row))
            if row.get('native_type')==16:details.append('  '+sortie_text(row,entities)+' · 原始安置参数 '+repr(row.get('placement_raw')))
            if row.get('native_type')==19 and row.get('subtype') in (0,1):details.append('  '+diplomacy_text(row,entities))
            binding=row.get('display_binding') or commands.get('binding') or {}
            details.append('  采集来源：'+str(binding.get('source_id')))
            ref=row.get('scout_reference')
            if valid_reference(row,ref,binding):
                details.append('  位置对照：'+location_text(row,binding)+' · '+ref['captured_at']+' · '+ref['snapshot_id'])
            if row.get('state_changes'):details.append('  状态采样对照：'+repr(row['state_changes']))
            if row.get('phase_changes'):details.append('  结算期内存对照：'+repr(row['phase_changes']))
            if row.get('personnel_reference'):details.append('  录用状态对照：'+repr(row['personnel_reference']))
            if row.get('construction_reference'):details.append('  建设城池对照：'+repr(row['construction_reference']))
            if anomaly_reason(row):details.append('  外挂范围异常：'+anomaly_reason(row))
            for key in ('source_file','source_byte_offset','source_line_sha256','raw_sha256','raw_hex'):
                if key in row:
                    details.append(f'  {key}: {row[key]}')
        for group in groups:
            sources=sorted({entry['raw']['display_source'] for entry in group['entries']
                            if entry['raw'] and entry['raw'].get('display_source')})
            if sources:details.append(group['label']+' · 另端补充：'+'、'.join(sources))
            for entry in group['entries']:
                item=entry.get('observation') or {}
                if item:details.append(group['label']+' · '+entry['evidence']+'：'+observation_text(item, view_state))
                if item.get('sortie_archive_reference'):
                    details.append('  出征数值原档案对照：'+repr(item['sortie_archive_reference']))
            for item in group['notes']:
                details.append(group['label']+' · 观察补充：'+observation_text(item, view_state))
        if commands.get('scan_pending'):
            details.append('记录读取中…')
        source_issue={'remote_not_imported':'封包来源尚未接通；目前显示观察补充',
                      'remote_invalid':'远端封包校验失败；目前显示观察补充',
                      'remote_unavailable':'远端封包暂不可用；显示保留记录'}.get(commands.get('status'))
        if source_issue:details.append(source_issue)
        capture=commands.get('capture_status') or {}
        if capture.get('error') or capture.get('phase') in ('waiting','error'):
            details.append('实时采样中断；显示保留记录')
            details.append('实时封包采样暂不可用；上列为已保留的观测。')
        if commands.get('errors') or commands.get('files_limited') or commands.get('omitted_rows'):
            details.append('部分记录未读入')
        if commands.get('unsupported') or commands.get('gaps'):
            details.append(f'全局采样缺口 {commands.get("gaps",0)}；未解码 {commands.get("unsupported",0)}，原始指令不完整')
        details.extend(('', '×3 参数记录', INPUT_NOTE))
        rows=[r for r in evidence.get('rows',[]) if (r.get('scope') or {}).get('force_id')==force_id]
        for row in reversed(rows):
            details.append(input_line(row))
        if not rows:
            details.append('所选势力暂无可核实的本机输入记录；不代表没有下令。')
        if evidence.get('errors') or evidence.get('omitted_rows') or evidence.get('files_limited'):
            details.append('输入记录存在读取限制、漏项或解析错误；当前列表不完整。')
        self._input_details = '\n'.join(details)
        if self.details_window is not None and self.details_window.winfo_exists():
            self._refresh_input_details()
        self._close_log(body,anchor)

    def open_scout(self, row, binding):
        from scout_map import open_scout_map
        if self.scout_window is not None and self.scout_window.winfo_exists():
            self.scout_window.destroy()
        self.scout_window = open_scout_map(self.winfo_toplevel(),row,binding)

    def open_construction(self, row, binding):
        from construction_map import open_construction_map
        if self.construction_window is not None and self.construction_window.winfo_exists():
            self.construction_window.destroy()
        self.construction_window = open_construction_map(self.winfo_toplevel(),row,binding)

    def _show_input_details(self):
        if self.details_window is not None and self.details_window.winfo_exists():
            self.details_window.lift()
            return
        self.details_window = tk.Toplevel(self)
        self.details_window.title('指令行动 · 证据详情')
        self.details_window.geometry('850x600')
        self.details_log = self._make_log(self.details_window)
        self._refresh_input_details()

    def _refresh_input_details(self):
        anchor = self.details_log.yview()[0]
        self._open_log(self.details_log)
        self.details_log.insert('end',self._input_details)
        self._close_log(self.details_log,anchor)

    def _lane_sig(self, lanes):
        rows = []
        for block in lanes or []:
            rows.append((
                block.get('short'),
                tuple((item.get('field'), item.get('line')) for item in (block.get('civil') or [])),
                tuple((item.get('field'), item.get('line')) for item in (block.get('military') or [])),
            ))
        return tuple(rows)

    def _anchor(self, widget, force_id):
        if self._shown_force == force_id and widget is not None:
            try:
                return widget.yview()[0]
            except tk.TclError:
                return 0.0
        return 0.0

    def _civil_seasons(self, lanes, calendar_label):
        """One row per year and season. Empty rounds stay off the civil tab."""
        groups = []
        found = {}
        for block in lanes or []:
            phase = block.get('phase') or {}
            year, season = phase.get('year_u16'), phase.get('season_u16')
            if isinstance(year, int) and isinstance(season, int):
                key = (year, season)
                title = calendar_label(year, season) or (block.get('short') or '—')
            else:
                key = ('row', len(groups))
                title = block.get('short') or '—'
            group = found.get(key)
            if group is None:
                group = {'title': title, 'civil': [], 'military': [], 'hires': []}
                found[key] = group
                groups.append(group)
            group['civil'].extend(block.get('civil') or [])
            group['military'].extend(block.get('military') or [])
            group['hires'].extend(block.get('hires') or [])
        return groups

    def _paint_inferred(self, lanes, anchor, military_chip_text, calendar_label):
        """Inferred commands stay on the first page until a raw stream exists."""
        body = self.raw_log
        self._open_log(body)
        body.insert('end', INFER_TAB + '\n', 'source')
        body.insert('end', INFER_NOTE + '\n', 'empty')
        groups = self._civil_seasons(lanes, calendar_label)
        hire_fields = ('录用', '主动加入')
        shown = False
        for group in reversed(groups):
            civil_ops = group.get('civil') or []
            military_ops = group.get('military') or []
            sorties = [item for item in military_ops if item.get('field') == '出征']
            other_military = [item for item in military_ops if item.get('field') != '出征']
            if not civil_ops and not military_ops:
                continue
            shown = True
            self._quarter_line(body, group.get('title') or '—')
            hires = [item for item in civil_ops if item.get('field') in hire_fields]
            others = [item for item in civil_ops if item.get('field') not in hire_fields]
            recruits = [item for item in hires if self._hire_kind(item) == '募将']
            walked_in = [item for item in hires if self._hire_kind(item) != '募将']
            slots = []
            for item in others:
                for text in self._command_lines(item):
                    slots.append(('line', item, text))
            slots.extend(('recruit', item, None) for item in recruits)
            slots.extend(('sortie', item, None) for item in sorties)
            marks = '①②③④⑤⑥⑦⑧⑨'
            for index, (kind, item, text) in enumerate(slots):
                mark = marks[index] if index < len(marks) else str(index + 1)
                if kind == 'line':
                    self._chip(body, mark + ' ' + text, kind='slot')
                elif kind == 'sortie':
                    self._chip(body, mark + ' ' + military_chip_text(item),
                               lambda it=item: self.locate_op(it), 'unit')
                    body.insert('end', '\n')
                else:
                    self._officer_chip(body, item, mark + ' ')
                    body.insert('end', '\n')
            for item in walked_in:
                self._officer_chip(body, item, '')
                body.insert('end', '\n')
            for item in other_military:
                self._chip(body, military_chip_text(item),
                           lambda it=item: self.locate_op(it), 'unit')
            if other_military:
                body.insert('end', '\n')
            if not slots and not walked_in and not other_military:
                self._chip(body, '—', kind='empty')
        if not shown:
            self._quarter_line(body, '—')
            self._chip(body, OBS_EMPTY, kind='empty')
        self._close_log(body, anchor)

    def _paint_civil(self, lanes, anchor, military_chip_text, calendar_label):
        body = self.log
        self._open_log(body)
        body.insert('end', OBS_BANNER + '\n', 'source')
        self.civil_labels = []
        groups = self._civil_seasons(lanes, calendar_label)
        hire_fields = ('录用', '主动加入')
        shown = False
        for group in reversed(groups):
            civil_ops = group.get('civil') or []
            sorties = [item for item in (group.get('military') or []) if item.get('field') == '出征']
            if not civil_ops and not sorties:
                continue
            shown = True
            label = group.get('title') or '—'
            self._quarter_line(body, label)
            self.civil_labels.append(label)
            hires = [item for item in civil_ops if item.get('field') in hire_fields]
            others = [item for item in civil_ops if item.get('field') not in hire_fields]
            recruits = [item for item in hires if self._hire_kind(item) == '募将']
            walked_in = [item for item in hires if self._hire_kind(item) != '募将']
            slots = []
            for item in others:
                for text in self._command_lines(item):
                    slots.append(('line', item, text))
            slots.extend(('recruit', item, None) for item in recruits)
            slots.extend(('sortie', item, None) for item in sorties)
            marks = '①②③④⑤⑥⑦⑧⑨'
            for index, (kind, item, text) in enumerate(slots):
                mark = marks[index] if index < len(marks) else str(index + 1)
                if kind == 'line':
                    self._chip(body, mark + ' ' + text, kind='slot')
                elif kind == 'sortie':
                    self._chip(body, mark + ' ' + military_chip_text(item),
                               lambda it=item: self.locate_op(it), 'unit')
                    body.insert('end', '\n')
                else:
                    self._officer_chip(body, item, mark + ' ')
                    body.insert('end', '\n')
            for item in walked_in:
                self._officer_chip(body, item, '')
                body.insert('end', '\n')
        if not shown:
            self._quarter_line(body, '—')
            self.civil_labels.append('—')
            self._chip(body, OBS_EMPTY, kind='empty')
        self._close_log(body, anchor)

    def _paint_military(self, lanes, anchor, military_chip_text):
        body = self.military_log
        self._open_log(body)
        body.insert('end', OBS_BANNER + '\n', 'source')
        self.military_labels = []
        if not lanes:
            self._quarter_line(body, '—')
            self.military_labels.append('—')
            self._chip(body, OBS_EMPTY, kind='empty')
        else:
            for block in reversed(lanes):
                label = block.get('short') or '—'
                self._quarter_line(body, label)
                self.military_labels.append(label)
                military_ops = block.get('military') or []
                if not military_ops:
                    self._chip(body, '—', kind='empty')
                else:
                    for item in military_ops:
                        self._chip(body, military_chip_text(item),
                                   lambda it=item: self.locate_op(it), 'unit')
                    body.insert('end', '\n')
        self._close_log(body, anchor)

    def _fill_hires(self, state, force_id, hire_quarter_lanes, calendar_label):
        lanes = hire_quarter_lanes((state or {}).get('history') or {}, force_id)
        sig = (force_id, True, tuple(
            (block.get('short'), tuple((item.get('field'), item.get('line')) for item in (block.get('hires') or [])))
            for block in lanes
        ))
        if sig == self._paint_sig:
            return
        anchor = self._anchor(self.log, force_id)
        self._shown_force = force_id
        self._paint_sig = sig
        body = self.log
        self._open_log(body)
        body.insert('end', HIRES_BANNER + '\n', 'source')
        self.civil_labels = []
        shown = False
        for group in reversed(self._civil_seasons(lanes, calendar_label)):
            hires = group.get('hires') or []
            if not hires:
                continue
            shown = True
            label = group.get('title') or '—'
            self._quarter_line(body, label)
            self.civil_labels.append(label)
            for item in hires:
                self._officer_chip(body, item)
            body.insert('end', '\n')
        if not shown:
            self._quarter_line(body, '—')
            self.civil_labels.append('—')
            self._chip(body, OBS_EMPTY, kind='empty')
        self._close_log(body, anchor)

    def _command_lines(self, item):
        """One new building is one command, even when the ledger stored them on one line."""
        field = str((item or {}).get('field') or '')
        if field.startswith('新建'):
            places = [place for place in (item.get('places') or []) if place]
            label = field[len('新建'):] or '建筑'
            if places:
                return [f'新建{label}：{place}' for place in places]
        return [str(item.get('line') or field or '')]

    def _hire_kind(self, item):
        kind = (item or {}).get('hire_kind')
        if kind in ('募将', '自动加入'):
            return kind
        return '募将' if (item or {}).get('field') == '录用' else '自动加入'

    def _officer_chip(self, body, item, prefix=''):
        record = self.officer_record(item)
        line = str(item.get('line') or '')
        city = record.get('location_city_name')
        if not city and '：' in line:
            city = line.split('：', 1)[-1].strip() or None
        if self._hire_kind(item) == '募将':
            text = hire_command_text(record, city).replace('录用 ', '募将 ', 1) + '（下季到）'
            kind = 'hire'
        else:
            text = officer_event_text(record, city, '主动加入').replace('加入 ', '自动加入 ', 1)
            kind = 'join'
        self._chip(body, prefix + text, lambda it=item: self.open_hire(it), kind)

    def officer_record(self, item):
        state = getattr(self.app, 'doc', None) or {} if self.app is not None else {}
        gid = (item.get('target') or {}).get('general_id') or item.get('general_id')
        name = item.get('after')
        gens = (state.get('entities') or {}).get('generals') or []
        record = None
        if gid is not None:
            hits = [row for row in gens if row.get('general_id_raw') == gid]
            if len(hits) == 1:
                record = hits[0]
        if record is None and name:
            hits = [row for row in gens if row.get('name') == name]
            if len(hits) == 1:
                record = hits[0]
        if record is None:
            record = {'name': name, 'general_id_raw': gid, 'attributes': {}}
        if not record.get('location_city_name') and record.get('location_city_id') is not None:
            cities = (state.get('entities') or {}).get('cities_and_barriers') or []
            city = next((row for row in cities if row.get('city_id') == record.get('location_city_id')), None)
            if city:
                record = {**record, 'location_city_name': city.get('name')}
        return record

    def open_hire(self, item):
        if self.app is None:
            return
        from original_art_panel import open_officer_record
        open_officer_record(self.app, self.officer_record(item))

    def locate_op(self, item=None):
        if self.busy or self.app is None or not item:
            return
        target = item.get('target') or {}
        state = getattr(self.app, 'doc', None) or {}
        entities = state.get('entities') or {}
        if target.get('kind') == 'field_units' and target.get('unit_id') is not None:
            match = [row for row in entities.get('field_units') or [] if row.get('unit_id') == target.get('unit_id')]
            if len(match) == 1:
                self.app.locate_object('force_units', match[0])
                return
        if target.get('kind') == 'cities_and_barriers' and target.get('city_id') is not None:
            match = [row for row in entities.get('cities_and_barriers') or [] if row.get('city_id') == target.get('city_id')]
            if len(match) == 1:
                self.app.locate_object('cities', match[0])
