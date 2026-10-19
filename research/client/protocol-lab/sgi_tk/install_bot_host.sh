#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
DEST="${SGI_TK_HOME:-$HOME/Library/Application Support/SGI-TK-Feed}"
LOG_DIR="${HOME}/Library/Logs"
LAUNCH_DIR="${HOME}/Library/LaunchAgents"
PLIST="${LAUNCH_DIR}/com.vkquant.sgi-tk-feed.plist"
CLIENT_SRC="${SGI_BOT_CLIENT:-$ROOT/../../../deliverables/sgi-grok-bot-0.1.0/sgi_bot_client.py}"
if [[ ! -f "${CLIENT_SRC}" ]]; then
  CLIENT_SRC="/Users/vk/Documents/Coding/三国志internet/deliverables/sgi-grok-bot-0.1.0/sgi_bot_client.py"
fi
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
ENV_FILE="${SGI_TK_INGEST_ENV:-$HOME/.config/sgi-tk/ingest.env}"

mkdir -p "${DEST}" "${LOG_DIR}" "${LAUNCH_DIR}" "$(dirname "${ENV_FILE}")"
cp "${ROOT}/sgi_tk_uploader.py" "${DEST}/sgi_tk_uploader.py"
cp "${ROOT}/sgi_tk_scheduler.py" "${DEST}/sgi_tk_scheduler.py"
cp "${CLIENT_SRC}" "${DEST}/sgi_bot_client.py"
chmod 755 "${DEST}/sgi_tk_uploader.py" "${DEST}/sgi_tk_scheduler.py"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}. Create it with SGI_TK_INGEST_TOKEN=... mode 0600." >&2
  exit 1
fi
chmod 600 "${ENV_FILE}"

cat > "${DEST}/run.sh" <<EOF
#!/bin/bash
set -euo pipefail
set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a
export SGI_BOT_CLIENT="${DEST}/sgi_bot_client.py"
export SGI_TK_LOCK="${DEST}/scheduler.lock"
export SGI_TK_STATE="${LOG_DIR}/sgi-tk-feed-state.json"
export SGI_TK_LOG="${LOG_DIR}/sgi-tk-feed.jsonl"
cd "${DEST}"
exec "${PYTHON_BIN}" "${DEST}/sgi_tk_scheduler.py"
EOF
chmod 755 "${DEST}/run.sh"

cat > "${PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.vkquant.sgi-tk-feed</string>
  <key>ProgramArguments</key>
  <array>
    <string>${DEST}/run.sh</string>
  </array>
  <key>WorkingDirectory</key><string>${DEST}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${LOG_DIR}/sgi-tk-feed.out.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/sgi-tk-feed.err.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/com.vkquant.sgi-tk-feed" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST}"
launchctl enable "gui/$(id -u)/com.vkquant.sgi-tk-feed"
launchctl kickstart -k "gui/$(id -u)/com.vkquant.sgi-tk-feed"
echo "installed ${PLIST}"
echo "stop: launchctl bootout gui/$(id -u)/com.vkquant.sgi-tk-feed"
echo "start: launchctl bootstrap gui/$(id -u) ${PLIST}"
