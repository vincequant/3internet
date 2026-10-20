"""Read-only, source-bound wild officer roster with full-pool probabilities."""
import json
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
import urllib.request

from officer_report import OfficerReport
from quick_control_model import probability_roster, owned_candidates, filter_roster, roster_cell, ROSTER_SKILLS, binding

SORTS={'统武从高到低':'blade','政治从高到低':'politics','录取估算从高到低':'probability',
       '智力从高到低':'intel','特殊成功率从高到低':'special'}
BLADE_SORTS=('统武从高到低','政治从高到低','录取估算从高到低')
MIN_CHANCE={'全部概率':None,'≥25%':.25,'≥50%':.5,'≥75%':.75,'≥90%':.9}
COLUMNS=(('name','武将',90),('city','所在城',72),
         ('politics','政治',55),('intel','智力',55),('special','特殊成功率',100),
         ('lead','统率',55),('war','武力',55),('blade','统武合计',80),
         ('probability','录取估算',100),('city_rank','同城排名',105),
         ('city_top','同城最高',85),('city_success_share','录到人时占比',110),
         ('ride','骑',42),('bow','弓',42),
         ('charge','突',42),('ambush','伏',42),('status','状态',100))
POLITICS_COLUMNS=('name','city','politics','probability','city_rank','city_top','city_success_share')
INTEL_COLUMNS=('name','city','intel','special','probability','city_rank','city_top','city_success_share')
WILD_COLUMNS=tuple(k for k,_,_ in COLUMNS if k not in ('status','intel','special'))
OWNED_COLUMNS=('name','city','status','lead','war','blade','ride','bow','charge','ambush')
BLADE_HINT='统武＝统率＋武力；骑＝骑马，弓＝弓箭，突＝奇袭／突击，伏＝埋伏。'
INTEL_HINT='智力名册只按智力筛选。特殊成功率是该将单独施放火攻、落石、混乱、天雷，附近尚无防计。没有这四项为0%；技能未读到则未知，不写成0。'
INTEL_SORTS=('智力从高到低','特殊成功率从高到低','录取估算从高到低')
WILD_EXPLANATION='同城排名计入全部在野将；第一仅代表本城估算最高，不保证成功。“录到人时占比”是本城成功招到人时录用此将的比例，并非这次成功率。政治不直接进入已核实的招揽门槛。不计同轮变化及其他势力先录走；技能未匹配标为未知。'


class ReportSource:
    """Give the report page a state only after binding(payload) matches this panel."""

    def __init__(self):
        self.doc=None;self.bound=None

    def publish(self,payload,bound):
        current=binding(payload)
        if current!=bound:raise ValueError('报将来自另一游戏实例')
        state=payload.get('state')
        if not isinstance(state,dict):raise ValueError('当前尚未进入游戏')
        self.bound=dict(current);self.doc=state

    def clear(self):
        self.doc=None;self.bound=None


class OfficerRoster:
    def __init__(self,panel,url):
        self.panel=panel;self.url=url;self.rows=[];self.owned_rows=[];self.owned_error='';self.visible={};self.loading=False
        self.bound=None;self.results=queue.Queue();self.closed=False;self.ticket=0;self.updated_at=0
        self.window=tk.Toplevel(panel.root);w=self.window
        w.title('武将名册 · 在野／政治／智力／本营将领／本城报将')
        w.geometry(f'{min(940,w.winfo_screenwidth()-60)}x{min(610,w.winfo_screenheight()-100)}+20+50')
        w.minsize(700,440)
        w.attributes('-topmost',True);w.protocol('WM_DELETE_WINDOW',self.close)
        body=ttk.Frame(w,padding=12);body.pack(fill='both',expand=True)
        self.header=tk.StringVar(value=BLADE_HINT)
        self.header_label=ttk.Label(body,textvariable=self.header);self.header_label.pack(anchor='w')
        modes=ttk.Frame(body);modes.pack(fill='x',pady=(8,0));self.modes=modes
        self.mode=tk.StringVar(value='blade')
        for value,label in (('blade','统武名册'),('politics','政治名册'),('intel','智力名册'),('owned','本营将领名册'),('report','本城报将')):
            ttk.Radiobutton(modes,text=label,value=value,variable=self.mode,command=self.change_mode).pack(side='left',padx=(0,16))
        self.city_first_only=tk.BooleanVar(value=False)
        self.first_check=ttk.Checkbutton(modes,text='只看同城第一（含并列）',variable=self.city_first_only,command=self.render)
        self.first_check.pack(side='left')
        self.min_politics=tk.StringVar(value='110');self.max_politics=tk.StringVar(value='')
        self.politics_controls=ttk.Frame(body)
        ttk.Label(self.politics_controls,text='政治 >').pack(side='left')
        ttk.Entry(self.politics_controls,textvariable=self.min_politics,width=5).pack(side='left',padx=(4,12))
        ttk.Label(self.politics_controls,text='政治 ≤').pack(side='left')
        ttk.Entry(self.politics_controls,textvariable=self.max_politics,width=5).pack(side='left',padx=4)
        ttk.Label(self.politics_controls,text='（上限留空，不设上限；政治名册不限制统武）').pack(side='left',padx=8)
        self.min_intel=tk.StringVar(value='90')
        self.intel_controls=ttk.Frame(body)
        ttk.Label(self.intel_controls,text='智力 >').pack(side='left')
        ttk.Entry(self.intel_controls,textvariable=self.min_intel,width=5).pack(side='left',padx=(4,12))
        ttk.Label(self.intel_controls,text='（默认大于90；留空不限制，不设上限）').pack(side='left',padx=8)
        bar=ttk.Frame(body);bar.pack(fill='x',pady=(8,4));self.bar=bar
        self.sort=tk.StringVar(value='统武从高到低');self.minimum=tk.StringVar(value='全部概率')
        self.search=tk.StringVar();self.skill_vars={k:tk.BooleanVar(value=False) for k in ROSTER_SKILLS}
        self.min_blade=tk.StringVar(value='170')
        for variable,options,width in ((self.sort,BLADE_SORTS,21),(self.minimum,MIN_CHANCE,11)):
            choice=ttk.Combobox(bar,textvariable=variable,values=list(options),state='readonly',width=width)
            choice.pack(side='left',padx=(0,8));choice.bind('<<ComboboxSelected>>',lambda e:self.render())
            if variable is self.sort:self.sort_choice=choice
            else:self.minimum_choice=choice
        ttk.Button(bar,text='刷新列表',command=self.refresh).pack(side='left')
        self.recruit_button=ttk.Button(bar,text='一键招揽选中武将',command=self.recruit,state='disabled')
        self.recruit_button.pack(side='left',padx=8)
        skills=ttk.Frame(body);skills.pack(fill='x',pady=(0,8));self.skills=skills
        self.blade_controls=ttk.Frame(skills);self.blade_controls.pack(side='left')
        ttk.Label(self.blade_controls,text='统武 >').pack(side='left')
        self.blade_down=ttk.Button(self.blade_controls,text='−',width=2,padding=(2,2),
                                   command=lambda:self.step_min_blade(-10))
        self.blade_down.pack(side='left',padx=(4,2))
        ttk.Entry(self.blade_controls,textvariable=self.min_blade,width=5).pack(side='left')
        self.blade_up=ttk.Button(self.blade_controls,text='+',width=2,padding=(2,2),
                                 command=lambda:self.step_min_blade(10))
        self.blade_up.pack(side='left',padx=(2,10))
        self.skill_controls=ttk.Frame(skills);self.skill_controls.pack(side='left')
        ttk.Label(self.skill_controls,text='同时具备：').pack(side='left')
        for key,label in ROSTER_SKILLS.items():
            ttk.Checkbutton(self.skill_controls,text=label,variable=self.skill_vars[key],command=self.render).pack(side='left',padx=(0,8))
        self.search_controls=ttk.Frame(skills);self.search_controls.pack(side='left',fill='x',expand=True)
        ttk.Label(self.search_controls,text='姓名／城池：').pack(side='left')
        ttk.Entry(self.search_controls,textvariable=self.search,width=14).pack(side='left',fill='x',expand=True)
        self.search.trace_add('write',lambda *_:self.render())
        self.min_blade.trace_add('write',lambda *_:self.render())
        for variable in (self.min_politics,self.max_politics,self.min_intel):variable.trace_add('write',lambda *_:self.render())
        table=ttk.Frame(body);table.pack(fill='both',expand=True);self.table=table
        self.tree=ttk.Treeview(table,columns=[c[0] for c in COLUMNS],displaycolumns=WILD_COLUMNS,show='headings',selectmode='browse')
        for key,label,width in COLUMNS:
            self.tree.heading(key,text=label)
            self.tree.column(key,width=width,minwidth=width,anchor='center',stretch=key in ('name','city'))
        for key,sort in (('blade','统武从高到低'),('politics','政治从高到低'),('probability','录取估算从高到低'),
                         ('intel','智力从高到低'),('special','特殊成功率从高到低')):
            self.tree.heading(key,command=lambda s=sort:self.set_sort(s))
        self.tree.grid(row=0,column=0,sticky='nsew');table.rowconfigure(0,weight=1);table.columnconfigure(0,weight=1)
        vertical=ttk.Scrollbar(table,orient='vertical',command=self.tree.yview);vertical.grid(row=0,column=1,sticky='ns')
        horizontal=ttk.Scrollbar(table,orient='horizontal',command=self.tree.xview);horizontal.grid(row=1,column=0,sticky='ew')
        self.tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        self.note=tk.StringVar(value='正在读取本局武将…');self.detail=tk.StringVar(value='选中一行后，一键提交该城普通招揽；不锁定将领。')
        self.note_label=ttk.Label(body,textvariable=self.note,wraplength=880)
        self.note_label.pack(anchor='w',pady=(8,4))
        self.detail_label=ttk.Label(body,textvariable=self.detail,wraplength=880)
        self.detail_label.pack(anchor='w')
        self.receipt_label=ttk.Label(body,textvariable=getattr(panel,'note',tk.StringVar(value='')),wraplength=880,style='Receipt.TLabel')
        self.receipt_label.pack(anchor='w',pady=(4,0))
        self.explanation_label=ttk.Label(body,text=WILD_EXPLANATION,wraplength=880,style='Muted.TLabel')
        self.explanation_label.pack(anchor='w',pady=(6,0))
        self.report_source=ReportSource();self._report_page=False
        self.report_view=OfficerReport(body,self.report_source)
        body.bind('<Configure>',lambda e:(self.note_label.configure(wraplength=max(200,e.width-24)),
                                         self.detail_label.configure(wraplength=max(200,e.width-24)),
                                         self.receipt_label.configure(wraplength=max(200,e.width-24)),
                                         self.explanation_label.configure(wraplength=max(200,e.width-24))))
        self.tree.bind('<<TreeviewSelect>>',self.choose)
        self.refresh();self.poll_id=w.after(100,self.poll);self.auto_id=w.after(5000,self.auto_refresh)

    def set_sort(self,value):
        self.sort.set(value);self.render()

    def step_min_blade(self,delta):
        try:value=int(self.min_blade.get().strip() or '170')
        except ValueError:
            self.render();return
        if not 0<=value<=510:
            self.render();return
        self.min_blade.set(str(max(0,min(510,value+delta))))

    def change_mode(self):
        if self.mode.get()=='report':
            self._show_report_page();return
        self._show_roster_page()
        owned=self.mode.get()=='owned'
        if owned:
            self.first_check.pack_forget();self.minimum_choice.pack_forget();self.recruit_button.pack_forget()
            self.explanation_label.configure(text='仅列当前已确认我方归属的将领；含出阵、负伤等状态，排除在野、未登场及死亡。位置未知保持未知。勾选技能须同时具备；未匹配资料标为未知。此页只读速查，不发送军令。')
        else:
            self.first_check.pack(side='left')
            self.minimum_choice.pack(side='left',after=self.sort_choice,padx=(0,8))
            self.recruit_button.pack(side='left',padx=8)
            self.explanation_label.configure(text=WILD_EXPLANATION)
        if self.mode.get()=='politics':
            self.blade_controls.pack_forget()
            self.skill_controls.pack_forget()
            self.intel_controls.pack_forget()
            self.politics_controls.pack(before=self.tree.master,fill='x',pady=(0,8))
            self.header.set('政治名册：只按政治筛选；录取估算与同城排名仍按完整候选池计算。')
            self.tree.configure(displaycolumns=POLITICS_COLUMNS)
            self.sort_choice.configure(values=('政治从高到低','录取估算从高到低'))
            self.sort.set('政治从高到低')
        elif self.mode.get()=='intel':
            self.blade_controls.pack_forget()
            self.skill_controls.pack_forget()
            self.politics_controls.pack_forget()
            self.intel_controls.pack(before=self.tree.master,fill='x',pady=(0,8))
            self.header.set(INTEL_HINT)
            self.tree.configure(displaycolumns=INTEL_COLUMNS)
            self.sort_choice.configure(values=INTEL_SORTS)
            self.sort.set('智力从高到低')
        else:
            self.politics_controls.pack_forget()
            self.intel_controls.pack_forget()
            self.skill_controls.pack(side='left',before=self.search_controls)
            self.blade_controls.pack(side='left',before=self.skill_controls)
            self.header.set(('本营将领：当前我方归属；' if owned else '')+BLADE_HINT)
            self.tree.configure(displaycolumns=OWNED_COLUMNS if owned else WILD_COLUMNS)
            self.sort_choice.configure(values=('统武从高到低',) if owned else BLADE_SORTS)
            self.sort.set('统武从高到低')
        self.render()

    def _show_report_page(self):
        self.header_label.pack_forget();self.first_check.pack_forget()
        self.politics_controls.pack_forget();self.intel_controls.pack_forget()
        self.bar.pack_forget();self.recruit_button.pack_forget();self.skills.pack_forget();self.table.pack_forget()
        for label in (self.note_label,self.detail_label,self.receipt_label,self.explanation_label):label.pack_forget()
        if not self.report_view.winfo_manager():self.report_view.pack(fill='both',expand=True,pady=(8,0))
        self._report_page=True;self.report_view.refresh();self.update_button()

    def _show_roster_page(self):
        if not self._report_page:return
        self.report_view.pack_forget()
        self.header_label.pack(before=self.modes,anchor='w')
        self.bar.pack(after=self.modes,fill='x',pady=(8,4))
        self.skills.pack(after=self.bar,fill='x',pady=(0,8))
        self.table.pack(after=self.skills,fill='both',expand=True)
        self.note_label.pack(after=self.table,anchor='w',pady=(8,4))
        self.detail_label.pack(after=self.note_label,anchor='w')
        self.receipt_label.pack(after=self.detail_label,anchor='w',pady=(4,0))
        self.explanation_label.pack(after=self.receipt_label,anchor='w',pady=(6,0))
        self._report_page=False

    def _clear_report(self):
        self.report_source.clear();self.report_view.refresh()

    def _publish_report(self,payload,bound):
        if payload is None or not self.panel.ready or self.panel.bound!=bound:self.report_source.clear()
        else:
            try:self.report_source.publish(payload,bound)
            except ValueError:self.report_source.clear()
        self.report_view.refresh()

    def refresh(self):
        if self.closed or self.loading:return
        if not self.panel.ready or not self.panel.bound:
            self.rows=[];self.owned_rows=[];self.owned_error='';self.bound=None;self._clear_report();self.render();self.note.set('等待连接当前游戏；不显示上一局名单。');return
        bound=dict(self.panel.bound);self.ticket+=1;ticket=self.ticket;self.loading=True
        def worker():
            rows=[];owned=[];error=None;owned_error='';accepted=None
            try:
                with urllib.request.urlopen(self.url,timeout=8) as response:payload=json.load(response)
                if binding(payload)!=bound:raise ValueError('武将列表来自另一游戏实例，请重新连接')
                accepted=payload
                try:rows=probability_roster(payload,bound)
                except Exception as exc:rows=[];error=str(exc)
                try:owned=owned_candidates(payload,bound);owned_error=''
                except Exception as exc:owned=[];owned_error=str(exc)
            except Exception as exc:
                rows=[];owned=[];accepted=None;error=str(exc);owned_error=error
            self.results.put((ticket,bound,rows,error,owned,owned_error,accepted))
        threading.Thread(target=worker,daemon=True).start()

    def poll(self):
        if self.closed:return
        if self.bound and (not self.panel.ready or self.panel.bound!=self.bound):
            self.ticket+=1;self.loading=False
            self.rows=[];self.owned_rows=[];self.owned_error='';self.bound=None;self._clear_report();self.render();self.note.set('连接已变化，正在读取当前对局…')
            if self.panel.ready and self.panel.bound:self.refresh()
        try:
            ticket,bound,rows,error,owned,owned_error,accepted=self.results.get_nowait()
        except queue.Empty:
            ticket=None
        if ticket is not None and ticket==self.ticket:
            self.loading=False
            if self.panel.ready and self.panel.bound==bound:
                self.bound=bound;self.rows=rows;self.owned_rows=owned;self.owned_error=owned_error;self.updated_at=time.monotonic()
                self._publish_report(accepted,bound);self.render()
                if error:self.note.set('读取失败，稍后自动重试：'+error)
            else:self.refresh()
        self.update_button()
        self.poll_id=self.window.after(100,self.poll)

    def auto_refresh(self):
        if self.closed:return
        self.refresh();self.auto_id=self.window.after(5000,self.auto_refresh)

    def render(self):
        selected=self.tree.selection();gid=selected[0] if selected else None
        try:
            political=self.mode.get()=='politics';intellectual=self.mode.get()=='intel';owned=self.mode.get()=='owned'
            raw='' if political or intellectual else self.min_blade.get().strip()
            lower=self.min_politics.get().strip() if political else ''
            upper=self.max_politics.get().strip() if political else ''
            intel_lower=self.min_intel.get().strip() if intellectual else ''
            source_rows=self.owned_rows if owned else self.rows
            rows=filter_roster(source_rows,'blade' if owned else SORTS[self.sort.get()],
                             [] if political or intellectual else [k for k,v in self.skill_vars.items() if v.get()],None if owned else MIN_CHANCE[self.minimum.get()],self.search.get(),
                             min_blade=int(raw) if raw else None,
                             min_politics=int(lower) if lower else None,max_politics=int(upper) if upper else None,
                             min_intel=int(intel_lower) if intel_lower else None,
                             city_first_only=False if owned else self.city_first_only.get())
        except ValueError as exc:
            self.visible={};self.tree.delete(*self.tree.get_children())
            self.detail.set('筛选输入无效，未选中武将。')
            self.note.set('政治界限请输入0–255整数，上限须大于下限；留空不限制' if self.mode.get()=='politics'
                          else '智力下限请输入0–255的整数，留空不限制' if self.mode.get()=='intel'
                          else '统武下限请输入0–510的整数，留空不限制');self.update_button();return
        self.tree.delete(*self.tree.get_children());self.visible={str(r['id']):r for r in rows}
        for row in rows:self.tree.insert('','end',iid=str(row['id']),values=[roster_cell(row,k) for k,_,_ in COLUMNS])
        prestige=next((r['prestige'] for r in self.rows if r.get('prestige') is not None),None)
        if owned:
            self.note.set(self.owned_error or f'显示 {len(rows)} / {len(self.owned_rows)} 名本营将领 · 仅当前我方归属 · 统武从高到低 · 每5秒刷新。')
        elif self.mode.get()=='intel':
            self.note.set(f'显示 {len(rows)} / {len(self.rows)} 名在野将 · 采集民望 {prestige if prestige is not None else "—"} · 每5秒刷新；点击智力／特殊／估算列头排序。特殊按该将单独施放、附近尚无防计计算。')
        else:self.note.set(f'显示 {len(rows)} / {len(self.rows)} 名在野将 · 采集民望 {prestige if prestige is not None else "—"} · 每5秒刷新；点击政治／统武／估算列头排序，右侧列可横向滚动。')
        if gid in self.visible:self.tree.selection_set(gid);self.choose()
        else:self.detail.set('本营名单只读速查；勾选骑、弓、突、伏条件须同时具备。' if owned else '选中一行后，一键提交该城普通招揽；不锁定将领。')
        self.update_button()

    def choose(self,event=None):
        ids=self.tree.selection()
        if not ids or ids[0] not in self.visible:return
        row=self.visible[ids[0]];skills='、'.join(row['skills']) if row['skills_matched'] else '未知（资料未匹配）'
        if self.mode.get()=='owned':
            self.detail.set(f'{row["name"]} · {row["city"]} · {row["status"]} · 统率 {row["lead"]}＋武力 {row["war"]}＝统武 {row["blade"]} · 技能：{skills or "无"}')
            self.update_button();return
        if self.mode.get()=='intel':
            spells='、'.join(row.get('special_skills') or []) or ('无这四项' if row.get('special_percent') is not None else '技能未知')
            origin={'native':'本局技能位','website':'资料技能'}.get(row.get('special_source'),'')
            self.detail.set(f'{row["name"]} · {row["city"]} · 智力 {roster_cell(row,"intel")} · 特殊成功率 {roster_cell(row,"special")}（{spells}'+(f'，{origin}' if origin else '')+f'） · 录取估算 {roster_cell(row,"probability")} · 同城 {roster_cell(row,"city_rank")}（{roster_cell(row,"city_top")}）· 录到人时占比 {roster_cell(row,"city_success_share")}'+(' · '+row['probability_reason'] if row.get('probability_reason') else ''))
            self.update_button();return
        combat='' if self.mode.get()=='politics' else f' · 统武 {row["blade"]}'
        skill_detail='' if self.mode.get()=='politics' else f' · 技能：{skills or "无"}'
        self.detail.set(f'{row["name"]} · {row["city"]} · 政治 {row["politics"]}{combat} · 录取估算 {roster_cell(row,"probability")} · 同城 {roster_cell(row,"city_rank")}（{roster_cell(row,"city_top")}）· 录到人时占比 {roster_cell(row,"city_success_share")}{skill_detail}'+(' · '+row['probability_reason'] if row.get('probability_reason') else ''))
        self.update_button()

    def update_button(self):
        ids=self.tree.selection();row=self.visible.get(ids[0]) if ids else None
        p=self.panel;s=getattr(p,'current_state',{})
        pending={r['city_id'] for r in getattr(p,'pending_targets',{}).values()}
        enabled=(self.mode.get() not in ('owned','report') and row and row.get('row_kind')!='owned' and row.get('success_probability') is not None and row['success_probability']>0
                 and p.ready and p.bound==self.bound and time.monotonic()-self.updated_at<=10
                 and not getattr(p,'busy',False) and not getattr(p,'selecting',False)
                 and row['city_id'] not in pending and not s.get('effect_pending')
                 and s.get('mode')==2 and s.get('phase')==1 and s.get('allowance')==1
                 and s.get('orders_used',3)<3 and not s.get('modal') and not s.get('native_dialogs'))
        self.recruit_button.configure(state='normal' if enabled else 'disabled')

    def recruit(self):
        if self.mode.get()=='report':return
        self.update_button()
        if str(self.recruit_button['state'])=='disabled':return
        ids=self.tree.selection()
        if ids:self.panel.recruit_officer(dict(self.visible[ids[0]]))

    def close(self):
        self.closed=True
        for name in ('poll_id','auto_id'):
            token=getattr(self,name,None)
            if token:self.window.after_cancel(token)
        self.window.destroy()
