import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from game_archive import build_demo_state, write_packed_archive
from native_command_evidence import SANPK_BUILD
from sortie_observations import SortieObservations


class SortieObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        before=build_demo_state(1);before.update(core_address='0xabc',build_sha256=SANPK_BUILD)
        before['entities']['field_units']=[]
        after=copy.deepcopy(before);after.update(snapshot_id='appearance',capture_end='2026-09-16T01:00:02+00:00')
        after['entities']['field_units']=[dict(unit_id=9,unit_kind='步兵',owner_raw=0,general_ids=[3],
            world_xy_raw=[50,101],soldiers_candidate=5000,training_degree=50,target_attack_unit='54')]
        later=copy.deepcopy(after);later.update(snapshot_id='later',capture_end='2026-09-16T01:00:03+00:00')
        later['entities']['field_units'][0].update(training_degree=99,target_attack_unit='999')
        self.path=write_packed_archive(self.root/'training-archives'/'match', [before,after,later],
                                      extra_manifest=dict(source_id='SOURCE'))
        item=dict(field='出征',line='出征 步兵#9（演示将） 出现于 (50,101)',command=True,
                  target=dict(kind='field_units',unit_id=9,world_xy_raw=[50,101]))
        history=dict(quarters=[dict(phase=dict(year_u16=200,season_u16=1),
            **{'from':before['capture_end'],'to':later['capture_end']},forces=[dict(owner=0,operations=[item])])])
        self.payload=dict(fresh=True,identity=before['identity'],source_id='SOURCE',state=dict(later,history=history))

    def item(self,result):
        return result['state']['history']['quarters'][0]['forces'][0]['operations'][0]

    def test_appearance_values_are_frozen_and_original_files_unchanged(self):
        files={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.path.iterdir() if p.is_file()}
        original=copy.deepcopy(self.payload)
        result=SortieObservations(self.root).attach(self.payload)
        item=self.item(result)
        self.assertEqual(item['unit_snapshot']['target_attack_unit'],'54')
        self.assertEqual(item['unit_snapshot']['training_degree'],50)
        self.assertEqual(item['snapshot_id'],'appearance')
        self.assertEqual(item['sortie_archive_reference']['seq'],2)
        self.assertEqual(self.payload,original)
        self.assertEqual(files,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in files})

    def test_other_source_process_build_core_name_position_or_time_is_rejected(self):
        changes=[lambda p:p.update(source_id='OTHER'),lambda p:p['identity'].update(creation_filetime=99),
                 lambda p:p['state'].update(build_sha256='other'),lambda p:p['state'].update(core_address='0xdef'),
                 lambda p:self.item(p).update(line='出征 步兵#9（别人） 出现于 (50,101)'),
                 lambda p:self.item(p)['target'].update(world_xy_raw=[51,101]),
                 lambda p:p['state']['history']['quarters'][0].update({'from':'2026-09-16T01:00:02+00:00'})]
        for change in changes:
            p=copy.deepcopy(self.payload);change(p)
            self.assertNotIn('unit_snapshot',self.item(SortieObservations(self.root).attach(p)))

    def test_bad_archive_sha_and_existing_unit_never_become_appearance_values(self):
        frame=self.path/'frames.jsonl';lines=frame.read_bytes().splitlines(keepends=True)
        wrapper=json.loads(lines[1]);wrapper['sha256']='0'*64
        lines[1]=json.dumps(wrapper).encode()+b'\n';frame.write_bytes(b''.join(lines))
        self.assertNotIn('unit_snapshot',self.item(SortieObservations(self.root).attach(self.payload)))

    def test_stale_game_is_not_restored(self):
        p=dict(self.payload,fresh=False)
        self.assertIs(SortieObservations(self.root).attach(p),p)


if __name__=='__main__':unittest.main()
