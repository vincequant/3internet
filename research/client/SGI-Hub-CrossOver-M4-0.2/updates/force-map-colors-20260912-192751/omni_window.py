"""全知情报：三国志 Internet 风格的本机小窗口。读取本机8767实时情报API；不写游戏内存，不操作游戏。"""
from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from player_view import player_id, local_projection, comparison_ids
import tkinter as tk
from tkinter import font as tkfont

ROOT = Path(r"D:\Coding\三国志internet")
MATCH = "sgi-e2e-20260912"
LATEST = ROOT / "data" / "omniscient" / MATCH / "latest.json"
PIDFILE = ROOT / "data" / "omniscient" / MATCH / "window.pid"
DRIVER = ROOT / "src" / "sgi_driver"

BG = "#d4d0c0"
DAMASK = "#c8c3ae"
DAMASK_LINE = "#b3ae98"
WELL = "#f7f4ea"
INK = "#2c281c"
GOLD = "#8a6a12"
GOLD_HI = "#c9a227"
MUTED = "#7a7464"
WARN = "#8a3030"
PANEL = "#3a342c"
SCROLL = "#e6d3a6"
BAR_BG = "#c8c4b4"
BAR_GOLD = "#c9a034"
BAR_RED = "#b84838"
BAR_GREEN = "#3f7a3a"
BAR_BLUE = "#3a5e8a"
SELECT = "#6b5420"
TITLE_BG = "#3f3a32"

W, H = 460, 760


def _font_family(root: tk.Tk) -> str:
    families = set(tkfont.families(root))
    for name in ("PingFang SC", "Songti SC", "楷体", "KaiTi", "STKaiti", "SimSun", "宋体", "Microsoft YaHei"):
        if name in families:
            return name
    return "TkDefaultFont"


def load_doc() -> dict | None:
    if not LATEST.exists():
        return None
    return json.loads(LATEST.read_text(encoding="utf-8"))


def age_s(doc: dict | None) -> float | None:
    if not doc or not doc.get("capture_end"):
        return None
    try:
        t = datetime.fromisoformat(doc["capture_end"])
        return (datetime.now(timezone.utc) - t).total_seconds()
    except ValueError:
        return None


def fmt_num(n) -> str:
    if n is None:
        return "未知"
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "未知"
    if n >= 10000:
        return f"{n:,}".replace(",", ",")
    return str(n)


def fmt_wan(n) -> str:
    if n is None:
        return "未知"
    n = int(n)
    if n >= 10000:
        return f"{n/10000:.1f}万".replace(".0万", "万")
    return str(n)


def force_title(f: dict) -> str:
    if f.get("label_from_ui"):
        return str(f["label_from_ui"])
    if f.get("ruler_from_ui"):
        return str(f["ruler_from_ui"]).replace("王", "")
    cities = f.get("cities") or []
    if len(cities) == 1:
        return f"{cities[0]}"
    if cities:
        return f"{cities[0]}"
    oid = f.get("force_slot_id")
    return "无主" if oid is None else f"槽{oid}"


def place_next_to_game(win: tk.Tk):
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    hwnd = user32.FindWindowW("三国志 Internet 网际网络威力加强版", "三国志Internet联机版3.5")
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x, y = 16, 48
    if hwnd:
        rc = wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rc)):
            if rc.right + 8 + W <= sw:
                x, y = rc.right + 8, max(8, rc.top)
            elif rc.left - 8 - W >= 0:
                x, y = rc.left - 8 - W, max(8, rc.top)
            else:
                x, y = max(8, sw - W - 12), max(8, rc.top)
    y = min(y, max(8, sh - H - 40))
    win.geometry(f"{W}x{H}+{x}+{y}")


def intelligence_rows(state, force_id):
    """Join by entity IDs, never by list position; unknown stays unknown."""
    e = state['entities']
    force = next((f for f in e['lords'] if f['force_id'] == force_id), None)
    officers = [g for g in e['generals'] if g['owner_raw'] == force_id]
    cities = [c for c in e['cities_and_barriers'] if c['owner_raw'] == force_id]
    buildings = [b for b in e['production_buildings'] if b['owner_raw'] == force_id]
    rulers = [g for g in e['generals'] if force and g['general_id_raw'] == force['ruler_general_id']]
    capital = next((c for c in e['cities_and_barriers'] if force and c['city_id'] == force['capital_city_id']), None)
    return {'force': force, 'officers': officers, 'cities': cities, 'buildings': buildings,
            'ruler': rulers[0].get('name') if len(rulers) == 1 else None,
            'capital': capital.get('name') if capital else None}


class OmniWindow:
    def __init__(self, root):
        from tkinter import ttk
        import queue
        self.root=root; self.face=_font_family(root); self.doc=None; self.sel=None; self.identity_session=None; self.last_player=None; self.combat_windows=[]
        self.inbox=queue.Queue(maxsize=1); self.stop=threading.Event()
        self.force_iids=[]; self.filter=tk.StringVar(); self.global_filter=tk.StringVar(); self.last_sig=None; self.sorts={}; self.row_records={}; self.rendering_tables=False
        self.city_filter=tk.StringVar(value="全部城市"); self.net_only=tk.BooleanVar(value=True)
        root.title('全知情报'); root.configure(bg=DAMASK); root.resizable(True,True)
        root.minsize(850,620)
        style=ttk.Style(root);style.theme_use('clam')
        style.configure('Treeview',background=WELL,fieldbackground=WELL,foreground=INK,rowheight=27,font=(self.face,11))
        style.configure('Treeview.Heading',background=BG,foreground=GOLD,font=(self.face,11,'bold'))
        style.map('Treeview',background=[('selected',SELECT)],foreground=[('selected','#fff3cf')])
        style.configure('TNotebook',background=DAMASK);style.configure('TNotebook.Tab',padding=(14,7),font=(self.face,11))
        top=tk.Frame(root,bg=PANEL);top.pack(fill='x',padx=10,pady=(10,6))
        tk.Label(top,text='全知情报',bg=PANEL,fg=GOLD_HI,font=(self.face,21,'bold')).pack(side='left',padx=16,pady=8)
        self.status=tk.Label(top,text='连接完整核心情报…',bg=PANEL,fg='#eee3c5',font=(self.face,10));self.status.pack(side='right',padx=12)
        identity_bar=tk.Frame(root,bg=DAMASK);identity_bar.pack(fill='x',padx=12,pady=3)
        self.identity_label=tk.Label(identity_bar,text='我方未确认',bg=DAMASK,fg=WARN,anchor='w');self.identity_label.pack(side='left')
        self.player_choice=tk.StringVar()
        self.player_combo=ttk.Combobox(identity_bar,textvariable=self.player_choice,state='readonly',width=16);self.player_combo.pack(side='left',padx=8)
        tk.Button(identity_bar,text='确认我方势力',command=self.confirm_player,bg=BG).pack(side='left')
        tk.Button(identity_bar,text='读档后重置我方',command=lambda:self.confirm_player(clear=True),bg=BG).pack(side='left',padx=6)
        self.workspace=ttk.Notebook(root);self.workspace.pack(fill='both',expand=True,padx=10)
        self.force_page=tk.Frame(self.workspace,bg=DAMASK);self.global_page=tk.Frame(self.workspace,bg=DAMASK)
        self.workspace.add(self.force_page,text='势力情报');self.workspace.add(self.global_page,text='全局资料 · 武将与在野地图')
        body=tk.Frame(self.force_page,bg=DAMASK);body.pack(fill='both',expand=True)
        tk.Label(self.global_page,text='全地图资料库',bg=DAMASK,fg=GOLD,font=(self.face,18,'bold'),anchor='w').pack(fill='x',padx=12,pady=(10,2))
        tk.Label(self.global_page,text='覆盖所有势力与无归属武将；不受势力列表选择影响。',bg=DAMASK,fg=MUTED,font=(self.face,11),anchor='w').pack(fill='x',padx=12)
        global_search=tk.Frame(self.global_page,bg=DAMASK);global_search.pack(fill='x',padx=12,pady=10)
        tk.Label(global_search,text='查找武将 / 城池 / ID',bg=DAMASK,fg=INK,font=(self.face,11)).pack(side='left')
        tk.Entry(global_search,textvariable=self.global_filter,font=(self.face,11),bg=WELL).pack(side='left',fill='x',expand=True,padx=8)
        self.global_filter.trace_add('write',lambda *_:self.render_detail())
        self.global_book=ttk.Notebook(self.global_page);self.global_book.pack(fill='both',expand=True,padx=10,pady=(0,10))
        left=tk.Frame(body,bg=DAMASK,width=435);left.pack(side='left',fill='y',padx=(0,10));left.pack_propagate(False)
        tk.Label(left,text='势力列表 · 已确认我军置顶',bg=DAMASK,fg=GOLD,font=(self.face,12,'bold')).pack(anchor='w',pady=5)
        self.force_tree=self.tree(left,[('force','势力',65),('gold','核心金',66),('cities','城关',36)])
        style.configure('Force.Treeview',rowheight=56)
        self.force_tree.configure(style='Force.Treeview',show='tree headings',displaycolumns=('gold','cities'))
        self.force_tree.column('#0',width=310,minwidth=310,stretch=False)
        self.force_tree.heading('#0',text='势力颜色 / 势力　　手牌（游戏原图）',command=lambda:self.sort(self.force_tree,'force'))
        from force_card_art import ForceCardArtwork
        self.force_art=ForceCardArtwork(root)
        self.force_tree.bind('<Motion>',self.force_card_hint)
        self.force_tree.bind('<Leave>',lambda _:self.force_hint.config(text='点击势力查看详情；指向卡牌查看名称。'))
        self.force_tree.tag_configure('player',background='#f4df96',foreground='#85291c',font=(self.face,11,'bold'))
        self.force_tree.tag_configure('unknown',foreground=MUTED)
        self.force_tree.bind('<<TreeviewSelect>>',self.choose)
        self.force_hint=tk.Label(left,text='点击势力查看详情；指向卡牌查看名称。',bg=DAMASK,fg=MUTED,font=(self.face,9),justify='left',wraplength=395);self.force_hint.pack(fill='x',pady=5)
        right=tk.Frame(body,bg=DAMASK);right.pack(side='left',fill='both',expand=True)
        self.heading=tk.Label(right,text='选择势力',bg=DAMASK,fg=INK,font=(self.face,18,'bold'),anchor='w');self.heading.pack(fill='x',pady=(4,2))
        self.summary=tk.Label(right,text='',bg=DAMASK,fg=MUTED,font=(self.face,11),anchor='w');self.summary.pack(fill='x')
        card=tk.Frame(right,bg=WELL,bd=2,relief='sunken');card.pack(fill='x',pady=8)
        self.resources=tk.Label(card,text='等待金米与兵种库存',bg=WELL,fg=INK,font=(self.face,14,'bold'),justify='left',anchor='w');self.resources.pack(fill='x',padx=12,pady=(8,4))
        from military_summary import MilitarySummary
        self.military=MilitarySummary(card);self.military.pack(fill='x',padx=6)
        tk.Button(card,text='训练参考收益 / 人才推荐',command=lambda:(self.workspace.select(self.global_page),self.global_book.select(self.decision_panel)),bg=BG).pack(anchor='e',padx=10,pady=2)
        tk.Button(card,text='兵力 / 武将对比与战力说明',command=self.show_combat,bg=BG).pack(anchor='e',padx=10,pady=4)
        self.projection=tk.Label(card,text='',bg=WELL,fg=WARN,font=(self.face,10),justify='left',anchor='w');self.projection.pack(fill='x',padx=12,pady=(0,8))
        tk.Label(right,text='训练预测为范围估计，执行武将/政治修正未确认；非战力增幅。',bg=DAMASK,fg=WARN,font=(self.face,10),anchor='w').pack(fill='x')
        search=tk.Frame(right,bg=DAMASK);search.pack(fill='x',pady=7)
        tk.Label(search,text='筛选名称 / ID / 坐标',bg=DAMASK,fg=INK,font=(self.face,10)).pack(side='left')
        tk.Entry(search,textvariable=self.filter,font=(self.face,11),bg=WELL).pack(side='left',fill='x',expand=True,padx=8)
        self.filter.trace_add('write',lambda *_:self.render_detail())
        self.city_combo=ttk.Combobox(global_search,textvariable=self.city_filter,state='readonly',width=14,values=['全部城市'])
        self.city_combo.pack(side='right');self.city_combo.bind('<<ComboboxSelected>>',lambda _:self.render_detail())
        tk.Checkbutton(right,text='变化页显示本观察周期净变化（取消则看最近逐次差分）',variable=self.net_only,command=self.render_detail,bg=DAMASK,font=(self.face,9)).pack(anchor='w')
        self.book=ttk.Notebook(right);self.book.pack(fill='both',expand=True)
        self.tables={};self.frames={}
        specs={
          'officers':('所属武将',[('id','将 ID',55),('name','姓名',90),('soldiers','兵力',60),('lead','统',40),('war','武',40),('intel','智',40),('pol','政',40),('cha','魅',40),('xy','世界坐标',85)]),
          'cities':('城池关隘',[('name','城关',80),('kind','类别',55),('defense','防御',85),('population','人口',80),('dev','开发',55),('commerce','商业',55),('xy','世界坐标',85)]),
          'buildings':('生产建筑',[('kind','类型',85),('id','ID 候选',70),('xy','世界坐标',85)]),
        }
        specs['all_officers']=('全武将',[('id','将 ID',55),('name','姓名',90),('owner','归属',55),('state','状态',75),('city','所在城',70),('lead','统',40),('war','武',40),('intel','智',40),('pol','政',40),('cha','魅',40)])
        specs['wild']=('在野',[('city','所在城',75),('name','姓名',90),('id','将 ID',55),('lead','统',45),('war','武',45),('intel','智',45),('pol','政',45),('cha','魅',45)])
        specs['field_units']=('出征部队',[('id','部队 ID',60),('kind','兵种',85),('xy','坐标',70),('generals','编成将',160),('soldiers','兵数候选',80),('training','部队训练',85),('combat','基本战力',85)])
        specs['changes']=('变化',[('time','时间 / 基线',140),('name','对象',90),('field','字段',120),('before','变化前',120),('after','变化后',120),('why','判读（非指令事实）',330)])
        for key,(title,cols) in specs.items():
            book=self.global_book if key in ('all_officers','wild') else self.book
            frame=tk.Frame(book,bg=WELL);book.add(frame,text=title);self.frames[key]=frame
            if key=='cards':
                tk.Label(frame,text='每势力 5 个手牌槽 · 独立只读采集，每秒更新 · 持有不代表当前可使用',bg=WELL,fg=MUTED,font=(self.face,10),anchor='w').pack(fill='x',padx=8,pady=8)
            if key=='wild':
                from native_city_map import CityLocator
                self.city_locator=CityLocator(frame);self.city_locator.pack(fill='x',side='top')
            self.tables[key]=self.tree(frame,cols)
        from decision_panel import DecisionPanel
        self.decision_panel=DecisionPanel(self.global_book,self);self.global_book.add(self.decision_panel,text='决策支援 · 收益与人才')
        self.location_window=None;self.object_locator=None
        for key in ('cities','buildings','field_units'):
            self.tables[key].bind('<<TreeviewSelect>>',lambda event,k=key:self.locate_object(k))
        self.tables['wild'].bind('<<TreeviewSelect>>',self.locate_wild)
        self.global_book.select(self.frames['wild'])
        self.workspace.select(self.force_page)
        foot=tk.Frame(root,bg=DAMASK);foot.pack(fill='x',padx=12,pady=7)
        self.coverage=tk.Label(foot,text='部队、训练条、外交关系仍未解析',bg=DAMASK,fg=WARN,font=(self.face,10));self.coverage.pack(side='left')
        tk.Button(foot,text='关闭',command=root.destroy,bg=BG).pack(side='right')
        self.root.bind('<Destroy>',lambda e:self.stop.set() if e.widget is self.root else None)
        threading.Thread(target=self.fetch,daemon=True,name='native-hub-api-reader').start()
        self.root.after(200,self.tick)

    def tree(self,parent,cols):
        from tkinter import ttk
        frame=tk.Frame(parent,bg=WELL);frame.pack(fill='both',expand=True)
        tree=ttk.Treeview(frame,columns=[c[0] for c in cols],show='headings',selectmode='browse')
        sy=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);sx=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
        tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        tree.grid(row=0,column=0,sticky='nsew');sy.grid(row=0,column=1,sticky='ns');sx.grid(row=1,column=0,sticky='ew')
        for key,title,width in cols:
            tree.heading(key,text=title,command=lambda k=key,t=tree:self.sort(t,k))
            tree.column(key,width=width,minwidth=width,stretch=True)
        return tree

    def sort(self,tree,key):
        items=[(tree.set(i,key),i) for i in tree.get_children()]
        def order(pair):
            try:return (0,float(pair[0].replace(',','')))
            except (ValueError,AttributeError):return (1,pair[0])
        old=self.sorts.get(tree);reverse=not old[1] if old and old[0]==key else True
        self.sorts[tree]=(key,reverse);items.sort(key=order,reverse=reverse)
        for pos,(_,iid) in enumerate(items):tree.move(iid,'',pos)
        if tree is self.force_tree and player_id(self.doc) is not None and tree.exists(str(player_id(self.doc))):tree.move(str(player_id(self.doc)),'',0)

    def fetch(self):
        from portable_client import poll
        poll(self)

    def tick(self):
        try:
            p=self.inbox.get_nowait()
            if not p.get('fresh'):
                from portable_client import invalidate_player
                if self.doc:self.doc=invalidate_player(self.doc)
                if p.get('state'):p['state']=invalidate_player(p['state'])
                elif self.doc:self.render()
            if p.get('state'):
                self.doc=p['state'];sig=str(self.doc.get('snapshot_id'))+json.dumps(self.doc['entities'],ensure_ascii=False)+json.dumps(self.doc['current_local_projection'])+json.dumps(self.doc.get('history',{}),ensure_ascii=False)+json.dumps(self.doc.get('player_identity',{}),ensure_ascii=False)
                if sig!=self.last_sig:self.last_sig=sig;self.render()
            from portable_client import status_text
            if p.get('fresh') is not True:
                p['fresh']=False
            text,color=status_text(p,self.doc)
            self.status.config(text=text,fg=color)
        except __import__('queue').Empty:pass
        if not self.stop.is_set():self.root.after(250,self.tick)

    def confirm_player(self,clear=False):
        from tkinter import messagebox
        from portable_client import confirm_player
        if not self.doc:return
        fid=None if clear else self.player_options.get(self.player_choice.get())
        if not clear and fid is None:return
        try:
            confirm_player(self.doc,fid)
        except Exception as error:messagebox.showerror('我方身份未更改',str(error))

    def choose(self,_=None):
        selection=self.force_tree.selection()
        if selection:self.sel=int(selection[0]);self.refresh_force_art();self.render_detail()

    def refresh_force_art(self):
        if not self.doc:return
        from native_city_map import GAME_PALETTE,force_rgb
        for force in self.doc['entities']['lords']:
            fid=force['force_id'];iid=str(fid)
            color=force_rgb(fid) if self.doc['identity']==GAME_PALETTE.get('identity') else (190,190,175)
            if self.force_tree.exists(iid):self.force_tree.item(iid,image=self.force_art.row(force,color,fid==self.sel,player_id(self.doc)))

    def force_card_hint(self,event):
        iid=self.force_tree.identify_row(event.y)
        if not iid or not self.doc:return
        force=next((f for f in self.doc['entities']['lords'] if str(f['force_id'])==iid),None)
        if not force:return
        slots=force.get('hand_cards',{}).get('slots',[])
        self.force_hint.config(text=force['name']+'：'+(' / '.join(r['name'] for r in slots) if slots else '手牌暂不可用'))

    def render(self):
        meta=self.doc.get('player_identity') or {};session=meta.get('session_id');pid=player_id(self.doc)
        if session!=self.identity_session:
            for window in self.combat_windows:
                if window.winfo_exists():window.destroy()
            self.combat_windows=[]
            self.sel=None;self.sorts.clear();self.force_art.rows.clear();self.row_records.clear()
            self.filter.set('');self.last_player=None
        if pid is not None and pid!=self.last_player:self.sel=pid
        self.identity_session=session;self.last_player=pid
        self.player_options={f"{f['name']}（{f['force_id']}）":f['force_id'] for f in self.doc['entities']['lords']}
        self.player_combo.configure(values=list(self.player_options))
        if self.player_choice.get() not in self.player_options:self.player_choice.set('')
        name=next((f['name'] for f in self.doc['entities']['lords'] if f['force_id']==pid),'未确认')
        source={'user_confirmed':'手动确认','screenshot_verified':'截图核对'}.get(meta.get('source'),'未确认')
        self.identity_label.config(text=f"我方：{name} · {source} · 读档后请重置")
        forces=self.doc['entities']['lords']; ids=[str(f['force_id']) for f in forces]
        if self.sel not in [f['force_id'] for f in forces]:self.sel=forces[0]['force_id'] if forces else None
        for iid in self.force_tree.get_children():
            if iid not in ids:self.force_tree.delete(iid)
        for f in sorted(forces,key=lambda f:(f['force_id']!=player_id(self.doc),f['force_id'])):
            iid=str(f['force_id']);data=intelligence_rows(self.doc,f['force_id'])
            vals=(('★' if f['force_id']==player_id(self.doc) else '◆')+(f.get('name') or '?'),fmt_num(f['gold']),len(data['cities']))
            tags=('player',) if f['force_id']==player_id(self.doc) else ('unknown',)
            if self.force_tree.exists(iid):self.force_tree.item(iid,values=vals,tags=tags)
            else:self.force_tree.insert('','end',iid=iid,values=vals,tags=tags)
        if player_id(self.doc) is not None and self.force_tree.exists(str(player_id(self.doc))):self.force_tree.move(str(player_id(self.doc)),'',0)
        if self.sel is not None:self.force_tree.selection_set(str(self.sel))
        self.coverage.config(text=f"已读 {len(forces)}势力 / {len(self.doc['entities']['generals'])}武将；状态/所在地为静态解析，部队待实战验证")
        city_names=sorted(set(c['name'] for c in self.doc['entities']['cities_and_barriers'] if c.get('name')))
        self.city_combo.configure(values=['全部城市']+city_names)
        self.refresh_force_art()
        self.render_detail()

    def show_combat(self):
        if not self.doc:return
        from military_summary import troop_info
        window=tk.Toplevel(self.root);window.title('兵力 / 武将对比 · 不等同伤害或胜率');window.geometry('800x610')
        self.combat_windows=[w for w in self.combat_windows if w.winfo_exists()]+[window]
        text=tk.Text(window,wrap='word',font=('Microsoft YaHei',11),bg=WELL,padx=16,pady=14);text.pack(fill='both',expand=True)
        force_ids=comparison_ids(self.doc,self.sel)
        for fid in force_ids:
            d=intelligence_rows(self.doc,fid);f=d['force']
            text.insert('end',f['name']+' · 当前势力库存\n')
            for key in ('infantry','cavalry','bow'):
                info=troop_info(key,f['armament_raw'][key]);text.insert('end',f"  {info['name']}：{f['troop_stock'][key]:,} 兵，训练 {info['training']} / 100\n")
            officers=sorted(d['officers'],key=lambda g:g['attributes']['lead'],reverse=True)[:3]
            text.insert('end','  统率最高的三名归属武将（不代表已编入同一部队）：\n')
            for g in officers:
                a=g['attributes'];text.insert('end',f"    {g.get('name','?')}：统 {a['lead']} / 武 {a['war']} / 智 {a['intel']}，个人兵力 {g['soldiers']:,}\n")
            text.insert('end','\n')
        text.insert('end','怎样判断优势\n先比较实际交战部队的兵种、可投入兵力和所编武将，再检查训练、地形与其他战斗修正。势力库存不能当成已经出征的兵力，最强三将也不能当作实际阵容。\n\n已确认的显示规则\n0–99 为基础兵种；100–199 为第二级；200–300 为第三级。训练进度取余数，300 显示100。204 是重装步兵、训练4；它不是204点伤害，也不意味着比原值105强约两倍。\n\n当前计算边界\n已找到武将统率读取和编组平均的代码线索，但尚未完成阵容、兵种系数、地形、攻防及伤害随机项的整条公式核验，因此暂不输出总战力或胜率。下一步需要以实际出征部队和战斗前后兵力差验证，才能建立可比较的预期伤害、交换比与胜率。')
        text.config(state='disabled')

    def locate_object(self,key):
        if self.rendering_tables:return
        selection=self.tables[key].selection()
        if not selection:return
        record=self.row_records.get(key,{}).get(selection[0])
        if record is None:return
        if self.location_window is None or not self.location_window.winfo_exists():
            from native_city_map import CityLocator
            self.location_window=tk.Toplevel(self.root);self.location_window.title('全知情报 · 城关 / 建筑 / 部队定位')
            self.location_window.geometry('880x560');self.location_window.minsize(720,420)
            self.object_locator=CityLocator(self.location_window);self.object_locator.pack(fill='both',expand=True)
        self.object_locator.update_state(self.doc)
        kind={'cities':'cities_and_barriers','buildings':'production_buildings','field_units':'field_units'}[key]
        self.object_locator.focus_entity(kind,record)
        self.location_window.deiconify();self.location_window.lift()

    def locate_wild(self,_=None):
        if self.rendering_tables:return
        selection=self.tables['wild'].selection()
        if not selection:return
        officer=self.row_records.get('wild',{}).get(selection[0])
        if officer:self.city_locator.focus_officer(officer)

    def render_detail(self):
        if not self.doc:return
        d=intelligence_rows(self.doc,self.sel);f=d['force']
        if not f:return
        kind='我军' if self.sel==player_id(self.doc) else '其他势力' if player_id(self.doc) is not None else '我方未确认'
        self.heading.config(text=f"{f.get('name') or '?'}　{kind}")
        self.summary.config(text=f"君主：{d['ruler'] or '未解码'}　首都：{d['capital'] or '未解码'}　城关 {len(d['cities'])}　归属武将 {len(d['officers'])}")
        t=f['troop_stock'];a=f['armament_raw']
        self.resources.config(text=f"金 {fmt_num(f['gold'])}　　米 {fmt_num(f['rice'])}　　信望 {f['prestige']}")
        self.military.update_force(f)
        self.military.update_prediction(self.doc,f)
        self.projection.config(text='')
        p=local_projection(self.doc,self.sel)
        if p is not None:
            different=[]
            for key,label in [('gold','金'),('rice','米')]:
                if p.get(key)!=f.get(key):different.append(label+' '+fmt_num(p.get(key)))
            for key,label in [('infantry','步'),('cavalry','骑'),('bow','弓')]:
                v=p.get('training_progress',{}).get(key)
                if v!=f.get('training_progress',{}).get(key):different.append(label+'训练 '+fmt_num(v))
            if different:self.projection.config(text='同一势力操作层与核心层差异：'+' · '.join(different))
        d['cards']=f.get('hand_cards',{}).get('slots',[])
        d['wild']=[g for g in self.doc['entities']['generals'] if g.get('status_code')==1 and g['owner_raw']==65535]
        d['all_officers']=self.doc['entities']['generals']
        d['field_units']=[u for u in self.doc['entities'].get('field_units',[]) if u['owner_raw']==self.sel]
        history=self.doc.get('history',{})
        d['changes']=[c for c in history.get('phase_net_changes' if self.net_only.get() else 'recent_changes',[]) if c.get('owner')==self.sel]
        force_names={f['force_id']:f['name'] for f in self.doc['entities']['lords']}
        generals_by_id={}
        for g in self.doc['entities']['generals']:generals_by_id.setdefault(g['general_id_raw'],[]).append(g)
        titles={'cards':'手牌','officers':'所属将','all_officers':'全武将','cities':'城关','buildings':'建筑','wild':'在野','field_units':'出征部队','changes':'变化'}
        query=self.filter.get().strip().lower();kindmap={'city':'城市','barrier':'关隘','parade_ground':'练兵所','horse_farm':'牧场','bow_studio':'弓工坊'}
        self.city_locator.update_state(self.doc)
        if self.location_window is not None and self.location_window.winfo_exists():self.object_locator.update_state(self.doc)
        self.rendering_tables=True
        for key in self.tables:
            query=(self.global_filter.get() if key in ('all_officers','wild') else self.filter.get()).strip().lower()
            self.row_records[key]={}
            tree=self.tables[key];ys=tree.yview();xs=tree.xview();tree.delete(*tree.get_children());matched=0
            for row_index,r in enumerate(d[key]):
                xy=','.join(map(str,r.get('world_xy_raw',[])))
                if key=='officers':vals=(r['general_id_raw'],r.get('name') or '姓名未解码',fmt_num(r['soldiers']),*[r['attributes'][a] for a in ['lead','war','intel','pol','cha']],xy)
                elif key=='cities':vals=(r.get('name') or '?',kindmap[r['type']],'/'.join(map(str,r['defense'])),fmt_num(r.get('population')),fmt_num(r.get('development')),fmt_num(r.get('commerce')),xy)
                elif key=='buildings':vals=(kindmap[r['type']],r.get('object_id_candidate'),xy)
                elif key in ('wild','all_officers'):
                    if key=='wild' and self.city_filter.get()!='全部城市' and r.get('location_city_name')!=self.city_filter.get():continue
                    attrs=[r['attributes'][a] for a in ['lead','war','intel','pol','cha']]
                    if key=='wild':vals=(r.get('location_city_name') or '城市未解析',r.get('name') or '姓名未解码',r['general_id_raw'],*attrs)
                    else:vals=(r['general_id_raw'],r.get('name') or '姓名未解码',force_names.get(r['owner_raw'],'无归属'),r.get('status_label','未解析'),r.get('location_city_name') or '未解析',*attrs)
                elif key=='cards':vals=(r['slot'],r['name'],r['card_id'],{'known':'已识别','empty':'空槽','unknown':'待识别'}[r['status']])
                elif key=='field_units':
                    gs=[]
                    for gid in r.get('general_ids',[]):
                        if gid is None:continue
                        found=generals_by_id.get(gid,[]);gs.append((found[0].get('name') or '?') if len(found)==1 else f'ID{gid}待核验')
                    vals=(r['unit_id'],r['unit_kind'],xy,' / '.join(gs),fmt_num(r.get('soldiers_candidate')),fmt_num(r.get('training_degree')),fmt_num(r.get('basic_combat_power')))
                else:
                    display=lambda v:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else str(v)
                    vals=(r.get('time',history.get('recording_since',''))[:19],r['name'],r['field'],display(r['before']),display(r['after']),r['interpretation'])
                if query and not any(query in str(v).lower() for v in vals):continue
                tree.insert('','end',iid=str(row_index),values=vals);self.row_records[key][str(row_index)]=r;matched+=1
            tree.yview_moveto(ys[0] if ys else 0);tree.xview_moveto(xs[0] if xs else 0)
            if tree in self.sorts:
                sort_key,reverse=self.sorts[tree]
                def sort_value(iid):
                    val=tree.set(iid,sort_key)
                    try:return (0,int(val.replace(',','')))
                    except ValueError:return (1,val)
                for ix,iid in enumerate(sorted(tree.get_children(),key=sort_value,reverse=reverse)):tree.move(iid,'',ix)
            label=titles[key]+f' ({matched})'
            if key=='cards':label='手牌 · '+(str(f['hand_cards']['occupied_count'])+' 张' if 'hand_cards' in f else '读取不可用')
            if key=='field_units' and not matched:label='部队（未观察到）'
            (self.global_book if key in ('all_officers','wild') else self.book).tab(self.frames[key],text=label)
        self.rendering_tables=False
        self.decision_panel.refresh()


def main():
    root=tk.Tk()
    root.geometry('1060x760+30+40')
    OmniWindow(root)
    root.mainloop()


if __name__ == '__main__':main()
