#!/usr/bin/env python3
"""Auto-fire the rounds agent shortly after the match actually starts.

Watches the current hub session's packets.jsonl for any *in-match* marker:
  - CSanInetInitGameData  (direct control-7 opening snapshot), or
  - "control_cmd": 5      (round sync batch / sync-table control frame), or
  - CSanInetPhaseEndCmd   (phase-end command carried in a round batch)
and, DELAY seconds later, touches shadow_round_c.flag exactly once
(no-op if the flag already exists).

Two robustness rules, both learned from run-20261018-162110 where the opening
snapshot was missed by the receive-slot sampler, nothing fired and the shadow
world silently fell behind:
  1. Several markers count, not just the opening snapshot: the recorder only
     *samples* the native receive slot, so any single frame can be missed.
  2. Only frames appended AFTER the watcher starts count, and the target file
     is resolved through fengye-hub-session/active.json, so neither a stale
     previous match nor pre-match room traffic can trigger a fire.

HARD RULE (roundtest1 + run-20261018-163226): never fire the rounds driver
before the opening has actually arrived. A driver running while the client is
still on the pre-match screen wedges the screen transition. Firing on the
first in-match frame +DELAY is safe because the driver's own pre-wait then
holds until the match is really under way.

Runs on the Mac side of the shadow lab (plain python3). One shot, then exits.
Log: shadow/logs/auto_fire.log
"""
import glob
import json
import os
import time

S = os.path.expanduser("~/sgi-protocol-lab-20260915/shadow")
BASE = os.path.expanduser("~/sgi-protocol-lab-20260915/fengye-hub-session")
LOG = os.path.join(S, "logs", "auto_fire.log")
MARKERS = ("CSanInetInitGameData", '"control_cmd": 5', "CSanInetPhaseEndCmd")
# 2026-10-19: 20s left a queue window right after the opening snapshot; 6s is
# enough for the match scene to be up and keeps the backlog tiny.
DELAY = 6.0


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except OSError:
        pass


def _active_packets():
    """packets.jsonl of the session named by active.json (None if unknown)."""
    try:
        with open(os.path.join(BASE, "active.json"), "r", encoding="utf-8") as f:
            d = json.load(f)
        pk = os.path.join(d.get("directory") or "", "packets.jsonl")
        return pk if os.path.exists(pk) else None
    except (OSError, ValueError):
        return None


def _newest_packets():
    pks = glob.glob(os.path.join(BASE, "run-*", "packets.jsonl"))
    try:
        return max(pks, key=os.path.getmtime) if pks else None
    except OSError:
        return None


def fire(reason):
    log(reason)
    time.sleep(DELAY)
    flag = os.path.join(S, "shadow_round_c.flag")
    if os.path.exists(flag):
        log("flag already present; no-op")
    else:
        open(flag, "w").close()
        log("auto-fired rounds agent (flag touched)")
    raise SystemExit(0)


def main():
    offsets = {}
    for p in glob.glob(os.path.join(BASE, "run-*", "packets.jsonl")):
        try:
            offsets[os.path.realpath(p)] = os.path.getsize(p)
        except OSError:
            pass
    log("watcher start (waiting for in-match activity)")
    deadline = time.time() + 4 * 3600
    while time.time() < deadline:
        try:
            _tick(offsets)
        except Exception as exc:  # never die silently: log and keep watching
            log("tick error: %r" % (exc,))
        time.sleep(5)
    log("watcher timed out (no in-match activity within 4h)")


def _tick(offsets):
    pk = _active_packets() or _newest_packets()
    if not pk:
        return
    key = os.path.realpath(pk)
    off = offsets.get(key)
    if off is None:
        # file appeared after the watcher started: a fresh session file,
        # count from its beginning (a new session cannot contain an old match)
        off = 0
    try:
        size = os.path.getsize(pk)
    except OSError:
        return
    if size <= off:
        return
    try:
        with open(pk, "r", encoding="utf-8", errors="replace") as f:
            f.seek(off)
            chunk = f.read(size - off)
    except OSError:
        return
    offsets[key] = size
    seen = [m for m in MARKERS if m in chunk]
    if seen:
        fire("in-match marker %r seen; firing in %ds" % (seen, int(DELAY)))


if __name__ == "__main__":
    main()
