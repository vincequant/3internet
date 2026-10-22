"""Opt-in diagnostics of this application's own widgets, not desktop control."""
import json
import os
from pathlib import Path
import time

def install(root, app):
    path = os.environ.get('SGI_VERIFY_OUTPUT')
    if not path:
        return
    started = time.monotonic()
    def capture():
        if app.doc is None and time.monotonic() - started < 35:
            root.after(1000, capture)
            return
        tree = app.world_cities.tree
        data = {
            'title': root.title(), 'window_viewable': bool(root.winfo_viewable()),
            'status': app.status.cget('text'), 'identity_label': app.identity_label.cget('text'),
            'snapshot_id': (app.doc or {}).get('snapshot_id'),
            'wild_rows': [list(app.tables['wild'].item(i)['values']) for i in app.tables['wild'].get_children()],
            'wild_filter_note': app.talent_filters.result.cget('text'),
            'hidden_barrier_wild': len(__import__('wild_locations').wild_location_groups(app.doc or {})[1]),
            'player_force_id': (app.doc or {}).get('player_force_id'),
            'player_context': (app.doc or {}).get('player_context'),
            'city_columns': [tree.heading(c)['text'] for c in tree['columns']],
            'city_rows': [list(tree.item(i)['values']) for i in tree.get_children()],
            'officer_columns': [app.tables['officers'].heading(c)['text'] for c in app.tables['officers']['columns']],
            'officer_rows': [list(app.tables['officers'].item(i)['values']) for i in app.tables['officers'].get_children()],
            'selected_force_id': app.sel,
            'nearby_defaults': {'radius': app.nearby_intel.radius.get(), 'origins': app.nearby_intel.origins.get(), 'filters': {k:bool(v.get()) for k,v in app.nearby_intel.filters.items()}},
            'war_force_ids': [int(i) for i in app.force_tree.get_children() if 'war' in app.force_tree.item(i)['tags']],
            'war_background': str(app.force_tree.tag_configure('war', 'background')),
            'force_unit_columns': [app.tables['force_units'].heading(c)['text'] for c in app.tables['force_units']['columns']],
            'force_unit_rows': [list(app.tables['force_units'].item(i)['values']) for i in app.tables['force_units'].get_children()],
            'force_unit_tab': app.book.tab(app.frames['force_units'], 'text'),
            'force_columns': [app.force_tree.heading(c)['text'] for c in app.force_tree['displaycolumns']],
            'original_art_tab': app.rules_panel.tabs.tab(app.original_art,'text'),
            'original_portraits': __import__('original_sprites').CATALOG['portraits']['count'],
            'color_tables': len(app.force_name_colors.tables),
            'battle_tab': app.workspace.tab(app.battles, 'text'),
            'battle_rows': [list(app.battles.tree.item(i)['values']) for i in app.battles.tree.get_children()],
            'military_rows': {k:[cell.cget('text') for cell in cells] for k,cells in app.military.tiles.items()},
            'preparation_tab': app.book.tab(app.preparation, 'text'),
            'preparation_status': app.preparation.status.cget('text'),
            'preparation_rows': [list(app.preparation.tree.item(i)['values']) for i in app.preparation.tree.get_children()],
            'card_effect_rows': list(app.diplomacy_cards.rows.values()),
            'strategy_topics': list(__import__('strategy_reference').TOPICS),
            'force_rows': [list(app.force_tree.item(i)['values']) for i in app.force_tree.get_children()],
        }
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')
    root.after(8000, capture)
