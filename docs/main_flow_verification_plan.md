# ShadowFleet 主流程验证方案

> **版本**: v1.0  
> **作者**: ShadowFleet DevOps Team  
> **日期**: 2026-03-24  
> **目的**: 验证 ShadowFleet 核心业务流程的端到端正确性

---

## 1. 概述

### 1.1 验证范围

本文档覆盖 ShadowFleet 以下三大核心主流程的完整验证：

| # | 流程名称 | 触发方式 | 关键路径 |
|---|----------|----------|----------|
| F1 | 节点配置流程 (Provisioning) | UI 手动提交 / API | 资产选择 → EC2 启动 → DNS 同步 → 就绪回调 |
| F2 | 哨兵自愈流程 (Sentinel Healing) | Daemon 定时循环 | 异常检测 → 控制面探测 → CN 探针测量 → 节点自愈 |
| F3 | 账号封禁处理 (Account Abandonment) | 自愈触发 | 检测封禁 → 批量下线节点 → 资源回收 |

### 1.2 验证环境

- **操作系统**: Windows 10 / Linux
- **Python**: 3.10+
- **外部依赖**:
  - AWS EC2（至少 1 个可用账号）
  - Cloudflare DNS（有效 API Token）
  - Xboard PostgreSQL（可写权限）
  - Telegram Bot（有效 Token，用于通知验证）

### 1.3 验证前置条件

- [ ] `config.dev.yaml` 配置完整且正确
- [ ] `config.yaml` 配置完整且正确
- [ ] Python 依赖已安装：`pip install -r requirements.txt`
- [ ] SQLite 数据库已初始化（`database/sqlite_connection.py` 运行后自动生成 `shadowfleet.db`）
- [ ] PostgreSQL Xboard 数据库连接正常（可使用 `psql` 或 `pgAdmin` 验证）
- [ ] AWS 凭证有效（`aws sts get-caller-identity` 验证）
- [ ] Cloudflare Token 有效（可读 Zone + 可写 DNS）
- [ ] Telegram Bot Token 有效（可发送消息到测试群组）

---

## 2. F1 — 节点配置流程 (Provisioning) 验证

### 2.1 流程说明

```
用户提交配置请求
    ↓
ProvisioningTaskService.submit_task() → SQLite fleet_provisioning_tasks
    ↓
Daemon Provisioner Worker 轮询并认领任务
    ↓
ProvisionerService.provision_node()
    ├→ AssetSelectorService.select_asset() → 选中最空闲资产
    ├→ NodeRegistryService.register_node() → Xboard v2_server INSERT
    ├→ ReadyCallbackService.register_callback() → SQLite fleet_ready_callbacks
    ├→ [AWS 路径] EC2Client.launch_ipv6_instance() → 启动实例
    │       └→ CFClient.sync_aaaa_record() → 同步 DNS AAAA 记录
    ├→ [Self-Hosted 路径] SSHClient.deploy_agent() → 部署探针
    └→ ReadyCallbackService.wait_for_ready_callback() → 等待节点就绪
    ↓
节点上报就绪 → ReadyCallbackService.fire_callback()
    ↓
NodeRegistryService.mark_node_online() → Xboard v2_server UPDATE online=1
    ↓
SQLite fleet_nodes 更新为 online 状态
    ↓
通知 (TG Reporter)
```

### 2.2 验证用例

#### TC-F1-01: 正常 AWS 节点配置

| 项目 | 内容 |
|------|------|
| **前置条件** | AWS 账号可用、Cloudflare Token 有效、Xboard 可写 |
| **输入** | `asset_type=aws`, `region=us-east-1`, `protocol=vmess`, `node_count=1` |
| **执行步骤** | 1. 启动 Daemon（`python daemon.py`）<br>2. 通过 UI 提交配置任务（`provisioner_page`）<br>3. 观察 Daemon 日志<br>4. 检查 AWS EC2 Console<br>5. 检查 Cloudflare DNS |
| **预期结果** | - SQLite `fleet_provisioning_tasks` 中任务状态为 `completed`<br>- AWS EC2 实例处于 `running` 状态<br>- Cloudflare DNS 中存在对应的 AAAA 记录<br>- Xboard `v2_server` 中存在对应记录且 `online=1`<br>- SQLite `fleet_nodes` 中节点状态为 `online`<br>- Telegram 收到成功通知 |
| **验证命令** | `sqlite3 shadowfleet.db "SELECT * FROM fleet_nodes WHERE status='online';"` |

#### TC-F1-02: Self-Hosted 节点配置

| 项目 | 内容 |
|------|------|
| **前置条件** | 目标机器 SSH 可达、探针 Agent 部署包就绪 |
| **输入** | `asset_type=self_hosted`, `host=<ip>`, `protocol=trojan`, `node_count=1` |
| **执行步骤** | 1. 启动 Daemon<br>2. 通过 UI 提交配置任务<br>3. 观察 Daemon 日志<br>4. SSH 到目标机器验证 Agent 运行状态 |
| **预期结果** | - 任务状态为 `completed`<br>- 目标机器上 `probe_agent` 进程运行中<br>- Xboard 中 `online=1`<br>- Telegram 收到成功通知 |

#### TC-F1-03: 资产不足时的拒绝行为

| 项目 | 内容 |
|------|------|
| **前置条件** | 该区域/协议的所有资产均已被占用 |
| **输入** | `asset_type=aws`, `region=us-east-1`, `protocol=ss` |
| **执行步骤** | 通过 UI 提交配置任务，观察系统响应 |
| **预期结果** | 任务状态为 `failed`，原因为 `no_available_asset`，Telegram 收到失败通知 |
| **验证命令** | `sqlite3 shadowfleet.db "SELECT * FROM fleet_provisioning_tasks WHERE status='failed';"` |

#### TC-F1-04: AWS 实例启动超时

| 项目 | 内容 |
|------|------|
| **前置条件** | 模拟 AWS API 延迟或超时 |
| **输入** | 正常配置请求，通过 mock 或网络隔离模拟超时 |
| **执行步骤** | 提交配置任务，等待超时处理 |
| **预期结果** | 任务状态为 `failed`，原因为超时相关错误，SQLite 中记录错误堆栈，不触发二次重试 |
| **验证命令** | `sqlite3 shadowfleet.db "SELECT status, error_message FROM fleet_provisioning_tasks WHERE status='failed';"` |

#### TC-F1-05: Cloudflare DNS 同步失败不影响节点就绪

| 项目 | 内容 |
|------|------|
| **前置条件** | Cloudflare Token 有效但 Zone 配置错误 |
| **输入** | 正常配置请求 |
| **执行步骤** | 提交任务，观察 DNS 同步失败的处理 |
| **预期结果** | 节点状态仍为 `online`，DNS 同步失败作为 warning 记录，不阻断主流程 |
| **验证命令** | `sqlite3 shadowfleet.db "SELECT status FROM fleet_nodes WHERE node_id='<id>';"` |

---

## 3. F2 — 哨兵自愈流程 (Sentinel Healing) 验证

### 3.1 流程说明

```
Daemon Sentinel Worker（定时循环，默认每 N 分钟一次）
    ↓
MonitorService.run_scan_cycle()
    ├→ XboardSentinelClient.get_server_minute_stats() → 获取分钟流量统计
    │       └→ 识别流量异常节点（持续低流量 / 流量为 0）
    ↓
MonitorService.detect_suspicious_nodes() → 可疑节点列表
    ↓
对于每个可疑节点：
    ├→ ProbeClient.probe_control_plane() → TCP 握手探测
    │       └→ 探测结果: reachable / unreachable
    ↓
如果控制面探测失败 → 确认阻断
    ↓
ProbeOrchestratorService.measure_candidate()
    ├→ ProbeMeasurementService.create_measurement_task() → 创建测量任务
    ├→ ProbeCommandService.enqueue_command() → 下发 CN 探针
    │       └→ 探针节点执行 curl/traceroute 测量
    ├→ ProbeMeasurementService.wait_for_remote_results() → 等待结果（超时 120s）
    └→ 判定: confirmed_blocked_by_gfw / measurement_timeout / not_blocked
    ↓
如果 confirmed_blocked_by_gfw:
    ↓
HealerService.heal_node()
    ├→ 获取分布式锁 (fleet_operation_locks)
    ├→ EC2Client.rotate_instance_ipv6() → 销毁旧实例，启动新实例（IPv6 热切换）
    ├→ CFClient.sync_aaaa_record() → 更新 DNS 记录
    ├→ XboardRepo.update_node_host() → 更新 Xboard 节点 host
    ├→ SQLite fleet_nodes 更新状态
    └→ 释放锁
    ↓
通知 (TG Reporter)
```

### 3.2 验证用例

#### TC-F2-01: 正常自愈流程（IPv6 热切换）

| 项目 | 内容 |
|------|------|
| **前置条件** | 存在 `online` 状态的 AWS 节点 |
| **输入** | 模拟 GFW 阻断（通过安全组拒绝 CN IP 段流量） |
| **执行步骤** | 1. 启动 Daemon（Sentinel Worker 激活）<br>2. 等待下一个扫描周期（或手动触发）<br>3. 观察日志中 `MonitorService` → `ProbeOrchestratorService` → `HealerService` 调用链 |
| **预期结果** | - 旧 EC2 实例被 `terminate`<br>- 新 EC2 实例启动（不同 IPv6 地址）<br>- Cloudflare AAAA 记录更新<br>- Xboard `v2_server` 中 `host` 更新<br>- SQLite `fleet_nodes` 中节点仍为 `online`<br>- Telegram 收到自愈通知（含 correlation_id） |
| **验证命令** | `aws ec2 describe-instances --filters "Name=tag:Name,Values=ShadowFleet-*" --query "Reservations[].Instances[].[InstanceId,State.Name,NetworkInterfaces[0].Ipv6Addresses[0].Ipv6Address]"` |

#### TC-F2-02: CN 探针测量超时

| 项目 | 内容 |
|------|------|
| **前置条件** | 存在可疑节点，但 CN 探针无法完成测量（网络问题） |
| **输入** | 同 TC-F2-01 |
| **执行步骤** | 等待测量超时（默认 120s） |
| **预期结果** | 测量结果为 `measurement_timeout`，不触发自愈，仅记录日志；Telegram 发送超时警告 |
| **验证命令** | `sqlite3 shadowfleet.db "SELECT * FROM fleet_monitor_detections;"` |

#### TC-F2-03: 节点标记为非阻断状态

| 项目 | 内容 |
|------|------|
| **前置条件** | 节点控制面可达，CN 探针测量结果为 `not_blocked` |
| **输入** | 模拟偶发性网络抖动 |
| **执行步骤** | 等待扫描周期，观察判定结果 |
| **预期结果** | 节点保持 `online` 状态，不触发自愈，仅记录日志 |

#### TC-F2-04: 自愈分布式锁冲突

| 项目 | 内容 |
|------|------|
| **前置条件** | 同一节点同时触发配置和自愈 |
| **输入** | 在节点配置过程中手动触发同一节点的自愈 |
| **执行步骤** | 同时执行配置和自愈请求 |
| **预期结果** | 后请求方等待锁超时后跳过，或直接跳过（取决于锁策略），不产生竞态条件 |

#### TC-F2-05: 自愈失败重试机制

| 项目 | 内容 |
|------|------|
| **前置条件** | AWS API 在首次调用时返回 ThrottlingException |
| **输入** | 同 TC-F2-01 |
| **执行步骤** | 观察内置的指数退避重试逻辑 |
| **预期结果** | 根据 `resilience.py` 中的 `execute_with_backoff` 策略重试 N 次后成功或最终失败；日志中可见 Correlation-ID 关联的所有重试记录 |

---

## 4. F3 — 账号封禁处理 (Account Abandonment) 验证

### 4.1 流程说明

```
HealerService.heal_node()
    ↓
AWS 账号被封禁（检测到封禁异常）
    ↓
AccountAbandonmentService.abandon_account(account_id)
    ├→ AssetRepo.get_nodes_by_account() → 获取该账号下所有节点
    ├→ XboardRepo.delete_node() → 批量从 Xboard 删除节点
    ├→ EC2Client.terminate_instance() → 批量终止 EC2 实例
    ├→ CFClient.delete_records() → 批量删除 Cloudflare DNS 记录
    ├→ SQLite fleet_nodes → 批量标记为 deleted
    └→ AccountAbandonmentNotifier.send_alert() → 紧急告警通知
```

### 4.2 验证用例

#### TC-F3-01: 检测到账号封禁后自动弃尸

| 项目 | 内容 |
|------|------|
| **前置条件** | 存在使用特定 AWS 账号的在线节点至少 1 个 |
| **输入** | 模拟 AWS 返回 `UnauthorizedOperation` 或 `AccountProblem` |
| **执行步骤** | 1. 启动 Daemon<br>2. 通过 mock 或 AWS 沙盒环境触发账号封禁异常<br>3. 观察 AccountAbandonmentService 执行 |
| **预期结果** | - Xboard `v2_server` 中该账号下的节点记录被删除<br>- EC2 实例被 Terminated<br>- Cloudflare DNS 记录被删除<br>- SQLite 中节点状态为 `deleted`<br>- Telegram 收到 **紧急告警**（红色标记） |
| **验证命令** | `sqlite3 shadowfleet.db "SELECT account_id, status, COUNT(*) FROM fleet_nodes GROUP BY account_id, status;"` |

#### TC-F3-02: 部分资源清理失败时的处理

| 项目 | 内容 |
|------|------|
| **前置条件** | Xboard 删除成功，但 EC2 Terminate 失败 |
| **输入** | 同 TC-F3-01，部分 API 失败 |
| **执行步骤** | 观察错误处理逻辑 |
| **预期结果** | Xboard 已清理的节点不再被重新处理；失败的 EC2 操作记录错误日志并通知；部分成功部分失败的状态均被正确记录 |

---

## 5. 通用验证检查项

### 5.1 日志与 Correlation-ID

- [ ] 所有日志输出包含 `correlation_id` 字段
- [ ] 单次请求的完整流水（配置→自愈→通知）可通过 `correlation_id` 串联
- [ ] 日志格式符合 `config.yaml` 中定义的格式规范
- [ ] **禁止**出现 `print()` 调用（业务逻辑层）

### 5.2 数据库一致性

- [ ] SQLite 与 Xboard PostgreSQL 数据同步一致
- [ ] PostgreSQL INSERT 操作使用 `RETURNING id`
- [ ] 事务边界正确（失败回滚，成功提交）
- [ ] 无裸 `except Exception as e: pass`

### 5.3 安全性

- [ ] `app.py` 不包含任何 AWS AK/SK 或数据库密码
- [ ] 所有敏感配置从 `config.yaml` 或环境变量读取
- [ ] User-Data 脚本中敏感信息使用 `sed` 替换时有容错

### 5.4 API 限流保护

- [ ] Cloudflare API 调用有 `TokenBucketRateLimiter`
- [ ] AWS Boto3 写操作有重试 + 退避策略
- [ ] Xboard API 调用无频繁重试导致的 RateLimitExceeded

### 5.5 代码质量

- [ ] 所有 Python 函数包含完整类型注解
- [ ] 所有 `.py` 文件不超过 400 行
- [ ] 无驼峰命名法（函数/变量使用 snake_case）
- [ ] Pydantic 模型用于数据库字段映射

---

## 6. 自动化验证脚本

### 6.1 快速冒烟测试

```python
# tests/integration/test_main_flows.py
import pytest
import sqlite3
from services.provisioning_task_service import ProvisioningTaskService
from services.manual_operation_service import ManualOperationService
from database.sqlite_connection import SQLiteConnectionManager


def test_provisioning_task_creation():
    """TC-F1-01: 验证配置任务可正常创建并写入 SQLite"""
    conn = SQLiteConnectionManager().get_connection()
    cursor = conn.cursor()
    
    # 验证表存在
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='fleet_provisioning_tasks'
    """)
    assert cursor.fetchone() is not None, "fleet_provisioning_tasks 表不存在"
    
    # 验证表结构
    cursor.execute("PRAGMA table_info(fleet_provisioning_tasks)")
    columns = {row[1] for row in cursor.fetchall()}
    required_columns = {
        "id", "asset_type", "region", "protocol", 
        "node_count", "status", "correlation_id", 
        "created_at", "updated_at", "error_message"
    }
    assert required_columns.issubset(columns), f"缺少列: {required_columns - columns}"
    conn.close()


def test_sentinel_detection_tables_exist():
    """TC-F2-*: 验证哨兵相关表存在"""
    conn = SQLiteConnectionManager().get_connection()
    cursor = conn.cursor()
    
    tables = ["fleet_monitor_cycles", "fleet_monitor_detections", "fleet_probes"]
    for table in tables:
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
        assert cursor.fetchone() is not None, f"{table} 表不存在"
    conn.close()


def test_lock_table_exists():
    """TC-F2-04: 验证分布式锁表存在"""
    conn = SQLiteConnectionManager().get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='fleet_operation_locks'
    """)
    assert cursor.fetchone() is not None
    conn.close()


def test_node_status_lifecycle():
    """验证节点状态生命周期"""
    # pending → provisioning → online → healing → online
    # 或: pending → provisioning → online → deleted
    valid_transitions = {
        "pending": ["provisioning", "failed"],
        "provisioning": ["online", "failed"],
        "online": ["healing", "deleted"],
        "healing": ["online", "failed"],
        "failed": ["pending"],  # 可重试
        "deleted": [],  # 终态
    }
    # 此测试检查 SQLite fleet_nodes 中无非法状态
    conn = SQLiteConnectionManager().get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT status FROM fleet_nodes")
    statuses = {row[0] for row in cursor.fetchall()}
    for status in statuses:
        assert status in valid_transitions, f"发现非法状态: {status}"
    conn.close()
```

### 6.2 执行方式

```bash
# 运行集成测试
python -m pytest tests/integration/test_main_flows.py -v

# 运行所有单元测试
python -m pytest tests/ -v --tb=short
```

---

## 7. 验证里程碑

| 里程碑 | 目标 | 对应测试用例 |
|--------|------|-------------|
| M1: 环境就绪 | 所有前置条件满足 | 人工确认 checklist |
| M2: 流程可跑通 | F1/F2/F3 至少各完成一次完整执行 | TC-F1-01, TC-F2-01, TC-F3-01 |
| M3: 异常路径覆盖 | 超时/锁冲突/资源不足等边界情况 | TC-F1-03~05, TC-F2-02~05, TC-F3-02 |
| M4: 数据一致性保证 | SQLite/Xboard/AWS 三端数据一致 | 通用检查项 5.2 |
| M5: 长期稳定性 | Daemon 运行 24h 无内存泄漏/僵尸进程 | 人工观察 + 日志审计 |

---

## 8. 已知限制

1. **AWS Mock 测试**: 当前无 AWS Moto mock 套件，F2/F3 的 AWS 操作验证依赖真实环境或手动模拟
2. **CN 探针可用性**: 探针节点需要预先部署，当前验证方案假设探针节点已在线
3. **Xboard API**: `XboardSentinelClient` 依赖 Xboard 版本和接口，`xboard_sentinel_interface_requirements.md` 中定义接口规范，需确保版本兼容
4. **并发压力测试**: 当前方案不含并发压力测试，建议后续补充 Locust 压力测试套件
