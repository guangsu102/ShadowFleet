1. 系统架构概述 (System Architecture)
ShadowFleet 是一个高度解耦的云原生代理中控管理平面 (Control Plane)。系统由后端的守护进程 (Daemon) 驱动高频业务流转，通过前端可视化驾驶舱 (Streamlit) 提供管理员干预接口。中控机部署于完全独立的海外非风控服务器，通过标准 API 与 AWS 和 Xboard PostgreSQL 数据库交互。

1.1 核心防线设计
网络防线： 全站纯 IPv6 架构，通过 AWS 弹性网卡动态更换 IPv6 地址实现 10 秒级防封自愈。

灾备防线： 针对支持域名的协议，接入 Cloudflare API，被封锁时自动开启小黄云 (Proxied) 极限续命。

安全红线： 严禁部署 Hysteria2 (hy2) 等纯 UDP 激进协议，阻断 AWS 官方 Abuse 风控。

2. 核心技术栈与依赖约束 (Technology Stack)
根据开发纪律，本系统严禁引入未经批准的第三方依赖。核心技术栈锁死如下：

核心语言： Python 3.10+ (全面启用 match-case 与 Type Hinting)

云资源调度： boto3 (严格禁止使用 Terraform 包装库)

数据库交互： * 远程 Xboard 面板：psycopg2-binary (严格遵守 PostgreSQL 参数化查询防注入)

本地状态机：内置 sqlite3

网络请求与检测： requests (调用第三方外部 API 必须显式设置 timeout=10)

可视化驾驶舱： streamlit >= 1.30 (禁止编写前端 HTML/JS，纯 Python 渲染)

配置解析与数据类： PyYAML, pydantic

告警中枢： python-telegram-bot

3. 模块拆分与目录编排 (Directory Structure)
采用严格的层级架构 (Layered Architecture)，严禁 UI 层越权直接调用基础设施层。


ShadowFleet/
├── app.py                   # UI 驾驶舱入口 (Streamlit)
├── daemon.py                # 后台自愈引擎入口 (死循环调度器)
├── config.yaml              # 全局配置 (舰队矩阵、凭证、预警阈值)
│
├── ui/                      # [表现层] Streamlit 页面与组件
├── services/                # [业务逻辑层] 核心调度编排 (provisioner, healer, monitor)
├── database/                # [数据持久层] Xboard PG 连接池与 Repository 仓储
├── infrastructure/          # [基础设施层] AWS API, Cloudflare API, Ping API
└── utils/                   # [通用工具包] Pydantic 配置解析器, TG 告警器, 日志器
4. 全局配置与弹性兵力矩阵 (Configuration & Fleet Matrix)
基于 config.yaml 的动态编排，是实现系统弹性的核心。系统必须定义不同区域的期望节点数 (desired_count) 和最低安全水位 (min_alert_threshold)。

config.yaml 结构示例与定义:

YAML
aws_credentials:
  - account_id: "acc_01"
    access_key: "AKIA..."
    secret_key: "..."
    status: "active" # 风控时自动标记为 banned

fleet_matrix:
  ap-northeast-1: # 东京区域
    AnyTLS: 
      desired_count: 5
      min_alert_threshold: 2  # 低于此值触发 Telegram 红色告警
    Trojan:
      desired_count: 3
      min_alert_threshold: 1
  us-west-2:
    WS:
      desired_count: 5
      min_alert_threshold: 3
5. 核心业务工作流 (Core Workflows)
5.1 无人值守初始化工作流 (Provisioning Flow)
services/provisioner.py 读取 config.yaml，发现 ap-northeast-1 缺少 AnyTLS 节点。

调用 database/xboard_repo.py 向 PostgreSQL 的 server 相关表写入预注册数据，获取自增 NodeID (SERIAL)。

通过 utils/template_engine.py 将 NodeID 渲染进 user_data_base.sh。

调用 infrastructure/aws/ec2_client.py 创建 t4g.xlarge ARM64 实例，注入 User-Data，安全组强制放行 ::/0 (IPv6 全网)。

实例开机，Bash 脚本静默执行，自动对接 Xboard，节点上线。

5.2 纯 IPv6 / CDN 极速自愈工作流 (Healing Flow)
嗅探： services/monitor.py 轮询 PostgreSQL 发现某节点流量 3 分钟内突降至 0。

确诊： 调用 infrastructure/third_party/ping_api.py 探测该 IPv6 443 端口，确诊大面积超时。

闪避 (Match-Case 分流)：

case AnyTLS: 调用 AWS Boto3 unassign_ipv6_addresses 卸载旧 IP，assign_ipv6_addresses 绑定新 IP，更新 PG 数据库 host 字段。

case WS/Trojan: 调用 Cloudflare API 开启 Proxied 小黄云，挂载 CDN。

闭环： 通过 TG Bot 推送变更结果，全程 不 重启/销毁 AWS 实例。

5.3 初始化反馈环 (Phone-home)： 在 user_data_base.sh 脚本末尾增加回调逻辑（如 Webhook 或 TG 消息），标志节点正式进入“Ready”状态。

6. 开发与编码规范约束 (Development Standards)
开发过程中必须严格遵循以下系统级约束：

6.1 代码质量与风格
强制 PEP 8 与蛇形命名： 函数与变量名严格采用 snake_case（如 aws_access_key），类名采用 PascalCase，常量采用 UPPER_SNAKE_CASE。绝对禁止使用 camelCase。

防御性编程： 严禁使用赤裸的 except Exception as e: pass。必须捕获精细化异常（如 psycopg2.OperationalError, botocore.exceptions.ClientError）。

强类型契约： 业务层之间传递的数据必须是经过 Pydantic 校验的数据模型 (Model) 或者是 dataclass，禁止使用结构不明的嵌套 Dictionary。

6.2 数据库操作规范 (PostgreSQL)
所有针对 Xboard 面板的写入操作，必须采用 参数化查询 (%s)，绝对禁止字符串拼接以防止 SQL 注入。

PostgreSQL 建表/交互时，自增主键映射必须认定为 SERIAL / BIGSERIAL，禁止混用 MySQL 概念。

Python 变量映射数据库字段时，变量名与数据库字段保持一致（如 Xboard 数据库字段名为 node_group，Python 数据类参数也应命名为 node_group）。

6.3 安全隔离与日志输出
允许硬编码：允许在 config.yaml 中硬编码环境密钥、URL、Token，但必须支持环境变量覆盖，并确保日志输出对敏感字段脱敏。

日志管控： 业务逻辑层 core/、services/ 目录下 绝对禁止出现 print() 语句。必须使用 logging.getLogger(__name__)，根据级别输出 INFO（状态变更）与 ERROR（异常堆栈）。

User-Data 提权： 动态生成的 Bash 脚本中，系统环境修改及 V2bX 服务操作必须显式携带 sudo 前缀。

6.4 本地状态机交互： 明确 app.py (UI) 以 只读 (Read-Only) 模式访问 sqlite3 数据库，由 daemon.py 负责唯一写入，避免多进程锁死 。

6.5 安全清理规范： SSH Provisioner 模块在完成装机后，必须执行 history -c 并清理 /tmp/ 下的所有敏感脚本和凭证。