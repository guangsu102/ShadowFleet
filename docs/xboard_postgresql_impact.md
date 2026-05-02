# Xboard PostgreSQL 数据库影响分析

> 本文档记录 ShadowFleet 系统直接通过 `psycopg2` 访问 Xboard PostgreSQL 数据库时，所影响的所有数据表、SQL 语句及调用链。

---

## 1. 概述

ShadowFleet 通过**两种路径**获取 Xboard 数据，绝不能混为一谈：

| 数据获取路径 | 模块 | Xboard 端实现 | 状态 |
|-------------|------|--------------|------|
| **HTTP REST API**（主要路径） | `services/xboard_sentinel_client.py` | Xboard 面板提供 `/api/v1/shadowfleet/*` 接口 | ✅ 监控流程实际使用 |
| **psycopg2 直查 PG**（次要路径） | `database/xboard_repo.py` | 直接 SQL 查询 PG 表 | ⚠️ 仅自愈流程使用；`list_server_minute_stats` 为**死代码** |

### 核心结论

- **`v2_stat_server_minute` 表**：ShadowFleet **从未通过 psycopg2 调用过**。监控流程走的是 `XboardSentinelClient`（HTTP API），不是 `XboardRepo.list_server_minute_stats`。
- **`XboardRepo.list_server_minute_stats`**：虽然代码存在，但**从未被任何模块导入或调用**，属于死代码。
- **psycopg2 实际只影响 1 个表**：`public.v2_server`（自愈流程）。

---

## 2. psycopg2 直查路径（XboardRepo）

ShadowFleet 中使用 `psycopg2` 直接连接 Xboard PostgreSQL 的**唯一入口**是 `database/xboard_repo.py`。

---

### 表 A: `public.v2_server`

Xboard 节点主表，自愈流程直接 SQL 操作。ShadowFleet 通过 **`sf-` 前缀**与 Xboard 手动创建的节点实现隔离。

#### 隔离机制

| 机制 | 说明 |
|------|------|
| `sf-` 前缀 | ShadowFleet 创建的节点 `name` 统一以 `sf-` 开头，由 `XboardRepo._enforce_sf_name()` 自动补全（无则加有则保），最大长度 64 字符 |
| 安全过滤 | 所有 UPDATE / DELETE / SELECT 必须匹配 `WHERE name LIKE 'sf-%'`，防止误操作 Xboard 节点 |

#### A.1 INSERT — 注册节点

**触发时机**: 节点首次从 AWS 启动完成。

**隔离**: `name` 字段由 `_enforce_sf_name()` 自动加 `sf-` 前缀（已存在则不加，最大截断至 64 字符）。

```sql
INSERT INTO public.v2_server (
    type, code, parent_id, group_ids, route_ids, name, rate, tags,
    host, port, server_port, protocol_settings, show, sort, created_at,
    updated_at, rate_time_enable, rate_time_ranges
)
VALUES (... -- name 已自动加 sf- 前缀
)
RETURNING id
```

**调用链**:
```
services/provisioning_aws_flow.py
  └─ XboardRepo.register_node()
       └─ INSERT public.v2_server
```

#### A.2 DELETE — 删除节点

**触发时机**: 节点下线/退役。

```sql
DELETE FROM public.v2_server WHERE id = %s AND name LIKE 'sf-%'
```

**调用链**:
```
services/healing_aws_flow.py
  └─ XboardRepo.delete_node()
       └─ DELETE public.v2_server
```

#### A.3 UPDATE — 更新节点 Host

**触发时机**: 节点 IP 变更后同步回 Xboard。

```sql
UPDATE public.v2_server
SET host = %s, updated_at = %s
WHERE id = %s AND name LIKE 'sf-%'
```

**调用链**:
```
services/healing_aws_flow.py
  └─ XboardRepo.update_node_host()
       └─ UPDATE public.v2_server
```

#### A.4 SELECT — 查询节点运行时信息（自愈流程）

**触发时机**: 自愈流程获取节点当前配置。

```sql
SELECT
    id, type, host, port, server_port, show
FROM public.v2_server
WHERE id = %s AND name LIKE 'sf-%'
```

**调用链**:
```
services/healing_support.py
  └─ XboardRepo.get_node_runtime()
       └─ SELECT public.v2_server
```

#### A.5 UPDATE — 更新节点可见性（show 字段）

**触发时机**: 节点上线/下线时更新显示状态。

```sql
UPDATE public.v2_server
SET show = %s, updated_at = %s
WHERE id = %s AND name LIKE 'sf-%'
```

**调用链**:
```
services/provisioning_aws_flow.py
  └─ XboardRepo.mark_node_online()    ← UPDATE show=true

services/healing_aws_flow.py
  └─ XboardRepo.mark_node_offline()   ← UPDATE show=false
```

---

### 表 B: `public.v2_stat_server_minute`

> ⚠️ **死代码 — 绝不被任何模块调用**

```sql
-- xboard_repo.py 第 281-344 行存在此方法，但从未被导入或调用
def list_server_minute_stats(self, ...):
    SELECT ... FROM public.v2_stat_server_minute ...
```

- **代码位置**: `database/xboard_repo.py:281`
- **被谁调用**: **无**。`monitor.py` 中监控流程走的是 `XboardSentinelClient`（HTTP），而不是 `XboardRepo`
- **结论**: 此方法可删除，或保留作为 Xboard 侧尚未提供 HTTP API 时的降级备选

---

## 3. HTTP API 路径（XboardSentinelClient）

ShadowFleet 监控流程**实际使用**的路径，通过 HTTP 调用 Xboard 面板接口，不涉及 psycopg2。

| 接口 | 方法 | Xboard 端表/逻辑 | 状态 |
|------|------|-----------------|------|
| `/api/v1/shadowfleet/server-minute-stats` | GET | 由 Xboard 面板聚合计算 | ✅ 监控流程使用 |
| `/api/v1/shadowfleet/server-runtime` | GET | 由 Xboard 面板查询 | ✅ 监控流程使用 |

**调用链（监控流程）**:
```
services/monitor.py
  └─ XboardSentinelClient (services/xboard_sentinel_client.py)
       └─ HTTP GET /api/v1/shadowfleet/server-minute-stats
       └─ HTTP GET /api/v1/shadowfleet/server-runtime
```

---

## 4. 完整调用链总图

```
ShadowFleet Daemon
│
├── Provisioning Flow（每 3 分钟轮询）
│   └─ services/provisioning_aws_flow.py
│       ├─ XboardRepo.register_node()    ← psycopg2 / INSERT v2_server
│       └─ XboardRepo.mark_node_online() ← psycopg2 / UPDATE v2_server (show=true)
│
├── Healing Flow（节点失活时触发）
│   └─ services/healing_aws_flow.py
│       ├─ XboardRepo.mark_node_offline() ← psycopg2 / UPDATE v2_server (show=false)
│       ├─ XboardRepo.update_node_host()  ← psycopg2 / UPDATE v2_server
│       └─ XboardRepo.delete_node()       ← psycopg2 / DELETE v2_server
│
├── Monitoring Flow（每 3 分钟轮询）—— 不走 psycopg2
│   └─ services/monitor.py
│       └─ XboardSentinelClient (HTTP API)
│            ├─ GET /api/v1/shadowfleet/server-minute-stats  ← 获取分钟流量
│            └─ GET /api/v1/shadowfleet/server-runtime       ← 获取节点运行态
│
└── ⚠️ Dead Code
     └─ XboardRepo.list_server_minute_stats() ← SELECT v2_stat_server_minute
          （从未被调用，可删除）
```

---

## 5. Xboard 数据库连接配置

| 配置项 | 来源 | 说明 |
|--------|------|------|
| Host | `config.yaml` → `xboard.host` | Xboard PostgreSQL 地址 |
| Port | `config.yaml` → `xboard.port` | 默认 `5432` |
| Database | `config.yaml` → `xboard.database` | Xboard 数据库名 |
| User | `config.yaml` → `xboard.user` | 连接用户名 |
| Password | `config.yaml` → `xboard.password` | 连接密码 |
| SSL Mode | `config.yaml` → `xboard.ssl_mode` | 建议 `require` 或 `verify-full` |

---

## 6. 安全注意事项

| 风险点 | 建议 |
|--------|------|
| Xboard 数据库密码明文存储在 `config.yaml` | 使用环境变量 `SHADOWFLEET_XBOARD_PASSWORD` 替代 |
| ShadowFleet 使用单一 PG 账号 | 建议自愈流程只授予 `SELECT/INSERT/UPDATE/DELETE` 权限，`list_server_minute_stats` 逻辑若不用可直接删除 |
| `public.v2_server` 被频繁 UPDATE | 确保 Xboard 侧无冲突触发器 |

---

## 7. 变更历史

| 版本 | 日期 | 修改内容 |
|------|------|----------|
| 1.0 | 2026-03-25 | 初版 |
| 1.1 | 2026-03-25 | 纠正错误：监控流程不走 psycopg2，`v2_stat_server_minute` 为死代码 |
| 1.2 | 2026-03-25 | 新增 sf- 隔离机制：INSERT 自动加前缀，UPDATE/DELETE/SELECT 加 `name LIKE 'sf-%'` 安全过滤 |

---

## 附录：涉及的文件清单

| 文件路径 | 描述 |
|----------|------|
| `database/connection.py` | psycopg2 连接池管理 |
| `database/xboard_repo.py` | Xboard PG SQL 操作（含一条死代码） |
| `services/xboard_sentinel_client.py` | Xboard HTTP API 客户端（监控流程实际使用） |
| `services/provisioning_aws_flow.py` | 节点注册上线流程 |
| `services/healing_aws_flow.py` | 节点自愈流程 |
| `services/healing_support.py` | 自愈辅助逻辑 |
| `services/monitor.py` | Sentinel 监控流程（HTTP 路径） |
| `config.yaml` / `config.dev.yaml` | 数据库连接配置 |
