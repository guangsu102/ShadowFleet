from __future__ import annotations

import socket
import ssl
import time

import requests


class ProbeCommandExecutor:
    def __init__(self, timeout_seconds: int) -> None:
        self._timeout_seconds = timeout_seconds

    def execute(self, command_type: str, payload: dict[str, object]) -> dict[str, object]:
        if command_type == "run_connectivity_probe":
            return self._run_connectivity_probe(payload)
        if command_type == "self_check":
            return {"status": "reachable", "reason": "self_check_ok"}
        if command_type == "refresh_config":
            return {"status": "reachable", "reason": "config_refresh_acknowledged"}
        if command_type == "drain_probe":
            return {"status": "reachable", "reason": "probe_draining_acknowledged"}
        if command_type == "resume_probe":
            return {"status": "reachable", "reason": "probe_resume_acknowledged"}
        raise ValueError(f"unsupported command_type: {command_type}")

    def _run_connectivity_probe(self, payload: dict[str, object]) -> dict[str, object]:
        measurement_id = self._required_text(payload, "measurement_id")
        target_host = self._optional_text(payload.get("domain_name")) or self._required_text(payload, "host")
        server_port = int(payload.get("server_port") or 0)
        node_type = self._required_text(payload, "node_type")
        resolved_ip = self._resolve_dns(target_host)
        if resolved_ip is None:
            return {
                "measurement_id": measurement_id,
                "status": "dns_failed",
                "reason": f"DNS 解析失败: host={target_host}",
                "failure_stage": "dns",
                "resolved_ip": None,
                "latency_ms": None,
            }
        tcp_failure = self._run_tcp_probe(target_host, server_port)
        if tcp_failure is not None:
            reason, latency_ms = tcp_failure
            return {
                "measurement_id": measurement_id,
                "status": "origin_unreachable",
                "reason": reason,
                "failure_stage": "tcp",
                "resolved_ip": resolved_ip,
                "latency_ms": latency_ms,
            }

        latency_ms = self._measure_latency_ms(target_host, server_port)
        if node_type in {"AnyTLS", "Trojan", "vless", "vmess"}:
            tls_failure = self._run_tls_probe(
                target_host=target_host,
                server_port=server_port,
                server_name=self._optional_text(payload.get("domain_name")) or target_host,
            )
            if tls_failure is not None:
                return {
                    "measurement_id": measurement_id,
                    "status": "tls_failed",
                    "reason": tls_failure,
                    "failure_stage": "tls",
                    "resolved_ip": resolved_ip,
                    "latency_ms": latency_ms,
                }

        if node_type == "AnyTLS":
            http_failure = self._run_http_probe(target_host)
            if http_failure is not None:
                return {
                    "measurement_id": measurement_id,
                    "status": "application_unreachable",
                    "reason": http_failure,
                    "failure_stage": "http",
                    "resolved_ip": resolved_ip,
                    "latency_ms": latency_ms,
                }
        if node_type == "Hysteria2":
            return {
                "measurement_id": measurement_id,
                "status": "probe_inconclusive",
                "reason": "agent 当前未实现 Hysteria2 UDP 探测",
                "failure_stage": "udp_not_supported",
                "resolved_ip": resolved_ip,
                "latency_ms": latency_ms,
            }
        return {
            "measurement_id": measurement_id,
            "status": "reachable",
            "reason": "国内探针主动探测成功",
            "failure_stage": None,
            "resolved_ip": resolved_ip,
            "latency_ms": latency_ms,
        }

    def _resolve_dns(self, target_host: str) -> str | None:
        try:
            address_info = socket.getaddrinfo(target_host, None, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            return None
        for info in address_info:
            sockaddr = info[4]
            if isinstance(sockaddr, tuple) and sockaddr:
                return str(sockaddr[0])
        return None

    def _run_tcp_probe(self, target_host: str, server_port: int) -> tuple[str, int | None] | None:
        started_at = time.monotonic()
        try:
            with socket.create_connection((target_host, server_port), timeout=self._timeout_seconds):
                return None
        except OSError as exc:
            return (f"TCP 连接失败: {exc}", int((time.monotonic() - started_at) * 1000))

    def _measure_latency_ms(self, target_host: str, server_port: int) -> int | None:
        started_at = time.monotonic()
        try:
            with socket.create_connection((target_host, server_port), timeout=self._timeout_seconds):
                return int((time.monotonic() - started_at) * 1000)
        except OSError:
            return None

    def _run_tls_probe(self, *, target_host: str, server_port: int, server_name: str) -> str | None:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        try:
            with socket.create_connection((target_host, server_port), timeout=self._timeout_seconds) as raw_socket:
                with ssl_context.wrap_socket(raw_socket, server_hostname=server_name):
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
                return f"HTTP 状态码异常: {response.status_code}"
        except requests.RequestException as exc:
            return f"HTTP 探测失败: {exc}"
        return None

    @staticmethod
    def _required_text(payload: dict[str, object], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} is required")
        return value.strip()

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
