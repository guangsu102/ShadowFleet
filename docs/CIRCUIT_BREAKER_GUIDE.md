# 熔断器（Circuit Breaker）实现指南

## 问题分析

### 为什么需要熔断器？

当外部服务（Xboard PostgreSQL、Cloudflare API、AWS API）出现故障或响应缓慢时：

**没有熔断器的情况**：
1. 请求持续发送到故障服务
2. 大量请求超时，占用线程/连接
3. 系统资源耗尽
4. 级联故障，整个系统崩溃 ⚠️

**有熔断器的情况**：
1. 检测到故障后，快速失败（fail-fast）
2. 停止发送请求到故障服务
3. 定期尝试恢复（half-open 状态）
4. 保护系统其他部分正常运行 ✅

---

## 熔断器工作原理

### 三种状态

```
         失败次数超过阈值
    CLOSED ──────────────> OPEN
      ↑                      │
      │                      │ 超时后
      │                      ↓
      └────────────── HALF_OPEN
           成功请求
```

#### 1. CLOSED（关闭状态）
- **正常状态**，请求正常通过
- 记录失败次数
- 失败次数超过阈值 → 转为 OPEN

#### 2. OPEN（打开状态）
- **熔断状态**，直接拒绝请求（快速失败）
- 不发送请求到后端服务
- 等待超时时间后 → 转为 HALF_OPEN

#### 3. HALF_OPEN（半开状态）
- **试探状态**，允许少量请求通过
- 如果请求成功 → 转为 CLOSED
- 如果请求失败 → 转回 OPEN

---

## 实现方案

### 1. 创建熔断器服务

```python
# services/circuit_breaker.py
"""
熔断器（Circuit Breaker）实现

保护外部服务调用，防止级联故障
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

T = TypeVar("T")


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"        # 关闭状态，正常通过
    OPEN = "open"            # 打开状态，快速失败
    HALF_OPEN = "half_open"  # 半开状态，试探恢复


@dataclass
class CircuitBreakerConfig:
    """熔断器配置"""
    failure_threshold: int = 5           # 失败阈值（连续失败次数）
    success_threshold: int = 2           # 成功阈值（半开状态需要的成功次数）
    timeout_seconds: int = 60            # 打开状态超时时间（秒）
    half_open_max_calls: int = 3         # 半开状态允许的最大请求数


class CircuitBreakerError(RuntimeError):
    """熔断器错误"""
    pass


class CircuitBreakerOpenError(CircuitBreakerError):
    """熔断器打开错误（快速失败）"""
    pass


class CircuitBreaker:
    """
    熔断器实现
    
    使用示例：
    ```python
    breaker = CircuitBreaker(
        name="xboard_api",
        failure_threshold=5,
        timeout_seconds=60,
    )
    
    try:
        result = breaker.call(lambda: xboard_repo.get_node(node_id))
    except CircuitBreakerOpenError:
        # 熔断器打开，快速失败
        logger.warning("Circuit breaker is open, using fallback")
        result = fallback_value
    ```
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout_seconds: int = 60,
        half_open_max_calls: int = 3,
    ) -> None:
        self.name = name
        self.config = CircuitBreakerConfig(
            failure_threshold=failure_threshold,
            success_threshold=success_threshold,
            timeout_seconds=timeout_seconds,
            half_open_max_calls=half_open_max_calls,
        )
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """获取当前状态"""
        with self._lock:
            return self._state

    def call(self, func: Callable[[], T]) -> T:
        """
        通过熔断器调用函数
        
        Args:
            func: 要调用的函数
            
        Returns:
            函数返回值
            
        Raises:
            CircuitBreakerOpenError: 熔断器打开，快速失败
            Exception: 函数执行失败
        """
        with self._lock:
            current_state = self._state
            
            # 1. 检查是否需要从 OPEN 转为 HALF_OPEN
            if current_state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    current_state = CircuitState.HALF_OPEN
                else:
                    # 仍然是 OPEN 状态，快速失败
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self.name}' is OPEN"
                    )
            
            # 2. HALF_OPEN 状态，限制请求数
            if current_state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self.name}' is HALF_OPEN, max calls reached"
                    )
                self._half_open_calls += 1
        
        # 3. 执行函数调用（在锁外执行，避免阻塞）
        try:
            result = func()
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        """处理成功调用"""
        with self._lock:
            self._failure_count = 0
            
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                
                # 成功次数达到阈值，转为 CLOSED
                if self._success_count >= self.config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._success_count = 0
                    self._half_open_calls = 0

    def _on_failure(self) -> None:
        """处理失败调用"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._state == CircuitState.HALF_OPEN:
                # 半开状态失败，立即转回 OPEN
                self._state = CircuitState.OPEN
                self._success_count = 0
                self._half_open_calls = 0
            elif self._state == CircuitState.CLOSED:
                # 关闭状态，检查是否达到失败阈值
                if self._failure_count >= self.config.failure_threshold:
                    self._state = CircuitState.OPEN

    def _should_attempt_reset(self) -> bool:
        """判断是否应该尝试重置（从 OPEN 转为 HALF_OPEN）"""
        if self._last_failure_time is None:
            return False
        
        elapsed = time.time() - self._last_failure_time
        return elapsed >= self.config.timeout_seconds

    def reset(self) -> None:
        """手动重置熔断器"""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            self._last_failure_time = None

    def get_stats(self) -> dict:
        """获取统计信息"""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "half_open_calls": self._half_open_calls,
                "last_failure_time": self._last_failure_time,
            }


class CircuitBreakerRegistry:
    """
    熔断器注册表
    
    管理所有熔断器实例
    """

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def get_or_create(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout_seconds: int = 60,
    ) -> CircuitBreaker:
        """获取或创建熔断器"""
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(
                    name=name,
                    failure_threshold=failure_threshold,
                    timeout_seconds=timeout_seconds,
                )
            return self._breakers[name]

    def get_all_stats(self) -> list[dict]:
        """获取所有熔断器的统计信息"""
        with self._lock:
            return [breaker.get_stats() for breaker in self._breakers.values()]

    def reset_all(self) -> None:
        """重置所有熔断器"""
        with self._lock:
            for breaker in self._breakers.values():
                breaker.reset()


# 全局熔断器注册表
_global_registry = CircuitBreakerRegistry()


def get_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    timeout_seconds: int = 60,
) -> CircuitBreaker:
    """获取全局熔断器实例"""
    return _global_registry.get_or_create(name, failure_threshold, timeout_seconds)
```

---

### 2. 集成到 XboardRepo

```python
# database/xboard_repo.py

from services.circuit_breaker import get_circuit_breaker, CircuitBreakerOpenError

class XboardRepo:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        # ... 现有代码
        self._circuit_breaker = get_circuit_breaker(
            name="xboard_postgres",
            failure_threshold=5,
            timeout_seconds=60,
        )

    def get_node_by_id(self, node_id: int) -> XboardNodeRecord | None:
        """获取节点（带熔断器保护）"""
        try:
            return self._circuit_breaker.call(
                lambda: self._get_node_by_id_impl(node_id)
            )
        except CircuitBreakerOpenError:
            self._logger.warning(
                "Circuit breaker is open for Xboard PostgreSQL, using fallback"
            )
            # 返回 None 或使用缓存
            return None

    def _get_node_by_id_impl(self, node_id: int) -> XboardNodeRecord | None:
        """实际的查询实现"""
        # 原有的查询逻辑
        with self._get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM v2_server_shadowsocks WHERE id = %s",
                    (node_id,)
                )
                row = cursor.fetchone()
                if row:
                    return self._map_row_to_record(row)
                return None
```

---

### 3. 集成到 CloudflareClient

```python
# infrastructure/cloudflare/cf_client.py

from services.circuit_breaker import get_circuit_breaker, CircuitBreakerOpenError

class CloudflareClient:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        # ... 现有代码
        self._circuit_breaker = get_circuit_breaker(
            name="cloudflare_api",
            failure_threshold=3,  # Cloudflare API 更敏感
            timeout_seconds=120,  # 更长的恢复时间
        )

    def create_dns_record(
        self,
        name: str,
        record_type: str,
        content: str,
        proxied: bool = False,
    ) -> str:
        """创建 DNS 记录（带熔断器保护）"""
        try:
            return self._circuit_breaker.call(
                lambda: self._create_dns_record_impl(name, record_type, content, proxied)
            )
        except CircuitBreakerOpenError:
            self._logger.error(
                "Circuit breaker is open for Cloudflare API, cannot create DNS record"
            )
            raise CloudflareClientError("Cloudflare API is unavailable (circuit breaker open)")

    def _create_dns_record_impl(
        self,
        name: str,
        record_type: str,
        content: str,
        proxied: bool,
    ) -> str:
        """实际的创建实现"""
        # 原有的创建逻辑
        response = self._execute_cf_call(
            operation_name="create_dns_record",
            func=lambda: self._session.post(
                f"{self._base_url}/zones/{self._zone_id}/dns_records",
                json={
                    "type": record_type,
                    "name": name,
                    "content": content,
                    "proxied": proxied,
                },
            ),
        )
        return response["result"]["id"]
```

---

### 4. 集成到 EC2Client

```python
# infrastructure/aws/ec2_client.py

from services.circuit_breaker import get_circuit_breaker, CircuitBreakerOpenError

class EC2Client:
    def __init__(
        self,
        runtime_context: RuntimeContext,
        aws_credential: AwsCredentials,
    ) -> None:
        # ... 现有代码
        self._circuit_breaker = get_circuit_breaker(
            name=f"aws_ec2_{aws_credential.region}",
            failure_threshold=5,
            timeout_seconds=90,
        )

    def launch_ipv6_instance(self, **kwargs) -> LaunchResult:
        """启动实例（带熔断器保护）"""
        try:
            return self._circuit_breaker.call(
                lambda: self._launch_ipv6_instance_impl(**kwargs)
            )
        except CircuitBreakerOpenError:
            self._logger.error(
                "Circuit breaker is open for AWS EC2 API, cannot launch instance"
            )
            raise EC2ClientError("AWS EC2 API is unavailable (circuit breaker open)")

    def _launch_ipv6_instance_impl(self, **kwargs) -> LaunchResult:
        """实际的启动实现"""
        # 原有的启动逻辑
        response = self._execute_ec2_call(
            operation_name="run_instances",
            func=lambda: self._ec2_client.run_instances(**kwargs),
        )
        # ...
```

---

### 5. 添加监控端点

```python
# api/router/health.py

@router.get("/circuit-breakers")
async def get_circuit_breakers_status(
    _current_user: None = Depends(get_current_user),
) -> dict:
    """获取所有熔断器状态"""
    from services.circuit_breaker import _global_registry
    
    stats = _global_registry.get_all_stats()
    
    return {
        "circuit_breakers": stats,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/circuit-breakers/{name}/reset")
async def reset_circuit_breaker(
    name: str,
    _current_user: None = Depends(require_operator),
) -> dict:
    """手动重置熔断器"""
    from services.circuit_breaker import _global_registry
    
    breaker = _global_registry.get_or_create(name)
    breaker.reset()
    
    return {
        "message": f"Circuit breaker '{name}' has been reset",
        "timestamp": datetime.utcnow().isoformat(),
    }
```

---

## 使用示例

### 1. 查看熔断器状态

```bash
curl http://localhost:8000/api/v1/health/circuit-breakers \
  -H "Authorization: Bearer <token>"

# 输出：
{
  "circuit_breakers": [
    {
      "name": "xboard_postgres",
      "state": "closed",
      "failure_count": 0,
      "success_count": 0,
      "half_open_calls": 0,
      "last_failure_time": null
    },
    {
      "name": "cloudflare_api",
      "state": "open",
      "failure_count": 5,
      "success_count": 0,
      "half_open_calls": 0,
      "last_failure_time": 1715342400.0
    },
    {
      "name": "aws_ec2_us-east-1",
      "state": "half_open",
      "failure_count": 0,
      "success_count": 1,
      "half_open_calls": 2,
      "last_failure_time": 1715342300.0
    }
  ],
  "timestamp": "2026-05-10T12:00:00.000000"
}
```

### 2. 手动重置熔断器

```bash
curl -X POST http://localhost:8000/api/v1/health/circuit-breakers/cloudflare_api/reset \
  -H "Authorization: Bearer <token>"

# 输出：
{
  "message": "Circuit breaker 'cloudflare_api' has been reset",
  "timestamp": "2026-05-10T12:00:00.000000"
}
```

---

## 优雅降级策略

### 1. Xboard PostgreSQL 故障

```python
def get_node_by_id(self, node_id: int) -> XboardNodeRecord | None:
    try:
        return self._circuit_breaker.call(
            lambda: self._get_node_by_id_impl(node_id)
        )
    except CircuitBreakerOpenError:
        # 降级：从 SQLite 缓存读取
        from database.state_repo import StateRepo
        state_repo = StateRepo(self._runtime)
        node = state_repo.get_node_by_xboard_node_id(node_id)
        
        if node:
            self._logger.info("Using SQLite cache for node %d", node_id)
            return self._convert_to_xboard_record(node)
        
        return None
```

### 2. Cloudflare API 故障

```python
def create_dns_record(self, name: str, ...) -> str:
    try:
        return self._circuit_breaker.call(
            lambda: self._create_dns_record_impl(name, ...)
        )
    except CircuitBreakerOpenError:
        # 降级：记录到队列，稍后重试
        self._enqueue_dns_operation("create", name, ...)
        
        # 返回临时 ID
        return f"pending-{uuid.uuid4()}"
```

### 3. AWS API 故障

```python
def launch_ipv6_instance(self, **kwargs) -> LaunchResult:
    try:
        return self._circuit_breaker.call(
            lambda: self._launch_ipv6_instance_impl(**kwargs)
        )
    except CircuitBreakerOpenError:
        # 降级：尝试其他区域
        alternative_region = self._get_alternative_region()
        if alternative_region:
            self._logger.warning(
                "AWS API unavailable in %s, trying %s",
                self._region,
                alternative_region,
            )
            # 使用备用区域的客户端
            # ...
        
        raise EC2ClientError("AWS EC2 API is unavailable in all regions")
```

---

## 监控和告警

### Prometheus 指标

```python
from prometheus_client import Counter, Gauge

# 熔断器状态指标
circuit_breaker_state = Gauge(
    'shadowfleet_circuit_breaker_state',
    'Circuit breaker state (0=closed, 1=half_open, 2=open)',
    ['name']
)

# 熔断器打开次数
circuit_breaker_opened_total = Counter(
    'shadowfleet_circuit_breaker_opened_total',
    'Total number of times circuit breaker opened',
    ['name']
)

# 在熔断器状态变化时更新指标
def _on_failure(self) -> None:
    # ... 现有逻辑
    
    if self._state == CircuitState.OPEN:
        circuit_breaker_opened_total.labels(name=self.name).inc()
        circuit_breaker_state.labels(name=self.name).set(2)
```

### 告警规则

```yaml
# Prometheus 告警规则
- alert: CircuitBreakerOpen
  expr: shadowfleet_circuit_breaker_state == 2
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "熔断器打开"
    description: "熔断器 {{ $labels.name }} 已打开超过 5 分钟"
```

---

## 总结

### 实现的功能

1. ✅ **三种状态**：CLOSED、OPEN、HALF_OPEN
2. ✅ **自动恢复**：超时后自动尝试恢复
3. ✅ **快速失败**：熔断器打开时立即失败
4. ✅ **线程安全**：支持并发调用
5. ✅ **统计信息**：记录失败次数、状态等
6. ✅ **手动控制**：支持手动重置
7. ✅ **优雅降级**：提供降级策略

### 优先级

**P1 高优先级**，因为：
- 防止级联故障
- 提高系统稳定性
- 实现相对简单（2-3 天）
- 立即提升系统可靠性
