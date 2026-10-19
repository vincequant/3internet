#!/usr/bin/env python3
"""Chat-text presence probe (F7 round-5, Q1 decisive check).

Searches every frame the observer session itself received for a unique test
string. If an allied private chat were delivered to this session, the string
would appear inside some inbound frame's bytes. Absence across a whole session
is the protocol-level verdict for that channel (no trace, fully reversible).

What it reads (read-only):
  ~/sgi-protocol-lab-20260915/fengye-hub-session/<run-*/packets.jsonl>
      rows with "raw_hex" (native slot observations + received packets)
  optional: any extra *.jsonl listed with --extra

Encodings tried for the needle: UTF-8, GBK, UTF-16LE.
Also reports frames whose declared recipient/target is NOT our own id (another
side-channel check), when the row carries a "target"/"sender" field.

Usage:
  python3 chat_text_probe.py "UNIQUE-STRING-123" [--session run-2026...] [--extra f1 f2]
Exit: 0 = found (channel delivers to us), 2 = not found (channel does not reach
this session), 1 = input error.
"""
import glob
import json
import os
import sys

BASE = os.path.expanduser("~/sgi-protocol-lab-20260915/fengye-hub-session")


def needles(text):
    out = []
    for enc in ("utf-8", "gbk", "utf-16-le"):
        try:
            out.append((enc, text.encode(enc)))
        except Exception:
            pass
    return out


def scan_file(path, pats, hits, others):
    frames = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                raw = row.get("raw_hex")
                if not raw:
                    continue
                try:
                    blob = bytes.fromhex(raw)
                except ValueError:
                    continue
                frames += 1
                for enc, pat in pats:
                    if pat in blob:
                        hits.append({"file": os.path.basename(path), "enc": enc,
                                     "len": len(blob), "ev": row.get("ev"),
                                     "wall": row.get("wall")})
                tgt = row.get("target")
                if isinstance(tgt, int) and tgt not in (0, 0xFFFFFFFF):
                    others.append({"file": os.path.basename(path), "target": tgt,
                                   "ev": row.get("ev"), "len": len(blob)})
    except OSError:
        pass
    return frames


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    text = sys.argv[1]
    pats = needles(text)
    session = None
    extra = []
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--session":
            session = sys.argv[i + 1]; i += 2
        elif sys.argv[i] == "--extra":
            extra = sys.argv[i + 1:]; i = len(sys.argv)
        else:
            i += 1
    runs = sorted(glob.glob(os.path.join(BASE, "run-*")), key=os.path.getmtime, reverse=True)
    if session:
        runs = [os.path.join(BASE, session)]
    if not runs:
        print("no session dirs found under", BASE)
        return 1
    hits, others = [], []
    total = 0
    for run in runs[:3]:
        for path in sorted(glob.glob(os.path.join(run, "*.jsonl"))) + extra:
            total += scan_file(path, pats, hits, others)
    print(json.dumps({
        "needle": text,
        "encoded_as": [e for e, _ in pats],
        "frames_scanned": total,
        "sessions": [os.path.basename(r) for r in runs[:3]],
        "found": len(hits),
        "hits": hits[:10],
        "frames_with_other_target": len(others),
        "other_target_samples": others[:5],
    }, ensure_ascii=False, indent=1))
    return 0 if hits else 2


if __name__ == "__main__":
    sys.exit(main())
