"""Read-only city locator inside the native intelligence application."""
import json
from pathlib import Path
import tkinter as tk

MAP_PATH=Path(__file__).with_name('map.json')

PALETTE_PATH=Path(__file__).with_name('game_palette.json')
try:GAME_PALETTE=json.loads(PALETTE_PATH.read_text(encoding='utf8'))
except (OSError,ValueError):GAME_PALETTE={}

def force_rgb(owner):
    return tuple(GAME_PALETTE.get('colors',{}).get(str(owner),{}).get('rgb',(190,190,175)))

def state_force_rgb(state,owner):
    # A named reference palette is independent of process addresses and game ownership.
    # Never reuse the historical boundary_snapshot ownership mapping.
    neutral=(190,190,175)
    if not state:return neutral
    forces=[f for f in state.get('entities',{}).get('lords',[]) if f.get('force_id')==owner]
    if len(forces)!=1:return neutral
    name=forces[0].get('name')
    entries=[e for e in GAME_PALETTE.get('colors',{}).values() if e.get('name')==name and name]
    if len(entries)!=1:return neutral
    rgb=entries[0].get('rgb')
    if not isinstance(rgb,(list,tuple)) or len(rgb)!=3 or any(type(v) is not int or not 0<=v<=255 for v in rgb):return neutral
    return tuple(rgb)

def map_viewport(width,height):
    # Original minimap resource is 525 x 350. Preserve its proportions.
    vw=min(width,height*1.5);vh=vw/1.5
    return ((width-vw)/2,(height-vh)/2,vw,vh)

def territory_pixel(base,owner,verified):
    if not verified or not isinstance(owner,int) or not 0<=owner<22:return base
    color=force_rgb(owner)
    return tuple(round(a*.25+b*.75) for a,b in zip(base,color))

def resolve_officer_city(state,officer):
    city_id=officer.get('location_city_id')
    if city_id is None:return None
    matches=[c for c in state['entities']['cities_and_barriers'] if c['city_id']==city_id]
    return matches[0] if len(matches)==1 else None

class CityLocator(tk.Frame):
    def __init__(self,parent):
        super().__init__(parent,bg='#eee8d5',bd=1,relief='sunken')
        self.state=None;self.entity_target=None;self.entity_identity=None;self.target_record=None;self.selected_id=None;self.officer_key=None;self.zoom=1.;self.center=(50.5,101.)
        self.world=(101,202);self.background=None;self.image=None;self.map_identity=None;self.map_mtime=None;self.legend_ids=None;self.territory_verified=False;self.target_text='点击下方在野武将，在地图定位其所在城池'
        bar=tk.Frame(self,bg='#eee8d5');bar.pack(fill='x')
        self.label=tk.Label(bar,text=self.target_text,bg='#eee8d5',fg='#4a3d1d',anchor='w',font=('Microsoft YaHei',10));self.label.pack(side='left',fill='x',expand=True,padx=6)
        for text,command in [('全图',self.fit),('－',lambda:self.change_zoom(-.5)),('＋',lambda:self.change_zoom(.5))]:tk.Button(bar,text=text,command=command,bg='#d4d0c0',padx=8,pady=0).pack(side='right',padx=2)
        self.canvas=tk.Canvas(self,height=320,bg='#d2d4bc',highlightthickness=0);self.canvas.pack(fill='both',expand=True)
        self.legend=tk.Frame(self,bg='#eee8d5');self.legend.pack(fill='x',padx=6)
        self.note=tk.Label(self,text='势力填色为地图中已读取的归属格；其余保留底图。',bg='#eee8d5',fg='#786c50',font=('Microsoft YaHei',8),anchor='w');self.note.pack(fill='x',padx=6)
        self.canvas.bind('<Configure>',lambda _:self.draw())
        self.canvas.bind('<Button-1>',self.click_city)
        self._load_map()

    def _load_map(self):
        try:
            from PIL import Image
            data=json.loads(MAP_PATH.read_text(encoding='utf8'));self.world=(data['width'],data['height']);self.map_identity=data['identity'];self.map_mtime=MAP_PATH.stat().st_mtime_ns
            assets=Path(__file__).parent/'assets'
            im=Image.open(assets/'SanInet.lbm').convert('RGB')
            mask=Image.open(assets/'SanInet.rbm');pixels=im.load()
            self.territory_verified=False
            if self.territory_verified:
                segments=GAME_PALETTE.get('boundary_snapshot',{}).get('segments',{})
                for y in range(im.height):
                    for x in range(im.width):
                        entry=segments.get(str(mask.getpixel((x,y))))
                        if entry:pixels[x,y]=force_rgb(entry['owner'])
            self.background=im
            self.note.config(text='标记与图例采用游戏截图参考配色，归属随采集更新；白色疆域线尚未绑定当前城市，未知势力保持中性。')
        except (OSError,ValueError,ImportError,KeyError):
            self.background=None;self.territory_verified=False
            self.note.config(text='原版底图不可用；仅显示已读取对象坐标。')

    def update_state(self,state):
        previous_identity=(self.state.get('player_identity') or {}).get('session_id') if self.state else None
        self.state=state
        if previous_identity is not None and previous_identity!=(state.get('player_identity') or {}).get('session_id'):
            self.clear_target('对局实例已变化，请重新选择定位对象')
        if self.entity_target is not None:
            kind,key=self.entity_target
            records=[r for r in state['entities'].get(kind,[]) if self.entity_key(kind,r)==key]
            if len(records)==1:self.focus_entity(kind,records[0],recenter=False)
            else:self.clear_target('所选对象已消失或标识不唯一；原定位已取消')
        try:
            if MAP_PATH.stat().st_mtime_ns!=self.map_mtime:self._load_map()
        except OSError:pass
        names=tuple((f['force_id'],f['name']) for f in state['entities']['lords'])
        from player_view import player_id
        legend_key=(names,player_id(state))
        if legend_key!=self.legend_ids:
            self.legend_ids=legend_key
            for widget in self.legend.winfo_children():widget.destroy()
            for i,(oid,name) in enumerate(names):
                rgb=self.color(oid);color='#'+''.join(f'{v:02x}' for v in rgb)
                item=tk.Frame(self.legend,bg='#eee8d5');item.grid(row=i//11,column=i%11,sticky='w',padx=(0,8))
                tk.Label(item,text='■',fg=color,bg='#eee8d5').pack(side='left')
                tk.Label(item,text=name+('★' if oid==player_id(state) else ''),bg='#eee8d5',fg='#493d23',font=('Microsoft YaHei',8)).pack(side='left')
        if self.officer_key is not None:
            candidates=[g for g in state['entities']['generals'] if (g['general_id_raw'],g['container_index'])==self.officer_key]
            if len(candidates)==1:self.focus_officer(candidates[0],recenter=False);return
            self.clear_target('所选武将已不在当前记录中；原定位已取消')
        self.draw()

    def clear_target(self,text):
        self.entity_target=None;self.target_record=None;self.selected_id=None;self.officer_key=None;self.target_text=text;self.label.config(text=text);self.draw()

    @staticmethod
    def entity_key(kind,record):
        field={'cities_and_barriers':'city_id','production_buildings':'object_id_candidate','field_units':'unit_id'}[kind]
        return (record.get('type'),record.get(field))

    def focus_entity(self,kind,record,recenter=True):
        xy=record.get('world_xy_raw')
        if not isinstance(xy,(list,tuple)) or len(xy)!=2 or not all(isinstance(v,(int,float)) for v in xy) or not (0<=xy[0]<self.world[0] and 0<=xy[1]<self.world[1]):
            self.clear_target('该对象坐标未解析或超出地图范围，无法定位');return
        key=self.entity_key(kind,record)
        matches=[r for r in self.state['entities'].get(kind,[]) if self.entity_key(kind,r)==key] if self.state else []
        if key[1] is None or len(matches)!=1:
            self.clear_target('对象标识尚未唯一确认，无法持续定位');return
        changed=self.entity_target!=(kind,key) or self.target_record is None or self.target_record.get('world_xy_raw')!=xy
        self.entity_target=(kind,key);self.entity_identity=self.state.get('identity');self.target_record=dict(record);self.officer_key=None
        self.selected_id=record.get('city_id') if kind=='cities_and_barriers' else None
        if recenter or changed:self.center=tuple(v+.5 for v in xy);self.zoom=2.
        labels={'parade_ground':'练兵所','horse_farm':'牧场','bow_studio':'弓工坊'}
        name=record.get('name') or labels.get(record.get('type')) or record.get('unit_kind') or '地图对象'
        self.target_name=f'{name} #{key[1]}'
        owner=next((f['name'] for f in self.state['entities']['lords'] if f['force_id']==record.get('owner_raw')),'未分配势力')
        self.label.config(text=f'{self.target_name}　坐标 {tuple(xy)}　归属：{owner}'+('　部队坐标待实战核验' if kind=='field_units' else ''))
        self.draw()

    def focus_officer(self,officer,recenter=True):
        self.entity_target=None;self.target_record=None
        if not self.state:return
        city=resolve_officer_city(self.state,officer)
        if city is None:
            self.clear_target(f"{officer.get('name') or '未解码武将'}：所在城池尚未解析，无法定位");return
        x,y=city['world_xy_raw']
        if not (0<=x<self.world[0] and 0<=y<self.world[1]):
            self.clear_target('该城坐标超出已知地图范围，无法定位');return
        changed=self.selected_id!=city['city_id'];self.selected_id=city['city_id']
        self.officer_key=(officer['general_id_raw'],officer['container_index'])
        if recenter or changed:self.center=(x+.5,y+.5);self.zoom=2.
        force=next((f['name'] for f in self.state['entities']['lords'] if f['force_id']==city['owner_raw']),'未分配势力')
        self.target_text=f"{officer.get('name') or '姓名未解码'} → {city['name']}　({x}, {y})　城属：{force}"
        self.label.config(text=self.target_text);self.draw()

    def color(self,owner):
        return state_force_rgb(self.state,owner)

    def fit(self):
        self.zoom=1.;self.center=(self.world[0]/2,self.world[1]/2);self.draw()
    def change_zoom(self,delta):
        self.zoom=max(1.,min(6.,self.zoom+delta));self.draw()
    def project(self,x,y):
        w=max(1,self.canvas.winfo_width());h=max(1,self.canvas.winfo_height())
        ox,oy,vw,vh=map_viewport(w,h)
        return (w/2+(x+.5-self.center[0])*vw*self.zoom/self.world[0],h/2+(y+.5-self.center[1])*vh*self.zoom/self.world[1])
    def draw(self):
        c=self.canvas;c.delete('all');w=c.winfo_width();h=c.winfo_height()
        if w<4 or h<4:return
        ox,oy,vw,vh=map_viewport(w,h)
        if self.background is not None and self.state:
            from PIL import Image,ImageTk
            dx=self.world[0]/self.zoom/2;dy=self.world[1]/self.zoom/2
            sx=self.background.width/self.world[0];sy=self.background.height/self.world[1]
            box=((self.center[0]-dx)*sx,(self.center[1]-dy)*sy,(self.center[0]+dx)*sx,(self.center[1]+dy)*sy)
            self.image=ImageTk.PhotoImage(self.background.transform((max(1,round(vw)),max(1,round(vh))),Image.Transform.EXTENT,box,resample=Image.Resampling.BILINEAR),master=c)
            c.create_image(ox,oy,image=self.image,anchor='nw')
            c.create_rectangle(ox,oy,ox+vw,oy+vh,outline='#7b775f',width=1)
        if not self.state:return
        for city in self.state['entities']['cities_and_barriers']:
            x,y=self.project(*city['world_xy_raw'])
            if not ox<=x<=ox+vw or not oy<=y<=oy+vh:continue
            oid=city['owner_raw'];rgb=self.color(oid);color='#'+''.join(f'{v:02x}' for v in rgb) if oid<22 else '#eeeece'
            c.create_rectangle(x-5,y-5,x+5,y+5,fill=color,outline='#241e12',tags=('city',f"city:{city['city_id']}"))
            if self.zoom>=2 and city['city_id']!=self.selected_id:c.create_text(x+7,y,text=city['name'],anchor='w',fill='#273722',font=('Microsoft YaHei',9))
        from unit_proximity import annotate
        annotate(self.state,legacy_id=None,world=self.world)
        # Buildings and deployed units share the same world coordinate transform.
        for kind in ('production_buildings','field_units'):
            for record in self.state['entities'].get(kind,[]):
                xy=record.get('world_xy_raw')
                if not isinstance(xy,(list,tuple)) or len(xy)!=2 or not all(isinstance(v,(int,float)) for v in xy) or not (0<=xy[0]<self.world[0] and 0<=xy[1]<self.world[1]):continue
                x,y=self.project(*xy)
                if not ox<=x<=ox+vw or not oy<=y<=oy+vh:continue
                oid=record.get('owner_raw',65535);color='#'+''.join(f'{v:02x}' for v in self.color(oid)) if 0<=oid<22 else '#eeeece'
                if kind=='field_units':
                    tint=record.get('proximity_color')
                    if tint:c.create_oval(x-10,y-10,x+10,y+10,fill=tint,outline='#38794d' if record.get('proximity_band')=='own' else '#ba7970',width=2,tags='unit_proximity')
                    c.create_polygon(x,y-6,x-5,y+5,x+5,y+5,fill=color,outline='#152316',tags='unit')
                else:c.create_oval(x-2,y-2,x+2,y+2,fill=color,outline='#525038',tags='building')
        c.create_text(8,h-8,text='▲部队：浅绿我方 / 浅红≤5格 / 浅黄6–10格（坐标观察范围）',anchor='sw',fill='#252819',font=('Microsoft YaHei',9))
        city=self.target_record or next((r for r in self.state['entities']['cities_and_barriers'] if r['city_id']==self.selected_id),None)
        if city:
            x,y=self.project(*city['world_xy_raw'])
            c.create_line(x,oy,x,oy+vh,fill='#b1281e',dash=(4,3));c.create_line(ox,y,ox+vw,y,fill='#b1281e',dash=(4,3))
            c.create_oval(x-12,y-12,x+12,y+12,outline='#fff4b0',width=5,tags='target')
            c.create_oval(x-12,y-12,x+12,y+12,outline='#b1281e',width=2,tags='target')
            label=c.create_text(x,y-25,text=self.target_name if self.target_record else city['name'],fill='#84190c',font=('Microsoft YaHei',12,'bold'),tags='target')
            bounds=c.bbox(label)
            if bounds:
                rect=c.create_rectangle(bounds[0]-5,bounds[1]-2,bounds[2]+5,bounds[3]+2,fill='#fff5d0',outline='#a88a43');c.tag_lower(rect,label)
    def click_city(self,event):
        # Optional map exploration, never game input.
        if not self.state:return
        closest=None;distance=100
        for city in self.state['entities']['cities_and_barriers']:
            x,y=self.project(*city['world_xy_raw']);d=(x-event.x)**2+(y-event.y)**2
            if d<distance:closest=city;distance=d
        if closest:
            self.entity_target=None;self.target_record=None;self.selected_id=closest['city_id'];self.officer_key=None;self.center=tuple(v+.5 for v in closest['world_xy_raw']);self.zoom=max(2.,self.zoom)
            self.label.config(text=f"{closest['name']}　坐标 {tuple(closest['world_xy_raw'])}");self.draw()
