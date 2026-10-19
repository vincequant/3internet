# -*- coding: utf-8 -*-
"""P39c2 bed child: a minimal placeholder process for the offline bed.

It accepts (and ignores) the standard child args injected by
p39c2_loader_host.py, then sleeps for --hold seconds. No Koeinm, no window,
no network - the bed only exercises the loader 1000-instruction path.
"""
import argparse
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', default='')
    ap.add_argument('--session-name', default='')
    ap.add_argument('--username', default='')
    ap.add_argument('--hold', type=int, default=30)
    args, _unknown = ap.parse_known_args()
    print('bed_child_up hold=%d' % args.hold, flush=True)
    time.sleep(max(1, args.hold))
    print('bed_child_done', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
