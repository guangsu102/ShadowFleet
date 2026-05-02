# ShadowFleet 远程部署测试文档

> **适用对象**：ShadowFleet 已完成 `docs/deployment_guide.md` 部署，Streamlit UI 和 Daemon 已能正常访问。
>
> **测试原则**：本地单元测试已覆盖所有 mock 环境下的业务逻辑（Schema / SQLite CRUD / Xboard Repo / AWS&CF 客户端 / Telegram / E2E moto）。本文档仅验证 **本地 mock 无法覆盖** 的部分：真实进程存活、真实网络连通、真实外部 API（Xboard/Cloudflare/AWS）、端到端 HTTP 链路。

---

## 测试前准备

```bash
# SSH 登录服务器
ssh shadowfleet@<SERVER_IP>

# 加载环境变量
source ~/.shadowfleet_env

# 进入项目目录
cd ~/ShadowFleet
source venv/bin/activate

# 确认 Python 版本
python3 --version

# 确认关键路径
DOMAIN="shadow.rensw.xyz"   # ← 按实际替换
CONFIG="config.prod.yaml"
```

---

## 阶段一：基础设施层（仅需手动检查）

| 检查项 | 操作方式 | 通过标准 |
|--------|---------|---------|
| Systemd 服务状态 | `sudo systemctl status shadowfleet-daemon --no-pager` | `Active: active (running)` |
| Streamlit UI 服务 | `sudo systemctl status shadowfleet-ui --no-pager` | `Active: active (running)` |
| Nginx 监听端口 | `ss -tlnp \| grep -E "(8501\|8787\|443)"` | 8501/8787 仅监听 127.0.0.1，443 监听所有 |
| SSL 证书 | `sudo certbot certificates 2>/dev/null \| grep "$DOMAIN"` 或 `sudo ls /etc/letsencrypt/live/$DOMAIN/` | 证书存在且未过期 |
| 防火墙 | `sudo ufw status verbose` | 22/80/443 允许，其余拒绝 |
| Nginx 配置 | `sudo nginx -t` | `syntax is ok / test is successful` |

---

## 阶段二：UI 操作 — 节点初始化（核心流程）

> **测试方式**：在浏览器中直接操作，全程观察页面反馈 + Telegram 通知 + 服务器日志。

### 2.1 准备工作：确认有可用资产

在 UI 中访问 **Assets 页面** (`/Assets`)，确认至少有一个 AWS 账号：

- `status = active`
- 该账号下至少有一个协议（如 `AnyTLS`）且 `enabled = true`
- `current_allocated_count < max_count`（有可用槽位）

如果无资产 → 先在 Assets 页面添加 AWS 账号和协议配置。

### 2.2 提交节点创建任务

1. 访问 **Provisioner 页面** (`/Provisioner`)
2. 填写表单：
   - **Node Name**：填一个测试名称，如 `test-manual-001`
   - **Asset**：选择步骤 2.1 中确认的 AWS 账号
   - **Protocol**：选择 `AnyTLS` 或其他有槽位的协议
   - **Region**：选择一个有 IPv6 的区域（如 `ap-northeast-1`）
   - 其余字段留空（自动使用默认值）
3. 点击 **提交**
4. **观察**：
   - 页面是否显示任务已提交（task_id / correlation_id）
   - Ops 页面是否出现新的 `provision_node` 任务（状态应为 `queued` → `running`）

### 2.3 观察 Daemon 处理日志

```bash
# 在另一个终端实时跟踪 Daemon 日志
sudo journalctl -u shadowfleet-daemon -f --since "30 seconds ago"
```

预期日志序列（按时间顺序）：

```
[provisioning_started]      # 开始初始化
[asset_selected]            # 选中了哪个 AWS 账号/协议
[registering_node_in_xboard]  # Xboard 注册
[ec2_instance_launching]   # AWS EC2 开始启动
[instance_id: i-xxxxx]      # 实例 ID 出现
[ipv6_address_assigned]     # IPv6 分配成功
[dns_record_syncing]       # Cloudflare DNS 同步
[waiting_ready_callback]    # 等待节点 phone-home
[ready_callback_received]   # 节点回调到达
[marking_node_online]       # 标记上线
[provisioning_succeeded]    # 全部完成
```

### 2.4 等待 Ready Callback（最多 5 分钟）

EC2 节点启动后，会在 User-Data 中自动执行 V2bX 安装脚本，完成后向 Daemon 发送 `/api/v1/provisioning/ready` 回调。

**观察节点是否出现在 Xboard 面板中**（在你的 Xboard 管理界面搜索 `sf-test-manual-001`）。

### 2.5 验证最终结果

- **UI Fleet 页面**：`test-manual-001` 状态应为 `online`
- **UI Dashboard**：Fleet Matrix 中对应区域/协议数量 +1
- **Telegram**：收到一条成功通知（绿色）

### 2.6 预期完整成功耗时

约 3~5 分钟（EC2 启动约 1 分钟 + V2bX 安装约 2~3 分钟 + 回调约 10 秒）。

---

## 阶段三：UI 操作 — Heal 自愈（核心流程）

> **前提**：阶段二成功，有一个 `online` 状态的节点。

### 3.1 手动触发 Heal

1. 访问 **Fleet 页面** (`/Fleet`)
2. 选中 `test-manual-001` 节点
3. 点击 **Manual Operation** → 选择 `force_heal`
4. 点击 **执行**

### 3.2 观察 Heal 日志

```bash
sudo journalctl -u shadowfleet-daemon -f --since "1 minute ago"
```

预期日志序列：

```
[healing_started]
[healing_strategy_selected] strategy=aws_ipv6_rotate
[acquiring_operation_lock]
[healing_completed]
[old_ipv6=2600:xxxx:xxxx:xxxx::xxx]   # 旧 IPv6
[new_ipv6=2600:xxxx:xxxx:xxxx::yyy]   # 新 IPv6，地址已更换
```

### 3.3 验证结果

- **UI Fleet 页面**：节点仍为 `online`，`last_healed_at` 时间已更新
- **Cloudflare DNS**：AA 记录值已变为新 IPv6
- **Telegram**：收到 Heal 成功通知

---

## 阶段四：UI 操作 — 节点启停与删除

> **前提**：阶段二成功，有一个 `online` 状态的节点。

### 4.1 Stop 操作

1. Fleet 页面选中节点 → **Manual Operation** → 选择 `stop_node` → 执行
2. 观察：节点状态变为 `offline`（约 30 秒内）
3. Telegram 收到通知

### 4.2 Start 操作

1. Fleet 页面选中 `offline` 节点 → **Manual Operation** → 选择 `start_node` → 执行
2. 观察：节点状态恢复 `online`（约 1 分钟内）
3. Telegram 收到通知

### 4.3 Decommission（删除）操作

1. Fleet 页面选中节点 → **Manual Operation** → 选择 `decommission_node` → 执行
2. 观察：
   - 节点状态变为 `deleted`
   - Xboard 面板中该节点消失
   - Cloudflare DNS 记录被清理
3. Telegram 收到通知

---

## 阶段五：UI 操作 — Probe 链路

> **前提**：有一台部署了 Probe Agent 的机器。

### 5.1 Probe 注册

在部署了 Probe Agent 的机器上确认 agent 已运行：

```bash
# 在 Probe Agent 机器上执行
systemctl status shadowfleet-probe   # 如果配置了 systemd
# 或直接运行
python3 probe_agent/agent.py
```

UI 中访问 **Probes 页面** (`/Probes`)，应能看到新注册的 probe：

- `probe_id` 自动生成
- `status = active`
- `last_seen` 时间更新

### 5.2 Probe 心跳

Probe Agent 每 15 秒自动发送心跳，无需手动操作。在 Probes 页面观察 `last_seen` 时间持续更新。

### 5.3 Probe 命令下发

1. UI 访问 **Ops 页面** (`/Ops`) 或 **Probes 页面**
2. 找到注册的 probe → 下发 `self_check` 命令
3. Probe Agent 收到后执行，结果返回到控制面
4. 观察 Probes 页面命令历史状态变为 `succeeded`

---

## 阶段六：基础设施连通性验证（脚本）

> 以下是 **脚本验证**，确认外部依赖的连通性，无法通过 UI 测试。

### 6.1 AWS 凭证有效性

```bash
cd ~/ShadowFleet && source venv/bin/activate
python3 -c "
import boto3, os
from dotenv import load_dotenv
load_dotenv(os.path.expanduser('~/.shadowfleet_env'), verbose=False)

sts = boto3.client('sts')
identity = sts.get_caller_identity()
print('✅ AWS Account:', identity['Account'])
print('✅ IAM ARN:', identity['Arn'])
print('✅ Region:', os.getenv('AWS_DEFAULT_REGION'))

ec2 = boto3.client('ec2', region_name=os.getenv('AWS_DEFAULT_REGION'))
vpcs = ec2.describe_vpcs()
print('✅ VPCs:', [vpc['VpcId'] for vpc in vpcs['Vpcs']])
" 2>&1

# 预期：输出 AWS Account/ARN，无 AccessDenied 错误
```

### 6.2 Xboard PostgreSQL 连通性

```bash
cd ~/ShadowFleet && source venv/bin/activate
python3 -c "
import psycopg2, os
from dotenv import load_dotenv
load_dotenv(os.path.expanduser('~/.shadowfleet_env'), verbose=False)

conn = psycopg2.connect(
    host=os.getenv('XB_DB_HOST', '127.0.0.1'),
    port=os.getenv('XB_DB_PORT', '5432'),
    database='xboard',
    user='tanxuan',
    password=os.getenv('XB_DB_PASSWORD', '')
)
cur = conn.cursor()
cur.execute('SELECT version();')
print('✅ PostgreSQL:', cur.fetchone()[0].split(',')[0])
conn.close()
" 2>&1

# 预期：输出 PostgreSQL 版本
```

### 6.3 Xboard ShadowFleet 节点查询

```bash
cd ~/ShadowFleet && source venv/bin/activate
python3 -c "
import psycopg2, os
from dotenv import load_dotenv
load_dotenv(os.path.expanduser('~/.shadowfleet_env'), verbose=False)

conn = psycopg2.connect(
    host=os.getenv('XB_DB_HOST', '127.0.0.1'),
    port=os.getenv('XB_DB_PORT', '5432'),
    database='xboard',
    user='tanxuan',
    password=os.getenv('XB_DB_PASSWORD', '')
)
cur = conn.cursor()
cur.execute(\"SELECT id, name, type, host, show FROM public.v2_server WHERE name LIKE 'sf-%%' ORDER BY created_at DESC LIMIT 10\")
rows = cur.fetchall()
print(f'Xboard ShadowFleet 节点: {len(rows)} 个')
for r in rows:
    print(f'  id={r[0]} | name={r[1]} | type={r[2]} | host={r[3]} | show={r[4]}')
conn.close()
" 2>&1

# 预期：能看到阶段二创建的节点（如 sf-test-manual-001）
```

### 6.4 Cloudflare API 连通性

```bash
source ~/.shadowfleet_env
curl -s -X GET \
  -H "Authorization: Bearer $CF_API_TOKEN" \
  -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/dns_records?per_page=20" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
if data.get('success'):
    records = data.get('result', [])
    sf = [r for r in records if 'sf-' in r.get('name', '') or 'test-' in r.get('name', '')]
    print(f'✅ CF API 连通 | 总记录: {len(records)} | ShadowFleet 相关: {len(sf)}')
    for r in sf[-3:]:
        print(f'   [{r[\"type\"]}] {r[\"name\"]} -> {r[\"content\"]} (proxied={r[\"proxied\"]})')
else:
    print('❌ CF API 错误:', data.get('errors'))
" 2>&1

# 预期：✅ CF API 连通，且能看到节点 AAAA 记录
```

### 6.5 Telegram 通知

```bash
source ~/.shadowfleet_env
curl -s -X POST \
  "https://api.telegram.org/bot$TG_BOT_TOKEN/sendMessage" \
  -d "chat_id=$TG_CHAT_ID" \
  -d "text=🟢 ShadowFleet 连通性测试 OK $(date '+%Y-%m-%d %H:%M:%S')" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ TG OK' if d.get('ok') else '❌ TG 失败: ' + str(d))"

# 预期：✅ TG OK，并在 Telegram 收到消息
```

---

## 阶段七：端到端 HTTP 链路验证（脚本）

> **测试 Probe Agent 与 Control Plane 的真实 HTTP 交互**。

### 7.1 获取 Bootstrap Token

```bash
cd ~/ShadowFleet && source venv/bin/activate
python3 -c "
from utils.config_parser import ConfigParser
config = ConfigParser.load('config.prod.yaml')
tokens = config.app.probe_bootstrap_tokens
print('Bootstrap tokens:', tokens)
" 2>&1
```

### 7.2 Probe 注册（真实 HTTP 请求）

```bash
DOMAIN="shadow.rensw.xyz"    # ← 替换
BOOTSTRAP_TOKEN="your_token" # ← 从 7.1 获取

curl -s -X POST \
  -H "Content-Type: application/json" \
  -d "{
    \"bootstrap_token\": \"$BOOTSTRAP_TOKEN\",
    \"probe_name\": \"manual-probe-$(date +%s)\",
    \"probe_machine_fingerprint\": \"fp-manual-test\",
    \"probe_asn\": 2497,
    \"probe_isp\": \"ManualTestISP\",
    \"probe_region\": \"ap-northeast-1\",
    \"probe_public_ip\": \"$(curl -s ifconfig.me)\",
    \"probe_version\": \"1.0.0\"
  }" \
  "https://$DOMAIN/probe/register" | python3 -m json.tool

# 预期：返回 probe_id, auth_token, config_version
```

### 7.3 Probe 心跳

```bash
# 使用上一步返回的 probe_id 和 auth_token
PROBE_ID="probe-xxxxxxxx"
AUTH_TOKEN="xxxxxxxxxxxxxxxxxxxxxxxxxxxx"

curl -s -X POST \
  -H "Content-Type: application/json" \
  -d "{
    \"probe_id\": \"$PROBE_ID\",
    \"probe_key\": \"$AUTH_TOKEN\",
    \"cpu_load\": 0.15,
    \"memory_used_mb\": 256,
    \"memory_total_mb\": 2048
  }" \
  "https://$DOMAIN/probe/heartbeat" | python3 -m json.tool

# 预期：{"status": "ok", "probe_id": "..."}
```

### 7.4 Probe 命令轮询

```bash
curl -s -X POST \
  -H "Content-Type: application/json" \
  -d "{\"probe_id\": \"$PROBE_ID\", \"probe_key\": \"$AUTH_TOKEN\", \"lease_owner\": \"manual-test\", \"max_commands\": 5}" \
  "https://$DOMAIN/probe/poll" | python3 -m json.tool

# 预期：首次为空数组 []
```

---

## 阶段八：稳定性与并发（脚本）

### 8.1 Daemon 日志 ERROR 检查

```bash
# 检查最近 1 小时内无 ERROR
ERROR_COUNT=$(sudo journalctl -u shadowfleet-daemon --since "1 hour ago" -p err --no-pager | grep -v "^-- No entries" | wc -l)
echo "ERROR 日志条数: $ERROR_COUNT"
# 预期：0

# 如有 ERROR，查看详情
sudo journalctl -u shadowfleet-daemon --since "1 hour ago" -p err --no-pager | tail -10
```

### 8.2 并发压测

```bash
DOMAIN="shadow.rensw.xyz"

echo "=== 并发 30 请求压测 ==="
for i in $(seq 1 30); do
  curl -s -o /dev/null -w "%{http_code}\n" "https://$DOMAIN/health" &
done
wait | sort | uniq -c

# 预期：30 个全部 200，无 429 / 502 / 500
```

---

## 测试结果记录模板

```bash
cat > ~/ShadowFleet/test_results_$(date +%Y%m%d_%H%M%S).md << 'EOF'
# ShadowFleet 远程测试报告
- 测试时间：YYYY-MM-DD HH:MM
- 测试人员：xxx
- 服务器 IP：xxx

## 阶段一：基础设施层
| 检查项 | 结果 |
|--------|------|
| Daemon 服务 | ✅/❌ |
| UI 服务 | ✅/❌ |
| Nginx 端口 | ✅/❌ |
| SSL 证书 | ✅/❌ |
| 防火墙 | ✅/❌ |

## 阶段二：节点初始化（UI）
| 检查项 | 结果 | 详情 |
|--------|------|------|
| 资产可用 | ✅/❌ | 资产数=X |
| 任务提交 | ✅/❌ | task_id=xxx |
| EC2 启动 | ✅/❌ | instance_id=xxx |
| Xboard 注册 | ✅/❌ | xboard_node_id=xxx |
| DNS 同步 | ✅/❌ | record_id=xxx |
| Ready 回调 | ✅/❌ | 耗时Xs |
| TG 通知 | ✅/❌ | msg_id=xxx |

## 阶段三：Heal 自愈（UI）
| 检查项 | 结果 |
|--------|------|
| 触发成功 | ✅/❌ |
| IPv6 更换 | ✅/❌ old→new |
| TG 通知 | ✅/❌ |

## 阶段四：启停删除（UI）
| 操作 | 结果 |
|------|------|
| Stop | ✅/❌ |
| Start | ✅/❌ |
| Decommission | ✅/❌ |

## 阶段五：Probe 链路
| 检查项 | 结果 |
|--------|------|
| Probe 注册 | ✅/❌ |
| Probe 心跳 | ✅/❌ |
| 命令下发 | ✅/❌ |

## 阶段六：连通性（脚本）
| 检查项 | 结果 |
|--------|------|
| AWS 凭证 | ✅/❌ |
| Xboard PostgreSQL | ✅/❌ |
| Xboard 节点查询 | ✅/❌ |
| Cloudflare API | ✅/❌ |
| Telegram | ✅/❌ |

## 阶段七：HTTP 链路（脚本）
| 检查项 | 结果 |
|--------|------|
| Probe 注册 | ✅/❌ |
| Probe 心跳 | ✅/❌ |
| Probe 轮询 | ✅/❌ |

## 阶段八：稳定性
| 检查项 | 结果 |
|--------|------|
| Daemon ERROR | ✅/❌ (count=0) |
| 并发压测 | ✅/❌ (30/30 成功) |

## 发现问题
1. [描述]
EOF
echo "报告已保存"
```

---

## 快速验收清单

> 一键执行（约 5 分钟，包含阶段一+六+七+八）：

```bash
bash << 'SCRIPT'
cd ~/ShadowFleet
source venv/bin/activate
source ~/.shadowfleet_env

echo "=== ShadowFleet 快速验收 ==="

echo "[1/6] Systemd 服务..."
sudo systemctl is-active shadowfleet-daemon shadowfleet-ui | xargs echo "状态:"

echo "[2/6] AWS 凭证..."
python3 -c "import boto3; i=boto3.client('sts').get_caller_identity(); print('OK -', i['Account'])" 2>&1

echo "[3/6] Xboard PostgreSQL..."
python3 -c "import psycopg2,os; from dotenv import load_dotenv; load_dotenv(os.path.expanduser('~/.shadowfleet_env')); c=psycopg2.connect(host=os.getenv('XB_DB_HOST','127.0.0.1'),port=5432,database='xboard',user='tanxuan',password=os.getenv('XB_DB_PASSWORD','')); cur=c.cursor(); cur.execute('SELECT COUNT(*) FROM public.v2_server WHERE name LIKE \"sf-%%\"'); print('SF节点:', cur.fetchone()[0]); c.close()" 2>&1

echo "[4/6] Cloudflare API..."
curl -s "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/dns_records?per_page=3" -H "Authorization: Bearer $CF_API_TOKEN" | python3 -c "import sys,json; d=json.load(sys.stdin); print('CF:', 'OK' if d.get('success') else 'FAIL')" 2>&1

echo "[5/6] Telegram..."
curl -s -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" -d "chat_id=$TG_CHAT_ID" -d "text=✅ 在线 $(date '+%H:%M:%S')" | python3 -c "import sys,json; d=json.load(sys.stdin); print('TG:', 'OK' if d.get('ok') else 'FAIL')" 2>&1

echo "[6/6] Daemon ERROR..."
sudo journalctl -u shadowfleet-daemon --since "1 hour ago" -p err --no-pager | grep -v "^-- No entries" | wc -l | xargs echo "ERROR count:"

echo "=== 验收完成 ==="
SCRIPT
```
