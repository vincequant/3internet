#!/usr/bin/env python3
"""Keep the C rounds-agent following for the whole match.

Watches shadow_round_c_receipt.bin; when the last SHG4 record shows the
'finished' event (event==3, i.e. max_rounds exhausted), it re-injects a fresh
dormant C agent and fires it again (rm flag+receipt -> inject -> touch flag).
One agent at a time, ordered application preserved; the world stays correct
and simply catches up whenever the backlog allows.

Runs on the Mac side of the shadow lab. Stop: pkill -f shadow_round_keeper
(also covered by stop_shadow.sh / shadow_force_quit.sh). Log: logs/round_keeper.log
"""
import os
import struct
import subprocess
import time

S = os.path.expanduser("~/sgi-protocol-lab-20260915/shadow")
LOG = os.path.join(S, "logs", "round_keeper.log")
RECEIPT = os.path.join(S, "shadow_round_c_receipt.bin")
FLAG = os.path.join(S, "shadow_round_c.flag")
MAX = os.environ.get("KEEPER_MAX_ROUNDS", "200")


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except OSError:
        pass


def finished():
    try:
        size = os.path.getsize(RECEIPT)
    except OSError:
        return False
    if size < 24:
        return False
    try:
        with open(RECEIPT, "rb") as f:
            f.seek(size - 24)
            rec = f.read(24)
    except OSError:
        return False
    if rec[:4] != b"SHG4":
        return False
    event = struct.unpack_from("<I", rec, 8)[0]
    # 2026-10-18 evening: re-inject ONLY after a clean finish (3). A fuse (6)
    # means the app made no progress for 6 cycles - re-injecting then just adds
    # another stuck worker thread on top of the wedged app (run-20261018-1638:
    # two fuse re-injects left 4 concurrent round threads and the keeper kept
    # churning). Fuse is now alert-only.
    return event == 3


def reinject():
    try:
        if os.path.exists(RECEIPT):
            import shutil
            shutil.copy(RECEIPT, os.path.join(S, "logs",
                        "receipt-%s.bin" % time.strftime("%Y%m%d-%H%M%S")))
    except OSError:
        pass
    cmd = (
        'cd "{s}" && set -u && source ./_env.sh && '
        'rm -f shadow_round_c.flag shadow_round_c_receipt.bin && '
        '"$WINE" "$P32" "$S/tools/p51_shadow_inject.py" --mode rounds '
        '--rounds-variant b --target-name SANPK.exe '
        '--agent-bin "$Z\\\\tools\\\\agent_rounds_e.bin" --bridge "$Z\\\\bridge" '
        '--flag "$Z\\\\shadow_round_c.flag" --receipt "$Z\\\\shadow_round_c_receipt.bin" '
        '--state "$Z\\\\inject-state-rounds-c.json" --max-rounds {m}'
    ).format(s=S, m=MAX)
    try:
        r = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        log("re-inject timed out")
        return False
    if "thread_id" in (r.stdout or ""):
        open(FLAG, "w").close()
        log("re-injected + fired (max %s)" % MAX)
        return True
    log("re-inject failed rc=%s out=%s err=%s" % (r.returncode,
        (r.stdout or "")[-200:], (r.stderr or "")[-200:]))
    return False


def main():
    log("keeper start (max %s)" % MAX)
    deadline = time.time() + 10 * 3600
    while time.time() < deadline:
        if finished():
            log("agent finished; re-arming")
            time.sleep(3)
            reinject()
            time.sleep(20)
        time.sleep(10)
    log("keeper timeout (10h)")


if __name__ == "__main__":
    main()
