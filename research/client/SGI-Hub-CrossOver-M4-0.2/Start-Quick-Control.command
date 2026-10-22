#!/bin/bash
set -eu
cd "$(dirname "$0")"
exec .venv/bin/python -B app/quick_control.py
