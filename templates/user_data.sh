#!/bin/bash
set -euo pipefail

LOGFILE="/var/log/shadowfleet-user-data.log"
if [ -w "$LOGFILE" ] || [ -w "$(dirname "$LOGFILE")" ]; then
  exec > >(sudo tee -a "$LOGFILE" >/dev/null) 2>&1
elif [ -w "/tmp" ]; then
  exec > >(tee -a "/tmp/shadowfleet-user-data.log" >/dev/null) 2>&1
fi

export DEBIAN_FRONTEND=noninteractive

SCRIPT_DIR="$(mktemp -d /tmp/shadowfleet-user-data.XXXXXX)"
INSTALL_SCRIPT_PATH="${SCRIPT_DIR}/install.sh"

cleanup() {
  rm -rf "${SCRIPT_DIR}"
}
trap cleanup EXIT

log() {
  printf '[shadowfleet][%s] %s\n' "__CORRELATION_ID__" "$1"
}

send_ready_callback() {
  if [ -z "__READY_CALLBACK_URL__" ] || [ -z "__READY_CALLBACK_TOKEN__" ]; then
    log "Ready callback skipped because callback endpoint is not configured"
    return 0
  fi

  local callback_payload
  local attempt

  callback_payload=$(cat <<EOF_CALLBACK
{"token":"__READY_CALLBACK_TOKEN__","xboard_node_id":__XBOARD_NODE_ID__,"correlation_id":"__CORRELATION_ID__","service_status":"ready"}
EOF_CALLBACK
)

  for attempt in 1 2 3 4 5 6; do
    if curl -fsS \
      -X POST \
      -H "Content-Type: application/json" \
      --connect-timeout 5 \
      --max-time 10 \
      --data "${callback_payload}" \
      "__READY_CALLBACK_URL__"; then
      log "Ready callback delivered successfully"
      return 0
    fi

    log "Ready callback attempt ${attempt} failed, retrying in 5 seconds"
    sleep 5
  done

  log "Ready callback failed after all retries"
  return 1
}

ensure_command() {
  if command -v "$1" >/dev/null 2>&1; then
    return 0
  fi

  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y curl wget ca-certificates tar unzip socat
    return 0
  fi

  if command -v yum >/dev/null 2>&1; then
    sudo yum install -y curl wget ca-certificates tar unzip socat
    return 0
  fi

  if command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y curl wget ca-certificates tar unzip socat
    return 0
  fi

  log "Unable to install missing dependency: $1"
  exit 1
}

ensure_command curl
ensure_command tee

log "Downloading V2bX install script"
DAEMON_ARTIFACT_BASE_URL="__DAEMON_ARTIFACT_BASE_URL__"
DAEMON_INSTALL_SCRIPT_URL="__DAEMON_INSTALL_SCRIPT_URL__"

if [ -n "${DAEMON_ARTIFACT_BASE_URL}" ]; then
  # Artifact cache enabled: fully self-contained, no outbound GitHub calls at all.
  curl -fsSL "${DAEMON_INSTALL_SCRIPT_URL}" -o "${INSTALL_SCRIPT_PATH}"
  # Rewrite binary download: GitHub releases -> daemon/releases
  sed -i 's|https://github.com/wyx2685/V2bX/releases/download|'"${DAEMON_ARTIFACT_BASE_URL}"'/releases|g' "${INSTALL_SCRIPT_PATH}"
  # Rewrite raw scripts: raw.githubusercontent -> daemon/raw
  sed -i 's|https://raw.githubusercontent.com/wyx2685/V2bX-script/master|'"${DAEMON_ARTIFACT_BASE_URL}"'/raw|g' "${INSTALL_SCRIPT_PATH}"
  # Rewrite version check: eliminate the GitHub API call entirely.
  # install.sh original: last_version=$(curl -Ls "https://api.github.com/...releases/latest" ...)
  # Target: last_version="__CACHED_V2BX_VERSION__"
  sed -i 's|^[[:space:]]*last_version=\$(curl -Ls "[^"]*api\.github\.com[^"]*latest[^"]*")[^;]*|last_version="__CACHED_V2BX_VERSION__"|' "${INSTALL_SCRIPT_PATH}"
else
  # No artifact cache: fall back to direct GitHub download (legacy mode)
  curl -fsSL "__GITHUB_INSTALL_SCRIPT_URL__" -o "${INSTALL_SCRIPT_PATH}"
fi
chmod +x "${INSTALL_SCRIPT_PATH}"

log "Installing V2bX"
__V2BX_INSTALL_COMMAND__

log "Writing V2bX config"
sudo mkdir -p /etc/V2bX
sudo tee /etc/V2bX/config.json >/dev/null <<'EOF_V2BX_CONFIG'
__V2BX_CONFIG_JSON__
EOF_V2BX_CONFIG

__V2BX_SING_ORIGIN_WRITE_BLOCK__

log "Restarting V2bX service"
sudo systemctl daemon-reload || true
sudo systemctl enable V2bX
sudo systemctl restart V2bX
sleep 3
sudo systemctl is-active --quiet V2bX

__NGINX_CONFIG_BLOCK__

log "Sending ready callback"
send_ready_callback

log "V2bX bootstrap completed"
