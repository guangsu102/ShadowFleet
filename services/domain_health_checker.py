"""
域名健康检查服务

检查域名的 DNS 解析和 SSL 证书有效性
"""

from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass
from datetime import datetime
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
