import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from native_command_evidence import CommandEvidenceReader, decode, command_line, SANPK_BUILD, KOEINM_SHA
from test_native_input_evidence import fixture


def packet(name='CSanInetDomesticCmd', subtype=0, actor=16, target=589, parameter=0):
    kind={'CSanInetDomesticCmd':18,'CSanInetDiplomacyCmd':19,'CSanInetPersonnelCmd':20}[name]
    body=struct.pack('<3i',kind,subtype,0)+b'\0'
    if kind==18:body+=struct.pack('<4i',actor,parameter,240,1)
    elif kind==19:body+=bytes((0,9,0,0,0))+struct.pack('<4i',actor,-1,-1,0)+struct.pack('<5H',26,12,24,13,0)
    else:body+=struct.pack('<2i',actor,target)
    return struct.pack('<3H',0xffff,1,len(name))+name.encode()+body


class CommandEvidenceTests(unittest.TestCase):
    def test_real_sortie_serialization_and_no_fabricated_unit_id(self):
        from test_action_timeline import CREATE
        raw=bytes.fromhex(CREATE);row=decode(raw)
        self.assertEqual((row['actor_force_id'],row['troop_kind_raw'],row['general_ids_raw']),(5,0,[554,-1,-1]))
        self.assertEqual((row['soldiers_raw'],row['rice_raw']),(5000,5000))
        self.assertEqual(row['placement_raw'],[1,1,-1,-1])
        self.assertNotIn('unit_id',row)
        self.assertIsNone(row['command_committed']);self.assertFalse(row['action_training_eligible'])
        for change in ((4,'<i',1),(13,'<h',4),(15,'<h',32),(17,'<h',-2),(23,'<i',-1)):
            bad=bytearray(raw);struct.pack_into(change[1],bad,30+change[0],change[2])
            with self.assertRaises(ValueError):decode(bytes(bad))

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.payload,prefix,_=fixture()
        self.payload['state']['build_sha256']=SANPK_BUILD
        self.bound=dict(prefix[0]['bound'],build=SANPK_BUILD)
        digest=hashlib.sha256(json.dumps(self.bound,sort_keys=True).encode()).hexdigest()[:20]
        self.folder=self.root/'native-payload-observations'/digest;self.folder.mkdir(parents=True)
        self.path=self.folder/'one-seg-0001.jsonl';self.reader=CommandEvidenceReader(self.root)

    def event(self, raw=None, pointer=0x222222):
        raw=raw or packet()
        return dict(schema='native-payload-observation-1',kind='network_payload_observation',
                    fake=False,read_only=True,no_target_calls=True,binding=self.bound,
                    target=self.payload['identity'],build=SANPK_BUILD,source_id='MAC',core=0x100000,
                    module=dict(sha256=KOEINM_SHA,fake=False),raw_hex=raw.hex(),
                    raw_sha256=hashlib.sha256(raw).hexdigest(),payload_length=len(raw),
                    captured_at='2026-10-10T09:02:00+00:00',queue='alternate',array=0x333333,
                    entry_index=0,entry_hex=struct.pack('<3I',45,pointer,len(raw)).hex(),
                    payload_pointer=pointer,metadata_raw=45)

    def write(self, events, path=None, mode='wb'):
        with (path or self.path).open(mode) as out:
            for event in events:out.write(json.dumps(event).encode()+b'\n')

    def test_reconnect_build_journal_accepts_exact_hash_and_retains_original_line(self):
        from network_payloads import KOEINM_RECONNECT_R1_SHA
        from native_command_evidence import _accept
        event = self.event()
        event['module']['sha256'] = KOEINM_RECONNECT_R1_SHA
        self.write([event])
        original = self.path.read_bytes()
        rows = self.reader.read(self.payload)['rows']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['source_line_sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(self.path.read_bytes(), original)
        event['module']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'module hash'):
            _accept(event, self.bound)

    def test_retained_construction_packets_are_not_rice_trades(self):
        samples=[('ffff010013004353616e496e6574446f6d6573746963436d64120000000400000030006c000012000000080000001e00000072000000','建牧场',[48,108]),
                 ('ffff010013004353616e496e6574446f6d6573746963436d6412000000040000001e007a0000120000000600000052000000d0070000','建陷阱',[30,122])]
        for raw,label,xy in samples:
            row=decode(bytes.fromhex(raw))
            self.assertEqual(row['action'],label)
            self.assertEqual(row['target_xy_raw'],xy)
            self.assertEqual(row['actor_force_id'],18)
            self.assertFalse(row['server_result_verified'])
            self.assertIn('目标坐标',command_line(dict(row,observed_at='2026-10-10T15:46:23+00:00')))

    def test_native_menu_trade_direction_and_unknown_parameters(self):
        self.assertEqual(decode(packet(subtype=3,parameter=0))['action'],'卖米')
        self.assertEqual(decode(packet(subtype=3,parameter=1))['action'],'买米')
        self.assertEqual(decode(packet(subtype=3,parameter=9))['action'],'米交易（方向未解码）')
        self.assertEqual(decode(packet(subtype=4,parameter=99))['action'],'内政指令 #4（类别未解码）')
        for parameter,label in ((4,'建火计'),(5,'建落石'),(6,'建陷阱'),(7,'建练兵所'),(8,'建牧场'),(9,'建弓工坊')):
            self.assertEqual(decode(packet(subtype=4,parameter=parameter))['action'],label)

    def test_real_coordinate_operands_for_demolition_and_scout_are_not_player_slots(self):
        samples=[('ffff010013004353616e496e6574446f6d6573746963436d64120000000800000039005a00000b000000000000000000000000000000','侦察',[57,90]),
                 ('ffff010013004353616e496e6574446f6d6573746963436d64120000000500000042005600000b000000000000000000000000000000','拆除',[66,86])]
        for raw,label,xy in samples:
            row=decode(bytes.fromhex(raw))
            self.assertEqual(row['action'],label);self.assertEqual(row['actor_force_id'],11)
            self.assertEqual(row['target_xy_raw'],xy);self.assertGreater(row['sender_raw'],7)
            self.assertIsNone(row['command_committed']);self.assertFalse(row['server_result_verified'])
            self.assertIn('目标坐标',command_line(dict(row,observed_at='2026-10-10T14:12:30+00:00')))

    def test_verified_layouts_decode_actual_operands_and_unknown_settlement(self):
        cases=[(packet(), '步兵训练'),(packet('CSanInetDomesticCmd',2),'施舍'),
               (packet('CSanInetDiplomacyCmd',3),'更换外交卡片'),
               (packet('CSanInetDiplomacyCmd',4),'外交卡片排序'),
               (packet('CSanInetPersonnelCmd',5),'加增武将'),
               (packet('CSanInetPersonnelCmd',1),'接纳仕官')]
        for raw,label in cases:
            row=decode(raw);self.assertEqual(row['action'],label)
            self.assertEqual(row['actor_force_id'],16)
            self.assertIsNone(row['command_committed']);self.assertIsNone(row['game_quarter'])
            self.assertFalse(row['action_training_eligible']);self.assertFalse(row['server_result_verified'])
        self.assertEqual(decode(cases[3][0])['cards_raw'],[26,12,24,13,0])

    def test_unknown_subtype_stays_numbered_and_damaged_or_unproven_layout_rejected(self):
        self.assertEqual(decode(packet(subtype=90))['action'],'内政指令 #90')
        raw=packet()
        bad=[raw[:-1],raw+b'\0',b'\x01\x80'+raw[2:],raw[:2]+b'\x02\0'+raw[4:],
             packet(actor=32),raw.replace(b'CSanInetDomesticCmd',b'XSanInetDomesticCmd')]
        for value in bad:
            with self.assertRaises(ValueError):decode(value)

    def test_independent_of_x3_reads_retro_packets_with_sha_and_byte_provenance(self):
        self.write([self.event()]);original=self.path.read_bytes()
        result=self.reader.read(self.payload);self.assertEqual(len(result['rows']),1)
        row=result['rows'][0];source=original[row['source_byte_offset']:].splitlines(keepends=True)[0]
        self.assertEqual(hashlib.sha256(source).hexdigest(),row['source_line_sha256'])
        self.assertEqual(row['raw_hex'],packet().hex());self.assertTrue(row['process_scope_only'])
        self.assertIsNone(row['match_id']);self.assertFalse(result['complete_command_stream'])
        self.assertIn('240',command_line(row));self.assertIn('首次采样',command_line(row))
        self.assertEqual(self.path.read_bytes(),original)
        self.assertEqual(self.reader.read(self.payload)['rows'],result['rows'])

    def test_stale_queue_entry_across_recovery_is_grouped_not_another_command(self):
        event=self.event();self.write([event])
        second=dict(event,captured_at='2026-10-10T09:09:00+00:00')
        self.write([second],self.folder/'two-seg-0001.jsonl')
        row=self.reader.read(self.payload)['rows'][0]
        self.assertEqual(row['observations'],2);self.assertIsNone(row['repeated_command_count'])
        self.assertEqual(row['observed_at'],event['captured_at'])
        self.assertEqual(row['last_observed_at'],second['captured_at'])
        moved=dict(event,queue='primary',array=0x555555,entry_index=3)
        self.write([moved],mode='ab')
        self.assertEqual(len(self.reader.read(self.payload)['rows']),1)
        self.write([self.event(pointer=0x222223)],mode='ab')
        self.assertEqual(len(self.reader.read(self.payload)['rows']),2)

    def test_wrong_process_source_module_hash_or_payload_hash_cannot_be_decoded(self):
        bad=[]
        for change in (lambda e:e.update(source_id='OTHER'),lambda e:e['binding'].update(created=99),
                       lambda e:e['target'].update(pid=12),lambda e:e['module'].update(sha256='bad'),
                       lambda e:e.update(raw_sha256='bad'),lambda e:e.update(fake=True),
                       lambda e:e.update(metadata_raw=46)):
            event=copy.deepcopy(self.event());change(event);bad.append(event)
        self.write(bad);result=self.reader.read(self.payload)
        self.assertFalse(result['rows']);self.assertEqual(result['errors'],len(bad))

    def test_remote_stale_other_process_and_player_sessions_are_handled_explicitly(self):
        self.write([self.event()]);self.assertTrue(self.reader.read(self.payload)['rows'])
        self.assertFalse(self.reader.read(self.payload,remote=True)['rows'])
        self.assertFalse(self.reader.read(dict(self.payload,fresh=False))['rows'])
        changed=copy.deepcopy(self.payload);changed['identity']['creation_filetime']+=1
        self.assertFalse(self.reader.read(changed)['rows'])
        # Player session changes on capture gaps; these bytes are deliberately
        # process-scoped, never promoted into a match or current-round action.
        changed=copy.deepcopy(self.payload);changed['state']['player_identity']['session_id']='new'
        result=self.reader.read(changed);self.assertEqual(len(result['rows']),1)
        self.assertTrue(result['process_scope_only']);self.assertIsNone(result['rows'][0]['match_id'])

    def test_partial_append_unsupported_and_gaps_are_visible_without_fabricating(self):
        line=json.dumps(self.event()).encode();self.path.write_bytes(line[:20])
        self.assertFalse(self.reader.read(self.payload)['rows'])
        with self.path.open('ab') as out:out.write(line[20:]+b'\n')
        self.assertEqual(len(self.reader.read(self.payload)['rows']),1)
        unsupported=packet().replace(b'CSanInetDomesticCmd',b'XSanInetDomesticCmd')
        self.write([self.event(unsupported),dict(kind='network_payload_gap',reason='budget')],mode='ab')
        result=self.reader.read(self.payload)
        self.assertEqual(len(result['rows']),1);self.assertEqual(result['unsupported'],1)
        self.assertEqual(result['gaps'],1)


if __name__=='__main__':unittest.main()
