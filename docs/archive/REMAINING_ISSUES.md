# ShadowFleet 剩余未实现问题清单

基于 DESIGN_ISSUES_ANALYSIS.md 的全面分析，以下是当前**尚未实现或需要进一步完善**的问题。

---

## 一、架构设计层面 - 未完成项

### 1.1 ❌ 双数据库架构的根本性改进（长期）
**当前状态**：
- ✅ 已实现监控和告警（`DatabaseSyncMonitor`）
- ✅ 已实现自动修复机制
- ❌ **未实现**：统一到单一数据源（PostgreSQL）

**建议方案**：
- 将 SQLite 改为只读缓存
- 所有写操作直接到 PostgreSQL
- 使用 PostgreSQL 的 LISTEN/NOTIFY 机制实现实时同步

**优先级**：P2（长期架构优化）

---

### 1.2 ❌ 缺乏明确的事务边界和 Saga 模式
**当前状态**：
- ✅ 已实现 `RollbackCoordinator` 统一回滚
- ✅ 已实现 `ProvisioningPipeline` 步骤化流程
- ❌ **未实现**：完整的 Saga 模式或分布式事务框架

**缺失功能**：
1. 补偿事务（Compensating Transaction）的自动化
2. 事务状态持久化和恢复
3. 跨服务的事务协调器

**建议方案**：
- 引入 Saga 编排器（Orchestrator）
- 为每个步骤定义明确的补偿操作
- 持久化事务状态到数据库

**优先级**：P1（影响可维护性）

---

### 1.3 ⚠️ 域名池管理需要增强
**当前状态**：
- ✅ 已实现基本的域名分配和复用
- ✅ 已实现并发控制（`BEGIN IMMEDIATE`）
- ⚠️ **部分实现**：缺少健康检查

**缺失功能**：
1. ❌ 域名 DNS 解析健康检查
2. ❌ SSL 证书有效性检查
3. ❌ 域名预分配和预热机制
4. ❌ 使用 Redis 分布式锁替代 SQLite 锁

**建议方案**：
```python
# services/domain_health_checker.py
class DomainHealthChecker:
    def check_dns_resolution(self, domain: str) -> bool:
        """检查 DNS 是否正确解析"""
        
    def check_ssl_certificate(self, domain: str) -> bool:
        """检查 SSL 证书是否有效"""
        
    def mark_domain_unhealthy(self, domain: str, reason: str):
        """标记域名为不健康状态"""
```

**优先级**：P1（影响稳定性）

---

## 二、并发与性能问题 - 未完成项

### 2.1 ❌ SQLite 性能优化
**当前状态**：
- ✅ 已启用 WAL 模式
- ✅ 已实现并发控制（`DistributedLock`）
- ❌ **未实现**：写入队列和批量处理

**缺失功能**：
1. ❌ 写入队列（Write Queue）
2. ❌ 批量写入优化
3. ❌ 热点数据迁移到 Redis
4. ❌ 按区域/协议分片

**建议方案**：
```python
# services/write_queue_service.py
class WriteQueueService:
    """批量写入队列，减少 SQLite 锁竞争"""
    
    def enqueue_write(self, operation: WriteOperation):
        """将写操作加入队列"""
        
    def flush_batch(self):
        """批量执行写操作"""
```

**优先级**：P1（影响扩展性）

---

### 2.2 ❌ 缺乏请求限流和熔断机制
**当前状态**：
- ✅ 已实现 API 层的 `RateLimitMiddleware`
- ✅ 已实现 `TokenBucketRateLimiter`（utils/resilience.py）
- ❌ **未实现**：针对外部服务的熔断器

**缺失功能**：
1. ❌ Circuit Breaker（熔断器）
2. ❌ 请求队列和背压机制
3. ❌ 优雅降级策略

**建议方案**：
```python
# services/circuit_breaker.py
class CircuitBreaker:
    """熔断器，保护外部服务调用"""
    
    def __init__(self, failure_threshold: int, timeout_seconds: int):
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        
    def call(self, func: Callable) -> Any:
        """通过熔断器调用函数"""
        if self.state == "OPEN":
            raise CircuitBreakerOpenError()
        
        try:
            result = func()
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise
```

**应用场景**：
- Xboard API 调用
- Cloudflare API 调用
- AWS API 调用

**优先级**：P1（影响稳定性）

---

### 2.3 ⚠️ 资源泄漏风险仍存在
**当前状态**：
- ✅ 已实现孤儿资源检测（`OrphanResourceDetector`）
- ✅ 已实现孤儿资源清理（`OrphanResourceCleaner`）
- ⚠️ **部分实现**：缺少统一的资源生命周期管理

**缺失功能**：
1. ❌ 统一的资源生命周期管理器
2. ❌ 资源使用监控和告警
3. ❌ 资源配额管理

**建议方案**：
```python
# services/resource_lifecycle_manager.py
class ResourceLifecycleManager:
    """统一追踪所有资源的生命周期"""
    
    def register_resource(self, resource_type: str, resource_id: str, metadata: dict):
        """注册资源"""
        
    def mark_resource_released(self, resource_id: str):
        """标记资源已释放"""
        
    def scan_leaked_resources(self) -> list[Resource]:
        """扫描泄漏的资源"""
```

**优先级**：P1（影响成本）

---

## 三、代码质量问题 - 未完成项

### 3.1 ⚠️ 职责耦合仍需改进
**当前状态**：
- ✅ 已重构 Provisioning 流程（`ProvisioningPipeline`）
- ⚠️ **部分改进**：其他服务仍存在耦合

**需要改进的服务**：
1. `HealerService` - 自愈流程仍然复杂
2. `FleetSchedulerService` - 调度逻辑与业务逻辑混合
3. `NodeRegistryService` - 职责过多

**优先级**：P2（代码质量）

---

### 3.2 ⚠️ 错误处理策略已统一，但需要全面应用
**当前状态**：
- ✅ 已实现 `UnifiedErrorHandler`
- ⚠️ **部分应用**：旧代码仍使用旧的错误处理方式

**需要迁移的模块**：
- `provisioning_aws_flow.py`
- `healing_aws_flow.py`
- `xboard_repo.py`
- `asset_repo.py`

**优先级**：P2（代码质量）

---

### 3.3 ❌ 配置管理需要进一步改进
**当前状态**：
- ✅ 已使用 Pydantic 进行验证
- ❌ **未实现**：配置中心和完整的热加载

**缺失功能**：
1. ❌ 配置中心（Consul/etcd）
2. ❌ 配置变更通知机制
3. ❌ 配置版本管理
4. ❌ 配置审计日志

**优先级**：P2（运维效率）

---

### 3.4 ❌ 日志和监控不足
**当前状态**：
- ✅ 已有结构化日志
- ✅ 已有 correlation_id 追踪
- ❌ **未实现**：分布式追踪（OpenTelemetry）
- ❌ **未实现**：关键指标监控（Prometheus）

**缺失功能**：
1. ❌ OpenTelemetry 集成
2. ❌ Prometheus 指标导出
3. ❌ 日志级别动态调整
4. ❌ 慢查询日志

**建议方案**：
```python
# utils/telemetry.py
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider

def setup_telemetry():
    """初始化 OpenTelemetry"""
    provider = TracerProvider()
    processor = BatchSpanProcessor(OTLPSpanExporter())
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
```

**优先级**：P1（可观测性）

---

## 四、安全性问题 - 未完成项

### 4.1 ❌ 敏感信息加密存储
**当前状态**：
- ❌ AWS 凭证、SSH 密钥等敏感信息**未加密**存储在 SQLite 中
- ❌ 日志中可能包含敏感信息
- ❌ 错误信息中可能暴露内部实现细节

**缺失功能**：
1. ❌ 敏感数据加密存储（使用 Fernet 或 AES）
2. ❌ 日志脱敏机制
3. ❌ 错误信息过滤

**建议方案**：
```python
# utils/encryption.py
from cryptography.fernet import Fernet

class SecretManager:
    """敏感信息加密管理"""
    
    def __init__(self, encryption_key: str):
        self._cipher = Fernet(encryption_key.encode())
        
    def encrypt(self, plaintext: str) -> str:
        """加密"""
        return self._cipher.encrypt(plaintext.encode()).decode()
        
    def decrypt(self, ciphertext: str) -> str:
        """解密"""
        return self._cipher.decrypt(ciphertext.encode()).decode()
```

**优先级**：P0（安全风险）

---

### 4.2 ❌ 权限控制不足
**当前状态**：
- ✅ 已有基本的 JWT 认证
- ✅ 已有角色区分（admin, operator, viewer）
- ❌ **未实现**：细粒度的 RBAC 权限控制
- ❌ **未实现**：操作审计日志

**缺失功能**：
1. ❌ RBAC 权限模型
2. ❌ 操作审计日志
3. ❌ 危险操作二次确认

**建议方案**：
```python
# services/audit_logger.py
class AuditLogger:
    """操作审计日志"""
    
    def log_operation(
        self,
        user_id: int,
        operation: str,
        resource_type: str,
        resource_id: str,
        result: str,
        details: dict,
    ):
        """记录操作审计"""
```

**优先级**：P1（安全合规）

---

### 4.3 ⚠️ 输入验证需要增强
**当前状态**：
- ✅ 已使用 Pydantic 进行基本验证
- ⚠️ **部分实现**：缺少业务层面的验证

**需要增强的验证**：
1. 节点名称格式验证（DNS 兼容）
2. 参数组合合法性验证
3. 资源配额验证

**优先级**：P1（稳定性）

---

## 五、可扩展性问题 - 未完成项

### 5.1 ❌ 单实例部署限制
**当前状态**：
- ❌ 由于 SQLite 限制，无法水平扩展
- ❌ Daemon 进程是单点
- ❌ 没有高可用方案

**缺失功能**：
1. ❌ 多实例部署支持
2. ❌ Daemon 主备切换
3. ❌ 负载均衡

**建议方案**：
- 迁移到 PostgreSQL
- 使用 Redis 实现分布式锁
- 使用 Consul 实现服务发现和主备选举

**优先级**：P2（长期架构）

---

### 5.2 ❌ 协议扩展性差
**当前状态**：
- ❌ 新增协议需要修改多处代码
- ❌ 协议配置逻辑分散
- ❌ 缺乏协议插件化机制

**缺失功能**：
1. ❌ 协议插件化架构
2. ❌ 协议配置抽象接口
3. ❌ 配置驱动的协议管理

**建议方案**：
```python
# services/protocol_plugin.py
class ProtocolPlugin(ABC):
    """协议插件接口"""
    
    @abstractmethod
    def get_protocol_type(self) -> str:
        """返回协议类型"""
        
    @abstractmethod
    def build_config(self, node: FleetNodeRecord) -> dict:
        """构建协议配置"""
        
    @abstractmethod
    def generate_node_id(self, node: FleetNodeRecord) -> str:
        """生成节点 ID"""
```

**优先级**：P2（扩展性）

---

### 5.3 ❌ 缺乏多云支持
**当前状态**：
- ❌ 只实现了 AWS
- ❌ 云厂商特定逻辑耦合在核心流程中

**缺失功能**：
1. ❌ 统一的云资源抽象层
2. ❌ 云厂商适配器模式
3. ❌ 多云混合部署

**优先级**：P2（扩展性）

---

## 六、测试覆盖不足 - 未完成项

### 6.1 ❌ 单元测试覆盖率低
**当前状态**：
- ✅ 已有部分单元测试（tests/unit/）
- ❌ **覆盖率不足**：核心业务逻辑缺乏测试

**缺失测试**：
1. ❌ Provisioning Pipeline 步骤测试
2. ❌ 错误处理和回滚测试
3. ❌ 并发控制测试
4. ❌ 域名池管理测试

**目标**：覆盖率 80%+

**优先级**：P1（代码质量）

---

### 6.2 ❌ 集成测试不完整
**当前状态**：
- ✅ 已有部分集成测试（tests/integration/）
- ❌ **不完整**：缺少端到端测试

**缺失测试**：
1. ❌ 完整的 Provisioning 流程测试
2. ❌ 异常场景测试（网络故障、超时）
3. ❌ 并发场景测试
4. ❌ 数据库同步测试

**优先级**：P1（稳定性）

---

### 6.3 ❌ 缺乏性能测试
**当前状态**：
- ❌ 没有性能基准测试
- ❌ 不清楚系统的性能瓶颈和容量上限

**缺失测试**：
1. ❌ 性能基准测试
2. ❌ 压力测试
3. ❌ 性能回归检测

**优先级**：P2（性能优化）

---

## 七、运维和可观测性问题 - 未完成项

### 7.1 ⚠️ 健康检查机制需要增强
**当前状态**：
- ✅ 已有 `/api/v1/health` 端点
- ✅ 已实现 `SystemHealthMonitor`
- ⚠️ **部分实现**：缺少依赖服务检查

**需要增强**：
1. ❌ 检查 Xboard 连接状态
2. ❌ 检查 Cloudflare API 可用性
3. ❌ 检查 AWS API 可用性
4. ❌ 区分 Readiness 和 Liveness

**优先级**：P1（可观测性）

---

### 7.2 ❌ 缺乏运维工具
**当前状态**：
- ❌ 没有数据备份和恢复机制
- ❌ 缺乏数据迁移工具
- ❌ 没有运维脚本

**缺失工具**：
1. ❌ 自动化备份脚本
2. ❌ 数据迁移工具
3. ❌ 批量操作脚本
4. ❌ 数据修复工具

**建议方案**：
```bash
# scripts/backup_sqlite.sh
#!/bin/bash
# 备份 SQLite 数据库

# scripts/restore_sqlite.sh
#!/bin/bash
# 恢复 SQLite 数据库

# scripts/migrate_data.py
# 数据迁移工具
```

**优先级**：P1（运维效率）

---

### 7.3 ⚠️ 告警机制需要完善
**当前状态**：
- ✅ 已有 Telegram 通知
- ⚠️ **部分实现**：告警规则简单

**需要完善**：
1. ❌ 告警分级（P0/P1/P2）
2. ❌ 告警聚合和去重
3. ❌ 告警静默和抑制
4. ❌ 告警升级机制

**优先级**：P1（运维效率）

---

## 八、优先级总结

### 🔴 P0 - 安全风险（立即处理）
1. ❌ **敏感信息加密存储**（4.1）
   - AWS 凭证、SSH 密钥等需要加密

### 🟠 P1 - 高优先级（近期处理）
1. ⚠️ **域名健康检查**（1.3）
2. ❌ **SQLite 写入队列优化**（2.1）
3. ❌ **熔断器实现**（2.2）
4. ⚠️ **资源生命周期管理**（2.3）
5. ❌ **OpenTelemetry 集成**（3.4）
6. ❌ **操作审计日志**（4.2）
7. ⚠️ **输入验证增强**（4.3）
8. ❌ **单元测试补充**（6.1）
9. ❌ **集成测试补充**（6.2）
10. ⚠️ **健康检查增强**（7.1）
11. ❌ **运维工具开发**（7.2）
12. ⚠️ **告警机制完善**（7.3）

### 🟡 P2 - 中优先级（中期规划）
1. ⚠️ **代码重构**（3.1）
2. ⚠️ **错误处理迁移**（3.2）
3. ❌ **配置中心**（3.3）
4. ❌ **协议插件化**（5.2）
5. ❌ **多云支持**（5.3）
6. ❌ **性能测试**（6.3）

### 🔵 P3 - 低优先级（长期规划）
1. ❌ **统一到 PostgreSQL**（1.1）
2. ❌ **Saga 模式**（1.2）
3. ❌ **多实例部署**（5.1）

---

## 九、快速行动建议

### 本周可以完成的任务
1. ✅ 实现敏感信息加密存储（SecretManager）
2. ✅ 实现熔断器（CircuitBreaker）
3. ✅ 增强健康检查（检查依赖服务）
4. ✅ 实现操作审计日志（AuditLogger）

### 本月可以完成的任务
1. ✅ 域名健康检查机制
2. ✅ SQLite 写入队列优化
3. ✅ 补充核心模块的单元测试
4. ✅ 开发基本的运维工具（备份/恢复）
5. ✅ OpenTelemetry 基础集成

---

**文档版本**: 1.0  
**最后更新**: 2026-05-10  
**下次审查**: 2026-06-10
