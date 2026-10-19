#!/bin/bash
# P36 E1 一鍵演示：抓包（用完即停）→ 事件流重建 →（可選）與主機側觀測對照。
#
# 用法:
#   ./p36_e1_demo.sh [秒數=120] [--watch <watch.jsonl>] \
#                    [--ifaces "utun11 lo0"] [--outdir <目錄>] [--no-capture]
#
# 例：
#   ./p36_e1_demo.sh 90 --watch ~/sgi-protocol-lab-20260915/evidence/watch-c4.jsonl
#
# 邊界（重要）:
#   - 只抓本機自有網卡（預設 utun11=中繼腿、lo0=本機投遞腿）；用完即停、不常駐。
#   - 同一時間只有一個窗口碰遊戲；執行前先在對話確認。
#   - 需要免密 sudo（tcpdump）；沒有時會提示先跑一次 sudo -v。
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
DUR=120
WATCH=""
IFACES="utun11 lo0"
OUTDIR=""
NOCAP=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --watch) WATCH="$2"; shift 2 ;;
    --ifaces) IFACES="$2"; shift 2 ;;
    --outdir) OUTDIR="$2"; shift 2 ;;
    --no-capture) NOCAP=1; shift ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) DUR="$1"; shift ;;
  esac
done

TS=$(date +%Y%m%d-%H%M%S)
OUTDIR="${OUTDIR:-$DIR/e1-live-$TS}"
mkdir -p "$OUTDIR"

if [[ $NOCAP -eq 0 ]]; then
  if ! sudo -n true 2>/dev/null; then
    echo "!! tcpdump 需要免密 sudo：請先執行一次 'sudo -v'，或手動抓包後用 --no-capture"
    exit 1
  fi
  echo "[capture] 介面: $IFACES  時長: ${DUR}s  輸出: $OUTDIR"
  for IF in $IFACES; do
    OUT="$OUTDIR/${IF//\//_}.pcap"
    sudo -n tcpdump -n -i "$IF" -U -w "$OUT" udp 2> "$OUT.stderr" &
  done
  sleep "$DUR"
  for IF in $IFACES; do
    OUT="$OUTDIR/${IF//\//_}.pcap"
    sudo -n pkill -TERM -f "tcpdump.*${OUT}" 2>/dev/null || true
  done
  sleep 2
  echo "[capture] 已停止（不留常駐抓包）"
fi

PCAPS=()
for F in "$OUTDIR"/*.pcap; do
  [[ -e "$F" ]] && PCAPS+=("$F")
done
if [[ ${#PCAPS[@]} -eq 0 ]]; then
  echo "!! $OUTDIR 下沒有 pcap 可重建"; exit 1
fi

CMD=(python3 "$DIR/p36_e1_reconstruct.py" "${PCAPS[@]}" --jsonl "$OUTDIR/events.jsonl")
if [[ -n "$WATCH" ]]; then
  CMD+=(--watch "$WATCH" --check-watch)
fi
"${CMD[@]}" | tee "$OUTDIR/timeline.txt"

echo
echo "完成。輸出目錄: $OUTDIR"
echo "  timeline.txt  人類可讀時間線"
echo "  events.jsonl  機器可讀事件流"
echo "  *.pcap        原始抓包（如需凍結證據請連同 sha256 一併歸檔）"
