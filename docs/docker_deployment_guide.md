# ShadowFleet Docker 容器化部署指南

> 源码上传到服务器后，基于 Docker Compose 的完整部署流程。
>
> **前置条件**：服务器已安装 Docker 和 Docker Compose。

---

## 目录

1. [架构概览](#1-架构概览)
2. [上传源码](#2-上传源码)
3. [服务器环境准备](#3-服务器环境准备)
4. [配置 config.yaml](#4-配置-configyaml)
5. [配置 .env 环境变量](#5-配置-env-环境变量)
6. [构建前端](#6-构建前端)
7. [构建并启动容器](#7-构建并启动容器)
8. [配置 Nginx 与 SSL](#8-配置-nginx-与-ssl)
9. [验证部署](#9-验证部署)
10. [常用运维命令](#10-常用运维命令)
11. [更新与回滚](#11-更新与回滚)

---

## 1. 架构概览

```
┌──────────────────────────────────────────────────────────────┐
│                         Nginx (:443)                         │
│         /api/* → shadowfleet-api:8000                        │
│         / → shadowfleet-frontend-dist volume (Vue SPA)      │
│         /probe/* → shadowfleet-daemon:8787                   │
│         /artifacts/* → shadowfleet-daemon:8080              │
└──────────┬────────────────────┬───────────────────────────────┘
           │                    │
           ▼                    ▼
┌──────────────────────┐   ┌───────────────────────────────┐
│  shadowfleet-api     │   │  shadowfleet-daemon           │
│  FastAPI (:8000)     │   │  python daemon.py (:8787)     │
│                      │   │  - Provisioning Worker        │
│                      │   │  - Sentinel Worker            │
└──────────────────────┘   │  - Manual Op Worker           │
                           │  HTTP Server (:8080)         │
                           └───────────────────────────────┘
                                              │
                                    ┌─────────┴─────────┐
                                    │  PostgreSQL       │
                                    │  (Xboard :5432)   │
                                    └───────────────────┘
```

### 容器说明

| 容器 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| `shadowfleet-api` | `shadowfleet/api:latest` | `8000` | FastAPI 后端 + Vue SPA 静态文件 |
| `shadowfleet-daemon` | `shadowfleet/daemon:latest` | `8787`（必须）、`8080`（可选） | 后台任务调度 + phone-home 回调 |
| `shadowfleet-nginx` | `nginx:1.27-alpine` | `80`、`443` | TLS 终止 + 反向代理 |

### 数据持久化（Docker Volume）

| Volume | 内容 |
|--------|------|
| `shadowfleet-db` | SQLite 数据库 `shadowfleet.db` |
| `shadowfleet-logs` | 日志文件 `logs/` |
| `shadowfleet-artifacts` | V2bX 安装包缓存（`artifact_cache_enabled=true` 时） |
| `shadowfleet-frontend` | Vue 构建产物（共享给 API 和 Nginx） |
| `shadowfleet-certbot` | Let's Encrypt SSL 证书 |

---

## 2. 上传源码

### 2.1 本地准备

上传前先检查源码目录，确保 `frontend/dist/` 已构建（否则部署后前端空白）：

```bash
cd frontend
npm install
npm run build
cd ..
```

如果不需要预构建，也可以跳过这一步，服务器上会自动构建。

### 2.2 上传到服务器

通过 `scp` 或 `rsync` 上传（注意排除敏感文件和依赖包）：

```bash
# 方式一：scp（整个项目）
scp -r ./ShadowFleet root@your-server:/opt/

# 方式二：rsync（排除不需要的文件，更快）
rsync -avz --exclude 'node_modules' \
         --exclude '.git' \
         --exclude 'frontend/node_modules' \
         --exclude '__pycache__' \
         --exclude '*.pyc' \
         --exclude '.pytest_cache' \
         --exclude 'config.yaml' \
         --exclude 'config.dev.yaml' \
         ./ShadowFleet/ root@your-server:/opt/shadowfleet/
```

---

## 3. 服务器环境准备

### 3.1 安装 Docker

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg

# 添加 Docker GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 添加 Docker APT 源
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

### 3.2 验证安装

```bash
docker --version
docker compose version
```

### 3.3 配置 Docker 开机自启

```bash
sudo systemctl enable docker
sudo systemctl enable containerd
```

### 3.4 （可选）以非 root 用户运行 Docker

```bash
sudo usermod -aG docker $USER
# 重新登录使用户组生效
newgrp docker
```

---

## 4. 配置 config.yaml

在服务器上，复制模板并填写必要配置：

```bash
cd /opt/shadowfleet
cp config.template.yaml config.yaml
nano config.yaml
```

需要重点修改的配置项：

```yaml
# app/config.yaml

app:
  environment: production          # 修改为 production
  sqlite_path: /data/shadowfleet.db # 容器内数据目录

  phone_home_listen_host: "0.0.0.0" # 监听所有网卡（容器内）
  phone_home_listen_port: 8787

  # Sentinel 暂不启用（生产稳定后再开）
  sentinel_enabled: false

xboard:
  host: 137.175.65.47               # Xboard 数据库地址
  port: 5432
  database: xboard
  user: tanxuan
  password: null                    # 留空，通过环境变量注入

telegram:
  enabled: true                     # 启用告警通知
  bot_token: null                   # 通过环境变量注入
  chat_id: null                     # 通过环境变量注入

cloudflare:
  enabled: true                    # 启用 DNS 管理
  api_token: null                   # 通过环境变量注入
  zone_id: null                     # 通过环境变量注入
  root_domain: "rensw.xyz"         # 你的根域名
```

> **安全提示**：`config.yaml` 中的敏感字段（密码、Token、密钥）全部留 `null`，通过 `.env` 环境变量注入。

---

## 5. 配置 .env 环境变量

```bash
cd /opt/shadowfleet
cp .env.example .env
nano .env
```

完整配置项说明：

```bash
SHADOWFLEET_ENVIRONMENT=production
```

> **说明**：所有业务配置（数据库密码、Telegram Token、Cloudflare、Dashboard 密码等）已在服务器的 `config.yaml` 中填写，Docker 通过 `config.yaml` 挂载读取。`.env` 只保留运行环境标识。

---

## 6. 构建前端

前端构建产物会写入 `shadowfleet-frontend-dist` volume，由 `shadowfleet-nginx` 挂载为静态文件目录（自动化流程，无需手动复制）。

### 6.1 构建前端镜像

```bash
cd /home/shadowfleet/ShadowFleet

# 构建并启动前端 builder（会自动把构建产物复制到 named volume）
docker compose --profile frontend-build up -d --build

# 等待构建完成（约 2-3 分钟）
sleep 30

# 确认 volume 中已有文件
docker exec shadowfleet-frontend-builder ls -la /usr/share/nginx/html/
```

### 6.2 验证构建结果

```bash
# 检查 volume 中是否有文件
docker exec shadowfleet-nginx ls -la /usr/share/nginx/html/

# 应该看到 index.html 和 assets/ 目录
```

---

## 7. 构建并启动容器

### 7.1 拉取基础镜像并构建

```bash
cd /opt/shadowfleet

# 构建 API 和 Daemon 镜像（约 3-5 分钟，首次）
docker compose build
```

### 7.2 启动所有容器

```bash
# 启动（daemon 模式，后台运行）
docker compose up -d

# 启动并实时查看日志
docker compose up -d && docker compose logs -f
```

### 7.3 检查容器状态

```bash
docker compose ps
```

正常输出：

```
NAME                   STATUS          PORTS
shadowfleet-frontend   Up              9000/tcp
shadowfleet-api        Up (healthy)    0.0.0.0:8000->8000/tcp
shadowfleet-daemon     Up              0.0.0.0:8787->8787/tcp, 0.0.0.0:8080->8080/tcp
shadowfleet-nginx      Up              0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
```

### 7.4 查看日志

```bash
# 实时查看所有容器日志
docker compose logs -f

# 只看 API 日志
docker compose logs -f shadowfleet-api

# 只看 Daemon 日志
docker compose logs -f shadowfleet-daemon

# 查看最近 100 行
docker compose logs --tail=100 shadowfleet-daemon
```

---

## 8. 配置 Nginx 与 SSL

### 8.1 首次申请 Let's Encrypt 证书

> **前提**：域名已解析到服务器 IP。

```bash
# 启动容器（不带 Nginx，先占住 80 端口）
docker compose up -d shadowfleet-api shadowfleet-daemon

# 申请证书（certbot 会自动修改 nginx.conf，需重新 mount）
certbot certonly --standalone \
    --preferred-challenges http \
    --domains your-domain.com \
    --email your@email.com \
    --agree-tos --non-interactive

# 证书存放于 /etc/letsencrypt/live/your-domain.com/
```

### 8.2 挂载证书到容器

证书申请成功后，编辑 `deploy/nginx.conf` 中的证书路径为实际路径，或通过 volume 直接挂载：

```bash
# 将证书软链接到项目目录（方便 volume 挂载）
sudo mkdir -p /opt/shadowfleet/certs/live/your-domain.com
sudo ln -s /etc/letsencrypt/live/your-domain.com/fullchain.pem /opt/shadowfleet/certs/live/your-domain.com/fullchain.pem
sudo ln -s /etc/letsencrypt/live/your-domain.com/privkey.pem /opt/shadowfleet/certs/live/your-domain.com/privkey.pem
```

修改 `deploy/nginx.conf` 中的证书路径：

```nginx
ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
```

添加 volume 挂载到 `docker-compose.yml` 的 nginx service 中：

```yaml
# 在 shadowfleet-nginx 的 volumes 中添加
- /opt/shadowfleet/certs:/etc/letsencrypt:ro
```

### 8.3 启动 Nginx

```bash
docker compose up -d shadowfleet-nginx
```

### 8.4 证书自动续期

Let's Encrypt 证书有效期 90 天，需配置自动续期：

```bash
# 编辑 crontab
sudo crontab -e

# 添加以下行（每天凌晨 3 点检查，过期前自动续期）
0 3 * * * docker exec shadowfleet-nginx nginx -s reload || true
0 3 * * * /usr/bin/certbot renew --deploy-hook "docker exec shadowfleet-nginx nginx -s reload"
```

---

## 9. 验证部署

### 9.1 健康检查

```bash
# API 健康检查
curl http://localhost:8000/api/v1/health
# 期望输出：{"status":"ok"}

# API 端点验证
curl http://localhost:8000/api/v1/dashboard/snapshot
# 期望输出：JSON 数据（可能需要认证）

# Phone-Home 端点验证
curl http://localhost:8787/probe/config?probe_id=test&auth_token=test
# 期望输出：{"error":"..."}（正常响应即服务正常）
```

### 9.2 浏览器访问

| 地址 | 说明 |
|------|------|
| `http://your-server-ip` | Vue SPA 前端 |
| `https://your-domain.com` | 带 SSL 的前端 |
| `https://your-domain.com/api/v1/health` | API 健康检查 |

### 9.3 容器健康状态

```bash
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
```

所有容器状态应为 `Up (healthy)`。

---

## 10. 常用运维命令

### 10.1 启停管理

```bash
# 停止所有容器
docker compose stop

# 启动所有容器
docker compose start

# 重启指定容器
docker compose restart shadowfleet-api
docker compose restart shadowfleet-daemon

# 停止并删除容器（保留数据卷）
docker compose down

# 停止并删除容器 + 删除数据卷（慎用，会清空数据库）
docker compose down -v
```

### 10.2 进入容器调试

```bash
# 进入 API 容器
docker compose exec shadowfleet-api /bin/bash

# 进入 Daemon 容器
docker compose exec shadowfleet-daemon /bin/bash

# Python 交互式调试
docker compose exec shadowfleet-api python -c "from services.xxx import Xxx"
```

### 10.3 数据管理

```bash
# 备份 SQLite 数据库
docker compose exec shadowfleet-api cp /data/shadowfleet.db /data/shadowfleet.db.$(date +%Y%m%d%H%M%S).bak

# 导出数据库到宿主机
docker compose exec shadowfleet-api tar czf /data/shadowfleet.db.tar.gz -C /data shadowfleet.db
docker cp shadowfleet-api:/data/shadowfleet.db.tar.gz ./

# 恢复数据库
docker cp ./shadowfleet.db.shadowfleet-api:/data/shadowfleet.db
```

### 10.4 日志轮转

Docker Compose 日志默认不轮转，需配置 `/etc/docker/daemon.json`：

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json > /dev/null <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "10"
  }
}
EOF

sudo systemctl restart docker
# 注意：修改后需要重新创建容器才会生效
docker compose down && docker compose up -d
```

---

## 11. 更新与回滚

### 11.1 更新流程

```bash
cd /opt/shadowfleet

# 1. 备份当前数据库
docker compose exec shadowfleet-api cp /data/shadowfleet.db /data/shadowfleet.db.bak

# 2. 上传新版本源码（覆盖 /opt/shadowfleet/）

# 3. 重新构建镜像
docker compose build --no-cache

# 4. 重启容器
docker compose up -d --build

# 5. 如果前端有更新，重新构建前端
docker compose --profile frontend-build up -d --build shadowfleet-frontend-builder

# 6. 验证
docker compose logs --tail=50 shadowfleet-api
curl http://localhost:8000/api/v1/health
```

### 11.2 回滚流程

```bash
cd /opt/shadowfleet

# 1. 停止当前容器
docker compose down

# 2. 从备份恢复数据库
docker cp shadowfleet.db.bak shadowfleet-api:/data/shadowfleet.db

# 3. 使用上一版本镜像标签（如果有打 tag）
# docker tag shadowfleet/api:previous shadowfleet/api:latest
# docker tag shadowfleet/daemon:previous shadowfleet/daemon:latest

# 4. 重启
docker compose up -d
```

### 11.3 镜像版本管理（可选）

如果需要版本管理，在 `docker-compose.yml` 中指定具体版本：

```bash
# 打标签
docker tag shadowfleet/api:latest shadowfleet/api:v0.2.0
docker tag shadowfleet/daemon:latest shadowfleet/daemon:v0.2.0
docker push shadowfleet/api:v0.2.0

# 回滚时
docker compose stop
docker tag shadowfleet/api:v0.1.0 shadowfleet/api:latest
docker tag shadowfleet/daemon:v0.1.0 shadowfleet/daemon:latest
docker compose up -d
```

---

## 附录：端口一览

| 端口 | 协议 | 容器 | 外部暴露 | 说明 |
|------|------|------|----------|------|
| 80 | TCP | nginx | 是 | ACME HTTP 验证 |
| 443 | TCP | nginx | 是 | HTTPS 入口 |
| 8000 | TCP | api | 可选 | API 直连（开发用） |
| 8787 | TCP | daemon | 是 | 节点 phone-home 回调 |
| 8080 | TCP | daemon | 否 | Artifact 缓存（可选） |

> `8787` 必须从外部访问（AWS 节点需要回调），建议在防火墙/安全组中仅允许 137.175.65.47 访问。
