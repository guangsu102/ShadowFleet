"""
增强的健康检查服务

提供 Liveness 和 Readiness 检查
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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

            if self._runtime.sqlite_manager is None:
                raise ValueError("SQLite connection manager is not initialized")

            with self._runtime.sqlite_manager.connection() as conn:
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

            if self._runtime.db_pool is None:
                raise ValueError("PostgreSQL connection pool is not initialized")

            with self._runtime.db_pool.cursor() as cursor:
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

            from infrastructure.cloudflare.cf_client import CFClient
            cf_client = CFClient(self._runtime)

            # 尝试验证 API Token（轻量级操作）
            cf_client._request(
                method="GET",
                endpoint="/user/tokens/verify",
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
            import os

            # 检查 SQLite 数据库所在磁盘
            sqlite_path = self._runtime.config.app.sqlite_path

            # 获取目录路径
            if os.path.isfile(sqlite_path):
                disk_path = os.path.dirname(sqlite_path)
            else:
                disk_path = sqlite_path

            stat = shutil.disk_usage(disk_path)

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
