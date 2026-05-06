#!/bin/bash
# 在 EC2 上运行此脚本验证 nginx stream 配置的正确方式

set -e

echo "=== 1. 查看当前 nginx.conf 结构 ==="
grep -n "include\|stream\|http\|events" /etc/nginx/nginx.conf

echo ""
echo "=== 2. 查看 sites-enabled 在 http 块内部还是外部 ==="
sed -n '1,50p' /etc/nginx/nginx.conf

echo ""
echo "=== 3. 测试方案A: 在 nginx.conf 末尾追加 stream 块 ==="
# 备份
sudo cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak

# 追加 stream 配置到 nginx.conf
cat <<'EOF' | sudo tee -a /etc/nginx/nginx.conf

# Stream config for AnyTLS
stream {
    upstream v2bx_backend_test {
        server 127.0.0.1:5105;
    }
    server {
        listen 5555;
        proxy_pass v2bx_backend_test;
    }
}
EOF

sudo nginx -t 2>&1
echo "方案A测试结果: $?"

echo ""
echo "=== 4. 恢复原配置 ==="
sudo cp /etc/nginx/nginx.conf.bak /etc/nginx/nginx.conf

echo ""
echo "=== 5. 测试方案B: 创建独立的 stream 配置文件，在 http 块之前 include ==="
# Debian 12+ 的做法: 创建 /etc/nginx/stream.conf.d/ 并在 http 块之前 include

# 创建 stream 目录
sudo mkdir -p /etc/nginx/stream.conf.d

# 写入 stream 配置
cat <<'EOF' | sudo tee /etc/nginx/stream.conf.d/v2bx-stream.conf
stream {
    upstream v2bx_backend_test {
        server 127.0.0.1:5105;
    }
    server {
        listen 5555;
        proxy_pass v2bx_backend_test;
    }
}
EOF

# 在 nginx.conf 的 http 块之前插入 include
sudo sed -i '/^http {/i include /etc/nginx/stream.conf.d/*.conf;' /etc/nginx/nginx.conf

sudo nginx -t 2>&1
echo "方案B测试结果: $?"

echo ""
echo "=== 恢复原配置 ==="
sudo cp /etc/nginx/nginx.conf.bak /etc/nginx/nginx.conf
sudo rm -rf /etc/nginx/stream.conf.d
