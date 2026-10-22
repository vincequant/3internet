"""Battle strategy reference: tutorial evidence separated from tactical inference."""
import tkinter as tk
from tkinter import ttk
import webbrowser
SOURCE='https://sanguoyouxi.vip/xsjc/军事作战.htm'
TOPICS={
'总览与判定': ('怎样判断计谋',
 '教程依据：特殊攻击先经过施术方智力判定；对方有对应防计时，还要经过防守方智力判定。由此不能只看己方智力就给出成功率。步兵可施展火计、落石、混乱、落雷等计谋。',
 '参考顺序：确认兵种和武将技能 → 看目标位置与地形 → 查敌方防计 → 在游戏菜单核对指令是否可用。高智力、合适技能和目标选择值得优先考虑，但不能保证成功。',
 '当前未确认独立的“计谋点数池”。外交点数与战场计谋判定是两套机制；智力不是可直接扣减的法力值。消耗、次数、恢复、行动限制及成功率公式均待游戏和代码对照。'),
'火计':('火计 / 火攻','教程效果：对范围内敌军造成火焰伤害。表列对应防计为反计。','参考：关注敌军是否聚集及对方有没有反计；不要把陷阱火计的地形参数直接套到主动火攻。','范围、伤害、持续时间、地形/天气影响和消耗未核实；菜单是否可用以游戏为准。'),
'落石':('落石','教程将其描述为较强的特殊攻击，适合攻击弓兵；对应防计为反计。','参考：面对弓兵目标可以优先查看落石是否可用，同时核对目标所在位置。','可施放地形、距离、威力与消耗未核实。主动落石与地图落石陷阱不是同一数据入口。'),
'混乱':('混乱','教程效果：使目标陷入混乱而不能行动；对应防计为收拾。','参考：作为控制手段，优先考虑可能立即威胁己方的目标；效果成功后再判断能否集中攻击。','持续回合、解除方式、免疫条件、消耗和成功率未核实，不显示固定控制时长。'),
'落雷':('落雷 / 资料技能“天雷”','教程效果表描述为雷击特殊攻击，不按普通武器兵种区分；对应防计写作“变天”。','参考：需要先确认己方相关技能和菜单可用性，再关注对方是否具备天变/变天相关防计。','不能据此推断必定命中、固定伤害、全屏攻击或无视一切防御；天气条件及费用尚未核实。'),
'引诱':('引诱','教程效果：诱使敌军进入己方所在方格并进行攻击；对应防计为收拾。','参考：可研究与陷阱、阵地配合，但先核对目标是否会移动到预想位置。','有效距离、触发路径、目标限制和消耗未核实；诱敌踩陷阱只是战术设想，不是保证效果。'),
'反计':('反计','教程把反计列为火计、落石的对应防计；防守方技能与智力参与特殊攻击判定。','参考：面对擅长火计/落石的步兵时，具备反计的编成将值得考虑。','未证实“反弹伤害”、必定防住或固定防御概率；不要把防计名称解释成必然反弹。'),
'收拾':('收拾','教程把收拾列为混乱、引诱的对应防计。','参考：重视关键部队的抗控制能力；不能仅凭有技能就当作绝对免疫。','是否还可主动解除异常、消耗、恢复或触发时机尚未核实。'),
'天变':('天变（教程表中写作“变天”）','教程“特殊攻击一览表”把“变天”列在落雷的防计栏；正文及本软件武将资料使用“天变”名称。','参考：目前按防御雷击相关技能理解更有依据。对方具备相关技能时，不应把落雷当作稳定伤害来源。','两种名称的引擎映射和具体触发率仍待核对。不能单凭名称认定可主动改变天气，也不能认定永久免疫落雷。'),
'计谋技能与宝物':('计谋技能、太平要术与外交点数','教程称计谋技能与策反、步兵计谋成功率有关；太平要术记载全体武将计谋成功率加成5%。外交另按政治＋魅力、提案/拒绝加成及卡片点数计算。','参考：将计谋武将的技能、智力及宝物作为分开的判断因素；先核对本局是否真的生效。','5%的加法/乘法口径未验证。现有武将技能来自资料匹配，完整实时技能位、宝物效果和独立计谋点数尚未解析。'),
'怎样配合验证':('一次只改变一个条件','先选一队已有的步兵，最好由会火攻、落石或混乱的武将带领；没有现成部队时，再在你愿意测试的存档中出征一队。','第一步：打开游戏部队详情和特殊攻击菜单，保留兵数、米粮、士气、战斗力、武将及可用指令，告诉我是哪台电脑，先采集。第二步：在完成前样本后，只执行一次你愿意测试的计谋，再采集。恢复或过回合作为另一轮。','不必先战斗或故意损失部队；先确认游戏是否显示计谋点/次数/费用，再决定核算对象。不同操作不要混在一组前后样本。')}
class StrategyReference(tk.Frame):
 def __init__(self,parent,app):
  super().__init__(parent,bg='#f7f4ea');self.topic=tk.StringVar(value='总览与判定')
  bar=tk.Frame(self,bg='#f7f4ea');bar.pack(fill='x',padx=10,pady=8)
  ttk.Combobox(bar,textvariable=self.topic,values=list(TOPICS),state='readonly',width=24).pack(side='left')
  tk.Button(bar,text='查看原始军事教程',command=lambda:webbrowser.open(SOURCE)).pack(side='right')
  from original_sprites import OriginalSprites
  self.art=OriginalSprites(self);self.art_label=tk.Label(self,bg='#f7f4ea');self.art_label.pack(anchor='w',padx=20)
  self.topic.trace_add('write',lambda *_:self.render())
  box=tk.Frame(self,bg='#f7f4ea');box.pack(fill='both',expand=True,padx=10,pady=5)
  self.text=tk.Text(box,wrap='word',bg='#f7f4ea',fg='#302c22',font=(app.face,12),padx=12,pady=10,relief='flat')
  scroll=ttk.Scrollbar(box,orient='vertical',command=self.text.yview);scroll.pack(side='right',fill='y');self.text.pack(side='left',fill='both',expand=True);self.text.configure(yscrollcommand=scroll.set)
  self.text.tag_configure('title',font=(app.face,17,'bold'),foreground='#8e701c');self.text.tag_configure('section',font=(app.face,12,'bold'))
  self.render()
 def render(self):
  file={'火计':'fire.png','落石':'rock.png','落雷':'lightning.png','天变':'lightning.png'}.get(self.topic.get());photo=self.art.named(file,95) if file else None;self.art_label.configure(image=photo or '')
  title,evidence,advice,unknown=TOPICS[self.topic.get()];self.text.config(state='normal');self.text.delete('1.0','end')
  self.text.insert('end',title+'\n\n','title')
  for heading,body in [('已知依据',evidence),('攻略参考',advice),('待验证',unknown)]:
   self.text.insert('end',heading+'\n','section');self.text.insert('end',body+'\n\n')
  self.text.insert('end','来源：三国志联机网·军事作战、外交卡片（2026-09-13核对）。这是资料参考，不是自动施法或实测成功率。');self.text.config(state='disabled');self.text.yview_moveto(0)
