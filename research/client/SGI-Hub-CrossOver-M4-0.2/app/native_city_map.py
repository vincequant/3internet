"""Read-only city locator inside the native intelligence application."""
import json
from pathlib import Path
import tkinter as tk
from map_unit_labels import unit_label,label_box,unit_label_ink
from panorama_model import (
    DETAIL_ZOOM, MIN_ZOOM, SWITCH_ZOOM, WORLD, capital_marks, cell_diamond, clamp_zoom, is_capital,
    layer_for_zoom, mbm_view, overlay_force_diamonds, paint_mbm_vision, show_kind_at_zoom,
    sprite_size, supply_lines, vision_overlay_cells,
)
from city_roads import mbm_to_world, path_for_layer
from tactical_terrain import Terrain, world_pixel

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
    indexed=GAME_PALETTE.get('color_index_rgb',{}).get(str(forces[0].get('color_index_raw')))
    if isinstance(indexed,(list,tuple)) and len(indexed)==3 and all(type(v) is int and 0<=v<=255 for v in indexed):return tuple(indexed)
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
        self.state=None;self.entity_target=None;self.entity_identity=None;self.target_record=None;self.selected_id=None;self.officer_key=None;self.zoom=6.;self.center=(50.5,101.)
        self.world=WORLD;self.scenario_id='china';self.scenario_name='大地图';self.background=None;self.terrain=None;self.terrain_error='';self.image=None;self.map_identity=None;self.map_mtime=None;self.legend_ids=None;self.territory_verified=False;self.target_text='点击下方在野武将，在地图定位其所在城池'
        bar=tk.Frame(self,bg='#eee8d5');bar.pack(fill='x')
        self.label=tk.Label(bar,text=self.target_text,bg='#eee8d5',fg='#4a3d1d',anchor='w',font=('Microsoft YaHei',10));self.label.pack(side='left',fill='x',expand=True,padx=6)
        tk.Button(bar,text='打开全景视窗',command=self.open_panorama_window,bg='#c4a35a',padx=8,pady=0).pack(side='left',padx=6)
        for text,command in [('全国示意',self.fit),('城战地面',self.battle_view),('－',lambda:self.change_zoom(-.5)),('＋',lambda:self.change_zoom(.5))]:tk.Button(bar,text=text,command=command,bg='#d4d0c0',padx=8,pady=0).pack(side='right',padx=2)
        self.show_units=tk.BooleanVar(value=True)
        tk.Checkbutton(bar,text='显示部队',variable=self.show_units,command=self.draw,bg='#eee8d5',fg='#302c22',selectcolor='#eee8d5').pack(side='right')
        self.canvas=tk.Canvas(self,height=320,bg='#d2d4bc',highlightthickness=0);self.canvas.pack(fill='both',expand=True)
        self.legend=tk.Frame(self,bg='#eee8d5');self.legend.pack(fill='x',padx=6)
        self.note=tk.Label(self,text='本页默认城战地面（SanInet.mbm）。滚轮缩放尽量不切全国示意图。半透明色块贴齐原作 96×48 菱格：首都 5、城池 3、关隘 1，逐格描边，兵营不画，不是游戏迷雾。',bg='#eee8d5',fg='#786c50',font=('Microsoft YaHei',8),anchor='w');self.note.pack(fill='x',padx=6)
        self.canvas.bind('<Configure>',lambda _=None:self.draw())
        self.canvas.bind('<Button-1>',self.click_city)
        from map_navigation import navigation_bar,bind_arrows,bind_pointer_wheel,bind_zoom_keys
        navigation_bar(self,self.pan,self.return_target).pack(fill='x',before=self.canvas)
        bind_arrows(self.canvas,self.pan)
        bind_arrows(self,self.pan)
        bind_zoom_keys(self.canvas,self._wheel_delta)
        bind_zoom_keys(self,self._wheel_delta)
        bind_pointer_wheel(self.canvas,self._wheel)
        bind_pointer_wheel(self,self._wheel)
        from original_sprites import OriginalSprites
        self.sprites=OriginalSprites(self.canvas)
        self._load_map()

    def _load_map(self):
        try:
            from PIL import Image
            data=json.loads(MAP_PATH.read_text(encoding='utf8'));self.world=(data['width'],data['height']);self.scenario_id='china';self.scenario_name='大地图';self.map_identity=data['identity'];self.map_mtime=MAP_PATH.stat().st_mtime_ns
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
            try:self.terrain=Terrain()
            except (OSError,ValueError) as error:self.terrain=None;self.terrain_error=str(error)
            hint='默认城战地面。滚轮缩放尽量不切全国示意图。半透明色块贴齐原作 96×48 菱格：首都 5、城池 3、关隘 1，逐格描边，兵营不画，不是迷雾。补给线沿道路，不是断粮判定。'
            if self.terrain_error:hint+=' MBM：'+self.terrain_error
            self.note.config(text=hint)
        except (OSError,ValueError,ImportError,KeyError):
            self.background=None;self.territory_verified=False
            self.note.config(text='原版底图不可用；仅显示已读取对象坐标。')

    def _apply_scenario(self,state):
        try:
            from scenario_maps import file_for, identify_detail
            spec,source=identify_detail(state)
        except Exception:
            return
        if spec['id']==self.scenario_id:
            return
        self.scenario_id=spec['id'];self.scenario_name=spec['name']
        self.world=(spec['width'],spec['height'])
        self.center=(self.world[0]/2,self.world[1]/2);self.zoom=MIN_ZOOM
        self.background=None;self.terrain=None;self.terrain_error=''
        try:
            from PIL import Image
            overview=file_for(spec,'overview')
            if overview:self.background=Image.open(overview).convert('RGB')
            mbm=file_for(spec,'mbm')
            if mbm:self.terrain=Terrain(str(mbm),size=tuple(spec['pixel']))
            else:self.terrain_error='缺少 '+spec['mbm']
        except (OSError,ValueError) as error:
            self.terrain=None;self.terrain_error=str(error)
        how={'memory':'内存网格','cities':'城名对照'}.get(source,'默认')
        text=f"当前剧本地图：{spec['name']} {spec['width']}×{spec['height']}（{how}）。坐标留在这张图上，不套大地图。"
        if self.terrain_error:text+=' 底图：'+self.terrain_error
        self.note.config(text=text)

    def update_state(self,state):
        previous_identity=(self.state.get('player_identity') or {}).get('session_id') if self.state else None
        self.state=state
        self._apply_scenario(state)
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
        field={'cities_and_barriers':'city_id','production_buildings':'object_id_candidate','field_units':'unit_id','traps':'trap_id'}[kind]
        return (record.get('type'),record.get(field))

    def focus_entity(self,kind,record,recenter=True,keep_zoom=False,default_zoom=None):
        from force_unit_tour import CITY_LOCATOR_ZOOM, retained_locator_zoom
        xy=record.get('world_xy_raw')
        if not isinstance(xy,(list,tuple)) or len(xy)!=2 or not all(isinstance(v,(int,float)) for v in xy) or not (0<=xy[0]<self.world[0] and 0<=xy[1]<self.world[1]):
            self.clear_target('该对象坐标未解析或超出地图范围，无法定位');return
        key=self.entity_key(kind,record)
        matches=[r for r in self.state['entities'].get(kind,[]) if self.entity_key(kind,r)==key] if self.state else []
        if key[1] is None or len(matches)!=1:
            self.clear_target('对象标识尚未唯一确认，无法持续定位');return
        changed=self.entity_target!=(kind,key) or self.target_record is None
        self.entity_target=(kind,key);self.entity_identity=self.state.get('identity');self.target_record=dict(record);self.officer_key=None
        self.selected_id=record.get('city_id') if kind=='cities_and_barriers' else None
        if recenter or changed:
            self.center=tuple(v+.5 for v in xy)
            self.zoom=retained_locator_zoom(self.zoom, keep_zoom, default=CITY_LOCATOR_ZOOM if default_zoom is None else default_zoom)
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
        if recenter or changed:self.center=(x+.5,y+.5);self.zoom=6.
        force=next((f['name'] for f in self.state['entities']['lords'] if f['force_id']==city['owner_raw']),'未分配势力')
        self.target_text=f"{officer.get('name') or '姓名未解码'} → {city['name']}　({x}, {y})　城属：{force}"
        self.label.config(text=self.target_text);self.draw()

    def color(self,owner):
        return state_force_rgb(self.state,owner)

    def fit(self):
        self.zoom=MIN_ZOOM;self.center=(self.world[0]/2,self.world[1]/2);self.draw()
    def battle_view(self):
        self.zoom=6.
        if self.target_record or self.selected_id is not None:self.return_target()
        else:self.draw()
    def open_panorama_window(self):
        from wine_nav import open_panorama
        open_panorama(self.center,self.zoom if self.zoom>=SWITCH_ZOOM else 6.)
    def pan(self,dx,dy):
        from map_navigation import move_center
        self.center=move_center(self.center,dx,dy,max(1,12/self.zoom),self.world,.5);self.draw()
    def return_target(self):
        record=self.target_record or next((r for r in (self.state or {}).get('entities',{}).get('cities_and_barriers',[]) if r.get('city_id')==self.selected_id),None)
        if record:self.center=tuple(v+.5 for v in record['world_xy_raw']);self.draw()
        else:self.fit()
    def change_zoom(self,delta):
        self.zoom=clamp_zoom(self.zoom+delta);self.draw()
    def _wheel(self,event,sx=None,sy=None):
        from map_navigation import wheel_direction_from_event
        direction=wheel_direction_from_event(event)
        if direction:self.change_zoom(0.5*direction)
    def _wheel_delta(self,direction):
        self.change_zoom(0.5*direction)
    def _layer(self):
        return layer_for_zoom(self.zoom)
    def project(self,x,y):
        w=max(1,self.canvas.winfo_width());h=max(1,self.canvas.winfo_height())
        if self._layer()=='mbm':
            box,scale=mbm_view(self.center,self.zoom,w,h)
            px,py=world_pixel(x,y)
            return ((px-box[0])*scale,(py-box[1])*scale)
        ox,oy,vw,vh=map_viewport(w,h)
        return (w/2+(x+.5-self.center[0])*vw*self.zoom/self.world[0],h/2+(y+.5-self.center[1])*vh*self.zoom/self.world[1])
    def _project_mbm(self,px,py,w,h,box=None,scale=None):
        if self._layer()=='mbm':
            if box is None:box,scale=mbm_view(self.center,self.zoom,w,h)
            return ((px-box[0])*scale,(py-box[1])*scale)
        wx,wy=mbm_to_world(px,py)
        return self.project(wx,wy)
    def _rgb(self,owner):
        return '#'+''.join(f'{v:02x}' for v in self.color(owner))
    def draw(self):
        c=self.canvas;c.delete('all');w=c.winfo_width();h=c.winfo_height()
        if w<4 or h<4:return
        layer=self._layer()
        box=scale=None
        if layer=='mbm' and self.terrain is not None:
            from PIL import Image,ImageTk
            box,scale=mbm_view(self.center,self.zoom,w,h)
            view=paint_mbm_vision(self.terrain,box,w,h,self._city_vision_items())
            self.image=ImageTk.PhotoImage(view,master=c)
            c.create_image(0,0,image=self.image,anchor='nw')
            ox,oy,vw,vh=0,0,w,h
        else:
            ox,oy,vw,vh=map_viewport(w,h)
            if self.background is not None and self.state:
                from PIL import Image,ImageTk
                dx=self.world[0]/self.zoom/2;dy=self.world[1]/self.zoom/2
                sx=self.background.width/self.world[0];sy=self.background.height/self.world[1]
                box=((self.center[0]-dx)*sx,(self.center[1]-dy)*sy,(self.center[0]+dx)*sx,(self.center[1]+dy)*sy)
                view=self.background.transform((max(1,round(vw)),max(1,round(vh))),Image.Transform.EXTENT,box,resample=Image.Resampling.BILINEAR)
                view=overlay_force_diamonds(view,self._city_vision_diamonds(w,h,None,None),alpha=56)
                self.image=ImageTk.PhotoImage(view,master=c)
                c.create_image(ox,oy,image=self.image,anchor='nw')
                c.create_rectangle(ox,oy,ox+vw,oy+vh,outline='#7b775f',width=1)
        if not self.state:return
        if layer=='mbm' and box is None:
            box,scale=mbm_view(self.center,self.zoom,w,h)
        self._draw_supply(w,h,ox,oy,vw,vh)
        city_size=sprite_size('城关',self.zoom,scale)
        unit_size=sprite_size('部队',self.zoom,scale)
        for city in self.state['entities']['cities_and_barriers']:
            x,y=self.project(*city['world_xy_raw'])
            if not ox<=x<=ox+vw or not oy<=y<=oy+vh:continue
            oid=city['owner_raw'];rgb=self.color(oid);color='#'+''.join(f'{v:02x}' for v in rgb) if oid<22 else '#eeeece'
            sprite=self.sprites.image(city,city_size,self.state)
            if sprite:c.create_image(x,y,image=sprite,tags=('city',f"city:{city['city_id']}",'original_sprite'))
            flag=self.sprites.flag(self.state,oid,max(16,city_size//3))
            if flag:c.create_image(x+city_size//4,y-city_size//4,image=flag,tags='original_flag')
            name=('都·' if is_capital(self.state,city) else '')+(city.get('name') or '')
            ink='#fff6da' if layer=='mbm' else '#273722'
            if self.zoom>=2 and city['city_id']!=self.selected_id:c.create_text(x+city_size//3,y,text=name,anchor='w',fill=ink,font=('Microsoft YaHei',9))
        from unit_proximity import annotate
        annotate(self.state,legacy_id=None,world=self.world)
        # Buildings and deployed units share the same world coordinate transform.
        for kind in ('production_buildings','field_units','traps'):
            if kind=='field_units' and not self.show_units.get():continue
            if not show_kind_at_zoom(kind,self.zoom):continue
            for record in self.state['entities'].get(kind,[]):
                xy=record.get('world_xy_raw')
                if not isinstance(xy,(list,tuple)) or len(xy)!=2 or not all(isinstance(v,(int,float)) for v in xy) or not (0<=xy[0]<self.world[0] and 0<=xy[1]<self.world[1]):continue
                x,y=self.project(*xy)
                if not ox<=x<=ox+vw or not oy<=y<=oy+vh:continue
                oid=record.get('owner_raw',65535);color='#'+''.join(f'{v:02x}' for v in self.color(oid)) if 0<=oid<22 else '#eeeece'
                if kind=='field_units':
                    tint=record.get('proximity_color')
                    if tint:c.create_oval(x-10,y-10,x+10,y+10,fill=tint,outline='#38794d' if record.get('proximity_band')=='own' else '#ba7970',width=2,tags='unit_proximity')
                    sprite=self.sprites.image(record,unit_size,self.state)
                    if sprite:
                        c.create_image(x,y-5,image=sprite,tags=('unit','original_sprite'))
                        flag=self.sprites.flag(self.state,oid,max(16,unit_size//3))
                        if flag:c.create_image(x+unit_size//4,y-unit_size//3,image=flag,tags='original_flag')
                    else:c.create_polygon(x,y-6,x-5,y+5,x+5,y+5,fill=color,outline='#152316',tags='unit')
                    if self.zoom>=2 or (self.target_record and self.target_record.get('type')=='field_unit' and record.get('unit_id')==self.target_record.get('unit_id')):
                        label_box(c,x,y+unit_size//3,unit_label(self.state,record),color,ink=unit_label_ink(self.state,record))
                elif kind=='traps':
                    sprite=self.sprites.image(record,unit_size,self.state)
                    if sprite:c.create_image(x,y,image=sprite,tags=('trap','original_sprite'))
                else:
                    sprite=self.sprites.image(record,unit_size)
                    if sprite:c.create_image(x,y-3,image=sprite,tags=('building','original_sprite'))
                    flag=self.sprites.flag(self.state,oid,max(16,unit_size//3))
                    if flag:c.create_image(x+unit_size//4,y-unit_size//4,image=flag,tags='original_flag')

        self._draw_capitals(w,h,layer)
        c.create_text(8,h-8,text=self.scenario_name+' · '+('原作地面' if layer=='mbm' else '全国示意')+' · 菱格视野 都5/城3/关1 · WASD 移动 · 滚轮或 -/= 缩放',anchor='sw',fill='#fff6da' if layer=='mbm' else '#252819',font=('Microsoft YaHei',9))
        city=self.target_record or next((r for r in self.state['entities']['cities_and_barriers'] if r['city_id']==self.selected_id),None)
        if city:
            x,y=self.project(*city['world_xy_raw'])
            ring=max(16,city_size//2)
            c.create_line(x,oy,x,oy+vh,fill='#b1281e',dash=(4,3));c.create_line(ox,y,ox+vw,y,fill='#b1281e',dash=(4,3))
            c.create_oval(x-ring,y-ring,x+ring,y+ring,outline='#fff4b0',width=5,tags='target')
            c.create_oval(x-ring,y-ring,x+ring,y+ring,outline='#b1281e',width=2,tags='target')
            label=c.create_text(x,y-ring-12,text=self.target_name if self.target_record else city['name'],fill='#84190c',font=('Microsoft YaHei',12,'bold'),tags='target')
            bounds=c.bbox(label)
            if bounds:
                rect=c.create_rectangle(bounds[0]-5,bounds[1]-2,bounds[2]+5,bounds[3]+2,fill='#fff5d0',outline='#a88a43');c.tag_lower(rect,label)
    def click_city(self,event):
        # Optional map exploration, never game input.
        if not self.state:return
        candidates=[]
        for kind in ('cities_and_barriers','field_units'):
            if kind=='field_units' and not self.show_units.get():continue
            if not show_kind_at_zoom(kind,getattr(self,'zoom',1)):continue
            for record in self.state['entities'].get(kind,[]):
                xy=record.get('world_xy_raw')
                if not isinstance(xy,(list,tuple)) or len(xy)!=2:continue
                x,y=self.project(*xy);d=(x-event.x)**2+(y-event.y)**2
                layer=self._layer() if callable(getattr(self,'_layer',None)) else 'lbm'
                radius=max(28,sprite_size('城关' if kind=='cities_and_barriers' else '部队',getattr(self,'zoom',1)))//2 if layer=='mbm' else 18
                if d<=radius**2:candidates.append((d,kind,record))
        if candidates:
            candidates.sort(key=lambda item:item[0])
            current=next((i for i,(_,kind,r) in enumerate(candidates) if self.entity_target==(kind,self.entity_key(kind,r))),-1)
            _,kind,record=candidates[(current+1)%len(candidates)]
            self.focus_entity(kind,record)

    def _city_vision_items(self):
        if not self.state:
            return []
        items=[]
        for item in vision_overlay_cells(self.state):
            items.append({'cell':item['cell'],'rgb':self.color(item.get('owner_raw')),'center':item.get('center')})
        return items
    def _city_vision_diamonds(self,w,h,box,scale):
        if self._layer()=='mbm':
            return []
        diamonds=[]
        for item in self._city_vision_items():
            points=[self._project_mbm(px,py,w,h,box,scale) for px,py in cell_diamond(*item['cell'])]
            ox,oy,vw,vh=map_viewport(w,h)
            points=[(x-ox,y-oy) for x,y in points]
            xs=[p[0] for p in points];ys=[p[1] for p in points]
            if max(xs)<-8 or min(xs)>w+8 or max(ys)<-8 or min(ys)>h+8:
                continue
            diamonds.append({'points':points,'rgb':item['rgb'],'center':item.get('center')})
        return diamonds

    def _draw_supply(self,w,h,ox,oy,vw,vh):
        box=scale=None
        if self._layer()=='mbm':
            box,scale=mbm_view(self.center,self.zoom,w,h)
        width=3 if self._layer()=='lbm' else max(3,int(self.zoom*0.45))
        for line in supply_lines(self.state):
            points=[self._project_mbm(px,py,w,h,box,scale) for px,py in path_for_layer(line['path'],self._layer(),self.zoom)]
            if len(points)<2:continue
            xs=[p[0] for p in points];ys=[p[1] for p in points]
            if max(xs)<ox-40 or min(xs)>ox+vw+40 or max(ys)<oy-40 or min(ys)>oy+vh+40:continue
            color=self._rgb(line['owner_raw']) if line['same_owner'] else '#f4efe2'
            stroke=width if line['same_owner'] else max(1,width-1)
            flat=[value for point in points for value in point]
            self.canvas.create_line(*flat,fill='#2a2c24',width=stroke+2,capstyle=tk.ROUND,joinstyle=tk.ROUND)
            self.canvas.create_line(*flat,fill=color,width=stroke,capstyle=tk.ROUND,joinstyle=tk.ROUND)

    def _draw_capitals(self,w,h,layer):
        ink='#6c5310' if layer=='lbm' else '#ffe9a3'
        for mark in capital_marks(self.state):
            x,y=self.project(*mark['world_xy'])
            if not (-50<=x<=w+50 and -50<=y<=h+50):continue
            self.canvas.create_text(x,y+16,text=f"首都 · {mark['force_name']} · {mark['city_name']}",fill=ink,font=('Microsoft YaHei',10,'bold'))
