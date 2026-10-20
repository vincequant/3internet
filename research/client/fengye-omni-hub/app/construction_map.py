"""Frozen city minimap for an original construction command."""
from copy import deepcopy
import tkinter as tk

from native_city_map import CityLocator
from panorama_model import cell_diamond
from command_construction import valid_construction
from scout_location import MAPS


class ConstructionLocator(CityLocator):
    def __init__(self, parent, row, binding):
        self.construction_target = tuple(row['target_xy_raw'])
        super().__init__(parent)
        for widget in self.label.master.winfo_children():
            if widget.cget('text') in ('打开全景视窗','显示部队'):
                widget.pack_forget()
        ref = deepcopy(row['construction_reference'])
        width, height = MAPS[ref['map_id']]
        state = dict(identity={'construction_reference':ref['binding_sha256'],'snapshot':ref['snapshot_id']},
                     scenario_map=dict(known=True,id=ref['map_id'],width=width,height=height),
                     entities=dict(cities_and_barriers=[ref['city']],lords=[],generals=[],
                                   field_units=[],production_buildings=[],traps=[]))
        self.update_state(state)
        self.focus_entity('cities_and_barriers',ref['city'])
        self.label.config(text=f'{row["action"]} · {ref["city"]["name"]}　目标 {self.construction_target}')
        self.note.config(text=f'城池及位置按对照快照 {ref["captured_at"]}；黄色格为原始指令目标，建成／结果未确认。')

    def _city_vision_items(self):
        return []

    def _city_vision_diamonds(self, *args):
        return []

    def _draw_supply(self, *args):
        pass

    def draw(self):
        super().draw()
        if not self.state or self.canvas.winfo_width() < 4:
            return
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        vertices = [self._project_mbm(x,y,w,h) for x,y in cell_diamond(*self.construction_target)]
        self.canvas.create_polygon(*[n for p in vertices for n in p],fill='',outline='#ffd35b',
                                   width=3,tags='construction_target')
        x,y = self.project(*self.construction_target)
        self.canvas.create_text(x+12,y-12,text='建設目標',anchor='w',fill='#ffd35b',tags='construction_target')


def open_construction_map(parent, row, binding):
    if not valid_construction(row,row.get('construction_reference'),binding):
        return None
    window = tk.Toplevel(parent)
    window.title(row['action']+' · '+row['construction_reference']['city']['name'])
    window.geometry('780x580');window.minsize(560,400)
    locator = ConstructionLocator(window,row,binding)
    locator.pack(fill='both',expand=True)
    from map_navigation import bind_arrows,bind_pointer_wheel,bind_zoom_keys
    bind_arrows(window,locator.pan);bind_zoom_keys(window,locator._wheel_delta);bind_pointer_wheel(window,locator._wheel)
    window.locator = locator
    window.after(40,lambda:locator.canvas.focus_set() if window.winfo_exists() else None)
    return window
