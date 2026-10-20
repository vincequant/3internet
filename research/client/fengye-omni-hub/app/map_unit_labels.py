"""Shared live map annotations; unknown morale stays unknown."""
from officer_sortie import AMBUSH_INK, unit_has_ambush
from state_history import kind_label
from unit_memory import attack_label
from native_unit_rules import AMBUSH, NAVY, RAID, displays_attack, unit_skill_mask

# Map tags keep 水 / 伏 / 奇. 骑 and 弓 stay off this label.
LABEL_SKILLS = ((NAVY, '水'), (AMBUSH, '伏'), (RAID, '奇'))


def label_skill_text(mask):
    if type(mask) is not int or not 0 <= mask <= 0xffffffff:
        return ''
    return ' '.join(name for bit, name in LABEL_SKILLS if mask & bit)

def unit_label_ink(state,u):
    return AMBUSH_INK if unit_has_ambush(state,u) else '#25271e'

def unit_label(state,u):
 ids=u.get('general_ids',[]);gid=ids[0] if ids else None
 gs=[g for g in state.get('entities',{}).get('generals',[]) if gid is not None and g.get('general_id_raw')==gid]
 general=gs[0].get('name','未知') if len(gs)==1 else '未知'
 attack=attack_label(u)
 kind=kind_label(u.get('unit_kind')) or '部队'
 label=f"{general}(攻:{attack}) - {kind}" if displays_attack(u) else f"{general} - {kind}"
 morale=u.get('morale')
 if type(morale) in (int,float):
  import math
  if math.isfinite(morale):label+=f" · 士气:{morale:g}"
 from unit_special_chance import special_brief
 chance=special_brief(state,u)
 skills=label_skill_text(unit_skill_mask(state,u))
 if skills:
  label+=f' · [{skills}]'
 return label+(f' · {chance}' if chance!='—' else '')

def label_box(canvas,x,y,text,color,anchor='n',tags='unit_label',ink=None):
 tid=canvas.create_text(x,y,text=text,anchor=anchor,fill=ink or '#25271e',font=('Microsoft YaHei',9),tags=tags)
 group=f'unit-label-{tid}'
 canvas.addtag_withtag(group,tid)
 b=canvas.bbox(tid)
 if b:
  rid=canvas.create_rectangle(b[0]-4,b[1]-2,b[2]+4,b[3]+2,fill='#fff9e7',outline=color,width=2,tags=tags);canvas.addtag_withtag(group,rid);canvas.tag_lower(rid,tid)
 return tid

def raise_label(canvas,tid):
 if tid is not None:canvas.tag_raise(f'unit-label-{tid}')
