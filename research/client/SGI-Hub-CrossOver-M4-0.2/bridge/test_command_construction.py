import copy
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from command_construction import retain_construction, valid_construction
from command_display import short_command
import test_native_command_evidence as native

RAW = bytes.fromhex('ffff010013004353616e496e6574446f6d6573746963436d6412000000040000001e007a0000120000000600000052000000d0070000')


def fixture():
    f=native.CommandEvidenceTests();f.setUp();f.write([f.event(RAW)])
    p=f.payload
    p['state'].update(identity=copy.deepcopy(p['identity']),snapshot_id='construction-city-frame',
                      capture_end='2026-10-10T09:03:00+00:00',
                      scenario_map=dict(id='china',known=True,width=101,height=202))
    p['state']['entities']['cities_and_barriers']=[dict(city_id=82,name='临江',type='city',owner_raw=18,world_xy_raw=[29,123]),
                                                  dict(city_id=83,name='更近的城',type='city',owner_raw=19,world_xy_raw=[30,122])]
    return f,p,f.reader.read(p)


class ConstructionReferenceTests(unittest.TestCase):
    def setUp(self):
        self.f,self.p,self.commands=fixture();self.addCleanup(self.f.doCleanups)

    def test_names_use_packet_city_id_not_nearest_city_and_keep_original_operands(self):
        out=retain_construction(self.commands,self.p['state']);row=out['rows'][0]
        self.assertEqual(short_command(row),'建陷阱 临江')
        self.assertEqual(row['value_raw'],82);self.assertEqual(row['target_xy_raw'],[30,122])
        self.assertIsNone(row['command_committed']);self.assertFalse(row['action_training_eligible'])
        self.assertNotIn('construction_reference',self.commands['rows'][0])
        self.assertEqual(short_command(self.commands['rows'][0]),'建陷阱 城池#82')

    def test_wrong_source_map_early_snapshot_missing_and_ambiguous_city_stay_unresolved(self):
        for mutate in (lambda s:s['identity'].update(pid=1),lambda s:s['identity'].update(creation_filetime=0),
                       lambda s:s.update(build_sha256='other'),lambda s:s['scenario_map'].update(known=False),
                       lambda s:s['scenario_map'].update(id='central'),
                       lambda s:s.update(capture_end='2026-10-10T09:01:00+00:00'),
                       lambda s:s['entities'].update(cities_and_barriers=[]),
                       lambda s:s['entities']['cities_and_barriers'].append(copy.deepcopy(s['entities']['cities_and_barriers'][0]))):
            state=copy.deepcopy(self.p['state']);mutate(state)
            self.assertNotIn('construction_reference',retain_construction(self.commands,state)['rows'][0])

    def test_reference_rejects_city_target_source_and_coordinate_tampering(self):
        out=retain_construction(self.commands,self.p['state']);row=out['rows'][0]
        self.assertTrue(valid_construction(row,row['construction_reference'],out['binding']))
        for mutate in (lambda r:r.update(binding_sha256='other'),lambda r:r['city'].update(city_id=83),
                       lambda r:r.update(target_xy=[29,122]),lambda r:r['city'].update(world_xy_raw=[102,1]),
                       lambda r:r.update(map_id='unknown'),lambda r:r['city'].update(name='')):
            ref=copy.deepcopy(row['construction_reference']);mutate(ref)
            self.assertFalse(valid_construction(row,ref,out['binding']))

    def test_cache_and_remote_keep_name_after_disconnect_without_live_state(self):
        from command_view_store import CommandViewStore
        from command_transport import SourceCommandExporter, import_commands, import_retained
        original=self.f.path.read_bytes();store=CommandViewStore(self.f.root)
        out=store.remember(self.p,self.commands);ref=copy.deepcopy(out['rows'][0]['construction_reference'])
        self.p['state']['entities']['cities_and_barriers'][0]['name']='后来的城名'
        merged=store.remember(self.p,self.commands)
        self.assertEqual(merged['rows'][0]['construction_reference'],ref)
        restored=CommandViewStore(self.f.root).load('MAC')
        self.assertEqual(short_command(restored['native_command_evidence']['rows'][0]),'建陷阱 临江')
        exporter=SourceCommandExporter(self.f.root);wire=exporter.attach(self.p)
        self.assertEqual(short_command(import_commands(wire)['rows'][0]),'建陷阱 临江')
        stale=exporter.attach(dict(self.p,fresh=False,state=None,identity=None))
        remote=import_retained(stale)
        self.assertEqual(short_command(remote['native_command_evidence']['rows'][0]),'建陷阱 临江')
        self.assertNotIn('state',remote);self.assertEqual(self.f.path.read_bytes(),original)
        wire['state']['native_command_transfer']['rows'][0]['construction_reference']['city']['city_id']=83
        self.assertEqual(import_commands(wire)['status'],'remote_invalid')


class ConstructionMapUiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.root=tk.Tk();self.root.withdraw()
        self.f,self.p,self.commands=fixture();self.addCleanup(self.f.doCleanups)

    def tearDown(self):
        self.root.destroy()

    def test_city_name_click_opens_city_center_and_marks_packet_target_offline(self):
        from quarter_ops_panel import QuarterOpsPanel
        commands=retain_construction(self.commands,self.p['state'])
        panel=QuarterOpsPanel(self.root);panel.pack()
        panel.update_force({'force_id':18},dict(native_command_evidence=commands))
        self.assertIn('1. 建陷阱 临江',panel.input_log.get('1.0','end'))
        tag=next(t for t in panel.input_log.tag_names() if str(t).startswith('command_'))
        bounds=panel.input_log.tag_ranges(tag)
        self.assertEqual(panel.input_log.get(*bounds),'临江')
        callback=panel.input_log.tk.call(panel.input_log._w,'tag','bind',tag,'<Button-1>')
        panel.input_log.tk.call(re.search(r'\[([^\s]+)',callback).group(1));self.root.update()
        locator=panel.construction_window.locator
        self.assertEqual(locator.selected_id,82);self.assertEqual(locator.center,(29.5,123.5))
        self.assertEqual(locator.construction_target,(30,122))
        self.assertEqual(len(locator.canvas.find_withtag('construction_target')),2)
        self.assertTrue(locator.canvas.find_withtag('target'))
        self.assertIn('结果未确认',locator.note.cget('text'))
        self.assertEqual(locator.state['entities']['field_units'],[])
        locator.pan(1,0);self.assertNotEqual(locator.center,(29.5,123.5))
        locator.return_target();self.assertEqual(locator.center,(29.5,123.5))
        old=panel.construction_window;panel.input_log.tk.call(re.search(r'\[([^\s]+)',callback).group(1))
        self.assertFalse(old.winfo_exists());self.assertIsNotNone(panel.construction_window)
        panel.update_force({'force_id':19},dict(native_command_evidence=commands))
        self.assertFalse(any(str(t).startswith('command_') for t in panel.input_log.tag_names()))


if __name__=='__main__':unittest.main()
