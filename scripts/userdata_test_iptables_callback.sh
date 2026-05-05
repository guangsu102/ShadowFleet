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
  printf '[shadowfleet][%s] %s\n' "b5abfabb-f2ee-43b8-bc2e-fbd1dcc6d81d" "$1"
}

send_ready_callback() {
  if [ -z "http://10.112.1.88:8787/api/v1/provisioning/ready" ] || [ -z "callback_token_placeholder" ]; then
    log "Ready callback skipped because callback endpoint is not configured"
    return 0
  fi

  local callback_payload
  local attempt

  callback_payload=$(cat <<EOF_CALLBACK
{"token":"callback_token_placeholder","xboard_node_id":1,"correlation_id":"b5abfabb-f2ee-43b8-bc2e-fbd1dcc6d81d","service_status":"ready"}
EOF_CALLBACK
)

  for attempt in 1 2 3 4 5 6; do
    if curl -fsS \
      -X POST \
      -H "Content-Type: application/json" \
      --connect-timeout 5 \
      --max-time 10 \
      --data "${callback_payload}" \
      "http://10.112.1.88:8787/api/v1/provisioning/ready"; then
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

# ============================================
# V2bX Bootstrap (full production flow)
# ============================================

log "[TEST] V2bX bootstrap started"

log "Downloading V2bX install script"
DAEMON_ARTIFACT_BASE_URL=""
DAEMON_INSTALL_SCRIPT_URL=""

if [ -n "${DAEMON_ARTIFACT_BASE_URL}" ]; then
  curl -fsSL "${DAEMON_INSTALL_SCRIPT_URL}" -o "${INSTALL_SCRIPT_PATH}"
  sed -i 's|https://github.com/wyx2685/V2bX/releases/download|'"${DAEMON_ARTIFACT_BASE_URL}"'/releases|g' "${INSTALL_SCRIPT_PATH}"
  sed -i 's|https://raw.githubusercontent.com/wyx2685/V2bX-script/master|'"${DAEMON_ARTIFACT_BASE_URL}"'/raw|g' "${INSTALL_SCRIPT_PATH}"
  sed -i 's|^[[:space:]]*last_version=\$(curl -Ls "[^"]*api\.github\.com[^"]*latest[^"]*")[^;]*|last_version=""|' "${INSTALL_SCRIPT_PATH}"
else
  curl -fsSL "https://raw.githubusercontent.com/wyx2685/V2bX-script/master/install.sh" -o "${INSTALL_SCRIPT_PATH}"
fi
chmod +x "${INSTALL_SCRIPT_PATH}"

log "Installing V2bX"
printf 'n\n' | sudo bash "${INSTALL_SCRIPT_PATH}"

log "Writing V2bX config"
sudo mkdir -p /etc/V2bX
sudo tee /etc/V2bX/config.json >/dev/null <<'EOF_V2BX_CONFIG'
{
  "Log": {
    "Level": "error",
    "Output": ""
  },
  "Cores": [
    {
      "Type": "sing",
      "Name": "shadowfleet-sing",
      "Log": {
        "Level": "error",
        "Timestamp": true
      },
      "NTP": {
        "Enable": false,
        "Server": "time.apple.com",
        "ServerPort": 0
      },
      "OriginalPath": "/etc/V2bX/sing_origin.json"
    }
  ],
  "Nodes": [
    {
      "Name": "test-ec2-node",
      "Core": "sing",
      "CoreName": "shadowfleet-sing",
      "ApiHost": "http://10.112.1.88:8787",
      "ApiKey": "sk_test_key",
      "NodeID": 1,
      "NodeType": "anytls",
      "Timeout": 30,
      "ListenIP": "::",
      "SendIP": "::",
      "ListenPort": 5105,
      "DeviceOnlineMinTraffic": 100,
      "MinReportTraffic": 0,
      "EnableTFO": false,
      "CertConfig": {
        "CertMode": "none",
        "RejectUnknownSni": false,
        "CertDomain": "",
        "CertFile": "/etc/V2bX/cert/node.pem",
        "KeyFile": "/etc/V2bX/cert/node.key"
      },
      "MultiplexConfig": {
        "Enable": true,
        "Padding": true,
        "Brutal": {
          "Enable": false,
          "UpMbps": 0,
          "DownMbps": 0
        }
      }
    }
  ]
}
EOF_V2BX_CONFIG

log "Writing V2bX sing origin config"
sudo tee /etc/V2bX/sing_origin.json >/dev/null <<'EOF_V2BX_SING_ORIGIN'
{
  "dns": {
    "servers": [
      {
        "tag": "cf",
        "address": "1.1.1.1"
      }
    ],
    "strategy": "prefer_ipv6"
  },
  "outbounds": [
    {
      "tag": "direct",
      "type": "direct",
      "domain_resolver": {
        "server": "cf",
        "strategy": "prefer_ipv6"
      }
    },
    {
      "type": "block",
      "tag": "block"
    }
  ],
  "route": {
    "rules": [
      {
        "ip_is_private": true,
        "outbound": "block"
      },
      {
        "outbound": "direct",
        "network": [
          "udp",
          "tcp"
        ]
      }
    ]
  },
  "experimental": {
    "cache_file": {
      "enabled": true
    }
  }
}
EOF_V2BX_SING_ORIGIN

log "Restarting V2bX service"
sudo systemctl daemon-reload || true
sudo systemctl enable V2bX
sudo systemctl restart V2bX
sleep 3
sudo systemctl is-active --quiet V2bX

# ============================================
# Nginx reverse proxy (AnyTLS passthrough)
# ============================================

log "Installing Nginx reverse proxy for AnyTLS passthrough"
sudo apt-get update -y || true
sudo apt-get install -y nginx

# AnyTLS Nginx config for node 1 (port 5105)
sudo tee /etc/nginx/sites-available/v2bx-node-1.conf >/dev/null <<'EOF_NGINX'
stream {
    upstream v2bx_backend_1 {
        server 127.0.0.1:5105;
    }
    server {
        listen 443;
        # node_1 backend
        proxy_pass v2bx_backend_1;
        proxy_protocol off;
        proxy_timeout 300s;
        proxy_connect_timeout 10s;
    }
}
EOF_NGINX
sudo ln -sf /etc/nginx/sites-available/v2bx-node-1.conf /etc/nginx/sites-enabled/v2bx-node-1.conf
sudo ln -sf /etc/nginx/sites-available/v2bx-base-stream.conf /etc/nginx/sites-enabled/ 2>/dev/null || true
sudo nginx -t && sudo systemctl reload nginx

# ============================================
# iptables connlimit (idempotent, no iptables-persistent)
# ============================================

log "Configuring iptables connection limit (500 conn/IP on port 443)"
# --- Base iptables rules (idempotent) ---
sudo iptables -C INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || sudo iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
sudo iptables -C INPUT -i lo -j ACCEPT 2>/dev/null || sudo iptables -A INPUT -i lo -j ACCEPT
sudo iptables -C INPUT -p icmp -j ACCEPT 2>/dev/null || sudo iptables -A INPUT -p icmp -j ACCEPT
sudo iptables -C INPUT -p tcp --dport 22 -j ACCEPT 2>/dev/null || sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT
sudo iptables -C INPUT -p udp --dport 53 -j ACCEPT 2>/dev/null || sudo iptables -A INPUT -p udp --dport 53 -j ACCEPT
sudo iptables -C INPUT -p udp --dport 67 -j ACCEPT 2>/dev/null || sudo iptables -A INPUT -p udp --dport 67 -j ACCEPT
sudo iptables -C INPUT -j DROP 2>/dev/null || sudo iptables -A INPUT -j DROP
# Connlimit rules for port 443 (idempotent)
sudo iptables -C INPUT -p tcp --syn --dport 443 -m connlimit --connlimit-above 500 --connlimit-mask 32 -j DROP 2>/dev/null || sudo iptables -A INPUT -p tcp --syn --dport 443 -m connlimit --connlimit-above 500 --connlimit-mask 32 -j DROP
sudo iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT
# IPv6 connlimit rules for port 443 (idempotent)
sudo ip6tables -C INPUT -p tcp --syn --dport 443 -m connlimit --connlimit-above 500 --connlimit-mask 128 -j DROP 2>/dev/null || sudo ip6tables -A INPUT -p tcp --syn --dport 443 -m connlimit --connlimit-above 500 --connlimit-mask 128 -j DROP
sudo ip6tables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || sudo ip6tables -A INPUT -p tcp --dport 443 -j ACCEPT

log "[TEST] Sending ready callback"
send_ready_callback

log "[TEST] V2bX bootstrap completed"
