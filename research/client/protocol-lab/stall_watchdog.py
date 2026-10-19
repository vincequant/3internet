#!/usr/bin/env python3
"""Early-warning watchdog for the shadow client (F7 round-3 consensus item).

Polls the shadow process every INTERVAL seconds and classifies:

  healthy   : tick accumulator advancing, f6bc in {0,1,2}
  suspicious: f6bc == 1 with a frozen accumulator for STALL_SAMPLES polls,
              or RX silent for > RX_AGE_ALERT seconds
  stalled   : both of the above (the deadlock signature we have seen twice)

On "stalled" it takes a fresh shadow_stall_probe capture into
evidence/stall-<timestamp>/ (threads + queues + locks + code snapshots) BEFORE
anyone restarts anything, and appends one line to logs/stall-watchdog.log.

Read-only: it never writes to the game process, never sends frames, never
restarts anything. Safe to leave running for a whole session.
"""
import json
import os
import subprocess
import sys
import time

S = os.path.expanduser("~/sgi-protocol-lab-20260915/shadow")
WINE = os.path.expanduser("~/Library/Application Support/SGI-Wine/runtime-sikarugir10/wswine.bundle/bin/wine")
P32 = os.path.expanduser("~/sgi-protocol-lab-20260915/python32/python.exe")
BRIDGE = r"Z:\Users\vkquant\sgi-protocol-lab-20260915\shadow\bridge"
LOG = os.path.join(S, "logs", "stall-watchdog.log")
STATE = os.path.join(S, "inject-state-resident.json")
EVID = os.path.expanduser("~/sgi-protocol-lab-20260915/evidence")

INTERVAL = 25.0
STALL_SAMPLES = 6          # ~2.5 min of frozen accumulator with f6bc==1
RX_AGE_ALERT = 120.0


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except OSError:
        pass


def probe(prefix_name="prefix-fengye-shadow"):
    env = dict(os.environ)
    env["WINEPREFIX"] = os.path.expanduser("~/Library/Application Support/SGI-Wine/" + prefix_name)
    try:
        out = subprocess.run([WINE, P32, os.path.join(S, "tools", "roundprobe.py"),
                              "--bridge", BRIDGE, "--samples", "1", "--interval", "0.1"],
                             capture_output=True, text=True, timeout=45, env=env).stdout
    except Exception:
        return None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if "tick_state_G68" in d:
                return d
    return None


LAG_FIELDS = ("tick_state_G68", "phase_4d8", "f_4d0", "f_4d4", "f_4d6", "f_6bc", "queue_84b4", "accum_G6c")
LAG_PATH = os.path.join(S, "logs", "lagwatch.jsonl")


def sample_lag(shadow):
    """One lag row per watchdog tick, reusing the shadow probe already taken.

    Replaces the standalone lag_watch.py loop: the host probe is the only extra
    wine launch (shadow side is shared), halving the per-sample cost.
    """
    host = probe("prefix-sikarugir10")
    row = {"wall": time.time(),
           "host": {k: (host or {}).get(k) for k in LAG_FIELDS} if host else None,
           "shadow": {k: shadow.get(k) for k in LAG_FIELDS} if shadow else None}
    if host and shadow:
        for key, lag_key in (("f_4d0", "lag_4d0"), ("f_4d4", "lag_4d4"), ("f_4d6", "lag_4d6")):
            hv, sv = host.get(key), shadow.get(key)
            row[lag_key] = (hv - sv) if isinstance(hv, int) and isinstance(sv, int) else None
    try:
        with open(LAG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def rx_age():
    """Age of the last received frame, from rx_watch.log's last line."""
    p = os.path.join(S, "logs", "rx-watch.log")
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            lines = f.read().strip().splitlines()
        for line in reversed(lines[-5:]):
            if "age=" in line:
                part = line.split("age=")[1].split("s")[0]
                return float(part)
    except Exception:
        pass
    return None


def capture(tag):
    d = os.path.join(EVID, "stall-%s" % tag)
    try:
        os.makedirs(d, exist_ok=True)
        pid = 0
        try:
            pid = int(json.load(open(STATE, encoding="utf-8"))["pid"])
        except Exception:
            pass
        if not pid:
            log("capture skipped: no resident state/pid")
            return None
        env = dict(os.environ)
        env["WINEPREFIX"] = os.path.expanduser("~/Library/Application Support/SGI-Wine/prefix-fengye-shadow")
        subprocess.run([WINE, P32, os.path.join(S, "tools", "shadow_stall_probe.py"),
                        "--pid", str(pid), "--state", r"Z:\Users\vkquant\sgi-protocol-lab-20260915\shadow\inject-state-resident.json",
                        "--out", "Z:\\Users\\vkquant\\sgi-protocol-lab-20260915\\evidence\\stall-%s" % tag],
                       capture_output=True, text=True, timeout=120, env=env)
        log("capture written: %s" % d)
        return d
    except Exception as exc:
        log("capture failed: %r" % (exc,))
        return None


def main():
    frozen = 0
    last_accum = None
    alerted = False
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 6 * 3600
    deadline = time.time() + duration
    while time.time() < deadline:
        d = probe()
        age = rx_age()
        sample_lag(d)
        if d is None:
            log("probe unavailable (shadow gone?)")
            time.sleep(INTERVAL)
            continue
        accum = d.get("accum_G6c")
        f6bc = d.get("f_6bc")
        if accum is not None and accum == last_accum and f6bc == 1:
            frozen += 1
        else:
            if frozen >= STALL_SAMPLES and not alerted:
                log("recovered: accumulator moving again (frozen samples=%d)" % frozen)
            frozen = 0
            alerted = False
        last_accum = accum
        if frozen >= STALL_SAMPLES and (age is None or age > RX_AGE_ALERT) and not alerted:
            tag = time.strftime("%Y%m%d-%H%M%S")
            log("STALLED: f6bc=1 frozen %d samples, rx age=%s -> capturing" % (frozen, age))
            capture(tag)
            alerted = True
            # keep watching; if the app recovers the loop resets `alerted`
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
