# ShadowFleet 远程部署方案

> Debian 12 (Bookworm) · Python 3.10+ · Streamlit UI + Daemon 守护进程

---

## 目录

1. [服务器环境准备](#1-服务器环境准备)
2. [Python 环境安装](#2-python-环境安装)
3. [项目部署步骤](#3-项目部署步骤)
4. [服务配置与启动](#4-服务配置与启动)
5. [Nginx 反向代理](#5-nginx-反向代理)
6. [Systemd 服务管理](#6-systemd-服务管理)
7. [SSL 证书配置](#7-ssl-证书配置)
8. [防火墙与网络安全](#8-防火墙与网络安全)
9. [启动验证](#9-启动验证)
10. [日志管理](#10-日志管理)
11. [更新与回滚](#11-更新与回滚)

---

## 1. 服务器环境准备

### 1.1 系统规格要求

| 项目 | 最低配置 | 推荐配置 |
|------|----------|----------|
| CPU | 1 核 | 2 核+ |
| 内存 | 1 GB | 2 GB+ |
| 磁盘 | 20 GB SSD | 50 GB+ SSD |
| 系统 | Debian 12 x64 | Debian 12 x64 |
| 网络 | 公网 IPv4 | 公网 IPv4 + IPv6 |

### 1.2 更新系统基础包

```bash
# SSH 登录服务器后执行
sudo apt update && sudo apt upgrade -y

# 安装基础工具
sudo apt install -y curl wget git unzip sudo \
    apt-transport-https ca-certificates gnupg \
    build-essential libpq-dev
```

### 1.3 创建专用部署用户

```bash
# 创建普通用户（不要用 root 运行）
sudo useradd -m -s /bin/bash -G sudo shadowfleet

# 切换到部署用户
sudo su - shadowfleet
cd ~
```

---

## 2. Python 环境安装

### 2.1 安装 Python 3.11 (Debian 12 默认是 3.11)

```bash
# Debian 12 默认带 Python 3.11，验证一下
python3 --version

# 安装 pip 和 venv
sudo apt install -y python3-full python3-pip python3-venv python3-dev

# 验证 pip
pip3 --version
```

### 2.2 创建 Python 虚拟环境

```bash
# 进入部署目录
mkdir -p ~/ShadowFleet
cd ~/ShadowFleet

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 升级基础包
pip install --upgrade pip setuptools wheel
```

---

## 3. 项目部署步骤

### 3.1 方式一：从 Git 拉取代码（推荐）

```bash
# 在 ~/ShadowFleet 目录下执行
# 如果还没有初始化 git，请先在本地操作后推送到远程

# 克隆仓库（替换为你的仓库地址）
git clone https://your-git-repo/ShadowFleet.git .

# 或者如果你已经通过 SFTP 上传了代码，跳过此步
```

### 3.2 方式二：SFTP / SCP 上传代码

在本地执行（Windows PowerShell）：

```powershell
# 打包项目（排除 .git 和 venv）
Compress-Archive -Path "d:\tanxuan\project\ShadowFleet\*" -DestinationPath "ShadowFleet.zip" -Exclude "*.git*", "venv\*"

# 上传到服务器（替换为你的服务器 IP）
scp ShadowFleet.zip shadowfleet@<SERVER_IP>:~/

# 在服务器上解压
unzip ShadowFleet.zip -d ~/ShadowFleet/
```

### 3.3 安装 Python 依赖

```bash
cd ~/ShadowFleet
source venv/bin/activate

# 安装所有依赖
pip install -r requirements.txt

# 安装项目（可编辑模式）
pip install -e .
```

### 3.4 安装 pytest (开发/调试用)

```bash
pip install pytest pytest-cov pytest-mock pytest-asyncio
```

---

## 4. 服务配置与启动

### 4.1 准备配置文件

```bash
# 复制并编辑配置
cp config.yaml config.prod.yaml

# 使用 vim 或 nano 编辑
nano config.prod.yaml
```

**关键配置项调整**（`config.prod.yaml`）：

```yaml
app:
  # 切换为生产环境
  environment: production
  # 监听所有网卡（以便 Nginx 代理）
  phone_home_listen_host: "0.0.0.0"
  # Daemon HTTP 端口
  phone_home_listen_port: 8787
  # 启用哨兵自愈（按需开启）
  sentinel_enabled: false

logging:
  level: INFO   # 生产环境用 INFO，避免日志过大

telegram:
  enabled: true  # 开启告警通知
  bot_token: "YOUR_BOT_TOKEN"
  chat_id: "YOUR_CHAT_ID"

cloudflare:
  enabled: true
  api_token: "YOUR_CF_API_TOKEN"
  zone_id: "YOUR_ZONE_ID"
  root_domain: "rensw.xyz"

xboard:
  host: "YOUR_XBOARD_DB_HOST"
  port: 5432
  database: xboard
  user: tanxuan
  password: "YOUR_DB_PASSWORD"
```

### 4.2 配置环境变量（推荐）

将敏感信息放在环境变量中，避免明文配置：

```bash
# 创建环境变量文件
nano ~/.shadowfleet_env
```

```bash
# ~/.shadowfleet_env

# AWS 凭证
export AWS_ACCESS_KEY_ID="AKIAXXXXXXXXXXXXX"
export AWS_SECRET_ACCESS_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
export AWS_DEFAULT_REGION="ap-northeast-1"

# Cloudflare
export CF_API_TOKEN="hK6welTvuPjdXXD5B4CX3y_7TRDt-bnDc5OgywaI"

# Xboard 数据库
export XB_DB_HOST="YOUR_XBOARD_HOST"
export XB_DB_PASSWORD="YOUR_DB_PASSWORD"

# Telegram
export TG_BOT_TOKEN="YOUR_BOT_TOKEN"
export TG_CHAT_ID="YOUR_CHAT_ID"

# 配置文件路径
export SF_CONFIG_PATH="/home/shadowfleet/ShadowFleet/config.prod.yaml"
```

```bash
# 加载环境变量
source ~/.shadowfleet_env

# 加入 shell 启动自动加载（可选）
echo 'source ~/.shadowfleet_env' >> ~/.bashrc
```

---

## 5. Nginx 反向代理

### 5.1 安装 Nginx

```bash
sudo apt install -y nginx
```

### 5.2 配置反向代理

```bash
# 创建站点配置
sudo nano /etc/nginx/sites-available/shadowfleet
```

```nginx
# ShadowFleet 反向代理配置
# 同时代理 Daemon (8787) 和 Streamlit UI (8501)

upstream shadowfleet_daemon {
    server 127.0.0.1:8787;
    keepalive 32;
}

upstream shadowfleet_ui {
    server 127.0.0.1:8501;
    keepalive 32;
}

server {
    listen 80;
    server_name shadow.rensw.xyz;   # 替换为你的域名

    # HTTP 重定向到 HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name shadow.rensw.xyz;   # 替换为你的域名

    # SSL 证书（Let's Encrypt 自动续期）
    ssl_certificate     /etc/letsencrypt/live/shadow.rensw.xyz/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/shadow.rensw.xyz/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers off;

    # 安全响应头
    add_header X-Frame-Options          "SAMEORIGIN"     always;
    add_header X-Content-Type-Options    "nosniff"        always;
    add_header X-XSS-Protection          "1; mode=block"  always;
    add_header Referrer-Policy           "no-referrer"    always;
    add_header Content-Security-Policy   "default-src 'self';" always;

    # ---------- Daemon API 代理 ----------
    location /api/ {
        proxy_pass         http://shadowfleet_daemon;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header   Connection "";

        # 超时设置
        proxy_connect_timeout 15s;
        proxy_send_timeout    30s;
        proxy_read_timeout    30s;
    }

    # ---------- Streamlit UI 代理 ----------
    location / {
        proxy_pass         http://shadowfleet_ui;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header   Connection "";

        # Streamlit WebSocket 支持
        proxy_read_timeout  86400s;
        proxy_send_timeout  86400s;

        # 流式响应
        proxy_buffering    off;
        chunked_transfer_encoding on;
    }
}
```

```bash
# 启用站点配置
sudo ln -s /etc/nginx/sites-available/shadowfleet /etc/nginx/sites-enabled/

# 测试配置语法
sudo nginx -t

# 重载 Nginx
sudo systemctl reload nginx
```

---

## 6. Systemd 服务管理

### 6.1 创建 Daemon 服务

```bash
sudo nano /etc/systemd/system/shadowfleet-daemon.service
```

```ini
[Unit]
Description=ShadowFleet Daemon - Self-Healing Engine
After=network.target network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=shadowfleet
Group=shadowfleet
WorkingDirectory=/home/shadowfleet/ShadowFleet



# 使用虚拟环境中的 Python
ExecStart=/home/shadowfleet/ShadowFleet/venv/bin/python daemon.py
ExecStartPost=/bin/sleep 3

# 自动重启配置
Restart=on-failure
RestartSec=10
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=60

# 日志输出重定向（由 journald 管理）
StandardOutput=journal
StandardError=journal
SyslogIdentifier=shadowfleet-daemon

# 安全加固
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/shadowfleet/ShadowFleet
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### 6.2 创建 Streamlit UI 服务（可选）

```bash
sudo nano /etc/systemd/system/shadowfleet-ui.service
```

```ini
[Unit]
Description=ShadowFleet Streamlit UI Dashboard
After=network.target network-online.target shadowfleet-daemon.service
Wants=network-online.target

[Service]
Type=simple
User=shadowfleet
Group=shadowfleet
WorkingDirectory=/home/shadowfleet/ShadowFleet



# Streamlit UI 入口
ExecStart=/home/shadowfleet/ShadowFleet/venv/bin/streamlit run app.py \
    --server.port 8501 \
    --server.address 127.0.0.1 \
    --server.headless true \
    --browser.gatherUsageStats false \
    --global.developmentMode false

Restart=on-failure
RestartSec=10
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=30

StandardOutput=journal
StandardError=journal
SyslogIdentifier=shadowfleet-ui

# 安全加固
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/shadowfleet/ShadowFleet
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### 6.3 注册并启动服务

```bash
# 重新加载 systemd 配置
sudo systemctl daemon-reload

# 启用开机自启
sudo systemctl enable shadowfleet-daemon.service
sudo systemctl enable shadowfleet-ui.service

# 启动服务
sudo systemctl start shadowfleet-daemon.service
sudo systemctl start shadowfleet-ui.service

# 查看服务状态
sudo systemctl status shadowfleet-daemon.service
sudo systemctl status shadowfleet-ui.service
```

**常用管理命令**：

```bash
# 重启
sudo systemctl restart shadowfleet-daemon
sudo systemctl restart shadowfleet-ui

# 停止
sudo systemctl stop shadowfleet-daemon
sudo systemctl stop shadowfleet-ui

# 查看日志
sudo journalctl -u shadowfleet-daemon -f --lines=50
sudo journalctl -u shadowfleet-ui -f --lines=50

# 查看错误日志
sudo journalctl -u shadowfleet-daemon -p err -f
```

---

## 7. SSL 证书配置

### 7.1 使用 Let's Encrypt (Certbot)

```bash
# 安装 Certbot
sudo apt install -y certbot python3-certbot-nginx

# 申请证书（自动配置 Nginx）
sudo certbot --nginx -d shadow.rensw.xyz

# 测试自动续期
sudo certbot renew --dry-run

# 设置定时续期（Certbot 自动安装 cron job）
# 手动确认续期任务存在
sudo systemctl list-timers | grep certbot
```

### 7.2 如果只有 IP（自签名证书）

```bash
# 生成自签名证书（仅限内网/测试环境）
sudo apt install -y openssl

sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/ssl/private/shadowfleet.key \
    -out /etc/ssl/certs/shadowfleet.crt \
    -subj "/C=CN/ST=Beijing/L=Beijing/O=ShadowFleet/CN=YOUR_SERVER_IP"

# 更新 Nginx 配置中的 ssl_certificate 路径
```

---

## 8. 防火墙与网络安全

### 8.1 UFW 防火墙配置

```bash
# 安装 UFW
sudo apt install -y ufw

# 设置默认策略
sudo ufw default deny incoming
sudo ufw default allow outgoing

# 允许 SSH（必须先允许，否则可能断开连接！）
sudo ufw allow 22/tcp comment 'SSH'

# 允许 HTTP/HTTPS
sudo ufw allow 80/tcp comment 'HTTP'
sudo ufw allow 443/tcp comment 'HTTPS'

# 允许 ShadowFleet 服务端口（仅允许 Nginx 访问，不直接暴露）
# Daemon 8787 和 UI 8501 通过 Nginx 代理，不直接对外开放

# 启用防火墙
sudo ufw enable

# 查看状态
sudo ufw status verbose
```

### 8.2 Fail2ban 防暴力破解

```bash
# 安装 Fail2ban
sudo apt install -y fail2ban

# 复制默认配置
sudo cp /etc/fail2ban/jail.conf /etc/fail2ban/jail.local

# 编辑配置
sudo nano /etc/fail2ban/jail.local
```

```ini
[sshd]
enabled  = true
port     = 22
maxretry = 5
findtime = 10m
bantime  = 1h
action   = iptables-allports

[nginx-http-auth]
enabled = true
maxretry = 5
```

```bash
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

---

## 9. 启动验证

### 9.1 检查服务状态

```bash
# 检查进程是否运行
ps aux | grep -E "(daemon|streamlit)" | grep -v grep

# 检查端口监听
ss -tlnp | grep -E "(8501|8787|443|80)"

# 检查服务状态
sudo systemctl status shadowfleet-daemon --no-pager
sudo systemctl status shadowfleet-ui --no-pager
```

### 9.2 访问验证

```bash
# 测试 Daemon API
curl -s http://127.0.0.1:8787/health

# 测试 Streamlit UI（本地）
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8501/

# 测试外部访问（替换为你的域名）
curl -s -o /dev/null -w "%{http_code}" https://shadow.rensw.xyz/
```

### 9.3 查看日志

```bash
# Daemon 实时日志
sudo journalctl -u shadowfleet-daemon -f

# UI 实时日志
sudo journalctl -u shadowfleet-ui -f

# 如果使用文件日志
tail -f /home/shadowfleet/ShadowFleet/shadowfleet.log
```

---

## 10. 日志管理

### 10.1 日志轮转配置

```bash
# 创建日志轮转配置
sudo nano /etc/logrotate.d/shadowfleet
```

```bash
# ShadowFleet 日志轮转配置

/home/shadowfleet/ShadowFleet/*.log {
    daily              # 每天轮转
    missingok          # 缺失文件不报错
    notifempty         # 空文件不轮转
    compress           # 压缩旧日志
    delaycompress      # 延迟压缩（保留最新1个不压缩）
    maxsize 100M       # 超过 100M 强制轮转
    maxage 30          # 超过 30 天删除
    create 0640 shadowfleet shadowfleet  # 轮转后创建新文件权限
    sharedscripts      # 所有日志轮转后只执行一次 postrotate
    postrotate
        systemctl reload shadowfleet-daemon > /dev/null 2>&1 || true
        systemctl reload shadowfleet-ui > /dev/null 2>&1 || true
    endscript
}
```

### 10.2 集中日志查看

```bash
# 查看所有 ShadowFleet 相关日志
sudo journalctl -u shadowfleet-daemon -u shadowfleet-ui --since "1 hour ago"

# 按错误级别过滤
sudo journalctl -u shadowfleet-daemon -p err

# 导出日志到文件
sudo journalctl -u shadowfleet-daemon --since "24 hours ago" > ~/daemon_24h.log
```

---

## 11. 更新与回滚

### 11.1 更新流程

```bash
# SSH 登录服务器
ssh shadowfleet@<SERVER_IP>

# 备份当前版本
cd ~/ShadowFleet
cp -r venv venv.bak.$(date +%Y%m%d%H%M%S)
cp config.prod.yaml config.prod.yaml.bak.$(date +%Y%m%d%H%M%S)

# 拉取新代码（如果用 Git）
git pull

# 或者上传新代码覆盖
# (在本地执行) scp -r ./new_version/* shadowfleet@SERVER:/home/shadowfleet/ShadowFleet/

# 更新依赖
source venv/bin/activate
pip install -r requirements.txt --upgrade

# 重启服务
sudo systemctl restart shadowfleet-daemon
sudo systemctl restart shadowfleet-ui

# 验证
sleep 5
sudo systemctl status shadowfleet-daemon --no-pager
```

### 11.2 回滚流程

```bash
# 停止服务
sudo systemctl stop shadowfleet-daemon shadowfleet-ui

# 恢复备份
cd ~/ShadowFleet
rm -rf venv
mv venv.bak.YYYYMMDDHHMMSS venv

mv config.prod.yaml config.prod.yaml.broken
mv config.prod.yaml.bak.YYYYMMDDHHMMSS config.prod.yaml

# 重启服务
sudo systemctl start shadowfleet-daemon
sudo systemctl start shadowfleet-ui
```

### 11.3 数据库迁移（如有）

```bash
# 如果有数据库迁移脚本，按顺序执行
# psql -h <DB_HOST> -U tanxuan -d xboard -f migration_001.sql
```

---

## 快速部署检查清单

```bash
# ===== 一键部署脚本 =====

# 1. 系统准备
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl wget git unzip sudo \
    apt-transport-https ca-certificates gnupg \
    build-essential libpq-dev nginx certbot python3-certbot-nginx

# 2. 创建用户
sudo useradd -m -s /bin/bash -G sudo shadowfleet

# 3. 安装 Python
sudo apt install -y python3-full python3-pip python3-venv python3-dev

# 4. 创建目录并上传代码
mkdir -p /home/shadowfleet/ShadowFleet

# 5. 安装依赖并配置（见上文步骤 3-6）
# ...
```
