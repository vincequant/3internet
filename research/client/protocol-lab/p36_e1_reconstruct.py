#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P36 E1 — 旁路收聽工具化：pcap → 對局事件流重建器（CLI）。

用法（離線回放）：
    python3 p36_e1_reconstruct.py <pcap> [<pcap> ...]
        [--watch watch-xxx.jsonl] [--name ID=名稱 ...]
        [--jsonl out.jsonl] [--md out.md]
        [--since epoch] [--until epoch]
        [--full] [--include-unknown] [--check-watch]

把 utun11（中繼腿）與 lo0（本機投遞腿）的抓包合成一條
「誰-何時-做了什麼」時間線：握手/名冊、成員幀（含聊天文本）、
投遞幀。同一邏輯幀在「直連 / a4 上行 / 中繼下行」多次出現時
自動合併為一個事件（sightings 記錄每個出現點）。

邊界：只讀 pcap；不連網、不發幀；抓包需單獨的 capture 腳本（用完即停）。
"""

import argparse
import datetime
import glob

import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p36_e1_wire as W  # noqa: E402

# ---------------------------------------------------------------- pcap I/O


def read_pcap(path):
    """yield (ts_epoch, linktype_ok_payload) 的 IPv4 UDP 摘要。"""
    with open(path, 'rb') as f:
        gh = f.read(24)
        if len(gh) < 24:
            return
        magic = gh[:4]
        if magic == b'\xd4\xc3\xb2\xa1':
            endian = '<'
        elif magic == b'\xa1\xb2\xc3\xd4':
            endian = '>'
        else:
            raise ValueError('不支援的 pcap magic: %r (%s)' % (magic, path))
        linktype = struct.unpack_from(endian + 'I', gh, 20)[0]
        while True:
            ph = f.read(16)
            if len(ph) < 16:
                break
            ts_sec, ts_usec, incl, _orig = struct.unpack(endian + 'IIII', ph)
            data = f.read(incl)
            pkt = strip_link(linktype, data)
            if pkt is None:
                continue
            ip = parse_ipv4_udp(pkt)
            if ip is None:
                continue
            sport, dport, payload = ip
            src = '.'.join(str(b) for b in pkt[12:16])
            dst = '.'.join(str(b) for b in pkt[16:20])
            yield {
                'ts': ts_sec + ts_usec / 1e6,
                'src': src, 'dst': dst, 'sport': sport, 'dport': dport,
                'payload': payload, 'pcap': os.path.basename(path),
            }


def strip_link(linktype, data):
    if linktype in (101, 12):  # RAW / RAW_IP
        return data
    if linktype in (0, 108):  # NULL / LOOP，前 4 字節家族號
        return data[4:]
    if linktype == 1:  # Ethernet
        if len(data) >= 14 and struct.unpack_from('>H', data, 12)[0] == 0x0800:
            return data[14:]
        return None
    if linktype == 113:  # Linux SLL
        return data[16:]
    return None


def parse_ipv4_udp(pkt):
    if len(pkt) < 20 or pkt[0] >> 4 != 4 or pkt[9] != 17:
        return None
    ihl = (pkt[0] & 0xF) * 4
    udp = pkt[ihl:]
    if len(udp) < 8:
        return None
    sport, dport, ulen = struct.unpack_from('>HHH', udp, 0)
    payload = udp[8:ulen] if 8 <= ulen <= len(udp) else udp[8:]
    return sport, dport, payload


# ---------------------------------------------------------------- helpers

LOCAL_HINT_PORTS = set(range(4576, 4600)) | {7777, 4630, 4631} | set(range(8576, 8600))
RELAY_PORT = 29100


def dir_tag(sp, dp):
    if dp == RELAY_PORT:
        return '→中繼'
    if sp == RELAY_PORT:
        return '中繼→'
    return '本機'


def fmt_t(ts):
    return datetime.datetime.fromtimestamp(ts).strftime('%H:%M:%S.%f')[:-3]


def short_hex(h, n=24):
    return h[:n] + ('…' if len(h) > n else '')


def trim_hex(h, n=256):
    return h if len(h) <= n else h[:n] + '…(%dB)' % (len(h) // 2)


# ---------------------------------------------------------------- events

class Event:
    __slots__ = ('key', 'ts0', 'class_', 'summary', 'fields', 'sightings', 'raw_hex')

    def __init__(self, key, ts, cls, summary, fields, raw_hex):
        self.key = key
        self.ts0 = ts
        self.class_ = cls
        self.summary = summary
        self.fields = fields
        self.sightings = []
        self.raw_hex = raw_hex

    def see(self, sight):
        self.sightings.append(sight)


def event_from_frame(frame_b, decoded, sight):
    """把一個解碼幀提升成事件（含 a4 內層遞迴規則）。"""
    cls = decoded.get('class')
    # a4 兜底：以內層幀為事件本體
    if cls == 'a4' and isinstance(decoded.get('inner'), dict) \
            and decoded['inner'].get('class') not in (None, 'unknown'):
        inner_b = frame_b[15:15 + decoded['len'] - 4]
        inner = decoded['inner']
        ev = event_from_frame(inner_b, inner, sight)
        ev.fields['via_a4_src'] = decoded.get('src_id')
        ev.fields['via_a4_dst'] = decoded.get('dst_id')
        return ev
    # '!' 幀與其「投遞到遊戲」形態按（來源+遊戲載荷）合併為同一事件
    if cls == 'bang':
        payload = decoded.get('payload') or b''
        gp = decoded.get('game_payload')
        body = gp if gp is not None else payload
        src = decoded.get('src_id')
        key = 'game:%s:%s' % (src, W.frame_sha(body)) if body else 'sha:' + W.frame_sha(frame_b)
    elif cls == 'delivered':
        gp = decoded.get('game_payload') or b''
        src = decoded.get('src_id')
        key = 'game:%s:%s' % (src, W.frame_sha(gp))
    else:
        key = 'sha:' + W.frame_sha(frame_b)
    summary = classify_summary(decoded)
    ev = Event(key, sight['ts'], cls, summary, decoded, frame_b.hex())
    ev.see(sight)
    return ev


def classify_summary(d):
    cls = d.get('class')
    if cls == 'bang':
        prev = d.get('game_payload_hex') or d.get('payload_hex', '')
        return "'!' 投遞/注入 len=%s port=%s src=%s:%s" % (
            d.get('plen'), d.get('deliver_port'), d.get('src_id'), d.get('src_port'))
    if cls == 'udt':
        sub = d.get('subtype_label')
        if sub == 'udt_data' and 'msg' in d:
            m = d['msg']
            if 'chat_text' in m:
                return '聊天 cmd=0x06'
            return '成員幀 cmd=%s len=%s' % (m.get('cmd_hex'), len(m.get('raw_hex', '')) // 2)
        return 'UDT %s' % sub
    if cls == 'a1':
        return 'loader 註冊/保活'
    if cls == 'a2':
        return '上線補充'
    if cls == 'a7':
        return '上線通知'
    if cls == 'af':
        return '陌生名單回報'
    if cls == 'a3':
        return '名冊下發 n=%s' % d.get('count')
    if cls == 'a8':
        return '註冊回執'
    if cls == 'aa':
        return '用戶更新'
    if cls == 'a9':
        return '用戶移除'
    if cls == 'hash':
        return '狀態時戳更新'
    if cls == 'rec2':
        return "'2' 時戳/狀態"
    if cls == 'rec1':
        return "'1' 用戶信息"
    if cls == 'delivered':
        return '本機投遞到遊戲'
    if cls == 'instr1000':
        return '1000 指令'
    return cls or '?'

# ---------------------------------------------------------------- aggregation

COLLAPSE_CLASSES = {'a1', 'a2', 'hash', 'rec2', 'rec1', 'aa'}  # 常態心跳類：聚合顯示
COLLAPSE_UDT_SUBS = {'udt_ack_release', 'udt_conn_open', 'udt_conn_establish',
                     'udt_window_update', 'udt_rtt_heartbeat', 'udt_unknown_74'}


def build_events(packets, full_mode, include_unknown, since, until):
    events = {}
    order = []
    stats = {'packets': 0, 'decoded': 0, 'unknown': 0, 'skipped_time': 0,
             'dropped_payloads': 0}
    for p in packets:
        ts = p['ts']
        if since is not None and ts < since:
            stats['skipped_time'] += 1
            continue
        if until is not None and ts > until:
            stats['skipped_time'] += 1
            continue
        stats['packets'] += 1
        b = p['payload']
        d = W.decode_frame(b)
        cls = d.get('class')
        if cls in (None, 'empty'):
            continue
        if cls == 'unknown' and not include_unknown:
            stats['unknown'] += 1
            continue
        stats['decoded'] += 1
        sight = {
            'ts': ts, 't': fmt_t(ts), 'dir': dir_tag(p['sport'], p['dport']),
            'wire': '%s:%d→%s:%d' % (p['src'], p['sport'], p['dst'], p['dport']),
            'len': len(b),
        }
        ev = event_from_frame(b, d, sight)
        # 聚合鍵：聊天/成員幀按內容 sha；心跳類按有效類別+關鍵 id 聚合
        eff_cls = ev.class_
        eff_d = ev.fields
        agg_key = ev.key
        if not full_mode:
            eff_sub = eff_d.get('subtype_label')
            collapse = (
                eff_cls in COLLAPSE_CLASSES
                or (eff_cls == 'udt' and eff_sub in COLLAPSE_UDT_SUBS)
                or (eff_cls == 'udt' and eff_sub == 'udt_data' and 'msg' not in eff_d)
            )
            if collapse:
                ident = eff_d.get('id') or eff_d.get('src_id') or eff_d.get('dst_id')
                tag = eff_sub if eff_cls == 'udt' else eff_cls
                if eff_cls == 'udt' and eff_sub == 'udt_data' and 'msg' not in eff_d:
                    tag = 'udt_ctrl'
                agg_key = 'agg:%s:%s' % (tag, ident)
        if agg_key in events:
            events[agg_key].see(sight)
        else:
            ev.key = agg_key
            events[agg_key] = ev
            order.append(agg_key)
    return events, order, stats


# ---------------------------------------------------------------- rendering

def names_from_watch(paths):
    names = {}
    for path in paths:
        with open(path) as f:
            for line in f:
                try:
                    j = json.loads(line)
                except Exception:
                    continue
                for m in j.get('members', []) or []:
                    mid, nm = m.get('id'), m.get('name')
                    if mid and nm:
                        names[int(mid)] = nm
    return names


def render_event(ev, names):
    d = ev.fields
    cls = ev.class_
    t = fmt_t(ev.ts0)
    n = '×%d' % len(ev.sightings)
    span = ''
    if len(ev.sightings) > 1:
        span = ' (%s→%s)' % (fmt_t(ev.sightings[0]['ts']), fmt_t(ev.sightings[-1]['ts']))
    nm = lambda i: W.id_label(i, names)  # noqa: E731
    if cls == 'a1':
        return '[%s] %s 上線/保活 id=%s port=%s %s%s' % (
            t, dir_tag_s(ev), nm(d.get('id')), d.get('port'), n if len(ev.sightings) > 1 else '', span)
    if cls == 'a8':
        return '[%s] %s 註冊回執 → %s  d=(%s,%s,%s) flag=%s' % (
            t, dir_tag_s(ev), nm(d.get('id')),
            hex(d.get('d1', 0)), hex(d.get('d2', 0)), hex(d.get('d3', 0)), d.get('flag'))
    if cls == 'a3':
        ids = ', '.join(nm(e['id']) for e in d.get('entries', []))
        return '[%s] %s 名冊下發 n=%s: %s' % (t, dir_tag_s(ev), d.get('count'), ids)
    if cls == 'a9':
        return '[%s] %s 用戶移除 id=%s' % (t, dir_tag_s(ev), nm(d.get('id')))
    if cls == 'aa':
        return '[%s] %s 用戶更新 id=%s d=(%s,%s,%s) flag=%s %s%s' % (
            t, dir_tag_s(ev), nm(d.get('id')),
            hex(d.get('d1', 0)), hex(d.get('d2', 0)), hex(d.get('d3', 0)), d.get('flag'), n, span)
    if cls == 'af':
        return '[%s] %s 陌生名單回報 id=%s a3key=%s' % (
            t, dir_tag_s(ev), nm(d.get('id')), hex(d.get('a3_key', 0)))
    if cls == 'bang':
        prev = d.get('game_payload_hex') if d.get('game_payload_hex') is not None else d.get('payload_hex', '')
        texts = W.gbk_runs(bytes.fromhex(prev))
        extra = (' 文本=%r' % texts[0][1]) if texts else ''
        crc = '' if d.get('crc_ok', True) else ' CRC✗'
        return '[%s] %s \'!\' id=%s port=%s src=%s:%s len=%s%s%s  %s' % (
            t, dir_tag_s(ev), nm(d.get('vip_id')), d.get('deliver_port'),
            nm(d.get('src_id')), d.get('src_port'), d.get('plen'), crc, extra, short_hex(prev))
    if cls == 'udt':
        sub = d.get('subtype_label')
        if sub == 'udt_data' and 'msg' in d:
            m = d['msg']
            if 'chat_text' in m:
                return '[%s] %s ★聊天 %s → %s: 「%s」%s' % (
                    t, dir_tag_s(ev), nm(m.get('sender_id')), nm(d.get('dst_id')), m['chat_text'], n)
            texts = m.get('gbk_text') or m.get('ascii_text') or []
            preview = (' 文本=%s' % texts) if texts else ''
            crc = '' if d.get('crc_ok', True) else ' CRC✗'
            return '[%s] %s 成員幀 cmd=%s %s → %s len(tail)=%s%s%s  %s' % (
                t, dir_tag_s(ev), m.get('cmd_hex'), nm(m.get('sender_id')),
                nm(d.get('dst_id')), d.get('aplen'), preview, crc, short_hex(d.get('apayload_hex', '')))
        return '[%s] %s UDT %s id=%s %s%s' % (
            t, dir_tag_s(ev), sub, nm(d.get('id')), n, span)
    if cls == 'delivered':
        return '[%s] %s 投遞到遊戲 src=%s:%s  %s' % (
            t, dir_tag_s(ev), nm(d.get('src_id')), d.get('src_port'),
            short_hex(d.get('game_payload_hex', '')))
    if cls == 'instr1000':
        return '[%s] %s 1000 指令(遊戲→loader) %s:%s → %s:%s len=%s  %s' % (
            t, dir_tag_s(ev), nm(d.get('addr1_id')), d.get('port1'),
            nm(d.get('addr2_id')), d.get('port2'), d.get('plen'),
            short_hex(d.get('payload_hex', '')))
    if cls == 'rec2':
        return '[%s] %s \'2\' id=%s value=%s %s%s' % (
            t, dir_tag_s(ev), nm(d.get('id')), d.get('value'), n, span)
    if cls == 'hash':
        return '[%s] %s \'#\' id=%s flag=%s value=%s %s%s' % (
            t, dir_tag_s(ev), nm(d.get('id')), d.get('flag'), d.get('value'), n, span)
    if cls == 'rec1':
        return '[%s] %s \'1\' id=%s d=(%s,%s,%s) %s%s' % (
            t, dir_tag_s(ev), nm(d.get('id')), hex(d.get('d1', 0)), hex(d.get('d2', 0)),
            hex(d.get('d3', 0)), n, span)
    return '[%s] %s %s %s' % (t, dir_tag_s(ev), ev.summary, short_hex(ev.raw_hex))


def dir_tag_s(ev):
    ds = {s['dir'] for s in ev.sightings}
    return '/'.join(sorted(ds)) or '?'


def event_to_json(ev, names):
    d = {k: v for k, v in ev.fields.items() if k not in ('payload', 'game_payload')}
    if 'payload_hex' in d:
        d['payload_hex'] = trim_hex(d['payload_hex'])
    if 'game_payload_hex' in d:
        d['game_payload_hex'] = trim_hex(d['game_payload_hex'])
    if 'apayload_hex' in d:
        d['apayload_hex'] = trim_hex(d['apayload_hex'])
    return {
        'ts': ev.ts0, 't': fmt_t(ev.ts0), 'class': ev.class_,
        'summary': ev.summary, 'fields': d,
        'sightings': [{'t': s['t'], 'dir': s['dir'], 'wire': s['wire'], 'len': s['len']}
                      for s in ev.sightings],
    }


# ---------------------------------------------------------------- watch cross-check

def watch_samples(path):
    out = []
    with open(path) as f:
        for line in f:
            try:
                j = json.loads(line)
            except Exception:
                continue
            if 'wall' in j:
                out.append(j)
    return out


def watch_member_transitions(samples):
    """回傳 [(wall, members)]，members 列表發生變化處。"""
    trans = []
    prev = None
    for j in samples:
        cur = tuple(sorted((m['id'], m['name']) for m in j.get('members', [])))
        if cur != prev:
            trans.append((j['wall'], list(cur)))
            prev = cur
    return trans


def check_watch(events, order, watch_path, names):
    samples = watch_samples(watch_path)
    if not samples:
        print('!! watch 檔案無樣本: %s' % watch_path)
        return
    w0, w1 = samples[0]['wall'], samples[-1]['wall']
    print('\n===== 主機側觀測對照（%s）=====' % os.path.basename(watch_path))
    print('watch 視窗: %s → %s（%d 樣本）' % (fmt_t(w0), fmt_t(w1), len(samples)))

    print('-- watch 名冊變化 --')
    for wall, members in watch_member_transitions(samples):
        mem = ', '.join('%s(id=%s)' % (n, i) for i, n in members)
        print('  [%s] members: %s' % (fmt_t(wall), mem or '（空）'))

    print('-- 流量側關鍵事件（與 watch 同窗者）--')
    for key in order:
        ev = events[key]
        if not (w0 - 30 <= ev.ts0 <= w1 + 30):
            continue
        d = ev.fields
        keep = ev.class_ in ('a1', 'a7', 'a8', 'a3', 'a9', 'bang')
        if ev.class_ == 'udt':
            keep = d.get('subtype_label') == 'udt_data' and \
                isinstance(d.get('msg'), dict) and 'chat_text' in d['msg']
        if keep:
            print('  ' + render_event(ev, names))

    # 名冊交集（watch id 是字串，統一為 int）
    watch_ids = set()
    for j in samples:
        for m in j.get('members', []):
            try:
                watch_ids.add(int(m['id']))
            except (TypeError, ValueError):
                pass
    traffic_ids = set()
    for key in order:
        d = events[key].fields
        for f in ('id', 'src_id', 'dst_id', 'vip_id'):
            v = d.get(f)
            if isinstance(v, int) and v >> 24 == 0x0A:
                traffic_ids.add(v)
        for e in d.get('entries', []) or []:
            traffic_ids.add(e['id'])
    both = watch_ids & traffic_ids
    print('-- 名冊核對 --')
    print('  watch ids:   %s' % sorted(watch_ids))
    print('  流量 ids(僅取 names 已知或有 name-map 者): %s' % sorted(traffic_ids)[:12])
    print('  交集:        %s' % sorted(both))
    print('  watch 多出（流量缺）: %s' % sorted(watch_ids - traffic_ids))
    ok = watch_ids.issubset(traffic_ids)
    print('  判定: %s' % ('一致：流量可完整重建在場成員' if ok else '有差異：watch 成員未在流量中出現，見上'))


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description='P36 E1 pcap→事件流重建器')
    ap.add_argument('pcaps', nargs='+')
    ap.add_argument('--watch', action='append', default=[],
                    help='主機側 watch jsonl（取 id→name 並做對照）')
    ap.add_argument('--name', action='append', default=[],
                    help='ID=名稱（覆蓋/補充）')
    ap.add_argument('--jsonl', help='輸出機器可讀事件流')
    ap.add_argument('--md', help='輸出 Markdown 時間線')
    ap.add_argument('--since', type=float, help='只處理 >= epoch')
    ap.add_argument('--until', type=float, help='只處理 <= epoch')
    ap.add_argument('--full', action='store_true', help='不聚合心跳類，全量列出')
    ap.add_argument('--include-unknown', action='store_true', help='列出未知類幀')
    ap.add_argument('--check-watch', action='store_true', help='與 watch 對照')
    ap.add_argument('--max-events', type=int, default=0, help='列印上限（0=全部）')
    args = ap.parse_args()

    names = names_from_watch(args.watch)
    for nv in args.name:
        if '=' in nv:
            k, v = nv.split('=', 1)
            names[int(k)] = v

    paths = []
    for pat in args.pcaps:
        hits = sorted(glob.glob(pat))
        paths.extend(hits if hits else [pat])
    packets = []
    for p in paths:
        packets.extend(read_pcap(p))
    # 按時間排序（多檔合併）
    packets.sort(key=lambda p: p['ts'])

    events, order, stats = build_events(packets, args.full, args.include_unknown,
                                        args.since, args.until)

    lines = []
    lines.append('===== P36 E1 旁路事件流重建 =====')
    lines.append('輸入: %s' % ', '.join(os.path.basename(p) for p in paths))
    lines.append('封包 %d / 解出 %d / 未知 %d' % (
        stats['packets'], stats['decoded'], stats['unknown']))
    if events:
        lines.append('事件 %d（%s → %s）' % (
            len(order), fmt_t(events[order[0]].ts0), fmt_t(events[order[-1]].ts0)))
        ids = set()
        for key in order:
            d = events[key].fields
            for f in ('id', 'src_id', 'dst_id', 'vip_id'):
                v = d.get(f)
                if isinstance(v, int) and v >> 24 == 0x0A:
                    ids.add(v)
        if ids:
            lines.append('流量中出現的成員: ' + ', '.join(
                W.id_label(i, names) for i in sorted(ids)))
    lines.append('')
    shown = 0
    for key in order:
        ev = events[key]
        shown += 1
        if args.max_events and shown > args.max_events:
            lines.append('…（其餘 %d 個事件略）' % (len(order) - shown + 1))
            break
        lines.append(render_event(ev, names))

    text = '\n'.join(lines)
    print(text)

    if args.jsonl:
        with open(args.jsonl, 'w') as f:
            for key in order:
                f.write(json.dumps(event_to_json(events[key], names), ensure_ascii=False) + '\n')
        print('\n[jsonl] %s' % args.jsonl)
    if args.md:
        with open(args.md, 'w') as f:
            f.write('# P36 E1 事件流重建\n\n```\n' + text + '\n```\n')
            if args.watch:
                f.write('\n（對照見 stdout / --check-watch）\n')
        print('[md] %s' % args.md)
    if args.check_watch and args.watch:
        for wp in args.watch:
            check_watch(events, order, wp, names)


if __name__ == '__main__':
    main()
