"""Mount the original force pages, fed only by an explicit shadow snapshot.

This module owns no reader, timer, input injector or connection. OmniWindow's
render/render_detail, ForceCompare.refresh and QuarterOpsPanel.update_force
are local renderers; the inherited fetch/tick must remain disabled by the
FengyeWindow host. No state changes are promoted to original command evidence.
"""
import tkinter as tk

from fengye_battle_panel import prepare_payload


def mount_force_views(app):
    existing = getattr(app, 'force_view_hosts', None)
    if existing:
        return existing
    hosts = {}
    for key, title, page in (('info', '勢力情報', app.force_page),
                             ('compare', '勢力對比', app.force_compare)):
        host = tk.Frame(app.control_book)
        app.control_book.add(host, text=title)
        if key == 'info':
            tk.Label(host, text='內政區僅顯示已捕獲的記錄；空白不代表沒有下令。',
                     fg='#657985', anchor='w', font=('', 10)).pack(fill='x', padx=8, pady=3)
        # The host is a descendant of the page's original master (workspace).
        # Tk can therefore reuse the exact original widget, with all children,
        # callbacks, card images and stock/quarter tabs preserved.
        page.pack(in_=host, fill='both', expand=True)
        hosts[key] = host
    app.force_view_hosts = hosts
    # Switching geometry managers removes these two original Notebook tabs.
    # Keep the host's hidden-tab diagnostics restricted to tabs still owned
    # by that Notebook; the mounted widgets themselves remain the originals.
    if hasattr(app, 'original_tabs'):
        mounted = {str(app.force_page), str(app.force_compare)}
        app.original_tabs = [tab for tab in app.original_tabs if str(tab) not in mounted]
    app.force_views_error = None
    app._fengye_force_game_key = None
    app.control_book.bind('<<NotebookTabChanged>>', lambda _e: _render_active(app), add='+')
    return hosts


def _reset_game_views(app):
    app.sel = None
    app.retained_command_view = None
    for attr in ('sorts', 'row_records'):
        value = getattr(app, attr, None)
        if isinstance(value, dict):
            value.clear()
    art = getattr(app, 'force_art', None)
    if art is not None:
        art.rows.clear()
    for name in ('quarter_ops', 'force_talent'):
        panel = getattr(app, name, None)
        if panel is not None:
            panel._paint_sig = None
            panel._shown_force = None
            expanded = getattr(panel, '_expanded_additions', None)
            if expanded is not None:
                expanded.clear()
    training = getattr(app, 'training_record', None)
    if training is not None:
        training.samples = []
        training.series = []
        training.session = None
        training.force_id = None


def update_force_views(app, payload):
    """Render the original pages from a verified shadow payload, without I/O.

    Failed/foreign payloads keep the last page and return False. Any renderer
    error is retained for the host logger, never shown as fresh source data.
    Raw payloads stay immutable even though original renderers derive fields.
    """
    try:
        display = prepare_payload(payload)
    except (TypeError, ValueError) as exc:
        app.force_views_error = '%s: %s' % (type(exc).__name__, exc)
        return False
    game_key = payload.get('game_key')
    previous_key = getattr(app, '_fengye_force_game_key', None)
    changed = game_key is not None and game_key != previous_key
    if changed:
        _reset_game_views(app)
    # Keep the raw state untouched. prepare_payload has already made a deep
    # copy and applied the same pure combat derivation as the original client.
    app.doc = display
    app._fengye_force_game_key = game_key
    app.force_views_error = None
    return _render_active(app)


def _render_active(app):
    """Hidden pages keep their widgets; entering one renders the latest doc."""
    hosts = getattr(app, 'force_view_hosts', {})
    current = str(app.control_book.select())
    active = next((key for key, host in hosts.items() if str(host) == current), None)
    # pack(in_=host) changes geometry, not native parentage or stacking. These
    # pages are still workspace children: the newer console sibling would
    # otherwise cover their entire surface even while winfo_ismapped is true.
    # Their bounds remain exactly the host's content rectangle.
    for key, page in (('info',app.force_page),('compare',app.force_compare)):
        if key == active:
            page.lift()
        else:
            page.lower()
    if not getattr(app, 'doc', None):
        return True
    if active is None:
        return True
    previous_selection = getattr(app, 'sel', None)
    try:
        if active == 'info':
            app.render()
        else:
            app.force_compare.refresh()
    except Exception as exc:
        app.force_views_error = '%s: %s' % (type(exc).__name__, exc)
        return False
    if active == 'info' and previous_selection in {
            f.get('force_id') for f in app.doc.get('entities', {}).get('lords', [])}:
        # OmniWindow normally preserves this selection. Explicitly keep the
        # host's choice if an identity label refreshed during rendering.
        if app.sel != previous_selection:
            app.sel = previous_selection
            app.force_tree.selection_set(str(previous_selection))
            app.render_detail()
            app.force_compare.refresh()
    app.force_views_error = None
    return True
