#!/usr/bin/env python3
# p38_decode_captured_frames.py — 解 p33/p34 实机 host_watch 的 last_msg_14c 原始帧
# 只读本地证据 jsonl, 不碰游戏/网络。
import json, struct, sys, os

BASE = os.path.expanduser("~/Documents/Coding/三国志internet/research/protocol-archive/evidence")

def be32(b, off):
    return struct.unpack_from(">I", b, off)[0]

def le32(b, off):
    return struct.unpack_from("<I", b, off)[0]

def describe(frame):
    if not frame:
        return "empty"
    c = frame[0]
    name = {
        0x01: "JOIN(req)", 0x06: "EXIT(req?)", 0x09: "HEARTBEAT",
        0x46: "F-relay/fanout", 0x54: "RPROBE9", 0x55: "RPROBE6",
        0x56: "RPROBE7", 0x57: "RPROBE8", 0x58: "ACK",
        0x63: "inner63(data)", 0x02: "ROW-ADD(02)", 0x03: "ROW-ADD-ACK?",
        0x04: "ROW-ADD(04)", 0x05: "ROW-ADD(05)", 0x07: "EXIT-NOTIFY(07)",
        0x08: "EXIT-NOTIFY(08)", 0x0b: "HOST-EXIT(0b)", 0x0a: "NOOP(0a)",
    }.get(c, "cmd%02x" % c)
    out = {"first": "%02x" % c, "kind": name, "len": len(frame)}
    if c == 0x63 and len(frame) >= 21:
        seq, stamp, blen = be32(frame, 1), frame[5:9].hex(), be32(frame, 9)
        sender, target = be32(frame, 13), be32(frame, 17)
        body = frame[21:]
        out.update(seq=seq, stamp=stamp, body_len_field=blen,
                   sender=sender, target=target,
                   body_hex=body[:64].hex(), body_actual=len(body))
        if len(body) >= 4:
            ctl = be32(body, 0)
            out["control"] = ctl
            if ctl == 7 and len(body) >= 12:
                out.update(d7_target=be32(body, 4), d7_len=be32(body, 8),
                           d7_data=body[12:44].hex())
            elif ctl == 4 and len(body) >= 8:
                out.update(d4_len=be32(body, 4), d4_data=body[8:40].hex())
    elif c in (0x01, 0x06, 0x55, 0x56, 0x57, 0x54):
        if len(frame) >= 5:
            out["seq"] = be32(frame, 1)
        if len(frame) >= 9:
            out["stamp"] = frame[5:9].hex()
        out["rest"] = frame[9:48].hex()
    elif c == 0x58:
        out["ack_seq"] = be32(frame, 1)
        out["tail"] = frame[5:12].hex()
    elif c == 0x09:
        out["seq/word1"] = be32(frame, 1)
        out["rest"] = frame[5:30].hex()
    return out

def scan(path):
    seen = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        msg = d.get("last_msg_14c")
        if not msg:
            continue
        try:
            b = bytes.fromhex(msg)
        except Exception:
            continue
        ln = d.get("last_len_414c")
        if ln and 0 < ln <= len(b):
            b = b[:ln]
        key = (d.get("last_sender_4150"), b)
        if key in seen:
            continue
        seen[key] = (d.get("wall") or d.get("t") or "", d.get("last_sender_4150"))
    return seen

for run in sys.argv[1:]:
    path = os.path.join(BASE, run, "host_watch.jsonl")
    if not os.path.exists(path):
        print("missing:", path); continue
    print("########", run)
    seen = scan(path)
    # group by decoded signature
    groups = {}
    for (sender, b), meta in seen.items():
        d = describe(b)
        sig = (d["first"], d.get("kind"), d.get("control"), d.get("len"))
        groups.setdefault(sig, []).append((meta, b, d))
    for sig, items in sorted(groups.items(), key=lambda kv: str(kv[0])):
        meta, b, d = items[0]
        print("-" * 80)
        print("sig:", sig, " count:", len(items), " sender(slot):", meta[1], " time:", meta[0])
        print("  decoded:", json.dumps(d, ensure_ascii=False))
        print("  raw[0:80]:", b[:80].hex())
