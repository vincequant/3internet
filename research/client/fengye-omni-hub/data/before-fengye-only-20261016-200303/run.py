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
    from local_runtime import configure as configure_runtime
    configure_runtime(args.data_dir)
    import tkinter as tk
    from mac_light_theme import apply_light_defaults
    from display_layout import configure
    from dock_icon import apply
    from fengye_source import FengyeSource, feed_items, control_ready, mode_text, decoded_commands
    from native_window import FengyeWindow
    from connection import CONNECTION, source_options, select_source
    # File viewers get a disposable cache, so they cannot replace live caches.
    cache = tempfile.TemporaryDirectory(prefix='fengye-replay-') if args.replay else None
    try:
        source = FengyeSource(data_dir=(cache.name if cache else args.data_dir), replay=args.replay)
        root = tk.Tk()
        apply_light_defaults(root)
        configure(root)
        apply(root, 'hub')
        app = FengyeWindow(root, source)
        def close():
            app.stop.set()
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
        bar = ttk.Frame(root)
        bar.pack(side='top', fill='x', before=root.winfo_children()[0], padx=12, pady=5)
        ttk.Label(bar, text='全知資料源：').pack(side='left')
        sources = source_options()
        choice = ttk.Combobox(bar, values=list(sources), state='readonly', width=26)
        choice.set(CONNECTION.cfg.get('selected_source') or CONNECTION.cfg['label'])
        choice.pack(side='left', padx=8)
        ttk.Label(bar, text='風夜封包／聊天另列於「風夜情報／操控台」').pack(side='left', padx=8)
        def switch_source(_=None):
            if choice.get() == CONNECTION.cfg.get('selected_source'):
                return
            try:
                select_source(choice.get())
            except Exception as error:
                messagebox.showerror('切換失敗', str(error), parent=root)
                return
            restart()
        choice.bind('<<ComboboxSelected>>', switch_source)
        if args.archive:
            from history_review import review_archive
            app._apply_review(review_archive(args.archive, seq=args.seq))
        if args.verify_json:
            started = time.monotonic()
            def verify():
                if source.sources.transport['status'] == 'not_checked' and time.monotonic() - started < 30:
                    root.after(250, verify)
                    return
                root.update_idletasks()
                record = {'title': root.title(), 'viewable': bool(root.winfo_viewable()),
                          'frontend': 'native-tk', 'run': (app.view.get('p34') or {}).get('run_name'),
                          'mode': mode_text(app.view), 'feed_count': len(app.feed_tree.get_children()),
                          'total_feed_count': len(feed_items(app.view)),
                          'snapshot_rows': [list(app.snapshot_tree.item(i, 'values')) for i in app.snapshot_tree.get_children()],
                          'control_ready': control_ready(app.view), 'chat_button': str(app.chat_button.cget('state')),
                          'stop_button': str(app.stop_button.cget('state')), 'render_error': app.render_error,
                          'workspace_tabs': [app.workspace.tab(i, 'text') for i in app.workspace.tabs()],
                          'legacy_tabs': [app.legacy_book.tab(i, 'text') for i in app.legacy_book.tabs()],
                          'selected_tab': app.workspace.tab(app.workspace.select(), 'text'),
                          'data_source': 'original-hub-and-fengye', 'upstream_state_loaded': app.doc is not None,
                          'world_source': 'original_archive' if args.archive else CONNECTION.cfg['label'],
                          'world_counts': {k: len(v) for k, v in ((app.doc or {}).get('entities') or {}).items() if isinstance(v, list)},
                          'rendered_forces': len(app.force_tree.get_children()),
                          'original_pages': {app.workspace.tab(t, 'text'): app.workspace.tab(t, 'state') for t in app.original_tabs},
                          'original_identity_controls_visible': bool(app.player_combo.winfo_ismapped()),
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
                # Exercise actual filtering and selection in the Tk widgets.
                app.feed_filter.set('遊戲數據')
                record['data_filter_count'] = len(app.feed_tree.get_children())
                if app.feed_tree.get_children():
                    app.feed_tree.selection_set(app.feed_tree.get_children()[0])
                    app.select_feed()
                    record['data_detail'] = app.feed_detail.get('1.0', 'end-1c')
                app.feed_filter.set('全部')
                app.workspace.select(app.fengye_page)
                app.fengye_book.select(app.console_page)
                root.update_idletasks()
                record['console_viewable'] = bool(app.console_state.winfo_viewable())
                app.fengye_book.select(app.intel_page)
                app.workspace.select(app.force_page)
                root.update_idletasks()
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
