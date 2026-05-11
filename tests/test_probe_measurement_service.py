"""
Tests for ProbeMeasurementService
"""
from unittest.mock import Mock, patch
import time

import pytest

from services.probe_measurement_service import (
    ProbeMeasurementService,
    ProbeMeasurementServiceError,
    RemoteResultWaitResult,
)
from services.monitor_models import MonitorCandidate, ProbeResult
from database.probe_models import ProbeMeasurementRecord


class TestProbeMeasurementService:
    """Test ProbeMeasurementService"""

    @pytest.fixture
    def mock_runtime_context(self):
        """Create a mock runtime context"""
        context = Mock()
        context.logger = Mock()
        context.logger.getChild.return_value = Mock()
        context.config = Mock()
        context.config.app = Mock()
        context.config.app.sentinel_probe_min_cn_probe_count = 3
        context.config.app.sentinel_probe_required_success_ratio = 0.6
        context.config.app.sentinel_probe_mode = "cn_probe_mesh"
        context.config.app.sentinel_probe_allow_auto_heal_hy2 = False
        return context

    @pytest.fixture
    def mock_repo(self):
        """Create a mock ProbeMeasurementRepo"""
        return Mock()

    @pytest.fixture
    def service(self, mock_runtime_context, mock_repo):
        """Create a ProbeMeasurementService instance"""
        with patch("services.probe_measurement_service.ProbeMeasurementRepo", return_value=mock_repo):
            return ProbeMeasurementService(mock_runtime_context)

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

    def test_init(self, mock_runtime_context, mock_repo):
        """Test ProbeMeasurementService initialization"""
        with patch("services.probe_measurement_service.ProbeMeasurementRepo", return_value=mock_repo):
            service = ProbeMeasurementService(mock_runtime_context)
            assert service._runtime_context == mock_runtime_context
            assert service._repo == mock_repo

    def test_create_measurement(self, service, candidate, control_plane_result, mock_repo):
        """Test create_measurement creates a measurement record"""
        mock_record = Mock(spec=ProbeMeasurementRecord)
        mock_record.measurement_id = "measurement-123"
        mock_repo.create_measurement.return_value = mock_record

        result = service.create_measurement(
            candidate=candidate,
            correlation_id="corr-123",
            control_plane_result=control_plane_result,
        )

        assert result == mock_record
        mock_repo.create_measurement.assert_called_once()
        call_args = mock_repo.create_measurement.call_args[0][0]
        assert call_args.xboard_node_id == 1
        assert call_args.correlation_id == "corr-123"
        assert call_args.final_status == "collecting"

    def test_record_remote_result(self, service, mock_repo):
        """Test record_remote_result records a probe result"""
        result_payload = {
            "status": "reachable",
            "resolved_ip": "1.2.3.4",
            "latency_ms": 100,
        }

        service.record_remote_result(
            measurement_id="measurement-123",
            probe_id="probe-1",
            result_payload=result_payload,
        )

        mock_repo.create_measurement_result.assert_called_once()
        call_args = mock_repo.create_measurement_result.call_args[0][0]
        assert call_args.measurement_id == "measurement-123"
        assert call_args.probe_id == "probe-1"
        assert call_args.probe_status == "reachable"

    def test_wait_for_remote_results_success(self, service, mock_repo):
        """Test wait_for_remote_results returns when enough results arrive"""
        mock_result_records = [
            Mock(result={"status": "reachable"}),
            Mock(result={"status": "reachable"}),
            Mock(result={"status": "reachable"}),
        ]
        mock_repo.list_measurement_results.return_value = mock_result_records

        result = service.wait_for_remote_results(
            measurement_id="measurement-123",
            minimum_result_count=3,
            timeout_seconds=10.0,
            poll_interval_seconds=0.1,
        )

        assert not result.timed_out
        assert len(result.results) == 3

    def test_wait_for_remote_results_timeout(self, service, mock_repo):
        """Test wait_for_remote_results times out when not enough results"""
        mock_result_records = [
            Mock(result={"status": "reachable"}),
        ]
        mock_repo.list_measurement_results.return_value = mock_result_records

        result = service.wait_for_remote_results(
            measurement_id="measurement-123",
            minimum_result_count=3,
            timeout_seconds=0.2,
            poll_interval_seconds=0.1,
        )

        assert result.timed_out
        assert len(result.results) == 1

    def test_wait_for_remote_results_zero_minimum(self, service):
        """Test wait_for_remote_results returns immediately when minimum is 0"""
        result = service.wait_for_remote_results(
            measurement_id="measurement-123",
            minimum_result_count=0,
            timeout_seconds=10.0,
            poll_interval_seconds=0.1,
        )

        assert not result.timed_out
        assert len(result.results) == 0

    def test_list_remote_results(self, service, mock_repo):
        """Test list_remote_results returns result payloads"""
        mock_result_records = [
            Mock(result={"status": "reachable", "latency_ms": 50}),
            Mock(result={"status": "reachable", "latency_ms": 60}),
        ]
        mock_repo.list_measurement_results.return_value = mock_result_records

        results = service.list_remote_results("measurement-123")

        assert len(results) == 2
        assert results[0]["status"] == "reachable"
        assert results[1]["latency_ms"] == 60

    def test_list_recent_measurements(self, service, mock_repo):
        """Test list_recent_measurements returns measurement records"""
        mock_records = [Mock(), Mock()]
        mock_repo.list_recent_measurements.return_value = mock_records

        results = service.list_recent_measurements(limit=20)

        assert len(results) == 2
        mock_repo.list_recent_measurements.assert_called_once_with(limit=20)

    def test_list_recent_measurements_for_node(self, service, mock_repo):
        """Test list_recent_measurements_for_node returns node-specific records"""
        mock_records = [Mock(), Mock()]
        mock_repo.list_recent_measurements_for_node.return_value = mock_records

        results = service.list_recent_measurements_for_node(xboard_node_id=1, limit=10)

        assert len(results) == 2
        mock_repo.list_recent_measurements_for_node.assert_called_once_with(xboard_node_id=1, limit=10)

    def test_count_recent_failed_cycles(self, service, mock_repo):
        """Test count_recent_failed_cycles counts consecutive failures"""
        mock_records = [
            Mock(final_status="confirmed_blocked_by_gfw"),
            Mock(final_status="confirmed_blocked_by_gfw"),
            Mock(final_status="confirmed_blocked_by_gfw"),
            Mock(final_status="healthy"),
        ]
        mock_repo.list_recent_measurements_for_node.return_value = mock_records

        count = service.count_recent_failed_cycles(xboard_node_id=1, limit=10)

        assert count == 3

    def test_count_recent_failed_cycles_custom_status(self, service, mock_repo):
        """Test count_recent_failed_cycles with custom status filter"""
        mock_records = [
            Mock(final_status="origin_fault"),
            Mock(final_status="origin_fault"),
            Mock(final_status="healthy"),
        ]
        mock_repo.list_recent_measurements_for_node.return_value = mock_records

        count = service.count_recent_failed_cycles(
            xboard_node_id=1,
            limit=10,
            status_filter="origin_fault",
        )

        assert count == 2

    def test_count_recent_confirmed_blocked_cycles(self, service, mock_repo):
        """Test count_recent_confirmed_blocked_cycles"""
        mock_records = [
            Mock(final_status="confirmed_blocked_by_gfw"),
            Mock(final_status="confirmed_blocked_by_gfw"),
        ]
        mock_repo.list_recent_measurements_for_node.return_value = mock_records

        count = service.count_recent_confirmed_blocked_cycles(xboard_node_id=1, limit=10)

        assert count == 2

    def test_finalize_measurement_healthy(self, service, candidate, control_plane_result, mock_repo):
        """Test finalize_measurement with healthy result"""
        measurement_record = Mock(measurement_id="measurement-123")
        remote_results = [
            {"status": "reachable"},
            {"status": "reachable"},
            {"status": "reachable"},
        ]

        finalized_record = Mock()
        finalized_record.measurement_id = "measurement-123"
        finalized_record.xboard_node_id = 1
        finalized_record.final_status = "healthy"
        finalized_record.reason = "国内探针均可达"
        finalized_record.control_plane_result = {}
        finalized_record.created_at = "2024-01-01T00:00:00"
        finalized_record.finished_at = "2024-01-01T00:01:00"
        mock_repo.finalize_measurement.return_value = finalized_record

        summary = service.finalize_measurement(
            candidate=candidate,
            measurement_record=measurement_record,
            control_plane_result=control_plane_result,
            remote_results=remote_results,
        )

        assert summary.final_status == "healthy"
        assert summary.probe_result_count == 3

    def test_finalize_measurement_confirmed_blocked(self, service, candidate, control_plane_result, mock_repo):
        """Test finalize_measurement with confirmed GFW blocking"""
        measurement_record = Mock(measurement_id="measurement-123")
        remote_results = [
            {"status": "dns_failed"},
            {"status": "origin_unreachable"},
            {"status": "tls_failed"},
        ]

        finalized_record = Mock()
        finalized_record.measurement_id = "measurement-123"
        finalized_record.xboard_node_id = 1
        finalized_record.final_status = "confirmed_blocked_by_gfw"
        finalized_record.reason = "海外可达且国内多探针连续失败"
        finalized_record.control_plane_result = {}
        finalized_record.created_at = "2024-01-01T00:00:00"
        finalized_record.finished_at = "2024-01-01T00:01:00"
        mock_repo.finalize_measurement.return_value = finalized_record

        summary = service.finalize_measurement(
            candidate=candidate,
            measurement_record=measurement_record,
            control_plane_result=control_plane_result,
            remote_results=remote_results,
        )

        assert summary.final_status == "confirmed_blocked_by_gfw"
        assert summary.probe_result_count == 3

    def test_finalize_measurement_origin_fault(self, service, candidate, mock_repo):
        """Test finalize_measurement with origin fault"""
        measurement_record = Mock(measurement_id="measurement-123")
        control_plane_result = ProbeResult(
            provider="local_active_probe",
            status="origin_unreachable",
            reason="TCP connection failed",
            success_region_count=0,
            failed_region_count=1,
            raw_payload={},
        )
        remote_results = [
            {"status": "origin_unreachable"},
            {"status": "origin_unreachable"},
            {"status": "origin_unreachable"},
        ]

        finalized_record = Mock()
        finalized_record.measurement_id = "measurement-123"
        finalized_record.xboard_node_id = 1
        finalized_record.final_status = "origin_fault"
        finalized_record.reason = "海外控制面探测已失败，更像源站故障"
        finalized_record.control_plane_result = {}
        finalized_record.created_at = "2024-01-01T00:00:00"
        finalized_record.finished_at = "2024-01-01T00:01:00"
        mock_repo.finalize_measurement.return_value = finalized_record

        summary = service.finalize_measurement(
            candidate=candidate,
            measurement_record=measurement_record,
            control_plane_result=control_plane_result,
            remote_results=remote_results,
        )

        assert summary.final_status == "origin_fault"

    def test_finalize_measurement_insufficient_samples(self, service, candidate, control_plane_result, mock_repo):
        """Test finalize_measurement with insufficient probe samples"""
        measurement_record = Mock(measurement_id="measurement-123")
        remote_results = [
            {"status": "reachable"},
        ]

        finalized_record = Mock()
        finalized_record.measurement_id = "measurement-123"
        finalized_record.xboard_node_id = 1
        finalized_record.final_status = "probe_inconclusive"
        finalized_record.reason = "国内探针样本不足"
        finalized_record.control_plane_result = {}
        finalized_record.created_at = "2024-01-01T00:00:00"
        finalized_record.finished_at = "2024-01-01T00:01:00"
        mock_repo.finalize_measurement.return_value = finalized_record

        summary = service.finalize_measurement(
            candidate=candidate,
            measurement_record=measurement_record,
            control_plane_result=control_plane_result,
            remote_results=remote_results,
        )

        assert summary.final_status == "probe_inconclusive"

    def test_finalize_measurement_hysteria2_no_auto_heal(self, service, control_plane_result, mock_repo):
        """Test finalize_measurement for Hysteria2 with auto-heal disabled"""
        candidate = MonitorCandidate(
            xboard_node_id=1,
            node_name="test-node",
            node_type="Hysteria2",
            asset_type="aws",
            domain_name="example.com",
            host="1.2.3.4",
            port="443",
            server_port=8443,
            status="active",
            last_healed_at=None,
        )
        measurement_record = Mock(measurement_id="measurement-123")
        remote_results = [
            {"status": "dns_failed"},
            {"status": "dns_failed"},
            {"status": "dns_failed"},
        ]

        finalized_record = Mock()
        finalized_record.measurement_id = "measurement-123"
        finalized_record.xboard_node_id = 1
        finalized_record.final_status = "probe_inconclusive"
        finalized_record.reason = "Hysteria2 当前仅支持人工复核，不自动确诊或自愈"
        finalized_record.control_plane_result = {}
        finalized_record.created_at = "2024-01-01T00:00:00"
        finalized_record.finished_at = "2024-01-01T00:01:00"
        mock_repo.finalize_measurement.return_value = finalized_record

        summary = service.finalize_measurement(
            candidate=candidate,
            measurement_record=measurement_record,
            control_plane_result=control_plane_result,
            remote_results=remote_results,
        )

        assert summary.final_status == "probe_inconclusive"

    def test_finalize_measurement_local_active_probe_mode(self, service, candidate, control_plane_result, mock_repo):
        """Test finalize_measurement in local_active_probe mode"""
        service._runtime_context.config.app.sentinel_probe_mode = "local_active_probe"
        measurement_record = Mock(measurement_id="measurement-123")
        remote_results = []

        finalized_record = Mock()
        finalized_record.measurement_id = "measurement-123"
        finalized_record.xboard_node_id = 1
        finalized_record.final_status = "healthy"
        finalized_record.reason = "控制面本地主动探测成功"
        finalized_record.control_plane_result = {}
        finalized_record.created_at = "2024-01-01T00:00:00"
        finalized_record.finished_at = "2024-01-01T00:01:00"
        mock_repo.finalize_measurement.return_value = finalized_record

        summary = service.finalize_measurement(
            candidate=candidate,
            measurement_record=measurement_record,
            control_plane_result=control_plane_result,
            remote_results=remote_results,
        )

        assert summary.final_status == "healthy"

    def test_serialize_probe_result(self):
        """Test _serialize_probe_result converts ProbeResult to dict"""
        probe_result = ProbeResult(
            provider="local_active_probe",
            status="reachable",
            reason="success",
            success_region_count=1,
            failed_region_count=0,
            failure_stage="none",
            resolved_ip="1.2.3.4",
            latency_ms=50,
            raw_payload={"key": "value"},
        )

        result = ProbeMeasurementService._serialize_probe_result(probe_result)

        assert result["provider"] == "local_active_probe"
        assert result["status"] == "reachable"
        assert result["resolved_ip"] == "1.2.3.4"
        assert result["latency_ms"] == 50

    def test_to_optional_text_none(self):
        """Test _to_optional_text with None"""
        result = ProbeMeasurementService._to_optional_text(None)
        assert result is None

    def test_to_optional_text_empty_string(self):
        """Test _to_optional_text with empty string"""
        result = ProbeMeasurementService._to_optional_text("")
        assert result is None

    def test_to_optional_text_whitespace(self):
        """Test _to_optional_text with whitespace"""
        result = ProbeMeasurementService._to_optional_text("   ")
        assert result is None

    def test_to_optional_text_valid_string(self):
        """Test _to_optional_text with valid string"""
        result = ProbeMeasurementService._to_optional_text("  test  ")
        assert result == "test"

    def test_to_optional_int_none(self):
        """Test _to_optional_int with None"""
        result = ProbeMeasurementService._to_optional_int(None)
        assert result is None

    def test_to_optional_int_valid_int(self):
        """Test _to_optional_int with valid int"""
        result = ProbeMeasurementService._to_optional_int(42)
        assert result == 42

    def test_to_optional_int_string_number(self):
        """Test _to_optional_int with string number"""
        result = ProbeMeasurementService._to_optional_int("123")
        assert result == 123
