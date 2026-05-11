"""
Tests for LocalProbeExecutor
"""
from unittest.mock import Mock, patch, MagicMock
import socket
import ssl

import pytest
import requests

from services.local_probe_executor import LocalProbeExecutor
from services.monitor_models import MonitorCandidate, ProbeResult


class TestLocalProbeExecutor:
    """Test LocalProbeExecutor"""

    @pytest.fixture
    def mock_runtime_context(self):
        """Create a mock runtime context"""
        context = Mock()
        context.logger = Mock()
        context.logger.getChild.return_value = Mock()
        context.config = Mock()
        context.config.app = Mock()
        context.config.app.sentinel_probe_timeout_seconds = 5
        return context

    @pytest.fixture
    def executor(self, mock_runtime_context):
        """Create a LocalProbeExecutor instance"""
        return LocalProbeExecutor(mock_runtime_context)

    @pytest.fixture
    def trojan_candidate(self):
        """Create a Trojan candidate"""
        return MonitorCandidate(
            xboard_node_id=1,
            node_name="test-node",
            node_type="Trojan",
            asset_type="aws",
            domain_name="example.com",
            host="1.2.3.4",
            port="443",
            server_port=8443,
            status="active",
            last_healed_at=None,
        )

    @pytest.fixture
    def hysteria2_candidate(self):
        """Create a Hysteria2 candidate"""
        return MonitorCandidate(
            xboard_node_id=2,
            node_name="test-hy2",
            node_type="Hysteria2",
            asset_type="aws",
            domain_name="example.com",
            host="1.2.3.4",
            port="443",
            server_port=8443,
            status="active",
            last_healed_at=None,
        )

    @pytest.fixture
    def anytls_candidate(self):
        """Create an AnyTLS candidate"""
        return MonitorCandidate(
            xboard_node_id=3,
            node_name="test-anytls",
            node_type="AnyTLS",
            asset_type="aws",
            domain_name="example.com",
            host="1.2.3.4",
            port="443",
            server_port=8443,
            status="active",
            last_healed_at=None,
        )

    def test_init(self, mock_runtime_context):
        """Test LocalProbeExecutor initialization"""
        executor = LocalProbeExecutor(mock_runtime_context)
        assert executor._runtime_context == mock_runtime_context
        assert executor._timeout_seconds == 5

    def test_provider_property(self, executor):
        """Test provider property returns correct value"""
        assert executor.provider == "local_active_probe"

    def test_probe_node_hysteria2_not_supported(self, executor, hysteria2_candidate):
        """Test probe_node returns inconclusive for Hysteria2"""
        result = executor.probe_node(hysteria2_candidate)

        assert result.status == "probe_inconclusive"
        assert result.failure_stage == "udp_not_supported"
        assert "Hysteria2" in result.reason

    @patch("services.local_probe_executor.socket.getaddrinfo")
    def test_probe_node_dns_failed(self, mock_getaddrinfo, executor, trojan_candidate):
        """Test probe_node returns dns_failed when DNS resolution fails"""
        mock_getaddrinfo.side_effect = socket.gaierror("DNS resolution failed")

        result = executor.probe_node(trojan_candidate)

        assert result.status == "dns_failed"
        assert result.failure_stage == "dns"
        assert "DNS 解析失败" in result.reason

    @patch("services.local_probe_executor.socket.getaddrinfo")
    @patch("services.local_probe_executor.socket.create_connection")
    def test_probe_node_tcp_failed(self, mock_create_connection, mock_getaddrinfo, executor, trojan_candidate):
        """Test probe_node returns origin_unreachable when TCP connection fails"""
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.2.3.4', 8443))
        ]
        mock_create_connection.side_effect = OSError("Connection refused")

        result = executor.probe_node(trojan_candidate)

        assert result.status == "origin_unreachable"
        assert result.failure_stage == "tcp"
        assert "TCP 连接失败" in result.reason

    @patch("services.local_probe_executor.socket.getaddrinfo")
    @patch("services.local_probe_executor.socket.create_connection")
    @patch("services.local_probe_executor.ssl.create_default_context")
    def test_probe_node_tls_failed(self, mock_ssl_context, mock_create_connection, mock_getaddrinfo, executor, trojan_candidate):
        """Test probe_node returns tls_failed when TLS handshake fails"""
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.2.3.4', 8443))
        ]

        mock_socket = MagicMock()
        mock_create_connection.return_value.__enter__.return_value = mock_socket

        mock_context = MagicMock()
        mock_ssl_context.return_value = mock_context
        mock_context.wrap_socket.side_effect = OSError("TLS handshake failed")

        result = executor.probe_node(trojan_candidate)

        assert result.status == "tls_failed"
        assert result.failure_stage == "tls"
        assert "TLS 握手失败" in result.reason

    @patch("services.local_probe_executor.socket.getaddrinfo")
    @patch("services.local_probe_executor.socket.create_connection")
    @patch("services.local_probe_executor.ssl.create_default_context")
    @patch("services.local_probe_executor.requests.head")
    def test_probe_node_http_failed(self, mock_requests_head, mock_ssl_context, mock_create_connection,
                                    mock_getaddrinfo, executor, anytls_candidate):
        """Test probe_node returns application_unreachable when HTTP probe fails"""
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.2.3.4', 8443))
        ]

        mock_socket = MagicMock()
        mock_create_connection.return_value.__enter__.return_value = mock_socket

        mock_context = MagicMock()
        mock_ssl_context.return_value = mock_context
        mock_context.wrap_socket.return_value.__enter__.return_value = MagicMock()

        mock_response = Mock()
        mock_response.status_code = 500
        mock_requests_head.return_value = mock_response

        result = executor.probe_node(anytls_candidate)

        assert result.status == "application_unreachable"
        assert result.failure_stage == "http"
        assert "HTTP 探测失败" in result.reason

    @patch("services.local_probe_executor.socket.getaddrinfo")
    @patch("services.local_probe_executor.socket.create_connection")
    @patch("services.local_probe_executor.ssl.create_default_context")
    def test_probe_node_success(self, mock_ssl_context, mock_create_connection, mock_getaddrinfo, executor, trojan_candidate):
        """Test probe_node returns reachable on success"""
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.2.3.4', 8443))
        ]

        mock_socket = MagicMock()
        mock_create_connection.return_value.__enter__.return_value = mock_socket

        mock_context = MagicMock()
        mock_ssl_context.return_value = mock_context
        mock_context.wrap_socket.return_value.__enter__.return_value = MagicMock()

        result = executor.probe_node(trojan_candidate)

        assert result.status == "reachable"
        assert result.success_region_count == 1
        assert result.failed_region_count == 0
        assert result.resolved_ip == "1.2.3.4"

    def test_resolve_target_host_domain_name(self, executor, trojan_candidate):
        """Test _resolve_target_host prefers domain_name"""
        result = executor._resolve_target_host(trojan_candidate)
        assert result == "example.com"

    def test_resolve_target_host_fallback_to_host(self, executor):
        """Test _resolve_target_host falls back to host"""
        candidate = MonitorCandidate(
            xboard_node_id=1,
            node_name="test-node",
            node_type="Trojan",
            asset_type="aws",
            domain_name=None,
            host="1.2.3.4",
            port="443",
            server_port=8443,
            status="active",
            last_healed_at=None,
        )
        result = executor._resolve_target_host(candidate)
        assert result == "1.2.3.4"

    def test_resolve_target_host_no_host(self, executor):
        """Test _resolve_target_host raises error when no host available"""
        candidate = MonitorCandidate(
            xboard_node_id=1,
            node_name="test-node",
            node_type="Trojan",
            asset_type="aws",
            domain_name=None,
            host=None,
            port="443",
            server_port=8443,
            status="active",
            last_healed_at=None,
        )
        with pytest.raises(ValueError, match="节点缺少可探测 host"):
            executor._resolve_target_host(candidate)

    @patch("services.local_probe_executor.socket.getaddrinfo")
    def test_resolve_dns_success(self, mock_getaddrinfo, executor):
        """Test _resolve_dns returns IP address"""
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.2.3.4', 0))
        ]

        result = executor._resolve_dns("example.com")

        assert result == "1.2.3.4"

    @patch("services.local_probe_executor.socket.getaddrinfo")
    def test_resolve_dns_failure(self, mock_getaddrinfo, executor):
        """Test _resolve_dns returns None on failure"""
        mock_getaddrinfo.side_effect = socket.gaierror("DNS failed")

        result = executor._resolve_dns("example.com")

        assert result is None

    @patch("services.local_probe_executor.socket.create_connection")
    def test_run_tcp_probe_success(self, mock_create_connection, executor):
        """Test _run_tcp_probe returns None on success"""
        mock_socket = MagicMock()
        mock_create_connection.return_value.__enter__.return_value = mock_socket

        result = executor._run_tcp_probe("example.com", 8443)

        assert result is None

    @patch("services.local_probe_executor.socket.create_connection")
    def test_run_tcp_probe_failure(self, mock_create_connection, executor):
        """Test _run_tcp_probe returns error tuple on failure"""
        mock_create_connection.side_effect = OSError("Connection refused")

        result = executor._run_tcp_probe("example.com", 8443)

        assert result is not None
        assert result[0] == "origin_unreachable"
        assert "TCP 连接失败" in result[1]

    def test_run_tcp_probe_invalid_port(self, executor):
        """Test _run_tcp_probe returns error for invalid port"""
        result = executor._run_tcp_probe("example.com", 0)

        assert result is not None
        assert result[0] == "probe_inconclusive"
        assert "缺少合法 server_port" in result[1]

    @patch("services.local_probe_executor.socket.create_connection")
    def test_measure_latency_ms_success(self, mock_create_connection, executor):
        """Test _measure_latency_ms returns latency"""
        mock_socket = MagicMock()
        mock_create_connection.return_value.__enter__.return_value = mock_socket

        result = executor._measure_latency_ms("example.com", 8443)

        assert result is not None
        assert isinstance(result, int)
        assert result >= 0

    @patch("services.local_probe_executor.socket.create_connection")
    def test_measure_latency_ms_failure(self, mock_create_connection, executor):
        """Test _measure_latency_ms returns None on failure"""
        mock_create_connection.side_effect = OSError("Connection failed")

        result = executor._measure_latency_ms("example.com", 8443)

        assert result is None

    @patch("services.local_probe_executor.socket.create_connection")
    @patch("services.local_probe_executor.ssl.create_default_context")
    def test_run_tls_probe_success(self, mock_ssl_context, mock_create_connection, executor):
        """Test _run_tls_probe returns None on success"""
        mock_socket = MagicMock()
        mock_create_connection.return_value.__enter__.return_value = mock_socket

        mock_context = MagicMock()
        mock_ssl_context.return_value = mock_context
        mock_context.wrap_socket.return_value.__enter__.return_value = MagicMock()

        result = executor._run_tls_probe("example.com", 8443, "example.com")

        assert result is None

    @patch("services.local_probe_executor.socket.create_connection")
    @patch("services.local_probe_executor.ssl.create_default_context")
    def test_run_tls_probe_failure(self, mock_ssl_context, mock_create_connection, executor):
        """Test _run_tls_probe returns error message on failure"""
        mock_socket = MagicMock()
        mock_create_connection.return_value.__enter__.return_value = mock_socket

        mock_context = MagicMock()
        mock_ssl_context.return_value = mock_context
        mock_context.wrap_socket.side_effect = OSError("TLS error")

        result = executor._run_tls_probe("example.com", 8443, "example.com")

        assert result is not None
        assert "TLS 握手失败" in result

    @patch("services.local_probe_executor.requests.head")
    def test_run_http_probe_success(self, mock_requests_head, executor):
        """Test _run_http_probe returns None on success"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_requests_head.return_value = mock_response

        result = executor._run_http_probe("example.com")

        assert result is None

    @patch("services.local_probe_executor.requests.head")
    def test_run_http_probe_server_error(self, mock_requests_head, executor):
        """Test _run_http_probe returns error for 5xx status"""
        mock_response = Mock()
        mock_response.status_code = 503
        mock_requests_head.return_value = mock_response

        result = executor._run_http_probe("example.com")

        assert result is not None
        assert "HTTP 探测失败" in result
        assert "503" in result

    @patch("services.local_probe_executor.requests.head")
    def test_run_http_probe_exception(self, mock_requests_head, executor):
        """Test _run_http_probe returns error on exception"""
        mock_requests_head.side_effect = requests.RequestException("Connection error")

        result = executor._run_http_probe("example.com")

        assert result is not None
        assert "HTTP 探测失败" in result
