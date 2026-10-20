"""Read-only camera movement shared by the map widgets."""
_WHEEL_LISTENERS = []
_WHEEL_TOPS = set()
_WHEEL_CLASSES = set()
_TOUCH_BANK = 0
_STEAL_CLASSES = (
    'TNotebook', 'Treeview', 'Listbox', 'Text', 'TCombobox',
    'TCheckbutton', 'Checkbutton', 'TButton', 'Button',
    'TEntry', 'Entry',
    'Frame', 'TFrame', 'Label', 'TLabel', 'Canvas',
)
_WHEEL_SEQS = (
    '<MouseWheel>',
    '<Shift-MouseWheel>',
    '<Option-MouseWheel>',
    '<Command-MouseWheel>',
    '<Control-MouseWheel>',
    '<Mod1-MouseWheel>',
    '<Mod2-MouseWheel>',
)
_TOUCH_SEQ = '<TouchpadScroll>'
_MOVE_KEYS = {
    'Up': (0, -1), 'Down': (0, 1), 'Left': (-1, 0), 'Right': (1, 0),
    'w': (0, -1), 's': (0, 1), 'a': (-1, 0), 'd': (1, 0),
    'W': (0, -1), 'S': (0, 1), 'A': (-1, 0), 'D': (1, 0),
}
_ZOOM_KEYS = {
    'minus': -1, 'equal': 1,
    '-': -1, '=': 1,
}


def move_center(center, dx, dy, step=1, world=(101, 202), offset=0):
    return tuple(max(offset, min(world[i] - 1 + offset, center[i] + d * step))
                 for i, d in enumerate((dx, dy)))


def wheel_direction(delta):
    try:
        value = float(delta)
    except (TypeError, ValueError):
        return 0
    if value == 0:
        return 0
    return 1 if value > 0 else -1


def precise_scroll_deltas(dxdy):
    """Unpack Tk 9 <TouchpadScroll> %D the same way as ::tk::PreciseScrollDeltas."""
    try:
        value = int(dxdy) & 0xffffffff
    except (TypeError, ValueError):
        return 0, 0
    delta_x = value >> 16
    if delta_x >= 0x8000:
        delta_x -= 0x10000
    low = value & 0xffff
    delta_y = low if low < 0x8000 else low - 0x10000
    return delta_x, delta_y


def wheel_direction_from_event(event):
    delta = getattr(event, 'delta', 0)
    direction = wheel_direction(delta)
    if direction:
        return direction
    num = getattr(event, 'num', None)
    if num == 4:
        return 1
    if num == 5:
        return -1
    dx, dy = precise_scroll_deltas(delta)
    return wheel_direction(dy or dx)


def _walk_up(widget):
    cur = widget
    seen = set()
    while cur is not None and id(cur) not in seen:
        yield cur
        seen.add(id(cur))
        try:
            parent = cur.winfo_parent()
            cur = cur.nametowidget(parent) if parent else None
        except Exception:
            break


def _pointer_root(widget, event=None):
    try:
        return widget.winfo_pointerxy()
    except Exception:
        pass
    if event is not None:
        try:
            return int(event.x_root), int(event.y_root)
        except Exception:
            pass
    return None


def _over_widget(widget, event):
    try:
        if not widget.winfo_exists() or not widget.winfo_ismapped():
            return None
    except Exception:
        return None
    points = []
    pointer = _pointer_root(widget, event)
    if pointer:
        points.append(pointer)
    try:
        points.append((int(event.x_root), int(event.y_root)))
    except Exception:
        pass
    under = None
    for x_root, y_root in points:
        try:
            under = widget.winfo_containing(x_root, y_root)
        except Exception:
            under = None
        if under is not None:
            for ancestor in _walk_up(under):
                if ancestor is widget:
                    try:
                        return (x_root - widget.winfo_rootx(), y_root - widget.winfo_rooty())
                    except Exception:
                        return (getattr(event, 'x', 0), getattr(event, 'y', 0))
        for factor in (1.0, 2.0, 0.5):
            try:
                sx = x_root / factor - widget.winfo_rootx()
                sy = y_root / factor - widget.winfo_rooty()
            except Exception:
                continue
            if 0 <= sx < max(1, widget.winfo_width()) and 0 <= sy < max(1, widget.winfo_height()):
                return int(sx), int(sy)
    return None


def _wheel_dispatch(event):
    for widget, handler in reversed(_WHEEL_LISTENERS):
        hit = _over_widget(widget, event)
        if hit is None:
            continue
        handler(event, hit[0], hit[1])
        return 'break'
    return None


def _touchpad_dispatch(event):
    global _TOUCH_BANK
    dx, dy = precise_scroll_deltas(getattr(event, 'delta', 0))
    step = dy if dy else dx
    if not step:
        return None
    if not any(_over_widget(widget, event) for widget, _handler in _WHEEL_LISTENERS):
        return None
    _TOUCH_BANK += step
    if abs(_TOUCH_BANK) < 16:
        return 'break'
    event.delta = 1 if _TOUCH_BANK > 0 else -1
    _TOUCH_BANK = 0
    return _wheel_dispatch(event)


def _wheel_button(delta):
    def inner(event):
        event.delta = delta
        return _wheel_dispatch(event)
    return inner


def _fallback_scroll(event):
    widget = getattr(event, 'widget', None)
    if widget is None:
        return None
    try:
        delta = getattr(event, 'delta', 0)
        widget.yview_scroll(-1 if float(delta) > 0 else 1, 'units')
        return 'break'
    except Exception:
        return None


def _class_wheel(event):
    if _wheel_dispatch(event) == 'break':
        return 'break'
    return _fallback_scroll(event)


def _class_touch(event):
    result = _touchpad_dispatch(event)
    if result == 'break':
        return 'break'
    return _fallback_scroll(event)


def _bind_seq(target, method, seq, fn, add='+'):
    try:
        getattr(target, method)(seq, fn, add=add)
        return True
    except Exception:
        return False


def _install_wheel(widget):
    top = widget.winfo_toplevel()
    key = id(top)
    if key in _WHEEL_TOPS:
        return
    _WHEEL_TOPS.add(key)
    for seq in _WHEEL_SEQS:
        _bind_seq(top, 'bind_all', seq, _wheel_dispatch)
        for cls in _STEAL_CLASSES:
            mark = (key, cls, seq)
            if mark in _WHEEL_CLASSES:
                continue
            _WHEEL_CLASSES.add(mark)
            try:
                top.bind_class(cls, seq, _class_wheel)
            except Exception:
                pass
    _bind_seq(top, 'bind_all', _TOUCH_SEQ, _touchpad_dispatch)
    for cls in _STEAL_CLASSES:
        mark = (key, cls, _TOUCH_SEQ)
        if mark in _WHEEL_CLASSES:
            continue
        _WHEEL_CLASSES.add(mark)
        try:
            top.bind_class(cls, _TOUCH_SEQ, _class_touch)
        except Exception:
            pass
    _bind_seq(top, 'bind_all', '<Button-4>', _wheel_button(1))
    _bind_seq(top, 'bind_all', '<Button-5>', _wheel_button(-1))

    def forget(_=None):
        _WHEEL_TOPS.discard(key)

    top.bind('<Destroy>', forget, add='+')


def bind_pointer_wheel(widget, handler):
    """Keep a shared wheel dispatch so one map's Leave cannot steal another map's zoom."""
    _WHEEL_LISTENERS.append((widget, handler))

    def drop(_=None):
        _WHEEL_LISTENERS[:] = [(item, fn) for item, fn in _WHEEL_LISTENERS if item is not widget]

    def local(event):
        if not wheel_direction_from_event(event):
            return None
        handler(event, getattr(event, 'x', 0), getattr(event, 'y', 0))
        return 'break'

    def local_touch(event):
        return _touchpad_dispatch(event)

    def ready(_=None):
        try:
            _install_wheel(widget)
            widget.focus_set()
        except Exception:
            pass

    widget.bind('<Map>', ready, add='+')
    widget.bind('<Destroy>', drop, add='+')
    widget.bind('<Enter>', lambda _e=None: widget.focus_set(), add='+')
    widget.bind('<Motion>', lambda _e=None: widget.focus_set(), add='+')
    for seq in _WHEEL_SEQS:
        _bind_seq(widget, 'bind', seq, local)
    _bind_seq(widget, 'bind', _TOUCH_SEQ, local_touch)
    _bind_seq(widget, 'bind', '<Button-4>', lambda e: local(_with_delta(e, 1)))
    _bind_seq(widget, 'bind', '<Button-5>', lambda e: local(_with_delta(e, -1)))
    try:
        ready()
        widget.after(80, ready)
    except Exception:
        pass


def _with_delta(event, delta):
    event.delta = delta
    return event


def navigation_bar(parent, move, reset):
    from tkinter import ttk
    bar = ttk.Frame(parent)
    for label, dx, dy in [('↑', 0, -1), ('↓', 0, 1), ('←', -1, 0), ('→', 1, 0)]:
        ttk.Button(bar, text=label, width=3, command=lambda x=dx, y=dy: move(x, y)).pack(side='left')
    ttk.Button(bar, text='回到定位', command=reset).pack(side='left', padx=4)
    return bar


def bind_arrows(canvas, move):
    def on_key(event):
        step = _MOVE_KEYS.get(event.keysym) or _MOVE_KEYS.get(event.char)
        if not step:
            return
        move(*step)
        return 'break'

    for key in ('Up', 'Down', 'Left', 'Right', 'w', 'a', 's', 'd', 'W', 'A', 'S', 'D'):
        canvas.bind('<' + key + '>', on_key, add='+')
    canvas.bind('<Button-1>', lambda event: canvas.focus_set(), add='+')


def bind_zoom_keys(widget, zoom):
    """Minus zooms out; equal zooms in so + is not required."""
    def on_key(event):
        direction = _ZOOM_KEYS.get(event.keysym) or _ZOOM_KEYS.get(event.char)
        if not direction:
            return
        zoom(direction)
        return 'break'

    def _bind(seq):
        try:
            widget.bind(seq, on_key, add='+')
        except Exception:
            return False
        return True

    named = 0
    for key in ('minus', 'equal'):
        if _bind('<' + key + '>'):
            named += 1
    if named < 2:
        _bind('<KeyPress>')
