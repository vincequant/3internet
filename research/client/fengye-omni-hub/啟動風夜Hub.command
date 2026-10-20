#!/bin/sh
cd "$(dirname "$0")" || exit 1
exec /opt/homebrew/bin/python3 -B launch.py
