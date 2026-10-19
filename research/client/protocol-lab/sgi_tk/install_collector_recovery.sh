#!/usr/bin/env bash
set -euo pipefail

DEST="${SGI_COLLECTOR_ROOT:-/Users/vkquant/sgi-protocol-lab-20260915}"
LAUNCH_DIR="${HOME}/Library/LaunchAgents"
PLIST="${LAUNCH_DIR}/com.vkquant.sgi-tk-dashboard.plist"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
WRAPPER="${DEST}/start_dashboard_if_needed.sh"

if [[ ! -f "${DEST}/dashboard.py" ]]; then
  echo "dashboard.py missing under ${DEST}" >&2
  exit 1
fi

mkdir -p "${LAUNCH_DIR}"
cat > "${WRAPPER}" <<'EOF'
#!/bin/bash
set -euo pipefail
DEST="/Users/vkquant/sgi-protocol-lab-20260915"
cd "${DEST}"
if lsof -nP -iTCP:18773 -sTCP:LISTEN >/dev/null 2>&1; then
  while lsof -nP -iTCP:18773 -sTCP:LISTEN >/dev/null 2>&1; do
    sleep 15
  done
  exit 0
fi
echo $$ > "${DEST}/dashboard.pid"
exec /usr/bin/python3 "${DEST}/dashboard.py"
EOF
chmod 755 "${WRAPPER}"

cat > "${PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.vkquant.sgi-tk-dashboard</string>
  <key>ProgramArguments</key>
  <array>
    <string>${WRAPPER}</string>
  </array>
  <key>WorkingDirectory</key><string>${DEST}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${DEST}/dashboard.launch.out.log</string>
  <key>StandardErrorPath</key><string>${DEST}/dashboard.launch.err.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/com.vkquant.sgi-tk-dashboard" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST}"
launchctl enable "gui/$(id -u)/com.vkquant.sgi-tk-dashboard"
echo "installed collector recovery ${PLIST}"
echo "This does not start a second dashboard while 127.0.0.1:18773 is already listening."
echo "stop: launchctl bootout gui/$(id -u)/com.vkquant.sgi-tk-dashboard"
echo "controlled dashboard-only restart: lsof -nP -iTCP:18773 -sTCP:LISTEN -t | xargs kill"
