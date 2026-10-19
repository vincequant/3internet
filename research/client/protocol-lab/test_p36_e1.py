#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P36 E1 離線測試：解碼器 + 事件重建（python3 -m unittest）。

黃金向量出處：evidence/p36-live-201443/ c4/c7/c9 真幀（2026-10-15）
＋ E2 注入幀（lo0-inject/validframe.pcap）。
"""
import os
import struct
import sys
import unittest
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import p36_e1_wire as W          # noqa: E402
import p36_e1_reconstruct as R   # noqa: E402

EVID = os.path.join(HERE, 'evidence', 'p36-live-201443')


def crc_loader(b):
    return zlib.crc32(b, 0xFFFFFFFF) & 0xFF


def build_bang(payload, vip=b'\x0a\x78\x48\x3a', port=0x1E61,
               src=b'\x0a\x63\x63\x63', sport=0x1E61):
    head = b'\x21\x00' + vip + struct.pack('>H', port) + src + \
        struct.pack('>H', sport) + struct.pack('<H', len(payload))
    body = head + payload
    return bytes([0x21, crc_loader(body[2:])]) + body[2:]


def build_chat_frame(msg, sender=b'\x0a\x78\x48\x3a', seq=7, ctr=0x1000,
                     dst=b'\x0a\x2e\x7a\x1c', dport=0xfa7e, marker=b'\x80\x00'):
    payload = struct.pack('>I', len(msg)) + msg
    plen = len(payload)
    body = (b'\x70' + sender + struct.pack('<I', seq) +
            struct.pack('<H', 13 + plen) + marker + dst +
            struct.pack('>H', dport) + struct.pack('<I', ctr) +
            bytes([plen]) + payload)
    return bytes([0x22, crc_loader(body)]) + body


def build_chat_msg(sender=b'\x0a\x78\x48\x3a', text='测试123'):
    return (b'\x06' + sender + b'\x46' + b'\x00' * 11 + b'\x07' +
            sender + b'\xff\xff\xff\xff' + text.encode('gbk') + b'\x00')


class TestPrimitives(unittest.TestCase):
    def test_id_mapping(self):
        self.assertEqual(W.be_id(bytes.fromhex('0a78483a')), 175654970)
        self.assertEqual(W.id_vip_string(175654970), '10.120.72.58')
        self.assertEqual(W.be_id(bytes.fromhex('0ae85a82')), 182999682)
        self.assertEqual(W.id_label(175654970, {175654970: '风云'}),
                         '风云(10.120.72.58)')

    def test_gbk_runs(self):
        runs = W.gbk_runs('风云'.encode('gbk'))
        self.assertEqual(runs[0][1], '风云')
        self.assertEqual(W.gbk_runs(b'\x0a\x09'), [])       # 非 GBK
        self.assertEqual(len(W.gbk_runs('好'.encode('gbk'))), 0)   # 單字默認濾除
        self.assertEqual(len(W.gbk_runs('好'.encode('gbk'), min_cjk=1)), 1)


class TestBang(unittest.TestCase):
    def test_roundtrip(self):
        f = build_bang(b'hello')
        d = W.decode_bang(f)
        self.assertTrue(d['ok'] and d['crc_ok'])
        self.assertEqual(d['deliver_port'], 7777)
        self.assertEqual(d['src_id'], 0x0A636363)
        self.assertEqual(d['src_port'], 7777)
        self.assertEqual(d['payload'], b'hello')

    def test_golden_inject_lo0(self):
        f = bytes.fromhex('21e4020000001e610a6363631e610900503336210000000000')
        d = W.decode_bang(f)
        self.assertTrue(d['ok'] and d['crc_ok'])
        self.assertTrue(d['vip_marker'])
        self.assertEqual(d['deliver_port'], 7777)
        self.assertEqual(d['payload_hex'], '503336210000000000')

    def test_delivery_marker(self):
        f = bytes.fromhex('503336210000000000ddccbbaa0a6363631e61')
        d = W.decode_delivered(f)
        self.assertTrue(d['ok'])
        self.assertEqual(d['game_payload'], b'P36!\x00\x00\x00\x00\x00')
        self.assertEqual(d['src_id'], 0x0A636363)
        self.assertEqual(d['src_port'], 7777)
        self.assertIsNone(d.get('reason'))


class TestUdtAndChat(unittest.TestCase):
    def test_synthetic_chat_roundtrip(self):
        msg = build_chat_msg(text='测试123')
        f = build_chat_frame(msg)
        d = W.decode_udt(f)
        self.assertTrue(d['crc_ok'])
        self.assertEqual(d['subtype_label'], 'udt_data')
        self.assertEqual(d['id'], 175654970)
        self.assertEqual(d['dst_id'], 170818076)
        m = d['msg']
        self.assertEqual(m['cmd'], 0x06)
        self.assertEqual(m['sender_id'], 175654970)
        self.assertEqual(m['chat_text'], '测试123')

    def test_golden_chat_hello2_c7(self):
        # evidence/p36-live-201443/c7-utun11.pcap 真幀（21:53:49）
        f = bytes.fromhex(
            '22b1700a78483af3030000320080010a2e7a1cfa7eb51000002500000021'
            '060a78483a460000000000000000000000070a78483affffffff68656c6c6f3200')
        d = W.decode_udt(f)
        self.assertTrue(d['crc_ok'])
        self.assertEqual(d['dst_id'], 170818076)
        self.assertEqual(d['msg']['chat_text'], 'hello2')

    def test_golden_bang_sgzwlb(self):
        # evidence c4-utun11.pcap 真幀（21:22:10 中繼下行，94B）
        f = bytes.fromhex(
            '21bd0ae85a82f5ac0a78483a1e614e000a78483a53475a574c4200000000000000000000000000000000000000000000000000b7e7d4c6000000000000000000000000000000000000000000000000000000000000080000000100000000')
        d = W.decode_bang(f)
        self.assertTrue(d['ok'] and d['crc_ok'])
        self.assertEqual(d['vip_id'], 182999682)
        self.assertEqual(d['deliver_port'], 0xf5ac)
        self.assertEqual(d['src_id'], 175654970)
        self.assertEqual(d['src_port'], 7777)
        self.assertEqual(d['plen'], 78)
        self.assertTrue(d['payload'].startswith(bytes.fromhex('0a78483a') + b'SGZWLB'))

    def test_golden_a4_wrapper(self):
        # evidence c4-utun11.pcap 真幀（21:22:10 上行，109B）
        f = bytes.fromhex(
            'a4000000000a78483a62000ae85a8221bd0ae85a82f5ac0a78483a1e614e000a78483a53475a574c4200000000000000000000000000000000000000000000000000b7e7d4c6000000000000000000000000000000000000000000000000000000000000080000000100000000')
        d = W.decode_a4(f)
        self.assertTrue(d['ok'])
        self.assertEqual(d['src_id'], 175654970)
        self.assertEqual(d['dst_id'], 182999682)
        self.assertEqual(d['inner']['class'], 'bang')
        self.assertTrue(d['inner']['crc_ok'])

    def test_golden_instr1000_lo0(self):
        # evidence c4-lo0.pcap 真幀（遊戲→loader 的 1000 指令）
        f = bytes.fromhex(
            'e803000000000a78483a1e610ae85a82f5ac4e000a78483a53475a574c4200000000000000000000000000000000000000000000000000b7e7d4c6000000000000000000000000000000000000000000000000000000000000080000000100000000')
        d = W.decode_frame(f)
        self.assertEqual(d['class'], 'instr1000')
        self.assertEqual(d['addr1_id'], 175654970)
        self.assertEqual(d['port1'], 7777)
        self.assertEqual(d['addr2_id'], 182999682)
        self.assertEqual(d['port2'], 0xf5ac)
        self.assertEqual(d['plen'], 78)


class TestRelayFrames(unittest.TestCase):
    def test_a3_roster(self):
        f = bytes.fromhex(
            'a33606000000000000220002000a78483adf4a94818cdbc612000111e101'
            '0ae85a82df4a94818b9dc612000111e201')
        d = W.decode_a3(f)
        self.assertTrue(d['ok'])
        self.assertEqual(d['count'], 2)
        self.assertEqual([e['id'] for e in d['entries']], [175654970, 182999682])
        self.assertEqual(d['entries'][0]['d1'], 0x81944adf)
        self.assertEqual(d['entries'][0]['flag'], 1)

    def test_a8_self_record(self):
        f = bytes.fromhex('a8350600000000000010000ae85a82df4a94818b9dc612000111e201')
        d = W.decode_frame(f)
        self.assertEqual(d['class'], 'a8')
        self.assertEqual(d['id'], 182999682)
        self.assertEqual(d['d1'], 0x81944adf)
        self.assertEqual(d['d3'], 0xe2110100)
        self.assertEqual(d['flag'], 1)

    def test_aa_update(self):
        f = bytes.fromhex('aa340600000000000011000ae85a82df4a94818b9dc612000111e201')
        d = W.decode_frame(f)
        self.assertEqual(d['class'], 'aa')
        self.assertEqual(d['id'], 182999682)

    def test_a1_register(self):
        f = bytes.fromhex(
            'a1000000000a8dcd0910000a8dcd09000000000000c612000111e2' +
            '4142434445464748414243444546474841424344454647484142434445464748' +
            '00000000')
        d = W.decode_frame(f)
        self.assertEqual(d['class'], 'a1')
        self.assertEqual(d['id'], 177065225)
        self.assertEqual(d['port'], 4578)

    def test_hash_and_2(self):
        d = W.decode_frame(bytes.fromhex('23f60ae85a820123cc5306'))
        self.assertEqual(d['class'], 'hash')
        self.assertEqual(d['id'], 182999682)
        self.assertEqual(d['flag'], 1)
        self.assertEqual(d['value'], 0x0653cc23)
        d = W.decode_frame(bytes.fromhex('32c40a78483a1ac37606'))
        self.assertEqual(d['class'], 'rec2')
        self.assertEqual(d['id'], 175654970)
        self.assertEqual(d['value'], 0x0676c31a)


class TestEventMerge(unittest.TestCase):
    def _packet(self, payload, sport, dport, ts):
        return {'ts': ts, 'src': '198.18.0.1', 'dst': '198.18.0.1',
                'sport': sport, 'dport': dport, 'payload': payload,
                'pcap': 'synthetic'}

    def test_bang_and_delivery_merge(self):
        bang = build_bang(b'hello')
        deliv = b'hello' + b'\xdd\xcc\xbb\xaa' + bytes.fromhex('0a636363') + \
            struct.pack('>H', 7777)
        packets = [self._packet(bang, 4577, 29100, 100.0),
                   self._packet(deliv, 4577, 7777, 100.5)]
        events, order, _ = R.build_events(packets, False, False, None, None)
        self.assertEqual(len(order), 1)
        self.assertEqual(len(events[order[0]].sightings), 2)

    def test_a4_inner_merges_with_direct(self):
        chat = build_chat_frame(build_chat_msg(text='好了'))
        a4 = (b'\xa4' + b'\x00' * 4 + bytes.fromhex('0a78483a') +
              struct.pack('<H', 4 + len(chat)) + bytes.fromhex('0ae85a82') + chat)
        packets = [self._packet(a4, 4577, 29100, 200.0),
                   self._packet(chat, 29100, 4578, 200.1)]
        events, order, _ = R.build_events(packets, False, False, None, None)
        self.assertEqual(len(order), 1)
        ev = events[order[0]]
        self.assertEqual(ev.class_, 'udt')
        self.assertEqual(ev.fields['msg']['chat_text'], '好了')
        self.assertEqual(len(ev.sightings), 2)

    def test_unknown_filtered_by_default(self):
        packets = [self._packet(b'\x99\x98\x97', 1234, 5678, 300.0)]
        events, order, stats = R.build_events(packets, False, False, None, None)
        self.assertEqual(len(order), 0)
        self.assertEqual(stats['unknown'], 1)
        events, order, stats = R.build_events(packets, False, True, None, None)
        self.assertEqual(len(order), 1)


class TestIntegrationEvidence(unittest.TestCase):
    @unittest.skipUnless(os.path.isdir(EVID), 'evidence 不在本機')
    def test_replay_lo0_inject(self):
        p = os.path.join(EVID, 'lo0-inject.pcap')
        pkts = list(R.read_pcap(p))
        self.assertEqual(len(pkts), 2)
        d0 = W.decode_frame(pkts[0]['payload'])
        self.assertEqual(d0['class'], 'bang')
        self.assertTrue(d0['crc_ok'])
        d1 = W.decode_frame(pkts[1]['payload'])
        self.assertEqual(d1['class'], 'delivered')
        self.assertEqual(d1['src_id'], 0x0A636363)

    @unittest.skipUnless(os.path.isdir(EVID), 'evidence 不在本機')
    def test_replay_c7_finds_hello2_chat(self):
        p = os.path.join(EVID, 'c7-utun11.pcap')
        texts = []
        for pkt in R.read_pcap(p):
            d = W.decode_frame(pkt['payload'])
            if d.get('class') == 'udt':
                m = d.get('msg') or {}
                if 'chat_text' in m:
                    texts.append(m['chat_text'])
            elif d.get('class') == 'a4':
                inner = d.get('inner') or {}
                m = inner.get('msg') or {}
                if 'chat_text' in m:
                    texts.append(m['chat_text'])
        self.assertIn('hello2', texts)


if __name__ == '__main__':
    unittest.main(verbosity=2)
