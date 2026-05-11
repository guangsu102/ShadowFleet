# 健康检查增强详细说明

## 问题分析

### 当前健康检查的问题

查看 `api/main.py:22-24`，当前的健康检查端点：

```python
@health_router.get("/api/v1/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
```

**问题**：
1. ❌ 只返回固定的 `{"status": "ok"}`，没有实际检查任何东西
2. ❌ 不检查依赖服务（Xboard PostgreSQL、Cloudflare、AWS）
3. ❌ 不检查本地资源（SQLite 数据库、磁盘空间）
4. ❌ 没有区分 **Readiness**（就绪检查）和 **Liveness**（存活检查）

### 为什么需要增强？

在生产环境中，健康检查用于：
1. **负载均衡器**：决定是否将流量路由到该实例
2. **Kubernetes/Docker**：决定是否重启容器
3. **监控系统**：判断服务是否正常运行
4. **自动恢复**：触发自动恢复机制

---

## Readiness vs Liveness 的区别

### Liveness（存活检查）
**目的**：判断应用程序是否还活着（进程是否卡死）

**检查内容**：
- 应用进程是否响应
- 是否陷入死锁
- 是否内存溢出

**失败后的动作**：**重启容器/进程**

**示例**：
```python
@app.get("/healthz")  # Kubernetes liveness probe
async def liveness():
    # 只检查应用本身是否活着
    return {"status": "alive"}
```

### Readiness（就绪检查）
**目的**：判断应用程序是否准备好接收流量

**检查内容**：
- 数据库连接是否正常
- 外部服务是否可用
- 缓存是否就绪
- 必要的配置是否加载

**失败后的动作**：**停止发送流量，但不重启**

**示例**：
```python
@app.get("/ready")  # Kubernetes readiness probe
async def readiness():
    # 检查所有依赖服务
    if not check_database():
        return {"status": "not_ready", "reason": "database_unavailable"}
    if not check_external_api():
        return {"status": "not_ready", "reason": "external_api_unavailable"}
    return {"status": "ready"}
```

---

## 增强方案

### 1. 创建增强的健康检查服务

```python
# services/health_check_service.py
"""
增强的健康检查服务

提供 Liveness 和 Readiness 检查
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


@dataclass(frozen=True)
class HealthCheckResult:
    """健康检查结果"""
    component: str  # 组件名称
    status: str  # healthy, degraded, unhealthy
    message: str | None = None
    response_time_ms: float | None = None


@dataclass(frozen=True)
class HealthStatus:
    """整体健康状态"""
    status: str  # healthy, degraded, unhealthy
    checks: list[HealthCheckResult]
    timestamp: str


class HealthCheckService:
    """健康检查服务"""

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime = runtime_context
        self._logger = runtime_context.logger.getChild("services.health_check")

    def check_liveness(self) -> HealthStatus:
        """
        存活检查 - 只检查应用本身是否活着
        
        用于 Kubernetes liveness probe
        失败时会重启容器
        """
        from datetime import datetime
        
        checks = [
            HealthCheckResult(
                component="application",
                status="healthy",
                message="Application is running",
            )
        ]
        
        return HealthStatus(
            status="healthy",
            checks=checks,
            timestamp=datetime.utcnow().isoformat(),
        )

    def check_readiness(self) -> HealthStatus:
        """
        就绪检查 - 检查所有依赖服务是否可用
        
        用于 Kubernetes readiness probe
        失败时停止发送流量，但不重启
        """
        from datetime import datetime
        
        checks: list[HealthCheckResult] = []
        
        # 1. 检查 SQLite 数据库
        checks.append(self._check_sqlite())
        
        # 2. 检查 Xboard PostgreSQL
        checks.append(self._check_xboard_postgres())
        
        # 3. 检查 Cloudflare API（如果启用）
        if self._runtime.config.cloudflare.enabled:
            checks.append(self._check_cloudflare_api())
        
        # 4. 检查磁盘空间
        checks.append(self._check_disk_space())
        
        # 确定整体状态
        unhealthy_count = sum(1 for c in checks if c.status == "unhealthy")
        degraded_count = sum(1 for c in checks if c.status == "degraded")
        
        if unhealthy_count > 0:
            overall_status = "unhealthy"
        elif degraded_count > 0:
            overall_status = "degraded"
        else:
            overall_status = "healthy"
        
        return HealthStatus(
            status=overall_status,
            checks=checks,
            timestamp=datetime.utcnow().isoformat(),
        )

    def _check_sqlite(self) -> HealthCheckResult:
        """检查 SQLite 数据库连接"""
        import time
        
        try:
            start_time = time.time()
            
            # 执行简单查询
            from database.sqlite_connection import get_sqlite_connection
            conn = get_sqlite_connection(self._runtime)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            
            response_time_ms = (time.time() - start_time) * 1000
            
            return HealthCheckResult(
                component="sqlite",
                status="healthy",
                message="SQLite connection OK",
                response_time_ms=response_time_ms,
            )
        except Exception as exc:
            self._logger.warning("SQLite health check failed: %s", exc)
            return HealthCheckResult(
                component="sqlite",
                status="unhealthy",
                message=f"SQLite connection failed: {exc}",
            )

    def _check_xboard_postgres(self) -> HealthCheckResult:
        """检查 Xboard PostgreSQL 连接"""
        import time
        
        try:
            start_time = time.time()
            
            # 执行简单查询
            from database.xboard_repo import XboardRepo
            xboard_repo = XboardRepo(self._runtime)
            
            # 尝试查询一个简单的表
            with xboard_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
            
            response_time_ms = (time.time() - start_time) * 1000
            
            # 如果响应时间过长，标记为 degraded
            if response_time_ms > 1000:  # 超过 1 秒
                return HealthCheckResult(
                    component="xboard_postgres",
                    status="degraded",
                    message=f"PostgreSQL slow response: {response_time_ms:.0f}ms",
                    response_time_ms=response_time_ms,
                )
            
            return HealthCheckResult(
                component="xboard_postgres",
                status="healthy",
                message="PostgreSQL connection OK",
                response_time_ms=response_time_ms,
            )
        except Exception as exc:
            self._logger.warning("PostgreSQL health check failed: %s", exc)
            return HealthCheckResult(
                component="xboard_postgres",
                status="unhealthy",
                message=f"PostgreSQL connection failed: {exc}",
            )

    def _check_cloudflare_api(self) -> HealthCheckResult:
        """检查 Cloudflare API 可用性"""
        import time
        
        try:
            start_time = time.time()
            
            from infrastructure.cloudflare.cf_client import CloudflareClient
            cf_client = CloudflareClient(self._runtime)
            
            # 尝试验证 API Token（轻量级操作）
            cf_client._execute_cf_call(
                operation_name="verify_token",
                func=lambda: cf_client._session.get(
                    f"{cf_client._base_url}/user/tokens/verify"
                ),
            )
            
            response_time_ms = (time.time() - start_time) * 1000
            
            if response_time_ms > 2000:  # 超过 2 秒
                return HealthCheckResult(
                    component="cloudflare_api",
                    status="degraded",
                    message=f"Cloudflare API slow response: {response_time_ms:.0f}ms",
                    response_time_ms=response_time_ms,
                )
            
            return HealthCheckResult(
                component="cloudflare_api",
                status="healthy",
                message="Cloudflare API OK",
                response_time_ms=response_time_ms,
            )
        except Exception as exc:
            self._logger.warning("Cloudflare API health check failed: %s", exc)
            return HealthCheckResult(
                component="cloudflare_api",
                status="unhealthy",
                message=f"Cloudflare API failed: {exc}",
            )

    def _check_disk_space(self) -> HealthCheckResult:
        """检查磁盘空间"""
        try:
            import shutil
            
            # 检查 SQLite 数据库所在磁盘
            sqlite_path = self._runtime.config.app.sqlite_path
            stat = shutil.disk_usage(sqlite_path)
            
            # 计算可用空间百分比
            available_percent = (stat.free / stat.total) * 100
            
            if available_percent < 5:  # 小于 5%
                return HealthCheckResult(
                    component="disk_space",
                    status="unhealthy",
                    message=f"Disk space critically low: {available_percent:.1f}% available",
                )
            elif available_percent < 10:  # 小于 10%
                return HealthCheckResult(
                    component="disk_space",
                    status="degraded",
                    message=f"Disk space low: {available_percent:.1f}% available",
                )
            
            return HealthCheckResult(
                component="disk_space",
                status="healthy",
                message=f"Disk space OK: {available_percent:.1f}% available",
            )
        except Exception as exc:
            self._logger.warning("Disk space check failed: %s", exc)
            return HealthCheckResult(
                component="disk_space",
                status="degraded",
                message=f"Disk space check failed: {exc}",
            )
```

---

### 2. 更新 API 端点

在 `api/router/health.py` 中添加：

```python
from services.health_check_service import HealthCheckService
from fastapi import Response

@router.get("/liveness")
async def liveness_check(
    ctx: RuntimeContext = Depends(get_runtime_context),
) -> dict:
    """
    存活检查 - 用于 Kubernetes liveness probe
    
    只检查应用本身是否活着，不检查依赖服务
    失败时会重启容器
    """
    health_service = HealthCheckService(ctx)
    status = health_service.check_liveness()
    
    return {
        "status": status.status,
        "timestamp": status.timestamp,
        "checks": [
            {
                "component": check.component,
                "status": check.status,
                "message": check.message,
            }
            for check in status.checks
        ],
    }


@router.get("/readiness")
async def readiness_check(
    response: Response,
    ctx: RuntimeContext = Depends(get_runtime_context),
) -> dict:
    """
    就绪检查 - 用于 Kubernetes readiness probe
    
    检查所有依赖服务是否可用
    失败时停止发送流量，但不重启
    """
    health_service = HealthCheckService(ctx)
    status = health_service.check_readiness()
    
    # 如果不健康，返回 503 状态码
    if status.status == "unhealthy":
        response.status_code = 503
    
    return {
        "status": status.status,
        "timestamp": status.timestamp,
        "checks": [
            {
                "component": check.component,
                "status": check.status,
                "message": check.message,
                "response_time_ms": check.response_time_ms,
            }
            for check in status.checks
        ],
    }
```

---

## 使用场景

### 1. Kubernetes 部署配置

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: shadowfleet
spec:
  template:
    spec:
      containers:
      - name: shadowfleet
        image: shadowfleet:latest
        ports:
        - containerPort: 8000
        
        # 存活检查 - 失败时重启容器
        livenessProbe:
          httpGet:
            path: /api/v1/health/liveness
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        
        # 就绪检查 - 失败时停止发送流量
        readinessProbe:
          httpGet:
            path: /api/v1/health/readiness
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 2
```

### 2. Docker Compose 健康检查

```yaml
# docker-compose.yml
services:
  shadowfleet:
    image: shadowfleet:latest
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health/readiness"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

---

## 测试示例

```bash
# 1. 测试存活检查
curl http://localhost:8000/api/v1/health/liveness

# 预期输出：
{
  "status": "healthy",
  "timestamp": "2026-05-10T12:00:00.000000",
  "checks": [
    {
      "component": "application",
      "status": "healthy",
      "message": "Application is running"
    }
  ]
}

# 2. 测试就绪检查
curl http://localhost:8000/api/v1/health/readiness

# 预期输出（所有服务正常）：
{
  "status": "healthy",
  "timestamp": "2026-05-10T12:00:00.000000",
  "checks": [
    {
      "component": "sqlite",
      "status": "healthy",
      "message": "SQLite connection OK",
      "response_time_ms": 5.2
    },
    {
      "component": "xboard_postgres",
      "status": "healthy",
      "message": "PostgreSQL connection OK",
      "response_time_ms": 15.8
    },
    {
      "component": "cloudflare_api",
      "status": "healthy",
      "message": "Cloudflare API OK",
      "response_time_ms": 120.5
    },
    {
      "component": "disk_space",
      "status": "healthy",
      "message": "Disk space OK: 45.2% available"
    }
  ]
}
```

---

## 总结

### 增强后的健康检查提供

1. ✅ **Liveness 检查**：判断应用是否活着
2. ✅ **Readiness 检查**：判断应用是否准备好接收流量
3. ✅ **依赖服务检查**：SQLite、PostgreSQL、Cloudflare API
4. ✅ **资源检查**：磁盘空间
5. ✅ **响应时间监控**：识别慢响应
6. ✅ **状态分级**：healthy、degraded、unhealthy
7. ✅ **Kubernetes 兼容**：支持 liveness/readiness probe

### 实现优先级

这是 **P1 高优先级**，因为：
- 对生产环境部署至关重要
- 实现相对简单（1-2 天）
- 立即提升系统可观测性
- 为自动化运维提供基础
