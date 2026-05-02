# 国内探针接入说明

## 1. 文档目标

本文档说明如何把一台中国大陆机器接入 ShadowFleet 的国内探针体系，使其能够完成以下动作：

- 向中控注册成为探针节点
- 定时发送心跳
- 拉取中控下发的探测命令
- 执行 DNS/TCP/TLS/HTTP 探测
- 回传测量结果，参与 Sentinel 最终阻断判定

本文档对应当前代码中的最小可运行版 `probe_agent`，重点覆盖接入步骤、配置项、启动方式、验收方法与边界说明。

## 2. 接入前提

接入前需要满足以下条件：

- 中控机器已部署 ShadowFleet 主程序代码
- 中控机器可以启动 `daemon.py`
- 国内探针机器可以通过 HTTP/HTTPS 访问中控的 `daemon` 监听地址
- 国内探针机器具备 Python 3.10+
- 国内探针机器已部署 ShadowFleet 代码，或至少具备 `probe_agent/` 目录及其依赖

推荐在探针机也拉取完整仓库，并在虚拟环境中安装依赖：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

如果只运行最小版探针 Agent，当前最少依赖是 `requests`。

## 3. 中控侧准备

### 3.1 开启探针控制面

编辑中控的 `config.yaml`，至少确认以下配置：

```yaml
app:
  sentinel_enabled: true
  sentinel_probe_mode: "cn_probe_mesh"
  probe_server_enabled: true
  probe_bootstrap_tokens:
    - "replace-with-a-strong-bootstrap-token"
  probe_poll_interval_seconds: 5.0
  probe_heartbeat_timeout_seconds: 60.0
  sentinel_probe_timeout_seconds: 10
  sentinel_probe_result_wait_timeout_seconds: 30.0
  sentinel_probe_min_cn_probe_count: 2
  sentinel_probe_required_success_ratio: 0.5
  sentinel_probe_confirm_cycles: 2
  sentinel_probe_allow_auto_heal_hy2: false
```

关键说明：

- `probe_server_enabled`: 是否启用 `/probe/*` 控制面接口
- `probe_bootstrap_tokens`: 探针首次注册使用的引导令牌，可以配置多个
- `sentinel_probe_mode`: 设为 `cn_probe_mesh` 后，Sentinel 会使用国内探针编排链路
- `sentinel_probe_min_cn_probe_count`: 一次测量至少要求的国内探针数量，当前建议不小于 `2`
- `sentinel_probe_confirm_cycles`: 连续多少个扫描周期确诊后才允许自动自愈
- `sentinel_probe_allow_auto_heal_hy2`: 当前建议保持 `false`

为了避免把引导令牌写入配置文件，也可以通过环境变量覆盖：

```bash
export SHADOWFLEET_PROBE_BOOTSTRAP_TOKENS="token-a,token-b"
```

### 3.2 启动中控守护进程

在项目根目录启动：

```bash
python daemon.py
```

当前探针控制面与现有 ready callback 共用同一个 HTTP 服务，默认监听：

- Host: `app.phone_home_listen_host`
- Port: `app.phone_home_listen_port`

默认配置下即：

- `0.0.0.0:8787`

探针相关接口为：

- `POST /probe/register`
- `POST /probe/heartbeat`
- `POST /probe/poll`
- `POST /probe/result`
- `GET /probe/config`

### 3.3 网络与安全要求

建议至少做到以下几点：

- 仅允许可信国内探针来源访问中控探针接口
- 不要把 `probe_bootstrap_tokens` 提交到 Git
- 中控应部署在稳定的公网地址或反向代理后
- 如果走反向代理，确保 `/probe/*` 路径能原样转发到 `daemon`

## 4. 探针机准备

### 4.1 必要环境变量

当前版本 `probe_agent` 通过环境变量加载配置。启动前至少设置以下变量：

```bash
export SHADOWFLEET_PROBE_CONTROL_PLANE_URL="http://your-control-plane-host:8787"
export SHADOWFLEET_PROBE_BOOTSTRAP_TOKEN="replace-with-a-strong-bootstrap-token"
export SHADOWFLEET_PROBE_NAME="cn-probe-shanghai-01"
export SHADOWFLEET_PROBE_MACHINE_FINGERPRINT="cn-probe-shanghai-01"
```

可选变量：

```bash
export SHADOWFLEET_PROBE_REGION="cn-shanghai"
export SHADOWFLEET_PROBE_ISP="china-telecom"
export SHADOWFLEET_PROBE_TAGS="cn,shanghai,telecom"
export SHADOWFLEET_PROBE_POLL_INTERVAL_SECONDS="5"
export SHADOWFLEET_PROBE_HEARTBEAT_INTERVAL_SECONDS="15"
export SHADOWFLEET_PROBE_TIMEOUT_SECONDS="10"
```

字段说明：

- `SHADOWFLEET_PROBE_CONTROL_PLANE_URL`: 中控地址，不能带尾部斜杠也可以，程序会自动处理
- `SHADOWFLEET_PROBE_BOOTSTRAP_TOKEN`: 注册用引导令牌，必须与中控配置一致
- `SHADOWFLEET_PROBE_NAME`: 探针展示名称，建议体现地区和运营商
- `SHADOWFLEET_PROBE_MACHINE_FINGERPRINT`: 探针唯一标识，必须稳定且唯一
- `SHADOWFLEET_PROBE_REGION`: 地区标签，用于调度和展示
- `SHADOWFLEET_PROBE_ISP`: 运营商标签
- `SHADOWFLEET_PROBE_TAGS`: 自定义标签，逗号分隔

### 4.2 关于 `machine_fingerprint`

`machine_fingerprint` 很关键：

- 同一台探针机器重启后，应该继续使用同一个值
- 如果变更这个值，中控会把它识别为一台新探针
- 当前实现会在注册时按 `machine_fingerprint` 识别是否复用已有探针记录

建议做法：

- 直接使用固定资产编号
- 或使用机器唯一 ID
- 不建议每次启动动态生成随机值

## 5. 启动探针 Agent

在仓库根目录执行：

```bash
python -m probe_agent.agent
```

启动后 Agent 的工作循环为：

1. 使用 bootstrap token 调用 `/probe/register`
2. 获取 `probe_id`、`auth_token`、`config_version`
3. 定时调用 `/probe/heartbeat`
4. 定时调用 `/probe/poll`
5. 收到命令后执行本地探测
6. 调用 `/probe/result` 回传结果
7. 当 `config_version` 变化时调用 `/probe/config`

## 6. 首次接入后的验收方法

### 6.1 日志验收

探针启动后，预期可以在 Agent 日志中看到类似信息：

- 注册成功
- 心跳成功
- 配置版本号
- 命令执行成功或失败

如果注册成功，通常会出现：

- `Probe registered probe_id=...`
- `Heartbeat acknowledged probe_id=...`

### 6.2 UI 验收

在驾驶舱里重点查看两个位置：

- `Dashboard` 页面中的“国内探针状态”“最近国内探针测量”
- `Ops` 页面中的“最近国内探针命令”“最近国内探针测量概览”

验收标准：

- 能看到新探针记录
- 探针状态为 `active`
- `last_seen_at` 持续刷新
- 当 Sentinel 触发测量时，能看到命令与 measurement 记录

### 6.3 数据层验收

如果需要进一步确认，可以检查 SQLite 中以下表是否有数据：

- `fleet_probes`
- `fleet_probe_configs`
- `fleet_probe_heartbeats`
- `fleet_probe_commands`
- `fleet_probe_measurements`
- `fleet_probe_measurement_results`

## 7. 当前探针能力边界

当前最小版探针 Agent 已支持：

- DNS 解析探测
- TCP 连接探测
- TLS 握手探测
- HTTP HEAD 探测

当前限制如下：

- 不支持 UDP 探测
- `Hysteria2` 默认只返回 `probe_inconclusive`，不自动确诊
- Agent 虽然会在 `config_version` 变化时拉取 `/probe/config`，但当前运行时参数仍以本地环境变量为主，服务端配置热更新尚未完全落地
- 当前 Agent 默认未主动探测公网出口 IP，因此 UI 里的 `public_ip` 可能为空

## 8. 推荐接入策略

为了提高判定质量，建议最少部署 2 台国内探针，最好满足：

- 至少 2 个不同地区
- 至少 2 个不同运营商
- 每台探针网络尽量稳定，不与业务代理服务复用同一台机器

建议标签示例：

- `cn,beijing,unicom`
- `cn,shanghai,telecom`
- `cn,guangzhou,mobile`

## 9. 常见问题

### 9.1 注册失败

优先检查：

- 中控是否已设置 `probe_server_enabled: true`
- `SHADOWFLEET_PROBE_BOOTSTRAP_TOKEN` 是否与中控一致
- 探针机是否能访问中控 `host:port`

### 9.2 心跳一直失败

优先检查：

- 中控 `daemon.py` 是否持续运行
- 反向代理或防火墙是否拦截 `/probe/heartbeat`
- 探针机与中控之间是否存在超时或 DNS 问题

### 9.3 UI 中探针变成 `offline`

触发原因通常是：

- Agent 已退出
- 心跳超时超过 `probe_heartbeat_timeout_seconds`
- 中控无法持续收到 `/probe/heartbeat`

### 9.4 看到了探针但没有 measurement

优先检查：

- `sentinel_enabled` 是否开启
- `sentinel_probe_mode` 是否为 `cn_probe_mesh`
- 当前是否真的出现了可疑节点候选
- 活跃探针数量是否达到 `sentinel_probe_min_cn_probe_count`

## 10. 建议的最小上线清单

- 中控开启 `probe_server_enabled`
- 中控配置至少一个安全的 bootstrap token
- 中控开启 `sentinel_enabled`
- 中控设置 `sentinel_probe_mode: cn_probe_mesh`
- 至少接入 2 台国内探针
- Dashboard/Ops 页面可以看到探针在线状态
- 能看到一次完整的命令下发与测量结果回传
- 保持 `sentinel_probe_allow_auto_heal_hy2: false`

## 11. 后续增强方向

后续建议继续补齐：

- UDP 探测与 `Hysteria2` 专项支持
- Agent 守护化部署样例，例如 `systemd`
- 服务端配置动态下发后在 Agent 侧热生效
- 探针排空、恢复、灰度调度能力
