#!/bin/bash
# P39c2 host-side capture ("camera") - run ON the host machine (where 丁满's
# game runs). Bounded, single purpose: record whether the relay ever delivers
# our uplink frame to this machine (relay interface + loopback delivery path),
# so the operator can tell "relay dropped it" from "lost on the way".
#
# One admin-password prompt; auto-stops; no residue (trap cleans children).
# Duration override for testing:  P39C2_CAP_SECONDS=60 bash <this file>
set -u
DURATION="${P39C2_CAP_SECONDS:-1500}"
DIR="$HOME/sgi-protocol-lab-20260915/evidence/p39c2-nonmember-uplink-20261016/host-capture-$(date +%H%M%S)"
mkdir -p "$DIR"
IFACE=$(route -n get 36.151.147.251 2>/dev/null | awk '/interface:/{print $2}')
[ -z "$IFACE" ] && IFACE=en0
OWNER="$(id -u):$(id -g)"
echo "=================================================="
echo "P39c2 主机侧录像（摄像头）"
echo "  输出目录 : $DIR"
echo "  中继接口 : $IFACE"
echo "  回环录像 : lo0"
echo "  时长     : ${DURATION} 秒（到时自动停止）"
echo "  过滤     : 中继/探针 IP、loader 4576、游戏 7777"
echo "=================================================="
echo "即将要求管理员密码（输入时屏幕不显示，属正常）。"
sudo /bin/sh -s "$IFACE" "$DIR" "$OWNER" "$DURATION" <<'EOS'
IFACE="$1"; DIR="$2"; OWNER="$3"; DURATION="$4"
trap 'kill $P1 $P2 2>/dev/null; exit 0' HUP INT TERM EXIT
/usr/sbin/tcpdump -i "$IFACE" -U -s0 -w "$DIR/host-cap-relay.pcap" \
    'udp and (host 36.151.147.251 or host 120.229.1.128 or port 4576 or port 7777)' &
P1=$!
/usr/sbin/tcpdump -i lo0 -U -s0 -w "$DIR/host-cap-lo0.pcap" \
    'udp and (port 7777 or port 4576)' &
P2=$!
echo "[$(date +%H:%M:%S)] 錄影中…"
sleep "$DURATION"
echo "[$(date +%H:%M:%S)] 時間到，收尾…"
kill $P1 $P2 2>/dev/null
sleep 1
chown -R "$OWNER" "$DIR"
EOS
echo "[$(date +%H:%M:%S)] CAPTURE_DONE"
ls -la "$DIR"
echo "完成。可以關掉此視窗；之後由研究者取檔比對。"
