"""Preselection document names are observed independently of match force attribution."""
import struct
import unittest
from unittest.mock import patch
from player_slots import (read_lobby_player_slots, VERIFIED_BUILD, DOC_VTABLE, CORE_VTABLE, PLAYER_VTABLE, CORE_ANCHOR)
from test_player_slots import Sparse, plant_name, RAW, CORE

DOC=CORE-0x912

def memory():
    m=Sparse();m.write(DOC,struct.pack('<I',DOC_VTABLE));m.write(CORE,struct.pack('<I',CORE_VTABLE))
    m.write(CORE_ANCHOR,struct.pack('<I',CORE))
    for slot in range(8):
        plant_name(m,slot,123 if slot==0 else 0,0,0xFFFFFFFF,RAW if slot==0 else b'',core=DOC+0xB0)
        m.write(DOC+0xB4+slot*0x87,struct.pack('<I',PLAYER_VTABLE))
    return m

class LobbyPlayerTests(unittest.TestCase):
    def test_name_survives_unselected_force_without_becoming_match_attribution(self):
        m=memory()
        with patch('player_slots._target_code_page',return_value=(936,'target_ntdll_NlsAnsiCodePage',True,{'test':True})):
            v=read_lobby_player_slots(m,CORE,VERIFIED_BUILD)
        self.assertEqual(len(v['player_slots']),8)
        row=v['player_slots'][0]
        self.assertEqual(row['nickname'],'韩立(筑基后期)')
        self.assertEqual(row['status'],'observed')
        self.assertEqual(row['force_id_raw'],0xFFFFFFFF)
        self.assertNotIn('force_id',row)
        self.assertFalse(row['force_attribution_confirmed'])
        self.assertIn('doc+0xB4',row['static_source']['slot'])
        self.assertFalse(v['layout']['force_attribution_confirmed'])
        self.assertNotIn(DOC+0xB4+8*0x87,[a for a,n in m.calls])

    def test_unknown_build_or_changed_roots_do_not_publish_names(self):
        m=memory()
        self.assertEqual(read_lobby_player_slots(m,CORE,'unknown')['player_slots'],[])
        self.assertEqual(m.calls,[])
        m.write(DOC,b'BAD!')
        self.assertEqual(read_lobby_player_slots(m,CORE,VERIFIED_BUILD)['player_slots'],[])
        m=memory();m.flip_on[DOC]=2
        with patch('player_slots._target_code_page',return_value=(936,'target_ntdll_NlsAnsiCodePage',True,None)):
            self.assertEqual(read_lobby_player_slots(m,CORE,VERIFIED_BUILD)['player_slots'],[])

    def test_changed_slot_or_wrong_player_vtable_is_unknown(self):
        for mutate in ('flip','vtable'):
            m=memory();addr=DOC+0xB4
            if mutate=='flip':m.flip_on[addr]=3
            else:m.write(addr,b'BAD!')
            with patch('player_slots._target_code_page',return_value=(936,'target_ntdll_NlsAnsiCodePage',True,None)):
                row=read_lobby_player_slots(m,CORE,VERIFIED_BUILD)['player_slots'][0]
            self.assertIsNone(row['nickname'])
            self.assertEqual(row['status'],'unknown')
            self.assertFalse(row['force_attribution_confirmed'])
            self.assertEqual(row['static_source']['kind'],'document_lobby_layout')

    def test_missing_target_codepage_keeps_raw_and_never_guesses(self):
        with patch('player_slots._target_code_page',return_value=(None,'target_ntdll_unavailable',False,None)):
            row=read_lobby_player_slots(memory(),CORE,VERIFIED_BUILD)['player_slots'][0]
        self.assertIsNone(row['nickname'])
        self.assertEqual(row['raw_hex'],RAW.hex())
        self.assertEqual(row['reason'],'code_page_unavailable')

    def test_changed_or_different_anchor_discards_the_document_observation(self):
        for changed in (False,True):
            m=memory()
            if changed:m.flip_on[CORE_ANCHOR]=2
            else:m.write(CORE_ANCHOR,struct.pack('<I',CORE+0x1000))
            with patch('player_slots._target_code_page',return_value=(936,'target_ntdll_NlsAnsiCodePage',True,None)):
                self.assertEqual(read_lobby_player_slots(m,CORE,VERIFIED_BUILD)['player_slots'],[])
