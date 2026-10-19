#!/usr/bin/env python3
"""Lag watch: sample BOTH clients' world tuples on the same fields and log the
lag, so "one round behind" can be classified objectively:

  lag == constant 1 for the whole match, converging at the end
      -> semantic offset (host counts the round it is collecting, observer
         counts the round it has applied) - not a real lag
  lag grows / never converges
      -> a real debt (missed batch, empty fires, backoff sleep)

Host prefix: prefix-sikarugir10 (丁满). Shadow prefix: prefix-fengye-shadow.
Appends one JSONL row per sample to logs/lagwatch.jsonl.
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
FIELDS = ("tick_state_G68", "phase_4d8", "f_4d0", "f_4d4", "f_4d6", "f_6bc", "queue_84b4", "accum_G6c")


def probe(prefix_name):
    env = dict(os.environ)
    env["WINEPREFIX"] = os.path.expanduser("~/Library/Application Support/SGI-Wine/" + prefix_name)
    try:
        out = subprocess.run(
            [WINE, P32, os.path.join(S, "tools", "roundprobe.py"),
             "--bridge", BRIDGE, "--samples", "1", "--interval", "0.1"],
            capture_output=True, text=True, timeout=40, env=env).stdout
    except Exception:
        return None
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if "tick_state_G68" in d:
            return {k: d.get(k) for k in FIELDS}
    return None


def main():
    out_path = os.path.join(S, "logs", "lagwatch.jsonl")
    interval = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
    duration = float(sys.argv[2]) if len(sys.argv) > 2 else 4 * 3600
    deadline = time.time() + duration
    while time.time() < deadline:
        host = probe("prefix-sikarugir10")
        shadow = probe("prefix-fengye-shadow")
        row = {"wall": time.time(), "host": host, "shadow": shadow}
        if host and shadow:
            for key, lag_key in (("f_4d0", "lag_4d0"), ("f_4d4", "lag_4d4"), ("f_4d6", "lag_4d6")):
                hv, sv = host.get(key), shadow.get(key)
                row[lag_key] = (hv - sv) if isinstance(hv, int) and isinstance(sv, int) else None
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        time.sleep(interval)


if __name__ == "__main__":
    main()
