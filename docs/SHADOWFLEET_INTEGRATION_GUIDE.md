# Xboard ShadowFleet Sentinel 对接文档

> 本文档描述 Xboard 向 ShadowFleet Sentinel 提供的 HTTP API 接口契约。

## 1. 概述

Xboard 通过一组只读 HTTP 接口向 ShadowFleet Sentinel 提供节点流量监控和运行态数据。Sentinel 通过这些接口判断节点是否失活，并发起主动探测。

**设计约束**：
- Sentinel 不直接查询 Xboard 数据库表
- Sentinel 不关心 Xboard 内部是落表、缓存还是聚合计算
- Xboard 仅需对外提供稳定的 HTTP 接口契约

---

## 2. 鉴权

所有 ShadowFleet 接口统一使用 **Bearer Token** 鉴权。

**Header 示例**：

```
Authorization: Bearer <xboard_sentinel_api_key>
Accept: application/json
```

**配置方式**（二选一）：

| 方式 | 配置项 | 说明 |
|------|--------|------|
| 环境变量 | `XBOARD_SENTINEL_API_KEY` | 适用于 Docker / 纯环境变量部署 |
| 后台设置 | `admin_setting('xboard_sentinel_api_key', ...)` | 适用于后台可视化配置 |

**鉴权失败响应**：

| 场景 | HTTP 状态码 | 响应体 |
|------|-------------|--------|
| 未提供 Token | 401 | `{"message": "missing bearer token"}` |
| Token 未配置 | 503 | `{"message": "shadowfleet api key not configured"}` |
| Token 无效 | 403 | `{"message": "invalid bearer token"}` |

---

## 3. 接口列表

### 3.1 读取节点分钟流量

**请求**：

```
GET /api/v1/shadowfleet/server-minute-stats
```

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `server_id` | integer | ✅ | Xboard 节点 ID |
| `server_type` | string | ✅ | 节点类型，如 `AnyTLS`、`Trojan`、`vmess`、`Shadowsocks` 等 |
| `lookback_minutes` | integer | ✅ | 回看分钟数，建议 `3` ~ `60`，最大 `60` |

**请求示例**：

```
GET /api/v1/shadowfleet/server-minute-stats?server_id=123&server_type=Trojan&lookback_minutes=10
Authorization: Bearer your_api_key_here
```

**成功响应（200）**：

```json
{
  "server_id": 123,
  "server_type": "Trojan",
  "samples": [
    {
      "sample_minute": 1742947200,
      "uplink_bytes": 1024,
      "downlink_bytes": 2048,
      "total_bytes": 3072,
      "active_user_count": 2
    },
    {
      "sample_minute": 1742947260,
      "uplink_bytes": 0,
      "downlink_bytes": 0,
      "total_bytes": 0,
      "active_user_count": 0
    }
  ]
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `server_id` | integer | 节点 ID |
| `server_type` | string | 节点类型（规范化后） |
| `samples` | array | 分钟样本数组 |
| `samples[].sample_minute` | integer | UTC Unix 秒时间戳，按整分钟对齐 |
| `samples[].uplink_bytes` | integer | 上行流量（字节） |
| `samples[].downlink_bytes` | integer | 下行流量（字节） |
| `samples[].total_bytes` | integer | 总流量 = uplink + downlink |
| `samples[].active_user_count` | integer | 该分钟活跃用户数 |

**返回约束**：
- `samples` 按 `sample_minute` **升序**返回
- 若某分钟无数据，该分钟返回全零样本（而非空）
- 最大支持回看 60 分钟

**错误响应**：

| 场景 | HTTP 状态码 | 响应体 |
|------|-------------|--------|
| 参数缺失/格式错误 | 422 | `{"message": "<field> is required" 或 "invalid server_type"}` |
| 节点不存在 | 404 | `{"message": "server not found"}` |

---

### 3.2 读取节点运行态

**请求**：

```
GET /api/v1/shadowfleet/server-runtime
```

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `server_id` | integer | ✅ | Xboard 节点 ID |
| `server_type` | string | ❌ | 节点类型（可不传） |

**请求示例**：

```
GET /api/v1/shadowfleet/server-runtime?server_id=123&server_type=Trojan
Authorization: Bearer your_api_key_here
```

**成功响应（200）**：

```json
{
  "id": 123,
  "type": "Trojan",
  "host": "jp-1.example.com",
  "port": "443",
  "server_port": 443,
  "show": true
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | integer | 节点 ID |
| `type` | string | 节点类型 |
| `host` | string | 节点域名或 IP |
| `port` | string | 连接端口 |
| `server_port` | integer | 服务器监听端口 |
| `show` | boolean | 是否在面板显示 |

**错误响应**：

| 场景 | HTTP 状态码 | 响应体 |
|------|-------------|--------|
| 参数缺失/格式错误 | 422 | `{"message": "<field> is required" 或 "invalid server_type"}` |
| 节点不存在 | 404 | `{"message": "server not found"}` |

---

## 4. 错误语义汇总

| HTTP 状态码 | 含义 | 典型响应 |
|-------------|------|----------|
| 200 | 成功 | - |
| 401 | 未提供 Token | `{"message": "missing bearer token"}` |
| 403 | Token 无效 | `{"message": "invalid bearer token"}` |
| 404 | 节点不存在 | `{"message": "server not found"}` |
| 422 | 参数不合法 | `{"message": "<field> is required" 或 "invalid server_type"}` |
| 429 | 限流 | - |
| 500/502/503/504 | 服务端错误 | - |
| 503 | Token 未配置 | `{"message": "shadowfleet api key not configured"}` |

---

## 5. Sentinel 使用流程

ShadowFleet Sentinel 按以下顺序使用接口：

```
1. GET /api/v1/shadowfleet/server-minute-stats
   └─ 判断：历史有流量（存在 total_bytes > 0）且最近 N 分钟 uplink = 0

2. 若满足条件，再调用 GET /api/v1/shadowfleet/server-runtime
   └─ 获取节点 host/port/type 用于构造探测目标

3. 基于运行态发起主动探测（DNS/TCP/TLS/HTTP）

4. 记录探测结果（可选）
```

---

## 6. 完整对接示例

### cURL 示例

**获取分钟流量**：

```bash
curl -X GET "https://xboard.example.com/api/v1/shadowfleet/server-minute-stats?server_id=123&server_type=Trojan&lookback_minutes=5" \
  -H "Authorization: Bearer your_api_key_here" \
  -H "Accept: application/json"
```

**获取节点运行态**：

```bash
curl -X GET "https://xboard.example.com/api/v1/shadowfleet/server-runtime?server_id=123" \
  -H "Authorization: Bearer your_api_key_here" \
  -H "Accept: application/json"
```

### Python 示例

```python
import requests

BASE_URL = "https://xboard.example.com/api/v1/shadowfleet"
API_KEY = "your_api_key_here"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json",
}


def get_server_minute_stats(server_id: int, server_type: str, lookback_minutes: int = 5):
    """获取节点分钟流量"""
    url = f"{BASE_URL}/server-minute-stats"
    params = {
        "server_id": server_id,
        "server_type": server_type,
        "lookback_minutes": lookback_minutes,
    }
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()


def get_server_runtime(server_id: int, server_type: str = None):
    """获取节点运行态"""
    url = f"{BASE_URL}/server-runtime"
    params = {"server_id": server_id}
    if server_type:
        params["server_type"] = server_type
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()


# 示例用法
stats = get_server_minute_stats(server_id=123, server_type="Trojan", lookback_minutes=5)
runtime = get_server_runtime(server_id=123, server_type="Trojan")

# 判断是否为可疑节点（历史有流量，最近3分钟无上行）
samples = stats["samples"]
recent_3_minutes = samples[-3:]
has_historical_traffic = any(s["total_bytes"] > 0 for s in samples[:-3])
recent_no_uplink = all(s["uplink_bytes"] == 0 for s in recent_3_minutes)

if has_historical_traffic and recent_no_uplink:
    print(f"可疑节点: {runtime['host']}:{runtime['port']}")
```

---

## 7. 注意事项

1. **时钟同步**：Xboard 服务器需保持 NTP 同步，确保 `sample_minute` 时间戳准确
2. **缓存有效期**：分钟统计数据缓存在内存中，默认 TTL 为 3 小时
3. **类型大小写**：`server_type` 建议使用规范化类型名（首字母大写），如 `Trojan`、`Vmess`
4. **限流建议**：建议 Sentinel 每次查询间隔不低于 10 秒，避免触发限流

---

## 8. 版本信息

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0 | 2026-03-25 | 初版，基于当前实现生成 |
