#!/bin/sh
# =============================================================================
# Frontend Docker 启动脚本
# 将构建产物从 /dist 复制到 /usr/share/nginx/html（供 nginx 读取）
# =============================================================================

mkdir -p /usr/share/nginx/html
cp -r /dist/. /usr/share/nginx/html/

echo "[frontend] Built files copied to /usr/share/nginx/html:"
ls -la /usr/share/nginx/html/

exec "$@"
