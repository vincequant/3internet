"""Shared live map annotations; unknown morale stays unknown."""
def unit_label(state,u):
 ids=u.get('general_ids',[]);gid=ids[0] if ids else None
 gs=[g for g in state.get('entities',{}).get('generals',[]) if gid is not None and g.get('general_id_raw')==gid]
 general=gs[0].get('name','未知') if len(gs)==1 else '未知'
 owner=next((f.get('name','未知') for f in state.get('entities',{}).get('lords',[]) if f.get('force_id')==u.get('owner_raw')),'无主/未知')
 morale=u.get('morale')
 if not isinstance(morale,(int,float)) or isinstance(morale,bool):morale='未知'
 return f"{owner} · {u.get('unit_kind','部队')} · {general}\n士气 {morale} · 对部队 {u.get('target_attack_unit') or '未知'} · 攻城 {u.get('target_attack_building') or '未知'}"
def label_box(canvas,x,y,text,color,anchor='n',tags='unit_label'):
 tid=canvas.create_text(x,y,text=text,anchor=anchor,fill='#25271e',font=('Microsoft YaHei',9),tags=tags)
 b=canvas.bbox(tid)
 if b:
  rid=canvas.create_rectangle(b[0]-4,b[1]-2,b[2]+4,b[3]+2,fill='#fff9e7',outline=color,width=2,tags=tags);canvas.tag_lower(rid,tid)
 return tid
