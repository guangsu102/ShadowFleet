"""
Tests for ProbeOrchestratorService
"""
from unittest.mock import Mock, patch

import pytest

from services.probe_orchestrator_service import (
    ProbeOrchestratorService,
    ProbeOrchestratorServiceError,
    ProbeOrchestrationResult,
)
from services.monitor_models import MonitorCandidate, ProbeMeasurementSummary, ProbeResult
from database.probe_models import ProbeMeasurementRecord, ProbeRecord


class TestProbeOrchestratorService:
    """Test ProbeOrchestratorService"""

    @pytest.fixture
    def mock_runtime_context(self):
        """Create a mock runtime context"""
        context = Mock()
        context.logger = Mock()
        context.logger.getChild.return_value = Mock()
        context.config = Mock()
        context.config.app = Mock()
        context.config.app.sentinel_probe_mode = "cn_probe_mesh"
        context.config.app.sentinel_probe_min_cn_probe_count = 3
        context.config.app.sentinel_probe_timeout_seconds = 5
        context.config.app.sentinel_probe_result_wait_timeout_seconds = 30
        context.config.app.probe_poll_interval_seconds = 1
        return context

    @pytest.fixture
    def mock_registry_service(self):
        """Create a mock ProbeRegistryService"""
        return Mock()

    @pytest.fixture
    def mock_command_service(self):
        """Create a mock ProbeCommandService"""
        return Mock()

    @pytest.fixture
    def mock_measurement_service(self):
        """Create a mock ProbeMeasurementService"""
        return Mock()

    @pytest.fixture
    def service(self, mock_runtime_context, mock_registry_service, mock_command_service, mock_measurement_service):
        """Create a ProbeOrchestratorService instance"""
        with patch("services.probe_orchestrator_service.ProbeRegistryService", return_value=mock_registry_service), \
             patch("services.probe_orchestrator_service.ProbeCommandService", return_value=mock_command_service), \
             patch("services.probe_orchestrator_service.ProbeMeasurementService", return_value=mock_measurement_service):
            return ProbeOrchestratorService(mock_runtime_context)

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

    @pytest.fixture
    def control_plane_result(self):
        """Create a mock ProbeResult"""
        return ProbeResult(
            provider="local_active_probe",
            status="reachable",
            reason="success",
            success_region_count=1,
            failed_region_count=0,
            resolved_ip="1.2.3.4",
            latency_ms=50,
            raw_payload={},
        )

    def test_init(self, mock_runtime_context):
        """Test ProbeOrchestratorService initialization"""
        with patch("services.probe_orchestrator_service.ProbeRegistryService"), \
             patch("services.probe_orchestrator_service.ProbeCommandService"), \
             patch("services.probe_orchestrator_service.ProbeMeasurementService"):
            service = ProbeOrchestratorService(mock_runtime_context)
            assert service._runtime_context == mock_runtime_context

    def test_measure_candidate_cn_probe_mesh(self, service, candidate, control_plane_result,
                                             mock_registry_service, mock_command_service, mock_measurement_service):
        """Test measure_candidate in cn_probe_mesh mode"""
        measurement_record = Mock()
        measurement_record.measurement_id = "m-123"
        mock_measurement_service.create_measurement.return_value = measurement_record

        probe_records = [
            Mock(probe_id="probe-1", status="active"),
            Mock(probe_id="probe-2", status="active"),
            Mock(probe_id="probe-3", status="active"),
        ]
        mock_registry_service.list_probes.return_value = probe_records

        wait_result = Mock()
        wait_result.timed_out = False
        wait_result.results = [
            {"status": "reachable"},
            {"status": "reachable"},
            {"status": "reachable"},
        ]
        mock_measurement_service.wait_for_remote_results.return_value = wait_result

        measurement_summary = Mock(spec=ProbeMeasurementSummary)
        measurement_summary.measurement_id = "m-123"
        measurement_summary.final_status = "healthy"
        mock_measurement_service.finalize_measurement.return_value = measurement_summary

        result = service.measure_candidate(
            candidate=candidate,
            control_plane_result=control_plane_result,
            correlation_id="corr-123",
        )

        assert isinstance(result, ProbeOrchestrationResult)
        assert result.measurement_summary == measurement_summary
        assert len(result.selected_probe_ids) == 3
        assert mock_command_service.enqueue_command.call_count == 3

    def test_measure_candidate_local_active_probe_mode(self, service, candidate, control_plane_result, mock_measurement_service):
        """Test measure_candidate in local_active_probe mode"""
        service._runtime_context.config.app.sentinel_probe_mode = "local_active_probe"

        measurement_record = Mock()
        measurement_record.measurement_id = "m-123"
        mock_measurement_service.create_measurement.return_value = measurement_record

        measurement_summary = Mock(spec=ProbeMeasurementSummary)
        measurement_summary.measurement_id = "m-123"
        measurement_summary.final_status = "healthy"
        mock_measurement_service.finalize_measurement.return_value = measurement_summary

        result = service.measure_candidate(
            candidate=candidate,
            control_plane_result=control_plane_result,
            correlation_id="corr-123",
        )

        assert isinstance(result, ProbeOrchestrationResult)
        assert len(result.selected_probe_ids) == 0
        mock_measurement_service.finalize_measurement.assert_called_once()

    def test_measure_candidate_timeout(self, service, candidate, control_plane_result,
                                       mock_registry_service, mock_command_service, mock_measurement_service):
        """Test measure_candidate when probe results timeout"""
        measurement_record = Mock()
        measurement_record.measurement_id = "m-123"
        mock_measurement_service.create_measurement.return_value = measurement_record

        probe_records = [
            Mock(probe_id="probe-1", status="active"),
            Mock(probe_id="probe-2", status="active"),
            Mock(probe_id="probe-3", status="active"),
        ]
        mock_registry_service.list_probes.return_value = probe_records

        wait_result = Mock()
        wait_result.timed_out = True
        wait_result.results = [
            {"status": "reachable"},
        ]
        mock_measurement_service.wait_for_remote_results.return_value = wait_result

        measurement_summary = Mock(spec=ProbeMeasurementSummary)
        measurement_summary.measurement_id = "m-123"
        measurement_summary.final_status = "probe_inconclusive"
        mock_measurement_service.finalize_measurement.return_value = measurement_summary

        result = service.measure_candidate(
            candidate=candidate,
            control_plane_result=control_plane_result,
            correlation_id="corr-123",
        )

        assert result.measurement_summary.final_status == "probe_inconclusive"

    def test_list_recent_measurements(self, service, mock_measurement_service):
        """Test list_recent_measurements delegates to measurement service"""
        mock_measurements = [Mock(), Mock()]
        mock_measurement_service.list_recent_measurements.return_value = mock_measurements

        result = service.list_recent_measurements(limit=20)

        assert len(result) == 2
        mock_measurement_service.list_recent_measurements.assert_called_once_with(limit=20)

    def test_count_recent_confirmed_blocked_cycles(self, service, mock_measurement_service):
        """Test count_recent_confirmed_blocked_cycles delegates to measurement service"""
        mock_measurement_service.count_recent_confirmed_blocked_cycles.return_value = 5

        result = service.count_recent_confirmed_blocked_cycles(xboard_node_id=1, limit=10)

        assert result == 5
        mock_measurement_service.count_recent_confirmed_blocked_cycles.assert_called_once_with(
            xboard_node_id=1,
            limit=10,
        )

    def test_count_recent_failed_cycles(self, service, mock_measurement_service):
        """Test count_recent_failed_cycles delegates to measurement service"""
        mock_measurement_service.count_recent_failed_cycles.return_value = 3

        result = service.count_recent_failed_cycles(
            xboard_node_id=1,
            limit=10,
            status_filter="origin_fault",
        )

        assert result == 3
        mock_measurement_service.count_recent_failed_cycles.assert_called_once_with(
            xboard_node_id=1,
            limit=10,
            status_filter="origin_fault",
        )

    def test_select_probe_ids_sufficient_probes(self, service, mock_registry_service):
        """Test _select_probe_ids with sufficient active probes"""
        probe_records = [
            Mock(probe_id="probe-1", status="active"),
            Mock(probe_id="probe-2", status="active"),
            Mock(probe_id="probe-3", status="active"),
            Mock(probe_id="probe-4", status="active"),
            Mock(probe_id="probe-5", status="inactive"),
        ]
        mock_registry_service.list_probes.return_value = probe_records

        result = service._select_probe_ids()

        assert len(result) == 3
        assert "probe-1" in result
        assert "probe-2" in result
        assert "probe-3" in result

    def test_select_probe_ids_insufficient_probes(self, service, mock_registry_service):
        """Test _select_probe_ids raises error when insufficient probes"""
        probe_records = [
            Mock(probe_id="probe-1", status="active"),
            Mock(probe_id="probe-2", status="inactive"),
        ]
        mock_registry_service.list_probes.return_value = probe_records

        with pytest.raises(ProbeOrchestratorServiceError, match="active cn probes are insufficient"):
            service._select_probe_ids()

    def test_select_probe_ids_exactly_minimum(self, service, mock_registry_service):
        """Test _select_probe_ids with exactly minimum probes"""
        probe_records = [
            Mock(probe_id="probe-1", status="active"),
            Mock(probe_id="probe-2", status="active"),
            Mock(probe_id="probe-3", status="active"),
        ]
        mock_registry_service.list_probes.return_value = probe_records

        result = service._select_probe_ids()

        assert len(result) == 3
