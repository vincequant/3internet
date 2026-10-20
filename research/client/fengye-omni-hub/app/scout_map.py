"""Frozen original-command target and static scout coverage, no live fog claim."""
from copy import deepcopy
import tkinter as tk

from native_city_map import CityLocator
from panorama_model import cell_diamond
from scout_location import MAPS, scout_cells, location_text, valid_reference


class ScoutLocator(CityLocator):
    def __init__(self, parent, row, binding):
        self.scout_center = tuple(row['target_xy_raw'])
        super().__init__(parent)
        for widget in self.label.master.winfo_children():
            if widget.cget('text') in ('打开全景视窗','显示部队'):
                widget.pack_forget()
        ref = deepcopy(row['scout_reference'])
        width, height = MAPS[ref['map_id']]
        state = dict(identity={'scout_reference':ref['binding_sha256'], 'snapshot':ref['snapshot_id']},
                     scenario_map=dict(known=True, id=ref['map_id'], width=width, height=height),
                     entities=dict(cities_and_barriers=ref['cities'], lords=ref['forces'],
                                   generals=[], field_units=[], production_buildings=[], traps=[]))
        self.update_state(state)
        self.label.config(text=f"偵察 · {location_text(row,binding)}　中心 {self.scout_center}")
        self.note.config(text=f"原始指令中心；黄色菱格为原版偵察范围（四邻4格，最多41格）。执行／结果未确认。\n城名及归属按对照快照 {ref['captured_at']}；不是当时已取得的情报。")
        self.return_target()

    def return_target(self):
        self.center = tuple(v+.5 for v in self.scout_center)
        self.zoom = 3.0
        self.draw()

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
        for x, y in scout_cells(self.scout_center, self.world):
            vertices = [self._project_mbm(px,py,w,h) for px,py in cell_diamond(x,y)]
            self.canvas.create_polygon(*[n for p in vertices for n in p], fill='',
                                       outline='#ffd35b', width=2, tags='scout_range')
        x, y = self.project(*self.scout_center)
        self.canvas.create_oval(x-7,y-7,x+7,y+7,fill='#d53926',outline='#fff3b0',width=2,tags='scout_center')
        self.canvas.create_text(x+12,y-12,text='偵察中心',anchor='w',fill='#fff3b0',tags='scout_center')


def open_scout_map(parent, row, binding):
    if not valid_reference(row, row.get('scout_reference'), binding):
        return None
    window = tk.Toplevel(parent)
    window.title('偵察 · '+location_text(row,binding))
    window.geometry('780x580'); window.minsize(560,400)
    locator = ScoutLocator(window,row,binding)
    locator.pack(fill='both',expand=True)
    from map_navigation import bind_arrows,bind_pointer_wheel,bind_zoom_keys
    bind_arrows(window,locator.pan)
    bind_zoom_keys(window,locator._wheel_delta)
    bind_pointer_wheel(window,locator._wheel)
    window.locator = locator
    window.after(40,lambda:locator.canvas.focus_set() if window.winfo_exists() else None)
    return window
