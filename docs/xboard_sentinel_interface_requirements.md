# Xboard Sentinel 接口需求文档

## 1. 目标

本文档定义 `ShadowFleet Sentinel` 对 Xboard 的最小 HTTP 接口依赖。

约束如下：

- `ShadowFleet Sentinel` 不直接查询 Xboard 数据库表
- `ShadowFleet Sentinel` 不关心 Xboard 内部是落表、缓存还是聚合计算
- Xboard 只需要对外提供稳定的 HTTP 接口契约

Sentinel 的核心用途：

- 每 `3-5` 分钟发现流量异常节点
- 根据最近 `3` 分钟上行流量归零判定可疑节点
- 对可疑节点执行主动探测

## 2. 鉴权约定

ShadowFleet 调用 Xboard Sentinel 接口时，统一使用：

- Header: `Authorization: Bearer <xboard_sentinel_api_key>`
- Header: `Accept: application/json`

基础地址示例：

- `https://xboard.example.com`

## 3. 必需接口

### 3.1 读取节点分钟流量

`GET /api/v1/shadowfleet/server-minute-stats`

查询参数：

- `server_id`：Xboard 节点 ID
- `server_type`：节点类型，如 `AnyTLS` / `Trojan` / `vmess`
- `lookback_minutes`：回看分钟数

响应示例：

```json
{
  "server_id": 123,
  "server_type": "Trojan",
  "samples": [
    {
      "sample_minute": 1741435200,
      "uplink_bytes": 0,
      "downlink_bytes": 0,
      "total_bytes": 0,
      "active_user_count": 0
    }
  ]
}
```

字段要求：

- `samples` 必须按 `sample_minute` 升序返回
- `sample_minute` 使用 UTC Unix 秒时间戳，按整分钟对齐
- 需要能支持 `lookback_minutes=60` 这一类常规查询

Sentinel 依赖该接口完成以下判断：

- 过去一段时间内至少出现过真实流量，即存在若干分钟 `total_bytes > 0`
- 最近 `3` 分钟窗口内，`uplink_bytes = 0`

建议：

- 最好每分钟都返回一条样本，即使流量为 `0`
- 若做不到连续采样，至少要保证 ShadowFleet 可以区分“无样本”和“零流量”

### 3.2 读取节点运行态

`GET /api/v1/shadowfleet/server-runtime`

查询参数：

- `server_id`

响应示例：

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

字段要求：

- `id`
- `type`
- `host`
- `port`
- `server_port`
- `show`

Sentinel 使用这些字段来：

- 构造主动探测目标
- 判断节点当前是否仍为可服务对象

## 4. 错误语义

建议 Xboard 接口返回以下语义：

- `401/403`：鉴权失败
- `404`：目标节点不存在
- `422`：参数不合法
- `429`：限流
- `500/502/503/504`：服务端暂时不可用

错误响应建议：

```json
{
  "message": "server not found"
}
```

## 5. ShadowFleet 对接逻辑

ShadowFleet Sentinel 将按如下顺序使用这些接口：

1. 调用 `GET /api/v1/shadowfleet/server-minute-stats`
2. 判断是否满足“历史活跃 + 最近 3 分钟上行归零”
3. 若满足，再调用 `GET /api/v1/shadowfleet/server-runtime`
4. 基于运行态发起 DNS/TCP/TLS/HTTP 主动探测
5. 当最终状态为 `confirmed_blocked_by_gfw` 时，交给 ShadowFleet 内部 Healer 继续处理

## 6. 最小结论

对当前 Sentinel 落地而言，Xboard 必须提供：

1. `GET /api/v1/shadowfleet/server-minute-stats`
2. `GET /api/v1/shadowfleet/server-runtime`

只要上述两个只读接口稳定可用，ShadowFleet Sentinel 就可以脱离对 Xboard 表结构的直接依赖。
