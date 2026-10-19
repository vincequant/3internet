#!/usr/bin/env python3
"""One-command evidence archive (NEXT_ROUND_QUEUE D-4).

Bundles one run directory (sources/, logs, host_watch, receipts, NOTES) into a
single tar.gz plus a sha256sums file, under evidence/archives/.

Usage:
  python3 archive_evidence.sh <evidence-subdir-or-run-dir> [--out <dir>]
"""
import hashlib
import os
import subprocess
import sys
import tarfile
import time

BASE = os.path.expanduser("~/sgi-protocol-lab-20260915/evidence")
OUT = os.path.join(BASE, "archives")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    src = sys.argv[1]
    if not os.path.isabs(src):
        src = os.path.join(BASE, src)
    if not os.path.isdir(src):
        print("not a directory:", src)
        return 1
    outdir = OUT
    if "--out" in sys.argv:
        outdir = sys.argv[sys.argv.index("--out") + 1]
    os.makedirs(outdir, exist_ok=True)
    name = "%s-%s.tar.gz" % (os.path.basename(src.rstrip("/")), time.strftime("%Y%m%d-%H%M%S"))
    dest = os.path.join(outdir, name)
    with tarfile.open(dest, "w:gz") as tar:
        tar.add(src, arcname=os.path.basename(src.rstrip("/")))
    digest = sha256(dest)
    sums = os.path.join(outdir, "sha256sums.txt")
    with open(sums, "a", encoding="utf-8") as f:
        f.write("%s  %s\n" % (digest, name))
    print("archived:", dest, "| bytes:", os.path.getsize(dest), "| sha256:", digest[:16])
    return 0


if __name__ == "__main__":
    sys.exit(main())
