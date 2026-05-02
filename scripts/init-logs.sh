#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"

mkdir -p "$PROJECT_ROOT/data/logs/nginx"
mkdir -p "$PROJECT_ROOT/data/certs" 2>/dev/null || true
mkdir -p "$PROJECT_ROOT/certs" 2>/dev/null || true

# Render logrotate config
LOGS_DIR="$PROJECT_ROOT/data/logs" envsubst < "$PROJECT_ROOT/deploy/logrotate.conf.template" > /etc/logrotate.d/shadowfleet 2>/dev/null || \
    envsubst < "$PROJECT_ROOT/deploy/logrotate.conf.template" > /tmp/shadowfleet-logrotate.conf

echo "[ShadowFleet] Init complete. Log dirs ready."
echo "[ShadowFleet] To manually rotate logs: logrotate -f /etc/logrotate.d/shadowfleet"
