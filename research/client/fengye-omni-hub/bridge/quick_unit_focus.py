"""Recenter the selected own unit through original camera scroll messages only.

Exact-build wrappers 418a66/418aaa dispatch to 418b85. SANPK implements
SB_THUMBTRACK (5), not SB_THUMBPOSITION (4); 498796 updates the camera.
No clicks, military/menu commands, target function calls or memory writes.
"""
import ctypes as C
from ctypes import wintypes as W
import struct
import time

from quick_view_pan import ViewPan

UNIT_VTABLES = frozenset((0x508678, 0x508878, 0x508a60, 0x508c48,
    0x508e30, 0x509018, 0x509200, 0x5093e8, 0x5095d0, 0x5097b8, 0x5099d0))


def require_focus_state(state):
    if state.get('modal') or state.get('widget_count') or state.get('native_dialogs'):
        raise ValueError('请先关闭游戏弹窗；阶段结束确认请选择「否」，再定位部队')
    if (state.get('mode') not in (1, 2) or state.get('phase') not in (3, 4, 5)
            or state.get('allowance') != 1 or state.get('ending') != 0):
        raise ValueError('当前不是我方部队行动输入阶段')
    if any(state.get(k) != 0 for k in ('map_mode', 'map_widget', 'strategy_dialog', 'recruit_dialog')):
        raise ValueError('请先完成或取消当前地图／指令交互')
    if not state.get('selected_unit') or type(state.get('selected_order')) is not int or state['selected_order'] < 0:
        raise ValueError('游戏当前没有选中的行动部队；不会猜选或跳过部队')


def focus_plan(state, context):
    require_focus_state(state)
    width, height, tw, th = context['dimensions']
    if ((width, height) != (101, 202)
            or any(type(v) is not int or v < 4 or v > 256 or v % 2 for v in (tw, th))):
        raise ValueError('游戏地图投影未核准')
    unit = context['unit']; x, y = unit['xy']
    if (unit['pointer'] != state['selected_unit'] or unit['owner'] != context['local_force']
            or type(x) is not int or type(y) is not int or not 0 <= x < width or not 0 <= y < height
            or context['order_xy'] != [x, y]):
        raise ValueError('当前部队、我方归属或行动记录不一致')
    cw, ch = context['client_size']; ew, eh = context['scroll_extent']
    if any(type(v) is not int or not 1 <= v <= 65535 for v in (cw, ch, ew, eh)):
        raise ValueError('游戏画面尺寸未核准')
    point = [tw*x + (tw//2 if y & 1 else 0) + tw//2, th*y//2 + th//4]
    target = [min(max(0, point[0]-cw//2), max(0, ew-cw)),
              min(max(0, point[1]-ch//2), max(0, eh-ch))]
    return dict(unit=unit, world_point=point, target_origin=target,
                messages=[dict(hwnd=state['hwnd'], message=message, wparam=(pos << 16) | 5, lparam=0)
                          for message, pos in zip((0x114, 0x115), target)], game_order=False)


def capture_context(native, state):
    """Bounded reads of the selected unit, its current order and projection roots."""
    require_focus_state(state)
    n = native; v = state['view']; d = state['document']; core = n.bound['core']
    roots = n.read(v+0x958, 0x30)
    selected = struct.unpack_from('<I', roots)[0]
    orders, count = struct.unpack_from('<II', roots, 8)
    index = struct.unpack_from('<i', roots, 0x24)[0]
    if (selected != state['selected_unit'] or index != state['selected_order']
            or not 1 <= count <= 100 or not 0 <= index < count):
        raise ValueError('部队行动队列已改变')
    unit_raw = n.read(selected, 12)
    vt, x, y, owner, uid = struct.unpack('<IhhHH', unit_raw)
    if vt not in UNIT_VTABLES:
        raise ValueError('选中对象不是已核准的部队类型')
    order_address = orders + index*0x26; order_raw = n.read(order_address, 0x26)
    slot = n.number(core+0x6c0)
    if not 0 <= slot < 8:
        raise ValueError('无法确认本机玩家槽位')
    force_address = core + slot*0x87 + 0x4a; fid = n.number(force_address)
    if not 0 <= fid < 40:
        raise ValueError('无法确认我方势力')
    global_raw = n.read(0x53bb20, 12); dimensions_raw = n.read(d+0xf22, 16)
    dimensions = list(struct.unpack('<iiii', dimensions_raw))
    if (struct.unpack('<III', global_raw) != (*dimensions[:2], v)
            or struct.unpack('<II', n.read(0x50b730+0x134, 8)) != (0x498694, 0x4986dd)
            or n.number(0x50b730+0xc4) != 0x418b85 or n.number(0x50b730+0xc8) != 0x498796):
        raise ValueError('游戏投影／镜头入口不匹配')
    rect = W.RECT()
    n.u.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]; n.u.GetClientRect.restype = W.BOOL
    if not n.u.GetClientRect(state['hwnd'], C.byref(rect)) or rect.left or rect.top:
        raise ValueError('无法核准游戏画面范围')
    result = dict(unit=dict(pointer=selected, id=uid, owner=owner, xy=[x, y]),
                  local_force=fid, dimensions=dimensions, order_xy=list(struct.unpack_from('<ii', order_raw)),
                  client_size=[rect.right, rect.bottom], scroll_extent=list(struct.unpack('<ii', n.read(v+0x6c, 8))),
                  order_hex=order_raw.hex(), roots_hex=roots.hex())
    if (n.read(v+0x958, 0x30) != roots or n.read(selected, 12) != unit_raw
            or n.read(order_address, 0x26) != order_raw or n.read(d+0xf22, 16) != dimensions_raw
            or n.read(0x53bb20, 12) != global_raw or n.number(core+0x6c0) != slot
            or n.number(force_address) != fid):
        raise ValueError('定位读取期间部队／地图发生变化')
    focus_plan(state, result)
    return result


class UnitFocus:
    def __init__(self, native, emit):
        self.n = native; self.emit = emit
        self.pan = ViewPan(native, emit)

    def require_foreground(self, state):
        foreground = self.n.u.GetForegroundWindow()
        focus, flags = self.pan.focus(foreground)
        if foreground != state['main_hwnd'] or focus != state['hwnd'] or flags:
            raise ValueError('请将游戏主地图置前并关闭菜单／聊天输入后定位')

    def execute(self, enabled, hotkey=False):
        if not enabled:
            raise ValueError('部队定位尚未启用')
        before = self.n.capture(); require_focus_state(before)
        # A panel click may activate the existing game window, never click its map.
        if not hotkey:
            self.n.u.SetForegroundWindow(before['main_hwnd'])
        else:self.require_foreground(before)
        context = capture_context(self.n, before); plan = focus_plan(before, context)
        receipts = []
        self.emit(dict(kind='unit_focus_intent', plan=plan, state=before, game_order=False, memory_written=False))
        try:
            for message in plan['messages']:
                current = self.n.capture()
                if hotkey:self.require_foreground(current)
                if ((current['view'], current['hwnd'], current['phase']) != (before['view'], before['hwnd'], before['phase'])
                        or capture_context(self.n, current) != context):
                    raise ValueError('定位期间部队／阶段已改变，已停止')
                if self.n.owner(message['hwnd']) != self.n.bound['pid']:
                    raise ValueError('游戏窗口归属已改变')
                posted = bool(self.n.u.PostMessageW(message['hwnd'], message['message'], message['wparam'], 0))
                receipts.append(dict(**message, posted=posted))
                if not posted:
                    raise ValueError('镜头消息未发送成功')
            # Observe the exact camera origin and unchanged selection/order; never resend.
            for _ in range(15):
                time.sleep(.02)
                after = self.n.capture()
                if ((after['view'], after['hwnd'], after['phase']) != (before['view'], before['hwnd'], before['phase'])
                        or capture_context(self.n, after) != context):
                    raise ValueError('定位后部队／阶段改变，结果未核准')
                origin = list(struct.unpack('<ii', self.n.read(after['view']+0x54, 8)))
                if origin == plan['target_origin']:
                    result = dict(status='unit_focused', note=f'已定位当前部队 #{context["unit"]["id"]} · 坐标 {context["unit"]["xy"]}',
                                  state=after, origin=origin, plan=plan, receipts=receipts,
                                  selection_order_unchanged=True, game_order=False, memory_written=False)
                    self.emit(dict(kind='unit_focus_receipt', **result)); return result
            raise ValueError('已发送镜头定位，未核准画面回执；未重试')
        except (ValueError, OSError) as error:
            if not receipts:raise
            result = dict(status='unknown', note=str(error), receipts=receipts,
                          game_order=False, memory_written=False)
            self.emit(dict(kind='unit_focus_receipt', **result)); return result
