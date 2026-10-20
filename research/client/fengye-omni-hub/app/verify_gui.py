"""Opt-in diagnostics of this application's own widgets, not desktop control."""
import json
import os
import re
from pathlib import Path
import time

def install(root, app):
    path = os.environ.get('SGI_VERIFY_OUTPUT')
    if not path:
        return
    started = time.monotonic()
    def algorithm_widgets():
        panel=app.rules_panel;calc=panel.attack_calculator
        data={'tabs':[panel.tabs.tab(t,'text') for t in panel.tabs.tabs()],
              'answer':calc.answer.cget('text'),'result':calc.result}
        if os.environ.get('SGI_VERIFY_ALGORITHMS')=='1':
            workspace=app.workspace.select();tab=panel.tabs.select()
            try:
                app.workspace.select(panel);panel.tabs.select(calc);root.update_idletasks()
                data['calculator_viewable']=bool(calc.winfo_viewable())
                data['calculator_size']=[calc.winfo_width(),calc.winfo_height()]
                panel.tabs.select(panel.algorithms);root.update_idletasks()
                data['manual_viewable']=bool(panel.algorithms.winfo_viewable())
                data['chapters']=len(panel.algorithms.rows)
                for key in ('defection','card_probability','war_reject'):
                    board=getattr(panel,key);app.workspace.select(board);root.update_idletasks()
                    data[key]={'viewable':bool(board.winfo_viewable()),'size':[board.winfo_width(),board.winfo_height()],
                               'rows':[list(board.tree.item(i)['values']) for i in board.tree.get_children()]}
                data['draw_count']=panel.card_probability.draws.get()
                data['card_pool_status']=(app.doc or {}).get('card_pool',{}).get('status')
            finally:
                panel.tabs.select(tab);app.workspace.select(workspace)
        return data
    def capture():
        if getattr(app,'retained_command_view',None):
            texts={};training_views={};construction_maps=[]
            if os.environ.get('SGI_VERIFY_ALL_FORCES'):
                selected=app.sel
                rows=app.retained_command_view['native_command_evidence']['rows']
                for fid in sorted({row['actor_force_id'] for row in rows}):
                    app.sel=fid;app.render_retained_commands()
                    texts[str(fid)]=app.quarter_ops.input_log.get('1.0','end')
                    training_views[str(fid)]={'summary':app.training_record.activity.cget('text'),
                        'counts':app.training_record.activity_counts,
                        'kinds':{k:v.cget('text') for k,v in app.training_record.kind_activity.items()}}
                    if os.environ.get('SGI_VERIFY_CONSTRUCTION')=='1':
                        panel=app.quarter_ops
                        names={r['construction_reference']['city']['name'] for r in rows
                               if r['actor_force_id']==fid and r.get('construction_reference')}
                        # Exercise the actual city-name tag callback, then
                        # capture this app's own minimap widgets.
                        for tag in panel.input_log.tag_names():
                            if not str(tag).startswith('command_'):continue
                            bounds=panel.input_log.tag_ranges(tag)
                            if not bounds or panel.input_log.get(*bounds) not in names:continue
                            callback=panel.input_log.tk.call(panel.input_log._w,'tag','bind',tag,'<Button-1>')
                            command=re.search(r'\[([^\s]+)',callback)
                            if not command:continue
                            panel.input_log.tk.call(command.group(1));root.update_idletasks()
                            window=panel.construction_window
                            if window is None or not window.winfo_exists():continue
                            locator=window.locator
                            construction_maps.append(dict(force_id=fid,title=window.title(),
                                city_id=locator.selected_id,center=locator.center,
                                target=locator.construction_target,
                                target_markers=len(locator.canvas.find_withtag('construction_target')),
                                viewable=bool(window.winfo_viewable()),note=locator.note.cget('text')))
                            window.destroy();panel.construction_window=None
                            break
                app.sel=selected;app.render_retained_commands()
            output=Path(path);output.parent.mkdir(parents=True,exist_ok=True)
            output.write_text(json.dumps({'title':root.title(),'window_viewable':bool(root.winfo_viewable()),
                'retained_only':True,'selected_force_id':app.sel,'player_identity':None,
                'status':app.status.cget('text'),'identity_label':app.identity_label.cget('text'),
                'algorithms':algorithm_widgets(),
                'workspace_tabs':[app.workspace.tab(t,'text') for t in app.workspace.tabs()],
                'force_command_texts':texts,
                'training_force_views':training_views,
                'training_activity_text':app.training_record.activity.cget('text'),
                'construction_maps':construction_maps,
                'quarter_ops_input_tabs':[app.quarter_ops.lane_book.tab(t,'text') for t in app.quarter_ops.lane_book.tabs()],
                'quarter_ops_input_text':app.quarter_ops.input_log.get('1.0','end'),
                'quarter_ops_input_details':app.quarter_ops._input_details},ensure_ascii=False,indent=2),encoding='utf8')
            return
        if app.doc is None and time.monotonic() - started < 35:
            root.after(1000, capture)
            return
        city_id = os.environ.get('SGI_VERIFY_CITY')
        if city_id and app.doc:
            city = next((c for c in app.doc['entities']['cities_and_barriers'] if str(c.get('city_id'))==city_id and c.get('type')=='city'),None)
            if city:app.locate_object('cities',city,show_city_wild=True)
            root.update_idletasks()
            output=Path(path);output.parent.mkdir(parents=True,exist_ok=True)
            output.write_text(json.dumps({'title':root.title(),'window_viewable':bool(root.winfo_viewable()),
                'snapshot_id':app.doc.get('snapshot_id'),'player_identity':app.doc.get('player_identity'),
                'city_recruit_probability':{'note':app.city_wild.note.cget('text'),
                    'rows':[list(app.city_wild.tree.item(i)['values']) for i in app.city_wild.tree.get_children()]}},ensure_ascii=False,indent=2),encoding='utf8')
            return
        tree = app.world_cities.tree
        data = {
            'title': root.title(), 'window_viewable': bool(root.winfo_viewable()),
            'geometry':root.geometry(),'screen':[root.winfo_screenwidth(),root.winfo_screenheight()],
            'ui_scale':getattr(root,'sgi_ui_scale',1.),
            'status': app.status.cget('text'), 'identity_label': app.identity_label.cget('text'),
            'snapshot_id': (app.doc or {}).get('snapshot_id'),
            'unit_calculations': [{k:u.get(k) for k in ('unit_id','unit_kind','basic_combat_power',
                'morale','attack_model','native_attack_index','native_attack_index_full_morale',
                'target_attack_unit','target_attack_full_morale','effective_skill_mask','move_remaining_raw')}
                for u in ((app.doc or {}).get('entities') or {}).get('field_units') or []],
            'map_unit_labels': [__import__('map_unit_labels').unit_label(app.doc or {}, u)
                for u in ((app.doc or {}).get('entities') or {}).get('field_units') or []],
            'terrain_encoding': ((app.doc or {}).get('terrain_grid') or {}).get('encoding'),
            'movement_rules': (app.doc or {}).get('movement_rules'),
            'wild_rows': [list(app.tables['wild'].item(i)['values']) for i in app.tables['wild'].get_children()],
            'wild_filter_note': app.talent_filters.result.cget('text'),
            'hidden_barrier_wild': len(__import__('wild_locations').wild_location_groups(app.doc or {})[1]),
            'player_force_id': (app.doc or {}).get('player_force_id'),
            'player_context': (app.doc or {}).get('player_context'),
            'talent_columns': [app.city_talent.tree.heading(c)['text'] for c in app.city_talent.tree['columns']],
            'war_unit_text': {
                'color': __import__('force_relations').WAR_UNIT_FOREGROUND,
                'global': [app.row_records['field_units'][i].get('owner_raw') for i in app.tables['field_units'].get_children() if __import__('force_relations').WAR_UNIT_TAG in app.tables['field_units'].item(i)['tags']],
                'nearby': [app.nearby_intel.rows[i]['record'].get('owner_raw') for i in app.nearby_intel.tree.get_children() if __import__('force_relations').WAR_UNIT_TAG in app.nearby_intel.tree.item(i)['tags']],
            },
            'city_columns': [tree.heading(c)['text'] for c in tree['columns']],
            'city_rows': [list(tree.item(i)['values']) for i in tree.get_children()],
            'officer_columns': [app.tables['officers'].heading(c)['text'] for c in app.tables['officers']['columns']],
            'officer_rows': [list(app.tables['officers'].item(i)['values']) for i in app.tables['officers'].get_children()],
            'selected_force_id': app.sel,
            'city_recruit_probability': ({'note':app.city_wild.note.cget('text'),
                'rows':[list(app.city_wild.tree.item(i)['values']) for i in app.city_wild.tree.get_children()]}
                if getattr(app,'city_wild',None) is not None else None),
            'nearby_defaults': {'radius': app.nearby_intel.radius.get(), 'origins': app.nearby_intel.origins.get(), 'filters': {k:bool(v.get()) for k,v in app.nearby_intel.filters.items()}},
            'war_force_ids': [int(i) for i in app.force_tree.get_children() if 'war' in app.force_tree.item(i)['tags']],
            'war_background': str(app.force_tree.tag_configure('war', 'background')),
            'force_unit_columns': [app.tables['force_units'].heading(c)['text'] for c in app.tables['force_units']['columns']],
            'force_unit_rows': [list(app.tables['force_units'].item(i)['values']) for i in app.tables['force_units'].get_children()],
            'force_unit_tab': app.book.tab(app.frames['force_units'], 'text'),
            'force_columns': [app.force_tree.heading(c)['text'] for c in app.force_tree['displaycolumns']],
            'algorithms':algorithm_widgets(),
            'original_portraits': __import__('original_sprites').CATALOG['portraits']['count'],
            'color_tables': len(app.force_name_colors.tables),
            'battle_tab': app.workspace.tab(app.battles, 'text'),
            'battle_rows': [list(app.battles.tree.item(i)['values']) for i in app.battles.tree.get_children()],
            'military_rows': {k:[(cell['value'] if isinstance(cell,dict) else cell).cget('text') for cell in cells] for k,cells in app.military.tiles.items()},
            'military_cities': [list(app.tables['cities'].item(i)['values']) for i in app.tables['cities'].get_children()],
            'military_columns': list(__import__('military_summary').COLS),
            'quarter_ops_tab': app.book.tab(app.quarter_ops.master, 'text'),
            'quarter_ops_input_tabs': [app.quarter_ops.lane_book.tab(t,'text') for t in app.quarter_ops.lane_book.tabs()],
            'quarter_ops_input_text': app.quarter_ops.input_log.get('1.0','end'),
            'quarter_ops_input_details': app.quarter_ops._input_details,
            'training_activity_text':app.training_record.activity.cget('text'),
            'training_activity_counts':app.training_record.activity_counts,
            'training_kind_activity':{k:v.cget('text') for k,v in app.training_record.kind_activity.items()},
            'quarter_ops_labels': list(getattr(app.quarter_ops, 'civil_labels', []) or []),
            'quarter_ops_military_labels': list(getattr(app.quarter_ops, 'military_labels', []) or []),
            'force_talent_tab': app.book.tab(app.force_talent.master, 'text'),
            'force_talent_labels': list(getattr(app.force_talent, 'civil_labels', []) or []),
            'workspace_tabs': [app.workspace.tab(t, 'text') for t in app.workspace.tabs()],
            'force_right_tabs': [app.book.tab(t, 'text') for t in app.book.tabs()],
            'preparation_tab': app.book.tab(app.preparation, 'text'),
            'preparation_columns': [app.preparation.tree.heading(c)['text'] for c in app.preparation.tree['columns']],
            'preparation_status': app.preparation.status.cget('text'),
            'preparation_rows': [list(app.preparation.tree.item(i)['values']) for i in app.preparation.tree.get_children()],
            'card_effect_rows': list(app.diplomacy_cards.rows.values()),
            'force_rows': [list(app.force_tree.item(i)['values']) for i in app.force_tree.get_children()],
            'force_badges': __import__('command_effects').force_badges(app.doc),
            'force_art_badges': {str(fid): cached[0][-1] for fid,cached in app.force_art.rows.items()},
        }
        if os.environ.get('SGI_VERIFY_COMMANDS')=='1' and app.doc:
            # Inspect this app's actual force-filtered widgets; restore the
            # selected force and folding state before returning to the event loop.
            from command_display import command_groups
            panel=app.quarter_ops
            commands=app.doc.get('native_command_evidence') or {}
            saved=set(panel._expanded_additions);views={};training_views={}
            training_tab=app.training_record.kind_book.select()
            force_ids={r['actor_force_id'] for r in commands.get('rows',[])}
            history=app.doc.get('history') or {}
            for account in list(history.get('quarters') or [])+[history.get('current_quarter')]:
                if account:force_ids.update(f['owner'] for f in account.get('forces') or [] if f.get('operations'))
            for fid in sorted(force_ids):
                panel.update_force({'force_id':fid},app.doc)
                app.training_record.update_activity(fid,app.doc)
                training_views[str(fid)]={'summary':app.training_record.activity.cget('text'),
                    'counts':app.training_record.activity_counts,
                    'kinds':{k:v.cget('text') for k,v in app.training_record.kind_activity.items()}}
                collapsed=panel.input_log.get('1.0','end')
                groups=command_groups([r for r in commands['rows'] if r['actor_force_id']==fid],app.doc.get('history'))
                panel._expanded_additions.update((fid,g['calendar']) for g in groups)
                panel._paint_sig=None;panel.update_force({'force_id':fid},app.doc)
                views[str(fid)]={'collapsed':collapsed,'expanded':panel.input_log.get('1.0','end'),
                                 'military':panel.military_log.get('1.0','end')}
            panel._expanded_additions=saved;panel._paint_sig=None
            panel.update_force({'force_id':app.sel},app.doc)
            app.training_record.update_activity(app.sel,app.doc)
            app.training_record.kind_book.select(training_tab)
            data['command_force_views']=views
            data['training_force_views']=training_views
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')
    root.after(8000, capture)
