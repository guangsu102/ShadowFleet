#!/bin/bash
set -e

# 自动添加执行权限（仅首次需要）
chmod +x "$0"

cd /home/shadowfleet/ShadowFleet

echo "=== [1/6] 拉取最新代码 ==="
git pull

echo "=== [2/6] 构建后端镜像 ==="
docker compose build --no-cache shadowfleet-api shadowfleet-daemon

echo "=== [3/6] 重启后端容器 ==="
docker compose up -d shadowfleet-api shadowfleet-daemon

echo "=== [4/6] 构建前端 ==="
docker compose --profile frontend-build up -d --build shadowfleet-frontend-builder

echo "=== [5/6] 等待前端构建并重启 Nginx ==="
sleep 30
docker compose restart shadowfleet-nginx

echo "=== [6/6] 验证服务状态 ==="
docker compose logs --tail=10 shadowfleet-api
docker compose ps

echo ""
echo "=== 部署完成 ==="
