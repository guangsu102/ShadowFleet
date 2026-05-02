# 1. 项目概述 (Project Overview)
ShadowFleet 是一个专为高频封锁环境设计、基于纯 IPv6 架构的全自动高可用代理节点中控系统。系统通过统筹管理多个 AWS 消耗型账号（月抛号）和自建节点部署，结合 PostgreSQL 驱动的 Xboard 面板，实现节点实例的自动开通、V2bX 配置动态注入、无头封锁检测与 10 秒级换 IP 自愈。系统提供基于 Streamlit 的 Web 驾驶舱，供管理员进行全局资源的俯视与接管。

# 2. 核心业务目标 (Core Objectives)
- AWS 月抛号（纯 IPv6 突击队）：利用 AWS 庞大且免费的 IPv6 地址池。机器本身不死，一旦 GFW 封锁了当前的 IPv6，中控直接调用 API 秒换 V6 IP 并更新 AAAA 记录。这种打法成本极低，且 IPv6 几乎是无限弹药。
- 静默弃尸逻辑 (Graceful Abandonment)：当确诊 AWS 账号被官方风控封禁（API 返回鉴权或状态错误）时，系统放弃一切抢救和销毁尝试，直接将账号标记为 Banned，在 Xboard 数据库中作废该账号下的所有节点，并自动从健康账号池中划拨资源重建防线。
- 零人工干预 (Zero Touch Ops)：从填入 AWS 凭证到节点在面板上线、再到节点被墙后的动态换 IP，全程无需 SSH 登录服务器手动操作。
- 高隐蔽性 (High Stealth)：中控系统必须 100% 部署在海外。国内探针仅承担网络测量职责，不持有 AWS、Cloudflare、Xboard 等敏感凭证，不参与资源调度与修复执行，从而将国内侧暴露面压缩到最小。
- 自有机器（高价值重装舰队）：
  1. 彻底摒弃传统的“手动 SSH 登录 + 复制粘贴脚本”的落后运维方式。管理员只需在 Web 驾驶舱内录入目标服务器的 IP、SSH 端口以及账号密码，中控底层的 SSH 自动化配置引擎 (Provisioner) 便会主动出击。它将在后台全自动完成登录提权、依赖环境清洗、V2bX 核心拉取以及动态面板鉴权信息的无缝注入。只需几分钟，一台原始裸机即可自动并入战斗序列。
  2. 这些通常是线路优秀的固定资产（如 CN2、软银等），IP 被墙换起来很贵或很麻烦。所以平时直连跑高性能，一旦探测到被墙，中控立刻调用 Cloudflare API 开启小黄云（绑定 CDN），牺牲部分延迟换取绝对的“永不失联”。

# 3. 功能性需求 (Functional Requirements)

## 3.1 资产与账号库模块 (Asset Management)
- 需求 1：系统需管理多个 AWS 账号（Access Key / Secret Key / Region）。
- 需求 2：系统需实时监控每个 AWS 账号的配额，严格限制单个账号下运行的实例不超过配额，同时需要增加风控规则减少账号被封。
- 需求 3：提供 UI 界面支持批量录入新账号，并实时展示账号的健康状态（Active / Banned / Full）。
- 需求 4：系统需支持自有固定资产（自建机器）的零触碰纳管与全自动装机。
  - 输入标准：提供 UI 界面供管理员录入自建机器的静态凭证（IP、SSH 端口、Root 账号、密码 / 密钥）。
  - 自动化装机 (SSH Provisioner)：录入后，系统底层的 SSH 运维引擎需自动建立连接，静默执行环境清洗、V2bX 核心拉取、配置文件生成及 Systemd 服务注册，实现“输入即上线”。
  - 资产类型隔离：资产库（数据库）必须在底层对“AWS 弹性资产”与“自建固定资产”进行严格的类型标记（Type Isolation）。自建机器不走实例销毁逻辑，而是绑定专用的生命周期状态（例如：Deploying 装机中 / Direct 直连满载中 / CDN_Proxied 小黄云避险中 / Offline 离线）。

## 3.2 节点编排与面板对接模块 (Node Provisioning)
- 需求 1：支持混合部署五种协议梯队：AnyTLS、Trojan、vless、vmess、Hysteria2（注：根据风控规则，Hysteria2 仅限自建固定节点使用）。
- 需求 2：纯 IPv6 网络初始化：系统调用 Boto3 开机时，安全组必须配置为放行 ::/0 (IPv6 全网段) 的 80/443 端口，禁止分配 Public IPv4。
- 需求 3：数据库强一致性对接：系统必须通过 psycopg2 直接操作 Xboard 的 PostgreSQL 数据库，实现节点的自动注册，并获取 NodeID。
- 需求 4：无人值守注入：利用 AWS User-Data，在开机时动态注入包含 Xboard NodeID 的 Bash 脚本，自动安装 V2bX 并启动对接。
- 需求 5：DNS 自动化：对于 AnyTLS、Trojan、vless、vmess 节点，系统需自动调用 Cloudflare API 分配子域名，并强制添加 AAAA/A 记录指向机器的新 IP。

## 3.3 无头监控与极速自愈模块 (Sentinel & Healer)
- 需求 1 (被动嗅探)：后台守护进程每 3-5 分钟轮询 Xboard PG 数据库，筛选出“过去有真实流量，但最近 3 分钟出站流量突降为 0”的可疑节点。
- 需求 2 (主动确诊)：针对可疑节点，系统不得依赖单一第三方测速 API 作为最终依据，而是采用“海外中控本地主动探测 + 国内多探针聚合测量”的双层判定模型。
  1. 海外中控先对目标节点执行 DNS/TCP/TLS/HTTP 主动探测，用于区分源站故障与链路异常。
  2. 国内探针通过控制面完成注册、心跳、配置同步、命令拉取与结果回传。
  3. Sentinel 必须基于一次 measurement 内的多探针结果做聚合判定，不允许由单次 API 响应或单个探针结果直接确诊 `blocked_by_gfw`。
- 需求 2.1 (判定状态标准化)：系统需统一输出以下底层探测状态：`reachable`、`dns_failed`、`origin_unreachable`、`tls_failed`、`application_unreachable`、`probe_inconclusive`；并在聚合后输出以下最终状态：`healthy`、`origin_fault`、`suspected_blocked`、`confirmed_blocked_by_gfw`。
- 需求 2.2 (高置信确诊规则)：仅当“海外中控可达 + 国内至少 2 个探针失败 + 连续 2 个扫描周期重复出现”时，系统才可将节点判定为 `confirmed_blocked_by_gfw`。参数阈值可配置，但默认必须满足“多探针 + 连续周期”两个条件。
- 需求 3 (AWS 换 IP 自愈流水线)：确诊 AWS IPv6 被墙后，执行以下动作（禁止销毁实例）：
  1. 调用 AWS API (UnassignIpv6Addresses / AssignIpv6Addresses)，为该 EC2 实例的弹性网卡 (ENI) 剔除旧 IPv6，申请并绑定全新 IPv6。
  2. 调用 Cloudflare API，更新该节点对应子域名的 AAAA 记录。
  3. 操作 PG 数据库，更新该节点在 Xboard 表中的 host 字段。
  4. 通过 Telegram Bot 推送自愈成功战报。
- 需求 3.1 (自愈触发约束)：仅 `confirmed_blocked_by_gfw` 允许触发自动自愈。`suspected_blocked`、`origin_fault`、`probe_inconclusive` 均不得直接触发换 IP 或切 CDN。
- 需求 4 (自有机器自愈保底)：自有机器被 GFW 封锁后，需自动调用 Cloudflare API 开启小黄云切入 CDN 避险。同时，系统支持在纳管初始化时，默认勾选“开机即调用 CF 开启 CDN”的安全策略。
- 需求 5 IPv6 随机化防封锁。 系统申请新 IPv6 地址时，应在 AWS 允许的掩码范围内随机生成末位地址，避免顺序递增（如 ::1, ::2）被 GFW 识别特征。
- 需求 6 账号配额预警隔离。 增加对 AWS API RequestLimit 的监控，当触发限流时，自愈任务应自动进入指数退避重试，而非判定为账号被封。
- 需求 7 (协议边界)：`Hysteria2` 在第一阶段不纳入自动确诊闭环。若缺少可靠 UDP 探测能力，系统必须返回 `probe_inconclusive` 或转人工复核，禁止直接判定为 `confirmed_blocked_by_gfw`。

## 3.4 可视化驾驶舱 (Web UI)
- 需求 1：提供基于 Streamlit 的 Web 界面，访问需具备基础密码验证或强 IP 白名单限制。
- 需求 2：全局态势大屏：直观展示节点健康状态、整体存活率、当月换 IP 次数以及 AWS 账号池消耗进度。
- 需求 3：舰队操作台：以数据表格展示各节点详情（实例 ID、当前 IP、协议、归属账号）。提供“单节点强制换 IP”、“节点主动下线废弃”等人工干预按钮。

# 4. 非功能性需求 (Non-Functional Requirements)
- 安全要求：允许在 config.yaml 中硬编码密码、密钥或 Token，但必须支持通过环境变量覆盖，并确保日志输出对敏感字段脱敏。绝不允许 Streamlit UI 进程直接执行耗时的 Boto3 调用或高频 SQL 查询，必须与守护进程（Daemon）通过轻量级机制或只读数据库交互解耦。
- 性能要求 (ARM64 硬件红利)：所有的 AWS EC2 必须选择 ARM64 架构（如 t4g.medium 或 t4g.xlarge），利用其原生的 AES 硬件指令集实现最高性价比的加解密吞吐量。
- 代码规范约束：必须使用 Python 3.10+，强制启用 Type Hinting，遵守 PEP 8，并通过 pydantic 进行严格的数据类校验。

# 5. 业务约束与阈值 (Business Constraints) - [弹性调度升级版]
## 5.1 协议级安全红线 (Protocol Security Ban)
- AWS 禁止 Hysteria2 协议（自有机器节点可使用）：由于 AWS 风控系统对长时间、大流量的 UDP 代理流量极其敏感，极易触发 Abuse 封禁。系统在生成 User-Data 注入脚本和对接面板时，针对 AWS 资源彻底锁死对 hy2 及同类纯 UDP 协议的支持，仅允许使用伪装性更好的 TCP/TLS 及 WebSocket 流派。

## 5.2 动态舰队编制与区域配额 (Dynamic Fleet Matrix & Regional Quotas)
- 按需配置策略：摒弃硬编码的固定节点总数。系统必须通过全局 config.yaml 动态读取每个 AWS 区域（Region）期望部署的各协议节点数量。例如：`ap-northeast-1` 区域部署 5台 AnyTLS + 3台 Trojan。
- 硬件规格匹配：AnyTLS (性能突击队) 绑定分配 4vCPU (如 t4g.xlarge)；Trojan / WS+TLS (兼容与灾备队) 绑定分配 2vCPU (如 t4g.large)。

## 5.3 算力水位与最低配置预警 (Capacity Watermark & Alerting)
- 低水位触发机制：守护进程需实时统计各区域/各协议的“健康存活节点数”，并与 config.yaml 中配置的“期望数量”进行比对。
- 红色预警推送：当由于账号耗尽、封禁频率过高等原因，使得某区域健康节点数低于设定下限时，系统必须通过 Telegram 触发最高级别告警（例如：“🚨 警告：日本区域 AnyTLS 节点仅剩 2 台，请立即补充 AWS 账号资产！”）。

## 5.4 重试与容错兜底 (Retry & Fault Tolerance)
- 任何涉及 AWS Boto3、Cloudflare API 或 Xboard PG 数据库的外部调用，必须实现带有指数退避 (Exponential Backoff) 的重试机制，防止因瞬时网络抖动导致自愈工作流异常中断。

# 6. 全局异常告警与事件推送 (Alerting & Notification)
- 多渠道精准触达：当底层调度引擎捕获到 AWS 账号触发风控（如 API 抛出 AuthFailure），或自建高价值节点发生物理级失联（SSH 拒绝连接 / 宕机）时，系统需在 1 分钟内触发异步告警，通过 Telegram Bot 推送到管理员终端。
- 结构化战报感知：推送信息需包含：受损账号/资产 ID、阻断发生时间、拦截原因分类（如 AWS 风控封号 / 节点 IP 被墙 / 面板通信异常），以及当前全站可用节点存活率，辅助管理员决定下一步战术动作。