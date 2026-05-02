🛡️ 第一阶段：地基、安全契约与通知中枢 (Foundation & Messaging)
目标：确立强类型数据流与告警通道；允许在 config.yaml 中硬编码密钥，但必须支持环境变量覆盖，并确保日志输出对敏感字段脱敏。

任务 1.1：强类型配置解析与 Fleet Matrix 校验

文件：config.yaml, utils/config_parser.py

细节：使用 Pydantic 校验 AWS 凭证、PG 连接及各区域期望的 desired_count。

任务 1.2：带追踪 ID 的日志系统

文件：utils/logger.py

细节：封装 logging，确保每条日志带上 Correlation-ID，实现从检测到自愈的全链路追踪。

任务 1.3：多级 Telegram 通知引擎

文件：utils/tg_reporter.py

细节：

INFO 级：节点上线、IPv6 成功更换战报。

ERROR 级：自愈失败、数据库连接异常。

CRITICAL 级：AWS 账号被封 (Banned)、区域水位低于 min_alert_threshold。

☁️ 第二阶段：基础设施驱动层 (Infrastructure & Randomized Networking)
目标：封装原子 API，内置限流保护与防封逻辑。

任务 2.1：AWS EC2 调度器 (支持 IPv6 随机化)

文件：infrastructure/aws/ec2_client.py

细节：

实现基于 Boto3 的实例生命周期管理。

核心逻辑：在申请新 IPv6 时，在子网范围内生成随机后缀，规避递增 IP 被封。

任务 2.2：Cloudflare CDN/DNS 状态机

文件：infrastructure/cloudflare/cf_client.py

细节：实现 AAAA 记录同步及 Proxied（小黄云）一键切换。

🗄️ 第三阶段：PG 数据持久层 (Repository & State Management)
目标：接管 Xboard 交互，严格遵守 SQL 安全规范。

任务 3.1：高性能 PG 连接池

文件：database/connection.py

细节：基于 psycopg2-binary 和 DBUtils 建立池化连接，支持上下文管理器。

任务 3.2：Xboard 数据仓储 (Repository)

文件：database/xboard_repo.py

细节：

强制约束：INSERT 语句必须带 RETURNING id 立即获取 NodeID。

实现参数化查询（%s），严禁字符串拼接。

⚙️ 第四阶段：核心业务编排与自愈流水线 (Service & Healing)
目标：实现“发现即处理”的无人值守逻辑。

任务 4.1：User-Data 模板渲染与部署反馈

文件：templates/user_data.sh, utils/template_engine.py

细节：Bash 脚本需包含 sudo 提权、V2bX 自动安装及 NodeID 注入。

任务 4.2：Provisioner (初始化流水线)

细节：选择账号 -> DB 注册节点 -> AWS 开机 -> CF 绑域名 -> TG 发送“舰队增援成功”通知。

任务 4.3：Healer (极速自愈流水线)

细节：

AnyTLS 逻辑：调用 AWS API 解绑并重新绑定随机 IPv6（不销毁实例，10 秒内恢复）。

WS/Trojan 逻辑：调用 CF API 开启小黄云 CDN 避险。

任务结束：发送“战损自愈完成”战报，包含旧 IP、新 IP 及耗时。

🖥️ 第五阶段：控制面、监控与 UI (Control & UI)
目标：驱动死循环检测并提供可视化管理。

任务 5.1：Sentinel 监测守护进程 (Daemon)

文件：daemon.py, services/monitor.py

细节：

每 3-5 分钟轮询流量异常节点。

先由海外中控执行本地 DNS/TCP/TLS/HTTP 主动探测，再编排国内探针完成多点测量聚合。

探针控制面需支持注册、心跳、拉取命令、回传结果、配置同步，不额外引入独立 Web 框架。

仅当 measurement 最终状态为 `confirmed_blocked_by_gfw`，且满足连续确认周期阈值时，才允许触发 Healer。

`Hysteria2` 第一阶段默认降级为 `probe_inconclusive` 或人工复核，不进入自动确诊闭环。

若发现 AWS 账号风控，执行“静默弃尸”，标记账号为 Banned 并发送 CRITICAL 告警 。

任务 5.2：Streamlit 驾驶舱 (Dashboard)

文件：app.py

细节：展示资产健康度、各区域存活率。

安全要求：UI 仅通过 services 层调用逻辑，禁止直接实例化 Boto3 或写数据库。