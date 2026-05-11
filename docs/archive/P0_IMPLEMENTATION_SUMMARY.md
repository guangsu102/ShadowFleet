# P0 高优先级问题实现总结

本文档总结了 4 个 P0 高优先级问题的实现方案。

---

## 1. ✅ 孤儿资源自动检测和清理

### 实现的组件

#### 1.1 `services/orphan_resource_detector.py`
**功能**：检测系统中的孤儿资源

**检测范围**：
- **EC2 实例**：在 AWS 中存在但 SQLite 中无记录的实例
  - 通过 `ManagedBy=ShadowFleet` 标签识别
  - 过滤创建时间超过 1 小时的实例（避免误判正在 provisioning 的实例）
- **DNS 记录**：在 Cloudflare 中存在但 SQLite 中无记录的域名
  - 只检查 `sf-` 开头的子域名
- **资产分配**：SQLite 中标记为 `allocated` 但对应节点已删除的分配
  - 使用 LEFT JOIN 查询孤儿分配
- **Xboard 节点**：在 Xboard 中存在但 SQLite 中无记录的节点

**核心方法**：
```python
scan_all_orphan_resources() -> OrphanResourceReport
```

#### 1.2 `services/orphan_resource_cleaner.py`
**功能**：清理检测到的孤儿资源

**清理策略**：
- **EC2 实例**：调用 `terminate_instance()` 终止实例
- **DNS 记录**：调用 Cloudflare API 删除记录
- **资产分配**：调用 `release_allocation_by_xboard_node_id()` 释放分配
- **Xboard 节点**：调用 `delete_node()` 删除节点

**支持功能**：
- **Dry Run 模式**：只记录日志，不实际执行清理
- **选择性清理**：可以选择清理哪些类型的资源
- **详细报告**：返回每个资源的清理结果

**核心方法**：
```python
cleanup_orphan_resources(report, dry_run=False) -> CleanupReport
```

---

## 2. ✅ 增强双数据库同步的监控和告警

### 实现的组件

#### 2.1 `services/database_sync_monitor.py`
**功能**：监控 Xboard (PostgreSQL) 和 SQLite 之间的数据一致性

**检查项**：
- **missing_in_sqlite**：Xboard 中存在但 SQLite 中缺失的节点
- **missing_in_xboard**：SQLite 中存在但 Xboard 中缺失的节点
- **status_mismatch**：状态不一致（Xboard.show ≠ SQLite.status）
- **host_mismatch**：Host 不一致

**健康状态分级**：
- `healthy`：无不一致
- `warning`：不一致数量 ≤ 5
- `critical`：不一致数量 > 5

**核心方法**：
```python
check_sync_health() -> SyncHealthReport
auto_repair_inconsistencies(report, dry_run=False) -> dict[str, int]
```

**自动修复策略**：
- `missing_in_sqlite`：暂不自动修复（需要手动介入）
- `missing_in_xboard`：标记 SQLite 节点为已删除
- `status_mismatch`：以 SQLite 为准，同步到 Xboard
- `host_mismatch`：以 SQLite 为准，同步到 Xboard

#### 2.2 `services/system_health_monitor.py`
**功能**：系统整体健康监控和告警

**监控内容**：
- 孤儿资源检测
- 数据库同步健康检查
- 生成综合健康报告
- 触发 Telegram 告警

**告警触发条件**：
- 孤儿资源数量 > 0
- 数据库同步状态非 `healthy`
- 整体状态为 `warning` 或 `critical`

**核心方法**：
```python
run_health_check(auto_cleanup_orphans=False, auto_repair_sync=False) -> SystemHealthReport
```

---

## 3. ✅ 完善错误处理和回滚机制

### 实现的组件

#### 3.1 `services/rollback_coordinator.py`
**功能**：统一的回滚协调器

**核心特性**：
- **优先级管理**：支持 4 个优先级（CRITICAL, HIGH, MEDIUM, LOW）
- **失败容忍**：支持 `allow_failure` 标记，允许某些回滚失败
- **完整执行**：确保所有回滚动作都尝试执行（除非遇到关键失败）
- **详细报告**：记录每个回滚动作的结果

**使用示例**：
```python
coordinator = RollbackCoordinator(logger)

# 注册回滚动作
coordinator.register_action(
    name="Delete Xboard node",
    action=lambda: xboard_repo.delete_node(node_id),
    priority=RollbackPriority.CRITICAL,
    resource_type="xboard_node",
    resource_id=str(node_id),
    allow_failure=False,
)

coordinator.register_action(
    name="Terminate EC2 instance",
    action=lambda: ec2_client.terminate_instance(instance_id),
    priority=RollbackPriority.HIGH,
    resource_type="ec2_instance",
    resource_id=instance_id,
    allow_failure=True,  # 允许失败（可能已被手动删除）
)

# 执行回滚
report = coordinator.execute_rollback(continue_on_failure=True)
```

**改进点**：
1. 替代原有的 `provisioning_failure_handler.py` 中的硬编码回滚逻辑
2. 支持自定义回滚顺序和策略
3. 提供详细的回滚报告，便于排查问题

---

## 4. ✅ 修复并发场景下的数据一致性问题

### 实现的组件

#### 4.1 `services/concurrency_control.py`
**功能**：提供并发控制机制

**实现的锁机制**：

##### 4.1.1 分布式锁（DistributedLock）
基于 SQLite 的轻量级分布式锁实现

**特性**：
- **TTL 支持**：锁自动过期，避免死锁
- **等待超时**：支持阻塞等待和超时
- **自动清理**：定期清理过期锁
- **上下文管理器**：支持 `with` 语法

**使用示例**：
```python
distributed_lock = DistributedLock(runtime_context)

# 方式 1：手动获取和释放
result = distributed_lock.acquire_lock(
    lock_key="domain:example.com",
    holder="worker-1",
    ttl_seconds=30,
    wait_timeout_seconds=10,
)
if result.acquired:
    try:
        # 执行需要锁保护的操作
        pass
    finally:
        distributed_lock.release_lock("domain:example.com", "worker-1")

# 方式 2：使用上下文管理器
with distributed_lock.lock("domain:example.com", "worker-1") as acquired:
    if acquired:
        # 执行需要锁保护的操作
        pass
```

**数据库表结构**：
```sql
CREATE TABLE distributed_locks (
    lock_key TEXT PRIMARY KEY,
    holder TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_distributed_locks_expires_at ON distributed_locks(expires_at);
```

##### 4.1.2 乐观锁（OptimisticLockManager）
基于版本号的乐观锁实现

**使用场景**：
- 读多写少的场景
- 冲突概率低的场景
- 需要高并发性能的场景

**使用示例**：
```python
optimistic_lock = OptimisticLockManager(runtime_context)

# 读取记录和版本号
node = state_repo.get_node_by_id(node_id)
current_version = node.version

# 尝试更新
success = optimistic_lock.update_with_version_check(
    table="fleet_nodes",
    record_id=node_id,
    updates={"status": "online", "updated_at": utcnow_iso()},
    expected_version=current_version,
)

if not success:
    # 版本冲突，需要重试
    pass
```

**应用场景**：
1. **域名分配并发控制**：替代现有的 `BEGIN IMMEDIATE` 方案
2. **资产分配并发控制**：防止同一资产被多次分配
3. **节点状态更新**：防止并发更新导致状态不一致

---

## 5. API 端点

### 5.1 `api/router/health.py`
提供以下健康检查和管理端点：

| 端点 | 方法 | 功能 | 权限 |
|------|------|------|------|
| `/api/v1/health/orphan-resources` | GET | 扫描孤儿资源 | 普通用户 |
| `/api/v1/health/orphan-resources/cleanup` | POST | 清理孤儿资源 | 操作员 |
| `/api/v1/health/sync-status` | GET | 检查数据库同步状态 | 普通用户 |
| `/api/v1/health/sync-status/repair` | POST | 修复同步问题 | 操作员 |
| `/api/v1/health/system` | GET | 系统整体健康检查 | 普通用户 |

**使用示例**：

```bash
# 1. 扫描孤儿资源
curl -X GET http://localhost:8000/api/v1/health/orphan-resources \
  -H "Authorization: Bearer <token>"

# 2. 清理孤儿资源（Dry Run）
curl -X POST http://localhost:8000/api/v1/health/orphan-resources/cleanup \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}'

# 3. 检查数据库同步状态
curl -X GET http://localhost:8000/api/v1/health/sync-status \
  -H "Authorization: Bearer <token>"

# 4. 修复同步问题（Dry Run）
curl -X POST http://localhost:8000/api/v1/health/sync-status/repair \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}'

# 5. 系统整体健康检查（带自动清理和修复）
curl -X GET "http://localhost:8000/api/v1/health/system?auto_cleanup=true&auto_repair=true" \
  -H "Authorization: Bearer <token>"
```

---

## 6. 集成到现有系统

### 6.1 在 Daemon 中定期执行健康检查

建议在 `daemon.py` 中添加定期任务：

```python
# 每小时执行一次健康检查
async def health_check_task():
    while True:
        try:
            monitor = SystemHealthMonitor(runtime_context)
            report = monitor.run_health_check(
                auto_cleanup_orphans=True,  # 自动清理孤儿资源
                auto_repair_sync=True,      # 自动修复同步问题
            )
            
            if report.overall_status != "healthy":
                logger.warning("System health check: %s", report.overall_status)
        except Exception as exc:
            logger.exception("Health check failed: %s", exc)
        
        await asyncio.sleep(3600)  # 1 小时
```

### 6.2 在 Provisioning 流程中使用回滚协调器

修改 `provision_aws_node` 使用新的回滚协调器：

```python
from services.rollback_coordinator import RollbackCoordinator, RollbackPriority

def provision_aws_node(...):
    coordinator = RollbackCoordinator(logger)
    
    try:
        # 注册节点
        registered_node_result = node_registry.register_node(...)
        coordinator.register_action(
            name="Delete registered node",
            action=lambda: node_registry.delete_node(registered_node_result.xboard_node_id),
            priority=RollbackPriority.CRITICAL,
            resource_type="xboard_node",
            resource_id=str(registered_node_result.xboard_node_id),
        )
        
        # 创建 EC2 实例
        launch_result = ec2_client.launch_ipv6_instance(...)
        coordinator.register_action(
            name="Terminate EC2 instance",
            action=lambda: ec2_client.terminate_instance(launch_result.instance_id),
            priority=RollbackPriority.HIGH,
            resource_type="ec2_instance",
            resource_id=launch_result.instance_id,
            allow_failure=True,
        )
        
        # ... 其他步骤
        
    except Exception as exc:
        # 执行回滚
        report = coordinator.execute_rollback()
        if report.critical_failures:
            logger.error("Critical rollback failures: %s", report.critical_failures)
        raise
```

### 6.3 在域名分配中使用分布式锁

修改 `domain_pool_manager.py` 使用分布式锁：

```python
from services.concurrency_control import DistributedLock

def allocate_domain(self, protocol_type: str, xboard_node_id: int) -> str:
    distributed_lock = DistributedLock(self._runtime)
    
    lock_key = f"domain_pool:{protocol_type}"
    holder = f"worker-{os.getpid()}"
    
    with distributed_lock.lock(lock_key, holder, ttl_seconds=30) as acquired:
        if not acquired:
            raise DomainPoolError("Failed to acquire lock for domain allocation")
        
        # 执行域名分配逻辑
        domain = self._find_and_claim_reusable_domain(protocol_type, xboard_node_id)
        return domain
```

---

## 7. 监控指标

建议监控以下指标：

### 7.1 孤儿资源指标
- `orphan_resources_total`：孤儿资源总数
- `orphan_resources_by_type{type="ec2|dns|allocation|xboard"}`：按类型分类的孤儿资源数
- `orphan_cleanup_success_total`：成功清理的孤儿资源数
- `orphan_cleanup_failure_total`：清理失败的孤儿资源数

### 7.2 数据库同步指标
- `db_sync_inconsistency_total`：数据库不一致数量
- `db_sync_health_status{status="healthy|warning|critical"}`：同步健康状态
- `db_sync_repair_success_total`：成功修复的不一致数
- `db_sync_repair_failure_total`：修复失败的不一致数

### 7.3 并发控制指标
- `distributed_lock_acquired_total`：成功获取锁的次数
- `distributed_lock_conflict_total`：锁冲突次数
- `distributed_lock_timeout_total`：锁获取超时次数
- `optimistic_lock_conflict_total`：乐观锁冲突次数

### 7.4 回滚指标
- `rollback_executed_total`：执行回滚的次数
- `rollback_action_success_total`：成功的回滚动作数
- `rollback_action_failure_total`：失败的回滚动作数
- `rollback_critical_failure_total`：关键回滚失败次数

---

## 8. 告警规则

建议配置以下告警规则：

### 8.1 孤儿资源告警
```yaml
- alert: HighOrphanResourceCount
  expr: orphan_resources_total > 10
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "检测到大量孤儿资源"
    description: "孤儿资源数量: {{ $value }}"

- alert: CriticalOrphanResourceCount
  expr: orphan_resources_total > 50
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "检测到严重的孤儿资源泄漏"
    description: "孤儿资源数量: {{ $value }}"
```

### 8.2 数据库同步告警
```yaml
- alert: DatabaseSyncWarning
  expr: db_sync_health_status{status="warning"} == 1
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "数据库同步状态异常"

- alert: DatabaseSyncCritical
  expr: db_sync_health_status{status="critical"} == 1
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "数据库同步状态严重异常"
```

### 8.3 并发控制告警
```yaml
- alert: HighLockContentionRate
  expr: rate(distributed_lock_conflict_total[5m]) > 10
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "锁竞争率过高"
    description: "锁冲突率: {{ $value }}/s"
```

---

## 9. 总结

本次实现完成了 4 个 P0 高优先级问题的解决方案：

1. ✅ **孤儿资源自动检测和清理**：实现了完整的检测和清理机制，支持 Dry Run 和选择性清理
2. ✅ **增强双数据库同步的监控和告警**：实现了一致性检查、自动修复和 Telegram 告警
3. ✅ **完善错误处理和回滚机制**：实现了统一的回滚协调器，支持优先级和失败容忍
4. ✅ **修复并发场景下的数据一致性问题**：实现了分布式锁和乐观锁机制

**下一步建议**：
1. 在测试环境充分测试这些新功能
2. 逐步集成到现有的 Provisioning 和 Healing 流程中
3. 配置监控指标和告警规则
4. 编写运维文档和故障排查指南
