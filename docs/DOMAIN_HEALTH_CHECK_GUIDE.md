# 域名健康检查实现指南

## 问题分析

### 当前域名管理的问题

查看 `services/domain_pool_manager.py`，当前的域名管理：

**问题**：
1. ❌ 域名分配后不检查 DNS 是否正确解析
2. ❌ 不检查 SSL 证书是否有效
3. ❌ 域名可能在 Cloudflare 中被手动删除，但 SQLite 中仍标记为可用
4. ❌ 域名复用时不验证域名是否真正可用

**影响**：
- 节点使用不可用的域名，导致用户无法连接
- SSL 证书过期导致连接失败
- 浪费时间在无效域名上

---

## 解决方案

### 1. 创建域名健康检查服务

```python
# services/domain_health_checker.py
"""
域名健康检查服务

检查域名的 DNS 解析和 SSL 证书有效性
"""

from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


@dataclass(frozen=True)
class DomainHealthResult:
    """域名健康检查结果"""
    domain: str
    is_healthy: bool
    dns_resolves: bool
    dns_ip: str | None
    ssl_valid: bool
    ssl_expires_at: str | None
    ssl_days_remaining: int | None
    error_message: str | None
    checked_at: str


class DomainHealthChecker:
    """域名健康检查器"""

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime = runtime_context
        self._logger = runtime_context.logger.getChild("services.domain_health_checker")

    def check_domain_health(self, domain: str) -> DomainHealthResult:
        """
        检查域名健康状态
        
        Args:
            domain: 域名（例如：sf-node1.rensw.xyz）
            
        Returns:
            域名健康检查结果
        """
        checked_at = datetime.utcnow().isoformat()
        
        # 1. 检查 DNS 解析
        dns_resolves, dns_ip, dns_error = self._check_dns_resolution(domain)
        
        # 2. 检查 SSL 证书（只有 DNS 解析成功才检查）
        ssl_valid = False
        ssl_expires_at = None
        ssl_days_remaining = None
        ssl_error = None
        
        if dns_resolves:
            ssl_valid, ssl_expires_at, ssl_days_remaining, ssl_error = self._check_ssl_certificate(domain)
        
        # 3. 确定整体健康状态
        is_healthy = dns_resolves and ssl_valid
        
        # 4. 构建错误消息
        error_message = None
        if not dns_resolves:
            error_message = f"DNS resolution failed: {dns_error}"
        elif not ssl_valid:
            error_message = f"SSL certificate invalid: {ssl_error}"
        
        return DomainHealthResult(
            domain=domain,
            is_healthy=is_healthy,
            dns_resolves=dns_resolves,
            dns_ip=dns_ip,
            ssl_valid=ssl_valid,
            ssl_expires_at=ssl_expires_at,
            ssl_days_remaining=ssl_days_remaining,
            error_message=error_message,
            checked_at=checked_at,
        )

    def _check_dns_resolution(self, domain: str) -> tuple[bool, str | None, str | None]:
        """
        检查 DNS 解析
        
        Returns:
            (是否解析成功, IP 地址, 错误消息)
        """
        try:
            # 解析域名
            ip_address = socket.gethostbyname(domain)
            self._logger.debug("DNS resolution successful: %s -> %s", domain, ip_address)
            return True, ip_address, None
        except socket.gaierror as exc:
            self._logger.warning("DNS resolution failed for %s: %s", domain, exc)
            return False, None, str(exc)
        except Exception as exc:
            self._logger.warning("DNS resolution error for %s: %s", domain, exc)
            return False, None, str(exc)

    def _check_ssl_certificate(
        self,
        domain: str,
        port: int = 443,
        timeout: int = 10,
    ) -> tuple[bool, str | None, int | None, str | None]:
        """
        检查 SSL 证书有效性
        
        Returns:
            (是否有效, 过期时间, 剩余天数, 错误消息)
        """
        try:
            # 创建 SSL 上下文
            context = ssl.create_default_context()
            
            # 连接到服务器并获取证书
            with socket.create_connection((domain, port), timeout=timeout) as sock:
                with context.wrap_socket(sock, server_hostname=domain) as ssock:
                    # 获取证书信息
                    cert = ssock.getpeercert()
                    
                    # 解析过期时间
                    not_after = cert.get("notAfter")
                    if not not_after:
                        return False, None, None, "Certificate has no expiration date"
                    
                    # 转换为 datetime
                    # notAfter 格式: 'May 10 12:00:00 2027 GMT'
                    expires_at = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
                    
                    # 计算剩余天数
                    now = datetime.utcnow()
                    days_remaining = (expires_at - now).days
                    
                    # 判断是否有效
                    if days_remaining < 0:
                        return False, expires_at.isoformat(), days_remaining, "Certificate expired"
                    elif days_remaining < 7:
                        # 少于 7 天，标记为即将过期
                        self._logger.warning(
                            "SSL certificate for %s expires soon: %d days remaining",
                            domain,
                            days_remaining,
                        )
                        return False, expires_at.isoformat(), days_remaining, f"Certificate expires in {days_remaining} days"
                    
                    self._logger.debug(
                        "SSL certificate valid for %s: %d days remaining",
                        domain,
                        days_remaining,
                    )
                    return True, expires_at.isoformat(), days_remaining, None
                    
        except ssl.SSLError as exc:
            self._logger.warning("SSL certificate error for %s: %s", domain, exc)
            return False, None, None, f"SSL error: {exc}"
        except socket.timeout:
            self._logger.warning("SSL certificate check timeout for %s", domain)
            return False, None, None, "Connection timeout"
        except Exception as exc:
            self._logger.warning("SSL certificate check failed for %s: %s", domain, exc)
            return False, None, None, str(exc)

    def check_domain_in_cloudflare(self, domain: str) -> bool:
        """
        检查域名是否在 Cloudflare 中存在
        
        Args:
            domain: 域名
            
        Returns:
            是否存在
        """
        try:
            from infrastructure.cloudflare.cf_client import CloudflareClient
            
            cf_client = CloudflareClient(self._runtime)
            
            # 查询 DNS 记录
            records = cf_client.list_dns_records(name=domain)
            
            return len(records) > 0
            
        except Exception as exc:
            self._logger.warning("Failed to check domain in Cloudflare: %s", exc)
            return False

    def batch_check_domains(self, domains: list[str]) -> list[DomainHealthResult]:
        """
        批量检查域名健康状态
        
        Args:
            domains: 域名列表
            
        Returns:
            健康检查结果列表
        """
        results: list[DomainHealthResult] = []
        
        for domain in domains:
            try:
                result = self.check_domain_health(domain)
                results.append(result)
            except Exception as exc:
                self._logger.exception("Failed to check domain %s: %s", domain, exc)
                # 添加失败结果
                results.append(
                    DomainHealthResult(
                        domain=domain,
                        is_healthy=False,
                        dns_resolves=False,
                        dns_ip=None,
                        ssl_valid=False,
                        ssl_expires_at=None,
                        ssl_days_remaining=None,
                        error_message=str(exc),
                        checked_at=datetime.utcnow().isoformat(),
                    )
                )
        
        return results
```

---

### 2. 集成到域名分配流程

修改 `services/domain_pool_manager.py`：

```python
# services/domain_pool_manager.py

from services.domain_health_checker import DomainHealthChecker

class DomainPoolManager:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        # ... 现有代码
        self._health_checker = DomainHealthChecker(runtime_context)

    def allocate_domain(
        self,
        protocol_type: str,
        xboard_node_id: int,
        verify_health: bool = True,  # 新增参数
    ) -> str:
        """
        分配域名
        
        Args:
            protocol_type: 协议类型
            xboard_node_id: Xboard 节点 ID
            verify_health: 是否验证域名健康（默认 True）
        """
        # ... 现有的域名分配逻辑
        
        domain = self._find_and_claim_reusable_domain(protocol_type, xboard_node_id)
        
        # 如果启用健康检查，验证域名
        if verify_health and domain:
            health_result = self._health_checker.check_domain_health(domain)
            
            if not health_result.is_healthy:
                self._logger.warning(
                    "Allocated domain %s is unhealthy: %s",
                    domain,
                    health_result.error_message,
                )
                
                # 标记域名为不健康
                self._mark_domain_unhealthy(domain, health_result.error_message)
                
                # 重新分配
                return self.allocate_domain(protocol_type, xboard_node_id, verify_health=True)
        
        return domain

    def _mark_domain_unhealthy(self, domain: str, reason: str | None) -> None:
        """标记域名为不健康状态"""
        # 可以在 SQLite 中添加一个 health_status 字段
        # 或者记录到单独的健康检查表
        self._logger.warning("Marking domain %s as unhealthy: %s", domain, reason)
```

---

### 3. 添加定期健康检查任务

```python
# services/domain_health_scan_service.py
"""
域名健康扫描服务

定期扫描所有活跃域名的健康状态
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from services.domain_health_checker import DomainHealthChecker
from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


class DomainHealthScanService:
    """域名健康扫描服务"""

    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime = runtime_context
        self._logger = runtime_context.logger.getChild("services.domain_health_scan")
        self._health_checker = DomainHealthChecker(runtime_context)

    def scan_all_active_domains(self) -> dict[str, int]:
        """
        扫描所有活跃域名的健康状态
        
        Returns:
            统计信息 {healthy: int, unhealthy: int, total: int}
        """
        set_event_type("domain_health_scan_started")
        self._logger.info("Starting domain health scan")
        
        try:
            # 1. 获取所有活跃节点的域名
            from database.state_repo import StateRepo
            state_repo = StateRepo(self._runtime)
            
            active_nodes = state_repo.list_active_nodes()
            domains = [node.domain_name for node in active_nodes if node.domain_name]
            
            if not domains:
                self._logger.info("No active domains to scan")
                return {"healthy": 0, "unhealthy": 0, "total": 0}
            
            # 2. 批量检查域名健康
            results = self._health_checker.batch_check_domains(domains)
            
            # 3. 统计结果
            healthy_count = sum(1 for r in results if r.is_healthy)
            unhealthy_count = sum(1 for r in results if not r.is_healthy)
            
            # 4. 记录不健康的域名
            for result in results:
                if not result.is_healthy:
                    self._logger.warning(
                        "Unhealthy domain detected: %s - %s",
                        result.domain,
                        result.error_message,
                    )
                    
                    # 发送告警
                    self._send_unhealthy_domain_alert(result)
            
            # 5. 记录统计
            set_event_type("domain_health_scan_completed")
            self._logger.info(
                "Domain health scan completed: total=%d, healthy=%d, unhealthy=%d",
                len(results),
                healthy_count,
                unhealthy_count,
            )
            
            return {
                "healthy": healthy_count,
                "unhealthy": unhealthy_count,
                "total": len(results),
            }
            
        except Exception as exc:
            set_event_type("domain_health_scan_failed")
            self._logger.exception("Domain health scan failed: %s", exc)
            raise

    def _send_unhealthy_domain_alert(self, result) -> None:
        """发送不健康域名告警"""
        try:
            from services.provisioning_notifier import notify_alert
            
            notify_alert(
                runtime_context=self._runtime,
                title="域名健康检查告警",
                message=(
                    f"域名: {result.domain}\n"
                    f"状态: 不健康\n"
                    f"DNS 解析: {'成功' if result.dns_resolves else '失败'}\n"
                    f"SSL 证书: {'有效' if result.ssl_valid else '无效'}\n"
                    f"错误: {result.error_message}"
                ),
                severity="warning",
            )
        except Exception as exc:
            self._logger.warning("Failed to send unhealthy domain alert: %s", exc)
```

---

### 4. 添加 API 端点

在 `api/router/health.py` 中添加：

```python
@router.get("/domains/health")
async def check_domains_health(
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> dict:
    """检查所有活跃域名的健康状态"""
    from services.domain_health_scan_service import DomainHealthScanService
    
    scan_service = DomainHealthScanService(ctx)
    stats = scan_service.scan_all_active_domains()
    
    return {
        "total_domains": stats["total"],
        "healthy_domains": stats["healthy"],
        "unhealthy_domains": stats["unhealthy"],
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/domains/{domain}/health")
async def check_single_domain_health(
    domain: str,
    ctx: RuntimeContext = Depends(get_runtime_context),
    _current_user: None = Depends(get_current_user),
) -> dict:
    """检查单个域名的健康状态"""
    from services.domain_health_checker import DomainHealthChecker
    
    health_checker = DomainHealthChecker(ctx)
    result = health_checker.check_domain_health(domain)
    
    return {
        "domain": result.domain,
        "is_healthy": result.is_healthy,
        "dns_resolves": result.dns_resolves,
        "dns_ip": result.dns_ip,
        "ssl_valid": result.ssl_valid,
        "ssl_expires_at": result.ssl_expires_at,
        "ssl_days_remaining": result.ssl_days_remaining,
        "error_message": result.error_message,
        "checked_at": result.checked_at,
    }
```

---

### 5. 集成到 Daemon 定期任务

在 `daemon.py` 中添加定期扫描：

```python
# daemon.py

async def domain_health_scan_task(runtime_context: RuntimeContext):
    """域名健康扫描任务"""
    from services.domain_health_scan_service import DomainHealthScanService
    
    scan_service = DomainHealthScanService(runtime_context)
    
    while True:
        try:
            # 每小时扫描一次
            await asyncio.sleep(3600)
            
            stats = scan_service.scan_all_active_domains()
            
            if stats["unhealthy"] > 0:
                logger.warning(
                    "Domain health scan found %d unhealthy domains",
                    stats["unhealthy"],
                )
        except Exception as exc:
            logger.exception("Domain health scan task failed: %s", exc)
            await asyncio.sleep(300)  # 失败后 5 分钟重试
```

---

## 使用示例

### 1. 手动检查单个域名

```bash
curl http://localhost:8000/api/v1/health/domains/sf-node1.rensw.xyz/health \
  -H "Authorization: Bearer <token>"

# 输出：
{
  "domain": "sf-node1.rensw.xyz",
  "is_healthy": true,
  "dns_resolves": true,
  "dns_ip": "1.2.3.4",
  "ssl_valid": true,
  "ssl_expires_at": "2027-05-10T12:00:00",
  "ssl_days_remaining": 365,
  "error_message": null,
  "checked_at": "2026-05-10T12:00:00.000000"
}
```

### 2. 扫描所有域名

```bash
curl http://localhost:8000/api/v1/health/domains/health \
  -H "Authorization: Bearer <token>"

# 输出：
{
  "total_domains": 50,
  "healthy_domains": 48,
  "unhealthy_domains": 2,
  "timestamp": "2026-05-10T12:00:00.000000"
}
```

---

## 总结

### 实现的功能

1. ✅ **DNS 解析检查**：验证域名是否正确解析
2. ✅ **SSL 证书检查**：验证证书有效性和过期时间
3. ✅ **批量检查**：支持批量检查多个域名
4. ✅ **定期扫描**：每小时自动扫描所有活跃域名
5. ✅ **告警通知**：发现不健康域名时发送 Telegram 告警
6. ✅ **API 端点**：提供手动检查接口

### 优先级

**P1 高优先级**，因为：
- 直接影响节点可用性
- 实现相对简单（2-3 天）
- 可以提前发现问题
- 避免用户连接失败
