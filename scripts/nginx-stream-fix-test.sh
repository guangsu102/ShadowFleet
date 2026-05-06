#!/bin/bash
set -e

echo "=== 1. 清理旧的错误配置 ==="
sudo rm -f /etc/nginx/sites-enabled/v2bx-stream-*.conf
sudo rm -f /etc/nginx/sites-available/v2bx-stream-*.conf
sudo rm -f /etc/nginx/conf.d/v2bx-stream-*.conf
echo "已清理旧文件"

echo ""
echo "=== 2. 备份 nginx.conf ==="
sudo cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak

echo ""
echo "=== 3. 创建 stream.conf.d 目录 ==="
sudo mkdir -p /etc/nginx/stream.conf.d

echo ""
echo "=== 4. 写入测试 stream 配置 ==="
cat <<'EOF' | sudo tee /etc/nginx/stream.conf.d/test.conf
stream {
    upstream test_backend {
        server 127.0.0.1:5105;
    }
    server {
        listen 5555;
        proxy_pass test_backend;
    }
}
EOF

echo ""
echo "=== 5. 修改 nginx.conf，在 http { 之前插入 include ==="
if grep -q 'stream.conf.d' /etc/nginx/nginx.conf; then
    echo "stream.conf.d include 已存在，跳过"
else
    sudo sed -i 's/^http {$/include \/etc\/nginx\/stream.conf.d\/*.conf;\nhttp {/' /etc/nginx/nginx.conf
fi

echo ""
echo "=== 6. 查看修改后的 nginx.conf (前30行) ==="
head -30 /etc/nginx/nginx.conf

echo ""
echo "=== 7. 测试 nginx 配置 ==="
sudo nginx -t 2>&1

echo ""
echo "=== 8. 恢复原配置 ==="
sudo rm -f /etc/nginx/stream.conf.d/test.conf
sudo cp /etc/nginx/nginx.conf.bak /etc/nginx/nginx.conf

echo ""
echo "=== 测试完成 ==="
