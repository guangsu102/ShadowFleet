"""Unit tests for ProbeOrchestratorService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from database.probe_models import ProbeMeasurementRecord, ProbeRecord
from services.monitor_models import MonitorCandidate, ProbeMeasurementSummary, ProbeResult
from services.probe_orchestrator_service import (
    ProbeOrchestratorService,
    ProbeOrchestratorServiceError,
)


@pytest.fixture
def mock_runtime_context():
    """Create a mock RuntimeContext for testing."""
    mock = MagicMock()
    mock.correlation_id = "test-correlation-id"
    mock.logger = MagicMock()
    mock.logger.getChild.return_value = mock.logger
    mock.config = MagicMock()
    mock.config.app = MagicMock()
    mock.config.app.sentinel_probe_mode = "cn_probe_mesh"
    mock.config.app.sentinel_probe_min_cn_probe_count = 3
    mock.config.app.sentinel_probe_timeout_seconds = 10
    mock.config.app.sentinel_probe_result_wait_timeout_seconds = 30
    mock.config.app.probe_poll_interval_seconds = 2
    return mock


@pytest.fixture
def sample_candidate():
    """Create a sample MonitorCandidate."""
    return MonitorCandidate(
        xboard_node_id=12345,
        node_name="test-node",
        node_type="AnyTLS",
        asset_type="aws",
        domain_name="test.example.com",
        host="test.example.com",
        port="443",
        server_port=443,
        status="online",
        last_healed_at=None,
    )


@pytest.fixture
def sample_probe_result():
    """Create a sample ProbeResult."""
    return ProbeResult(
        provider="local_active_probe",
        status="reachable",
        reason="控制面本地探测成功",
        success_region_count=1,
        failed_region_count=0,
        resolved_ip="1.2.3.4",
        latency_ms=50,
        raw_payload={"target_host": "test.example.com"},
    )


class TestProbeOrchestratorServiceMeasureCandidate:
    """Tests for measure_candidate method."""

    def test_measure_candidate_cn_probe_mesh_mode_success(
        self, mock_runtime_context, sample_candidate, sample_probe_result
    ):
        """Should orchestrate CN probe mesh measurement successfully."""
        mock_registry_service = MagicMock()
        mock_registry_service.list_probes.return_value = [
            ProbeRecord(
                id=1,
                probe_id="probe-001",
                probe_name="CN-Beijing-1",
                status="active",
                auth_token="token-001",
                machine_fingerprint="fp-001",
                public_ip="1.1.1.1",
                region="cn-north-1",
                isp="China Telecom",
                tags=[],
                capabilities={},
                config_version=1,
                last_seen_at="2026-03-24T00:00:00Z",
                created_at="2026-03-24T00:00:00Z",
                updated_at="2026-03-24T00:00:00Z",
            ),
            ProbeRecord(
                id=2,
                probe_id="probe-002",
                probe_name="CN-Shanghai-1",
                status="active",
                auth_token="token-002",
                machine_fingerprint="fp-002",
                public_ip="2.2.2.2",
                region="cn-east-1",
                isp="China Unicom",
                tags=[],
                capabilities={},
                config_version=1,
                last_seen_at="2026-03-24T00:00:00Z",
                created_at="2026-03-24T00:00:00Z",
                updated_at="2026-03-24T00:00:00Z",
            ),
            ProbeRecord(
                id=3,
                probe_id="probe-003",
                probe_name="CN-Guangzhou-1",
                status="active",
                auth_token="token-003",
                machine_fingerprint="fp-003",
                public_ip="3.3.3.3",
                region="cn-south-1",
                isp="China Mobile",
                tags=[],
                capabilities={},
                config_version=1,
                last_seen_at="2026-03-24T00:00:00Z",
                created_at="2026-03-24T00:00:00Z",
                updated_at="2026-03-24T00:00:00Z",
            ),
        ]

        mock_command_service = MagicMock()

        mock_measurement_service = MagicMock()
        mock_measurement_service.create_measurement.return_value = ProbeMeasurementRecord(
            id=1,
            measurement_id="m-001",
            xboard_node_id=12345,
            correlation_id="corr-001",
            control_plane_result={},
            final_status="collecting",
            reason="collecting_remote_probe_results",
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
            finished_at=None,
        )
        mock_measurement_service.wait_for_remote_results.return_value = MagicMock(
            timed_out=False,
            results=[
                {"status": "reachable"},
                {"status": "reachable"},
                {"status": "reachable"},
            ],
        )
        mock_measurement_service.finalize_measurement.return_value = ProbeMeasurementSummary(
            measurement_id="m-001",
            xboard_node_id=12345,
            final_status="healthy",
            reason="国内探针均可达",
            control_plane_result={},
            probe_result_count=3,
            created_at="2026-03-24T00:00:00Z",
            finished_at="2026-03-24T00:00:10Z",
        )

        with patch(
            "services.probe_orchestrator_service.ProbeRegistryService",
            return_value=mock_registry_service,
        ), patch(
            "services.probe_orchestrator_service.ProbeCommandService",
            return_value=mock_command_service,
        ), patch(
            "services.probe_orchestrator_service.ProbeMeasurementService",
            return_value=mock_measurement_service,
        ):
            service = ProbeOrchestratorService(mock_runtime_context)
            result = service.measure_candidate(
                candidate=sample_candidate,
                control_plane_result=sample_probe_result,
                correlation_id="corr-001",
            )

        assert result.measurement_summary.final_status == "healthy"
        assert len(result.selected_probe_ids) == 3
        assert mock_command_service.enqueue_command.call_count == 3

    def test_measure_candidate_local_active_probe_mode_no_remote_probes(
        self, mock_runtime_context, sample_candidate, sample_probe_result
    ):
        """Should skip remote probes in local_active_probe mode."""
        mock_runtime_context.config.app.sentinel_probe_mode = "local_active_probe"

        mock_registry_service = MagicMock()
        mock_command_service = MagicMock()

        mock_measurement_service = MagicMock()
        mock_measurement_service.create_measurement.return_value = ProbeMeasurementRecord(
            id=1,
            measurement_id="m-001",
            xboard_node_id=12345,
            correlation_id="corr-001",
            control_plane_result={},
            final_status="collecting",
            reason="collecting_remote_probe_results",
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
            finished_at=None,
        )
        mock_measurement_service.finalize_measurement.return_value = ProbeMeasurementSummary(
            measurement_id="m-001",
            xboard_node_id=12345,
            final_status="healthy",
            reason="控制面本地主动探测成功",
            control_plane_result={},
            probe_result_count=0,
            created_at="2026-03-24T00:00:00Z",
            finished_at="2026-03-24T00:00:10Z",
        )

        with patch(
            "services.probe_orchestrator_service.ProbeRegistryService",
            return_value=mock_registry_service,
        ), patch(
            "services.probe_orchestrator_service.ProbeCommandService",
            return_value=mock_command_service,
        ), patch(
            "services.probe_orchestrator_service.ProbeMeasurementService",
            return_value=mock_measurement_service,
        ):
            service = ProbeOrchestratorService(mock_runtime_context)
            result = service.measure_candidate(
                candidate=sample_candidate,
                control_plane_result=sample_probe_result,
                correlation_id="corr-001",
            )

        assert result.measurement_summary.final_status == "healthy"
        assert len(result.selected_probe_ids) == 0
        mock_command_service.enqueue_command.assert_not_called()

    def test_measure_candidate_insufficient_probes_raises_error(
        self, mock_runtime_context, sample_candidate, sample_probe_result
    ):
        """Should raise error when not enough active probes are available."""
        mock_registry_service = MagicMock()
        mock_registry_service.list_probes.return_value = [
            ProbeRecord(
                id=1,
                probe_id="probe-001",
                probe_name="CN-Beijing-1",
                status="active",
                auth_token="token-001",
                machine_fingerprint="fp-001",
                public_ip="1.1.1.1",
                region="cn-north-1",
                isp="China Telecom",
                tags=[],
                capabilities={},
                config_version=1,
                last_seen_at="2026-03-24T00:00:00Z",
                created_at="2026-03-24T00:00:00Z",
                updated_at="2026-03-24T00:00:00Z",
            ),
        ]

        mock_command_service = MagicMock()
        mock_measurement_service = MagicMock()
        mock_measurement_service.create_measurement.return_value = ProbeMeasurementRecord(
            id=1,
            measurement_id="m-001",
            xboard_node_id=12345,
            correlation_id="corr-001",
            control_plane_result={},
            final_status="collecting",
            reason="collecting_remote_probe_results",
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
            finished_at=None,
        )

        with patch(
            "services.probe_orchestrator_service.ProbeRegistryService",
            return_value=mock_registry_service,
        ), patch(
            "services.probe_orchestrator_service.ProbeCommandService",
            return_value=mock_command_service,
        ), patch(
            "services.probe_orchestrator_service.ProbeMeasurementService",
            return_value=mock_measurement_service,
        ):
            service = ProbeOrchestratorService(mock_runtime_context)
            with pytest.raises(
                ProbeOrchestratorServiceError,
                match="active cn probes are insufficient for measurement",
            ):
                service.measure_candidate(
                    candidate=sample_candidate,
                    control_plane_result=sample_probe_result,
                    correlation_id="corr-001",
                )

    def test_measure_candidate_timeout_warning_logged(
        self, mock_runtime_context, sample_candidate, sample_probe_result
    ):
        """Should log warning when probe result collection times out."""
        mock_registry_service = MagicMock()
        mock_registry_service.list_probes.return_value = [
            ProbeRecord(
                id=i,
                probe_id=f"probe-{i:03d}",
                probe_name=f"CN-Probe-{i}",
                status="active",
                auth_token=f"token-{i:03d}",
                machine_fingerprint=f"fp-{i:03d}",
                public_ip=f"{i}.{i}.{i}.{i}",
                region="cn-north-1",
                isp="China Telecom",
                tags=[],
                capabilities={},
                config_version=1,
                last_seen_at="2026-03-24T00:00:00Z",
                created_at="2026-03-24T00:00:00Z",
                updated_at="2026-03-24T00:00:00Z",
            )
            for i in range(1, 4)
        ]

        mock_command_service = MagicMock()

        mock_measurement_service = MagicMock()
        mock_measurement_service.create_measurement.return_value = ProbeMeasurementRecord(
            id=1,
            measurement_id="m-001",
            xboard_node_id=12345,
            correlation_id="corr-001",
            control_plane_result={},
            final_status="collecting",
            reason="collecting_remote_probe_results",
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
            finished_at=None,
        )
        mock_measurement_service.wait_for_remote_results.return_value = MagicMock(
            timed_out=True,
            results=[{"status": "reachable"}],
        )
        mock_measurement_service.finalize_measurement.return_value = ProbeMeasurementSummary(
            measurement_id="m-001",
            xboard_node_id=12345,
            final_status="probe_inconclusive",
            reason="国内探针样本不足",
            control_plane_result={},
            probe_result_count=1,
            created_at="2026-03-24T00:00:00Z",
            finished_at="2026-03-24T00:00:10Z",
        )

        with patch(
            "services.probe_orchestrator_service.ProbeRegistryService",
            return_value=mock_registry_service,
        ), patch(
            "services.probe_orchestrator_service.ProbeCommandService",
            return_value=mock_command_service,
        ), patch(
            "services.probe_orchestrator_service.ProbeMeasurementService",
            return_value=mock_measurement_service,
        ):
            service = ProbeOrchestratorService(mock_runtime_context)
            result = service.measure_candidate(
                candidate=sample_candidate,
                control_plane_result=sample_probe_result,
                correlation_id="corr-001",
            )

        assert result.measurement_summary.final_status == "probe_inconclusive"
        mock_runtime_context.logger.warning.assert_called_once()


class TestProbeOrchestratorServiceCountMethods:
    """Tests for count_recent_confirmed_blocked_cycles and count_recent_failed_cycles."""

    def test_count_recent_confirmed_blocked_cycles(self, mock_runtime_context):
        """Should delegate to measurement service."""
        mock_measurement_service = MagicMock()
        mock_measurement_service.count_recent_confirmed_blocked_cycles.return_value = 3

        with patch(
            "services.probe_orchestrator_service.ProbeRegistryService"
        ), patch(
            "services.probe_orchestrator_service.ProbeCommandService"
        ), patch(
            "services.probe_orchestrator_service.ProbeMeasurementService",
            return_value=mock_measurement_service,
        ):
            service = ProbeOrchestratorService(mock_runtime_context)
            count = service.count_recent_confirmed_blocked_cycles(
                xboard_node_id=12345, limit=10
            )

        assert count == 3
        mock_measurement_service.count_recent_confirmed_blocked_cycles.assert_called_once_with(
            xboard_node_id=12345, limit=10
        )

    def test_count_recent_failed_cycles(self, mock_runtime_context):
        """Should delegate to measurement service with status filter."""
        mock_measurement_service = MagicMock()
        mock_measurement_service.count_recent_failed_cycles.return_value = 2

        with patch(
            "services.probe_orchestrator_service.ProbeRegistryService"
        ), patch(
            "services.probe_orchestrator_service.ProbeCommandService"
        ), patch(
            "services.probe_orchestrator_service.ProbeMeasurementService",
            return_value=mock_measurement_service,
        ):
            service = ProbeOrchestratorService(mock_runtime_context)
            count = service.count_recent_failed_cycles(
                xboard_node_id=12345, limit=10, status_filter="origin_fault"
            )

        assert count == 2
        mock_measurement_service.count_recent_failed_cycles.assert_called_once_with(
            xboard_node_id=12345, limit=10, status_filter="origin_fault"
        )


class TestProbeOrchestratorServiceSelectProbeIds:
    """Tests for _select_probe_ids internal method."""

    def test_select_probe_ids_returns_active_probes_only(self, mock_runtime_context):
        """Should only select probes with status='active'."""
        mock_registry_service = MagicMock()
        mock_registry_service.list_probes.return_value = [
            ProbeRecord(
                id=1,
                probe_id="probe-001",
                probe_name="Active-1",
                status="active",
                auth_token="token-001",
                machine_fingerprint="fp-001",
                public_ip="1.1.1.1",
                region="cn-north-1",
                isp="China Telecom",
                tags=[],
                capabilities={},
                config_version=1,
                last_seen_at="2026-03-24T00:00:00Z",
                created_at="2026-03-24T00:00:00Z",
                updated_at="2026-03-24T00:00:00Z",
            ),
            ProbeRecord(
                id=2,
                probe_id="probe-002",
                probe_name="Offline-1",
                status="offline",
                auth_token="token-002",
                machine_fingerprint="fp-002",
                public_ip="2.2.2.2",
                region="cn-east-1",
                isp="China Unicom",
                tags=[],
                capabilities={},
                config_version=1,
                last_seen_at="2026-03-24T00:00:00Z",
                created_at="2026-03-24T00:00:00Z",
                updated_at="2026-03-24T00:00:00Z",
            ),
            ProbeRecord(
                id=3,
                probe_id="probe-003",
                probe_name="Active-2",
                status="active",
                auth_token="token-003",
                machine_fingerprint="fp-003",
                public_ip="3.3.3.3",
                region="cn-south-1",
                isp="China Mobile",
                tags=[],
                capabilities={},
                config_version=1,
                last_seen_at="2026-03-24T00:00:00Z",
                created_at="2026-03-24T00:00:00Z",
                updated_at="2026-03-24T00:00:00Z",
            ),
            ProbeRecord(
                id=4,
                probe_id="probe-004",
                probe_name="Active-3",
                status="active",
                auth_token="token-004",
                machine_fingerprint="fp-004",
                public_ip="4.4.4.4",
                region="cn-west-1",
                isp="China Telecom",
                tags=[],
                capabilities={},
                config_version=1,
                last_seen_at="2026-03-24T00:00:00Z",
                created_at="2026-03-24T00:00:00Z",
                updated_at="2026-03-24T00:00:00Z",
            ),
        ]

        with patch(
            "services.probe_orchestrator_service.ProbeRegistryService",
            return_value=mock_registry_service,
        ), patch("services.probe_orchestrator_service.ProbeCommandService"), patch(
            "services.probe_orchestrator_service.ProbeMeasurementService"
        ):
            service = ProbeOrchestratorService(mock_runtime_context)
            probe_ids = service._select_probe_ids()

        assert len(probe_ids) == 3
        assert "probe-001" in probe_ids
        assert "probe-003" in probe_ids
        assert "probe-004" in probe_ids
        assert "probe-002" not in probe_ids
