"""Searchable military/domestic algorithm book inside 攻略预判."""
import tkinter as tk
from tkinter import ttk
from algorithm_catalog import find_chapters
BG,FG,GOLD,MUTED='#f7f4ea','#302c22','#8e701c','#786e56'
class AlgorithmGuide(tk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,bg=BG);self.app=app;self.current=None;self.rows={}
        tk.Label(self,text='军事与内政 · 算法手册',bg=BG,fg=GOLD,font=(app.face,18,'bold'),anchor='w').pack(fill='x',padx=12,pady=(10,4))
        tk.Label(self,text='按公式、算例和适用条件查阅；已核实分支、实测模型与攻略参考分别标明。',bg=BG,fg=MUTED,anchor='w').pack(fill='x',padx=12,pady=(0,8))
        bar=tk.Frame(self,bg=BG);bar.pack(fill='x',padx=12,pady=4)
        self.category=tk.StringVar(value='全部');self.query=tk.StringVar();self.show_evidence=tk.BooleanVar(value=False)
        ttk.Combobox(bar,textvariable=self.category,values=('全部','军事','内政'),state='readonly',width=8).pack(side='left')
        tk.Label(bar,text='  搜索：',bg=BG,fg=FG).pack(side='left');ttk.Entry(bar,textvariable=self.query,width=24).pack(side='left',fill='x',expand=True)
        ttk.Checkbutton(bar,text='研究依据',variable=self.show_evidence,command=self.render).pack(side='left',padx=8)
        shell=ttk.Panedwindow(self,orient='horizontal');shell.pack(fill='both',expand=True,padx=10,pady=8)
        left=tk.Frame(shell,bg=BG);right=tk.Frame(shell,bg=BG);shell.add(left,weight=1);shell.add(right,weight=3)
        self.tree=ttk.Treeview(left,columns=('level',),show='tree headings',selectmode='browse',height=16)
        self.tree.heading('#0',text='算法目录');self.tree.column('#0',width=250,minwidth=180)
        self.tree.heading('level',text='核实范围');self.tree.column('level',width=170,minwidth=100)
        ys=ttk.Scrollbar(left,orient='vertical',command=self.tree.yview);xs=ttk.Scrollbar(left,orient='horizontal',command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set,xscrollcommand=xs.set);self.tree.grid(row=0,column=0,sticky='nsew');ys.grid(row=0,column=1,sticky='ns');xs.grid(row=1,column=0,sticky='ew');left.rowconfigure(0,weight=1);left.columnconfigure(0,weight=1)
        self.text=tk.Text(right,wrap='word',bg=BG,fg=FG,font=(app.face,12),padx=14,pady=10,relief='flat',width=60)
        scroll=ttk.Scrollbar(right,orient='vertical',command=self.text.yview);self.text.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self.text.pack(fill='both',expand=True)
        for tag,font,fg in (('title',(app.face,17,'bold'),GOLD),('heading',(app.face,13,'bold'),FG),('note',(app.face,11),MUTED)):
            self.text.tag_configure(tag,font=font,foreground=fg)
        self.tree.bind('<<TreeviewSelect>>',self.select)
        self.category.trace_add('write',self.filter);self.query.trace_add('write',self.filter);self.filter()
    def filter(self,*_):
        previous=self.current;self.tree.delete(*self.tree.get_children());self.rows={}
        rows=find_chapters(self.category.get(),self.query.get())
        for group in ('军事','内政'):
            matches=[c for c in rows if c['category']==group]
            if not matches:continue
            self.tree.insert('','end',iid=group,text=f'{group}算法（{len(matches)}）',open=True)
            for i,c in enumerate(matches,1):
                self.rows[c['id']]=c;self.tree.insert(group,'end',iid=c['id'],text=f'{i}. {c["title"]}',values=(c['level'],))
        self.current=previous if previous in self.rows else next(iter(self.rows),None)
        if self.current:self.tree.selection_set(self.current);self.tree.see(self.current)
        self.render()
    def select(self,_=None):
        selected=self.tree.selection()
        if selected and selected[0] in self.rows:self.current=selected[0];self.render()
    def render(self):
        t=self.text;t.configure(state='normal');t.delete('1.0','end');c=self.rows.get(self.current)
        if c:
            t.insert('end',c['title']+'\n\n','title');t.insert('end',c['summary']+'\n\n')
            t.insert('end','核实范围：'+c['level']+'\n\n','note')
            for title,body in c['sections']:
                t.insert('end',title+'\n','heading');t.insert('end',body+'\n\n')
            if self.show_evidence.get():
                t.insert('end','研究依据\n','heading');t.insert('end',c['evidence']+'\n\n','note')
                t.insert('end','原版算术以SANPK 3.5及已核准的生命周期修复版本为范围；旧回放缺字段时不补造。片段核实不代表全部引擎或每次实战结果已验收。\n','note')
        else:t.insert('end','没有匹配的算法；可清空搜索或选择「全部」。')
        t.configure(state='disabled');t.yview_moveto(0)
