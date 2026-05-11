"""
Tests for ProbeClient
"""
from unittest.mock import Mock, patch

import pytest

from services.probe_client import ProbeClient, ProbeClientError
from services.monitor_models import MonitorCandidate, ProbeResult


class TestProbeClient:
    """Test ProbeClient"""

    @pytest.fixture
    def mock_runtime_context(self):
        """Create a mock runtime context"""
        context = Mock()
        context.logger = Mock()
        context.logger.getChild.return_value = Mock()
        context.config = Mock()
        context.config.app = Mock()
        context.config.app.sentinel_probe_provider = "local_active_probe"
        context.config.app.sentinel_probe_timeout_seconds = 5
        return context

    @pytest.fixture
    def mock_local_executor(self):
        """Create a mock LocalProbeExecutor"""
        return Mock()

    @pytest.fixture
    def client(self, mock_runtime_context, mock_local_executor):
        """Create a ProbeClient instance"""
        with patch("services.probe_client.LocalProbeExecutor", return_value=mock_local_executor):
            return ProbeClient(mock_runtime_context)

    @pytest.fixture
    def candidate(self):
        """Create a mock MonitorCandidate"""
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

    def test_init(self, mock_runtime_context):
        """Test ProbeClient initialization"""
        with patch("services.probe_client.LocalProbeExecutor") as mock_executor_class:
            client = ProbeClient(mock_runtime_context)
            assert client._runtime_context == mock_runtime_context
            mock_executor_class.assert_called_once_with(mock_runtime_context)

    def test_provider_property(self, client):
        """Test provider property returns correct value"""
        assert client.provider == "local_active_probe"

    def test_probe_node_success(self, client, candidate, mock_local_executor):
        """Test probe_node returns result from local executor"""
        expected_result = ProbeResult(
            provider="local_active_probe",
            status="reachable",
            reason="success",
            success_region_count=1,
            failed_region_count=0,
            resolved_ip="1.2.3.4",
            latency_ms=50,
            raw_payload={},
        )
        mock_local_executor.probe_node.return_value = expected_result

        result = client.probe_node(candidate)

        assert result == expected_result
        mock_local_executor.probe_node.assert_called_once_with(candidate)

    def test_probe_node_unsupported_provider(self, mock_runtime_context, candidate):
        """Test probe_node raises error for unsupported provider"""
        mock_runtime_context.config.app.sentinel_probe_provider = "unsupported_provider"

        with patch("services.probe_client.LocalProbeExecutor"):
            client = ProbeClient(mock_runtime_context)

            with pytest.raises(ProbeClientError, match="Unsupported sentinel_probe_provider"):
                client.probe_node(candidate)

    def test_probe_node_executor_raises_probe_client_error(self, client, candidate, mock_local_executor):
        """Test probe_node re-raises ProbeClientError"""
        mock_local_executor.probe_node.side_effect = ProbeClientError("Probe failed")

        with pytest.raises(ProbeClientError, match="Probe failed"):
            client.probe_node(candidate)

    def test_probe_node_executor_raises_generic_exception(self, client, candidate, mock_local_executor):
        """Test probe_node wraps generic exceptions in ProbeClientError"""
        mock_local_executor.probe_node.side_effect = RuntimeError("Unexpected error")

        with pytest.raises(ProbeClientError, match="Unexpected error"):
            client.probe_node(candidate)

    def test_probe_node_logs_exception(self, client, candidate, mock_local_executor):
        """Test probe_node logs exception details"""
        mock_local_executor.probe_node.side_effect = RuntimeError("Test error")

        with pytest.raises(ProbeClientError):
            client.probe_node(candidate)

        client._logger.exception.assert_called_once()
        call_args = client._logger.exception.call_args[0]
        assert "Probe failed" in call_args[0]
