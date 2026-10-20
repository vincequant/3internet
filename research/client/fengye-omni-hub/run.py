#!/usr/bin/env python3
"""Launch the native Fengye Hub. No browser, HTTP server, or game startup."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
for folder in (ROOT, ROOT / 'app', ROOT / 'bridge'):
    sys.path.insert(0, str(folder))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', help='Read an existing raw observation JSON; controls stay disabled')
    parser.add_argument('--data-dir')
    parser.add_argument('--archive', help='Open an existing original Hub game archive')
    parser.add_argument('--seq', type=int, help='Archive frame; default original replay selection')
    parser.add_argument('--verify-json', help='Write native widget verification, without sending controls')
    parser.add_argument('--verify-exit', action='store_true')
    args = parser.parse_args()
    if args.archive or args.seq is not None:
        parser.error('玩家視角的全知來源已關閉；風夜記錄請使用 --replay')
    from local_runtime import configure as configure_runtime
    runtime_data = configure_runtime(args.data_dir)
    from fengye_diagnostics import configure as configure_diagnostics
    configure_diagnostics(runtime_data)
    import tkinter as tk
    from mac_light_theme import apply_light_defaults
    from display_layout import configure
    from fengye_icon import apply
    from fengye_source import FengyeSource, control_ready, mode_text, decoded_commands
    from native_window import FengyeWindow
    from connection import CONNECTION
    # File viewers get a disposable cache, so they cannot replace live caches.
    cache = tempfile.TemporaryDirectory(prefix='fengye-replay-') if args.replay else None
    try:
        source = FengyeSource(data_dir=(cache.name if cache else args.data_dir), replay=args.replay)
        root = tk.Tk()
        apply_light_defaults(root)
        configure(root)
        apply(root)
        app = FengyeWindow(root, source)
        # 2026-10-20: 驗收用；指定初始分頁（例如 FENGYE_START_TAB=外部指令）。
        start_tab = os.environ.get('FENGYE_START_TAB')
        if start_tab:
            names = [app.control_book.tab(tid, 'text') for tid in app.control_book.tabs()]
            open('/tmp/hub-tab-debug.log', 'a', encoding='utf-8').write(
                'start_tab=%r tabs=%r\n' % (start_tab, names))
            for tid in app.control_book.tabs():
                if app.control_book.tab(tid, 'text') == start_tab:
                    app.control_book.select(tid)
                    break
        def close():
            app.stop.set()
            if hasattr(app, 'battle_panel'):
                app.battle_panel.dispose()
            CONNECTION.close()
            root.destroy()
        root.protocol('WM_DELETE_WINDOW', close)
        from graceful_shutdown import install
        install(root, close)
        def restart():
            close()
            os.execv(sys.executable, [sys.executable, str(ROOT / 'run.py')] + sys.argv[1:])
        app.on_reload = restart
        from tkinter import ttk, messagebox
        if args.verify_json:
            started = time.monotonic()
            def verify():
                if source.sources.transport['status'] == 'not_checked' and time.monotonic() - started < 30:
                    root.after(250, verify)
                    return
                root.update_idletasks()
                record = {'title': root.title(), 'viewable': bool(root.winfo_viewable()),
                          'frontend': 'native-tk', 'run': (app.view.get('p34') or {}).get('run_name'),
                          'mode': mode_text(app.view),
                          'control_ready': control_ready(app.view), 'chat_button': str(app.chat_button.cget('state')),
                          'stop_button': str(app.stop_button.cget('state')), 'render_error': app.render_error,
                          'room_channel': app.room_channel.cget('text'),
                          'workspace_tabs': [app.workspace.tab(i, 'text') for i in app.workspace.tabs()],
                          'selected_tab': app.workspace.tab(app.workspace.select(), 'text'),
                          'data_source': 'fengye-only', 'upstream_state_loaded': app.doc is not None,
                          'world_source': None,
                          'world_counts': {k: len(v) for k, v in ((app.doc or {}).get('entities') or {}).items() if isinstance(v, list)},
                          'rendered_forces': len(app.force_tree.get_children()),
                          'original_pages': {app.workspace.tab(t, 'text'): app.workspace.tab(t, 'state') for t in app.original_tabs},
                          'original_identity_controls_visible': bool(app.player_combo.winfo_ismapped()),
                          'room_controls': {key: str(getattr(app, key).cget('state')) for key in
                                            ('room_start', 'room_search', 'room_join', 'room_leave', 'room_stop',
                                             'room_register', 'room_d8')},
                          'room_monitor': app.rooms.state,
                          'fengye_decoded': decoded_commands(app.view),
                          'original_panorama_bindings': list(app.panorama.canvas.bindtags())}
                if app.doc:
                    app.workspace.select(app.panorama)
                    app.refresh_panorama(force=True)
                    root.update()
                    record['panorama_viewable'] = bool(app.panorama.canvas.winfo_viewable())
                    record['panorama_items'] = len(app.panorama.canvas.find_all())
                    record['original_officer_rows'] = len(app.tables['all_officers'].get_children())
                    record['original_force_officer_rows'] = len(app.tables['officers'].get_children())
                # 風夜操控台（0.2.18）：主視窗唯一可見分頁；逐個子分頁確認可視。
                app.workspace.select(app.console_page)
                root.update_idletasks()
                record['console_viewable'] = bool(app.console_state.winfo_viewable())
                record['console_state_text'] = app.console_state.cget('text')
                record['console_subtabs'] = [app.control_book.tab(i, 'text') for i in app.control_book.tabs()]
                sub_views = []
                player_text = {}
                def visible_text(widget):
                    items = []
                    if widget.winfo_ismapped() and isinstance(widget, (tk.Label, tk.Button)):
                        value = str(widget.cget('text'))
                        if value:
                            items.append(value)
                    for child in widget.winfo_children():
                        items.extend(visible_text(child))
                    return items
                for tid in app.control_book.tabs():
                    app.control_book.select(tid)
                    root.update_idletasks()
                    page = app.control_book.nametowidget(tid)
                    sub_views.append(bool(page.winfo_viewable()))
                    player_text[app.control_book.tab(tid, 'text')] = visible_text(page)
                record['console_subtabs_viewable'] = sub_views
                app.control_book.select(app.room_control_page)
                app._toggle_probe_layer()
                root.update_idletasks()
                player_text['手動進房設定'] = visible_text(app.room_control_page)
                app._toggle_probe_layer()
                record['player_page_text'] = player_text
                out = Path(args.verify_json)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
                if args.verify_exit:
                    close()
            root.after(1500, verify)
        root.mainloop()
    finally:
        CONNECTION.close()
        if cache:
            cache.cleanup()


if __name__ == '__main__':
    main()
