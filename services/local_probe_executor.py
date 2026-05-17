from __future__ import annotations

import platform
import socket
import ssl
import subprocess
import time
from typing import TYPE_CHECKING

import requests

from services.monitor_models import MonitorCandidate, ProbeResult

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext

TLS_PROTOCOL_NODE_TYPES = {"AnyTLS", "Trojan", "vless", "vmess"}
HTTP_PROBE_NODE_TYPES = {"AnyTLS"}


class LocalProbeExecutor:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("services.local_probe_executor")
        self._timeout_seconds = runtime_context.config.app.sentinel_probe_timeout_seconds

    @property
    def provider(self) -> str:
        return "local_active_probe"

    def probe_node(self, candidate: MonitorCandidate) -> ProbeResult:
        """
        使用ICMP ping探测节点是否可达
        """
        target_host = self._resolve_target_host(candidate)

        # 首先尝试DNS解析
        resolved_ip = self._resolve_dns(target_host)
        if resolved_ip is None:
            return ProbeResult(
                provider=self.provider,
                status="dns_failed",
                reason=f"DNS 解析失败: host={target_host}",
                success_region_count=0,
                failed_region_count=1,
                failure_stage="dns",
                raw_payload={"target_host": target_host},
            )

        # 使用ping检测
        ping_result = self._run_ping_probe(resolved_ip)
        if ping_result["success"]:
            return ProbeResult(
                provider=self.provider,
                status="reachable",
                reason=f"Ping成功: {ping_result['reason']}",
                success_region_count=1,
                failed_region_count=0,
                resolved_ip=resolved_ip,
                latency_ms=ping_result.get("latency_ms"),
                raw_payload={
                    "target_host": target_host,
                    "resolved_ip": resolved_ip,
                    "ping_output": ping_result.get("output"),
                },
            )
        else:
            return ProbeResult(
                provider=self.provider,
                status="origin_unreachable",
                reason=f"Ping失败: {ping_result['reason']}",
                success_region_count=0,
                failed_region_count=1,
                failure_stage="icmp",
                resolved_ip=resolved_ip,
                raw_payload={
                    "target_host": target_host,
                    "resolved_ip": resolved_ip,
                    "ping_output": ping_result.get("output"),
                },
            )

    def _resolve_target_host(self, candidate: MonitorCandidate) -> str:
        # If daemon has IPv6, prefer domain_name or host (which resolve to IPv6)
        # If daemon only has IPv4, use IPv4 address if available
        daemon_has_ipv6 = bool(self._runtime_context.daemon_ipv6)

        if daemon_has_ipv6:
            # Daemon has IPv6, use domain_name or host
            for value in (candidate.domain_name, candidate.host):
                if value is not None and value.strip():
                    return value.strip()
        else:
            # Daemon only has IPv4, prefer IPv4 address
            if candidate.ipv4_address is not None and candidate.ipv4_address.strip():
                return candidate.ipv4_address.strip()
            # Fallback to domain_name or host if IPv4 address not available
            for value in (candidate.domain_name, candidate.host):
                if value is not None and value.strip():
                    return value.strip()

        raise ValueError(f"节点缺少可探测 host: xboard_node_id={candidate.xboard_node_id}")

    def _resolve_dns(self, target_host: str) -> str | None:
        try:
            info = socket.getaddrinfo(target_host, None, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            self._logger.warning("DNS resolution failed target_host=%s", target_host)
            return None
        for row in info:
            sockaddr = row[4]
            if isinstance(sockaddr, tuple) and sockaddr:
                return str(sockaddr[0])
        return None

    def _run_tcp_probe(self, target_host: str, server_port: int) -> tuple[str, str, int | None] | None:
        if server_port <= 0:
            return ("probe_inconclusive", "节点缺少合法 server_port", None)
        started_at = time.monotonic()
        try:
            with socket.create_connection((target_host, server_port), timeout=self._timeout_seconds):
                latency_ms = int((time.monotonic() - started_at) * 1000)
                return None if latency_ms >= 0 else ("probe_inconclusive", "TCP 探测结果异常", None)
        except OSError as exc:
            latency_ms = int((time.monotonic() - started_at) * 1000)
            return ("origin_unreachable", f"TCP 连接失败: {exc}", latency_ms)

    def _measure_latency_ms(self, target_host: str, server_port: int) -> int | None:
        started_at = time.monotonic()
        try:
            with socket.create_connection((target_host, server_port), timeout=self._timeout_seconds):
                return int((time.monotonic() - started_at) * 1000)
        except OSError:
            return None

    def _run_tls_probe(
        self,
        target_host: str,
        server_port: int,
        server_name: str | None,
    ) -> str | None:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        try:
            with socket.create_connection((target_host, server_port), timeout=self._timeout_seconds) as raw_socket:
                with ssl_context.wrap_socket(
                    raw_socket,
                    server_hostname=(server_name or target_host),
                ):
                    return None
        except OSError as exc:
            return f"TLS 握手失败: {exc}"

    def _run_http_probe(self, domain_name: str) -> str | None:
        try:
            response = requests.head(
                f"https://{domain_name}",
                timeout=self._timeout_seconds,
                allow_redirects=True,
            )
            if response.status_code >= 500:
                return f"HTTP 探测失败: status_code={response.status_code}"
        except requests.RequestException as exc:
            return f"HTTP 探测失败: {exc}"
        return None

    def _run_ping_probe(self, target_ip: str) -> dict:
        """
        使用系统ping命令探测目标IP
        返回格式: {"success": bool, "reason": str, "latency_ms": float|None, "output": str}
        """
        # 检测操作系统类型
        system = platform.system().lower()

        # 根据操作系统构建ping命令
        if system == "windows":
            # Windows: ping -n 1 -w 5000 <ip>
            cmd = ["ping", "-n", "1", "-w", str(int(self._timeout_seconds * 1000)), target_ip]
        else:
            # Linux/Unix: ping -c 1 -W 5 <ip>
            cmd = ["ping", "-c", "1", "-W", str(int(self._timeout_seconds)), target_ip]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds + 2,
            )

            output = result.stdout + result.stderr

            if result.returncode == 0:
                # Ping成功，尝试提取延迟时间
                latency_ms = self._extract_ping_latency(output, system)
                return {
                    "success": True,
                    "reason": f"ICMP echo reply received (latency: {latency_ms}ms)" if latency_ms else "ICMP echo reply received",
                    "latency_ms": latency_ms,
                    "output": output,
                }
            else:
                return {
                    "success": False,
                    "reason": f"Ping failed with return code {result.returncode}",
                    "latency_ms": None,
                    "output": output,
                }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "reason": f"Ping timeout after {self._timeout_seconds}s",
                "latency_ms": None,
                "output": "",
            }
        except Exception as exc:
            return {
                "success": False,
                "reason": f"Ping execution error: {exc}",
                "latency_ms": None,
                "output": str(exc),
            }

    def _extract_ping_latency(self, output: str, system: str) -> float | None:
        """从ping输出中提取延迟时间（毫秒）"""
        import re

        try:
            if system == "windows":
                # Windows格式: "时间=XXms" 或 "time=XXms"
                match = re.search(r'[Tt]ime[=<]\s*(\d+(?:\.\d+)?)\s*ms', output)
            else:
                # Linux格式: "time=XX.X ms"
                match = re.search(r'time=(\d+(?:\.\d+)?)\s*ms', output)

            if match:
                return float(match.group(1))
        except Exception:
            pass

        return None
