import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from native_command_evidence import decode
from scout_location import retain_locations, location_text, valid_reference, steps
import test_native_command_evidence as native

RAW = bytes.fromhex('ffff010013004353616e496e6574446f6d6573746963436d64120000000800000039005a00000b000000000000000000000000000000')


def fixture():
    f=native.CommandEvidenceTests();f.setUp()
    f.write([f.event(RAW)])
    p=f.payload
    p['state'].update(identity=copy.deepcopy(p['identity']),snapshot_id='historical-source-frame',
        capture_end='2026-10-10T14:12:31+00:00',
        scenario_map=dict(id='china',known=True,width=101,height=202))
    p['state']['entities']['cities_and_barriers']=[dict(city_id=12,name='许昌',type='city',owner_raw=0,world_xy_raw=[57,89])]
    p['state']['entities']['lords'].append(dict(force_id=0,name='魏',capital_city_id=12))
    return f,p,f.reader.read(p)


class ScoutLocationTests(unittest.TestCase):
    def setUp(self):
        self.f,self.p,self.commands=fixture();self.addCleanup(self.f.doCleanups)

    def test_real_packet_near_and_exact_capital_names(self):
        result=retain_locations(self.commands,self.p['state']);row=result['rows'][0]
        self.assertEqual(location_text(row,result['binding']),'魏都许昌附近')
        exact=copy.deepcopy(self.commands);exact['rows'][0]['target_xy_raw']=[57,89]
        exact=retain_locations(exact,self.p['state'])
        self.assertEqual(location_text(exact['rows'][0],exact['binding']),'魏都许昌')
        self.assertEqual(steps([57,89],[57,90]),1)
        self.assertNotIn('scout_reference',self.commands['rows'][0])
        self.assertIsNone(row['command_committed']);self.assertFalse(row['action_training_eligible'])

    def test_far_tied_or_unowned_capitals_do_not_get_false_names(self):
        state=copy.deepcopy(self.p['state'])
        state['entities']['cities_and_barriers'][0]['world_xy_raw']=[10,10]
        r=retain_locations(self.commands,state);self.assertEqual(location_text(r['rows'][0],r['binding']),'57,90')
        state=copy.deepcopy(self.p['state']);state['entities']['cities_and_barriers'].append(dict(city_id=13,name='另一城',type='city',owner_raw=0,world_xy_raw=[57,91]))
        r=retain_locations(self.commands,state);self.assertEqual(location_text(r['rows'][0],r['binding']),'57,90')
        state=copy.deepcopy(self.p['state']);state['entities']['cities_and_barriers'][0]['owner_raw']=65535
        r=retain_locations(self.commands,state);self.assertEqual(location_text(r['rows'][0],r['binding']),'许昌附近')

    def test_wrong_process_unknown_map_and_regional_coordinates_stay_unresolved(self):
        for mutate in (lambda s:s['identity'].update(creation_filetime=0),lambda s:s['scenario_map'].update(known=False),lambda s:s['scenario_map'].update(id='central',width=55,height=127)):
            state=copy.deepcopy(self.p['state']);mutate(state)
            self.assertNotIn('scout_reference',retain_locations(self.commands,state)['rows'][0])

    def test_reference_rejects_target_source_and_schema_tampering(self):
        r=retain_locations(self.commands,self.p['state']);row=r['rows'][0];bound=r['binding']
        self.assertTrue(valid_reference(row,row['scout_reference'],bound))
        for change in (lambda x:x.update(target_xy=[58,90]),lambda x:x.update(binding_sha256='other'),lambda x:x.update(map_id='central'),lambda x:x.update(cities=x['cities']*9),lambda x:x['forces'][0].update(force_id=32)):
            ref=copy.deepcopy(row['scout_reference']);change(ref)
            self.assertFalse(valid_reference(row,ref,bound))

    def test_cache_preserves_first_reference_across_capital_change_and_restart(self):
        from command_view_store import CommandViewStore
        store=CommandViewStore(self.f.root);original=self.f.path.read_bytes()
        result=store.remember(self.p,self.commands)
        self.p['state']['entities']['lords'][-1]['capital_city_id']=99
        self.p['state']['capture_end']='2026-10-10T15:00:00+00:00'
        changed=store.remember(self.p,self.commands)
        self.assertEqual(result['rows'][0]['scout_reference'],changed['rows'][0]['scout_reference'])
        offline=CommandViewStore(self.f.root).load('MAC')
        self.assertEqual(location_text(offline['native_command_evidence']['rows'][0],offline['binding']),'魏都许昌附近')
        self.assertEqual(self.f.path.read_bytes(),original);self.assertNotIn('state',offline)

    def test_remote_reference_roundtrip_and_binding_rejection(self):
        from command_transport import SourceCommandExporter, import_commands
        wire=SourceCommandExporter(self.f.root).attach(self.p)
        result=import_commands(wire)
        self.assertEqual(location_text(result['rows'][0],result['binding']),'魏都许昌附近')
        wire['state']['native_command_transfer']['rows'][0]['scout_reference']['binding_sha256']='wrong source'
        self.assertEqual(import_commands(wire)['status'],'remote_invalid')

    def test_static_range_uses_four_neighbours_and_clips_at_edges(self):
        from scout_location import scout_cells
        cells=scout_cells([57,90])
        self.assertEqual(len(cells),41)
        self.assertTrue(all(steps([57,90],p)<=4 for p in cells))
        edge=scout_cells([0,0],(55,127))
        self.assertLess(len(edge),41);self.assertTrue(all(0<=x<55 and 0<=y<127 for x,y in edge))


class ScoutMapUiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.root=tk.Tk();self.root.withdraw()
        self.f,self.p,self.commands=fixture();self.addCleanup(self.f.doCleanups)

    def tearDown(self):
        self.root.destroy()

    def test_real_click_opens_frozen_center_and_41_cells_not_city_center(self):
        import re
        from quarter_ops_panel import QuarterOpsPanel
        commands=retain_locations(self.commands,self.p['state'])
        panel=QuarterOpsPanel(self.root);panel.pack()
        panel.update_force({'force_id':11},dict(native_command_evidence=commands))
        self.assertIn('1. 侦察 魏都许昌附近',panel.input_log.get('1.0','end'))
        tag=next(t for t in panel.input_log.tag_names() if str(t).startswith('command_'))
        callback=panel.input_log.tk.call(panel.input_log._w,'tag','bind',tag,'<Button-1>')
        panel.input_log.tk.call(re.search(r'\[([^\s]+)',callback).group(1))
        self.root.update()
        locator=panel.scout_window.locator
        self.assertEqual(locator.scout_center,(57,90));self.assertEqual(locator.center,(57.5,90.5))
        self.assertEqual(len(locator.canvas.find_withtag('scout_range')),41)
        self.assertEqual(len(locator.canvas.find_withtag('scout_center')),2)
        self.assertIn('结果未确认',locator.note.cget('text'))
        self.assertEqual(locator.state['entities']['field_units'],[])
        locator.pan(1,0);self.assertNotEqual(locator.center,(57.5,90.5))
        locator.return_target();self.assertEqual(locator.center,(57.5,90.5))
        panel.update_force({'force_id':0},dict(native_command_evidence=commands))
        self.assertFalse(any(str(t).startswith('command_') for t in panel.input_log.tag_names()))


if __name__=='__main__':unittest.main()
