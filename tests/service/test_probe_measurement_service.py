"""Unit tests for ProbeMeasurementService."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from database.probe_models import ProbeMeasurementRecord
from services.monitor_models import MonitorCandidate, ProbeResult
from services.probe_measurement_service import (
    ProbeMeasurementService,
    RemoteResultWaitResult,
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
    mock.config.app.sentinel_probe_min_cn_probe_count = 3
    mock.config.app.sentinel_probe_required_success_ratio = 0.7
    mock.config.app.sentinel_probe_mode = "cn_probe_mesh"
    mock.config.app.sentinel_probe_allow_auto_heal_hy2 = False
    mock.config.app.probe_poll_interval_seconds = 1.0
    return mock


@pytest.fixture
def mock_probe_measurement_repo():
    """Create a mock ProbeMeasurementRepo."""
    return MagicMock()


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


class TestProbeMeasurementServiceCreateMeasurement:
    """Tests for create_measurement method."""

    def test_create_measurement_success(
        self,
        mock_runtime_context,
        mock_probe_measurement_repo,
        sample_candidate,
        sample_probe_result,
    ):
        """Should create measurement record with correct fields."""
        expected_record = ProbeMeasurementRecord(
            id=1,
            measurement_id="m-12345",
            xboard_node_id=12345,
            correlation_id="corr-001",
            control_plane_result={},
            final_status="collecting",
            reason="collecting_remote_probe_results",
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
            finished_at=None,
        )
        mock_probe_measurement_repo.create_measurement.return_value = expected_record

        with patch(
            "services.probe_measurement_service.ProbeMeasurementRepo",
            return_value=mock_probe_measurement_repo,
        ):
            service = ProbeMeasurementService(mock_runtime_context)
            result = service.create_measurement(
                candidate=sample_candidate,
                correlation_id="corr-001",
                control_plane_result=sample_probe_result,
            )

        assert result.measurement_id == "m-12345"
        assert result.xboard_node_id == 12345
        assert result.final_status == "collecting"
        mock_probe_measurement_repo.create_measurement.assert_called_once()


class TestProbeMeasurementServiceRecordRemoteResult:
    """Tests for record_remote_result method."""

    def test_record_remote_result_success(
        self, mock_runtime_context, mock_probe_measurement_repo
    ):
        """Should record remote probe result correctly."""
        result_payload = {
            "status": "reachable",
            "resolved_ip": "1.2.3.4",
            "latency_ms": 100,
        }

        with patch(
            "services.probe_measurement_service.ProbeMeasurementRepo",
            return_value=mock_probe_measurement_repo,
        ):
            service = ProbeMeasurementService(mock_runtime_context)
            service.record_remote_result(
                measurement_id="m-001",
                probe_id="probe-001",
                result_payload=result_payload,
            )

        mock_probe_measurement_repo.create_measurement_result.assert_called_once()
        call_args = mock_probe_measurement_repo.create_measurement_result.call_args[0][0]
        assert call_args.measurement_id == "m-001"
        assert call_args.probe_id == "probe-001"
        assert call_args.probe_status == "reachable"

    def test_record_remote_result_missing_status_defaults_to_inconclusive(
        self, mock_runtime_context, mock_probe_measurement_repo
    ):
        """Should default to probe_inconclusive when status is missing."""
        result_payload = {"latency_ms": 100}

        with patch(
            "services.probe_measurement_service.ProbeMeasurementRepo",
            return_value=mock_probe_measurement_repo,
        ):
            service = ProbeMeasurementService(mock_runtime_context)
            service.record_remote_result(
                measurement_id="m-001",
                probe_id="probe-001",
                result_payload=result_payload,
            )

        call_args = mock_probe_measurement_repo.create_measurement_result.call_args[0][0]
        assert call_args.probe_status == "probe_inconclusive"


class TestProbeMeasurementServiceWaitForRemoteResults:
    """Tests for wait_for_remote_results method."""

    def test_wait_for_remote_results_immediate_success(
        self, mock_runtime_context, mock_probe_measurement_repo
    ):
        """Should return immediately when enough results are available."""
        mock_probe_measurement_repo.list_measurement_results.return_value = [
            MagicMock(result={"status": "reachable"}),
            MagicMock(result={"status": "reachable"}),
            MagicMock(result={"status": "reachable"}),
        ]

        with patch(
            "services.probe_measurement_service.ProbeMeasurementRepo",
            return_value=mock_probe_measurement_repo,
        ):
            service = ProbeMeasurementService(mock_runtime_context)
            result = service.wait_for_remote_results(
                measurement_id="m-001",
                minimum_result_count=3,
                timeout_seconds=10.0,
                poll_interval_seconds=1.0,
            )

        assert result.timed_out is False
        assert len(result.results) == 3

    def test_wait_for_remote_results_timeout(
        self, mock_runtime_context, mock_probe_measurement_repo
    ):
        """Should timeout when not enough results arrive in time."""
        mock_probe_measurement_repo.list_measurement_results.return_value = [
            MagicMock(result={"status": "reachable"}),
        ]

        with patch(
            "services.probe_measurement_service.ProbeMeasurementRepo",
            return_value=mock_probe_measurement_repo,
        ), patch("time.sleep"), patch("time.monotonic", side_effect=[0, 0.5, 11.0]):
            service = ProbeMeasurementService(mock_runtime_context)
            result = service.wait_for_remote_results(
                measurement_id="m-001",
                minimum_result_count=3,
                timeout_seconds=10.0,
                poll_interval_seconds=1.0,
            )

        assert result.timed_out is True
        assert len(result.results) == 1

    def test_wait_for_remote_results_zero_minimum_returns_immediately(
        self, mock_runtime_context, mock_probe_measurement_repo
    ):
        """Should return immediately when minimum_result_count is 0."""
        with patch(
            "services.probe_measurement_service.ProbeMeasurementRepo",
            return_value=mock_probe_measurement_repo,
        ):
            service = ProbeMeasurementService(mock_runtime_context)
            result = service.wait_for_remote_results(
                measurement_id="m-001",
                minimum_result_count=0,
                timeout_seconds=10.0,
                poll_interval_seconds=1.0,
            )

        assert result.timed_out is False
        assert len(result.results) == 0


class TestProbeMeasurementServiceFinalizeMeasurement:
    """Tests for finalize_measurement method."""

    def test_finalize_measurement_healthy_all_probes_reachable(
        self,
        mock_runtime_context,
        mock_probe_measurement_repo,
        sample_candidate,
        sample_probe_result,
    ):
        """Should mark as healthy when control plane and all remote probes succeed."""
        measurement_record = ProbeMeasurementRecord(
            id=1,
            measurement_id="m-001",
            xboard_node_id=12345,
            correlation_id="corr-001",
            control_plane_result={},
            final_status="collecting",
            reason=None,
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
            finished_at=None,
        )

        remote_results = [
            {"status": "reachable"},
            {"status": "reachable"},
            {"status": "reachable"},
        ]

        finalized_record = ProbeMeasurementRecord(
            id=1,
            measurement_id="m-001",
            xboard_node_id=12345,
            correlation_id="corr-001",
            control_plane_result={},
            final_status="healthy",
            reason="国内探针均可达",
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
            finished_at="2026-03-24T00:00:10Z",
        )
        mock_probe_measurement_repo.finalize_measurement.return_value = finalized_record

        with patch(
            "services.probe_measurement_service.ProbeMeasurementRepo",
            return_value=mock_probe_measurement_repo,
        ):
            service = ProbeMeasurementService(mock_runtime_context)
            result = service.finalize_measurement(
                candidate=sample_candidate,
                measurement_record=measurement_record,
                control_plane_result=sample_probe_result,
                remote_results=remote_results,
            )

        assert result.final_status == "healthy"
        assert result.reason == "国内探针均可达"

    def test_finalize_measurement_confirmed_blocked_by_gfw(
        self,
        mock_runtime_context,
        mock_probe_measurement_repo,
        sample_candidate,
        sample_probe_result,
    ):
        """Should mark as confirmed_blocked_by_gfw when control plane succeeds but CN probes fail."""
        measurement_record = ProbeMeasurementRecord(
            id=1,
            measurement_id="m-001",
            xboard_node_id=12345,
            correlation_id="corr-001",
            control_plane_result={},
            final_status="collecting",
            reason=None,
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
            finished_at=None,
        )

        remote_results = [
            {"status": "origin_unreachable"},
            {"status": "origin_unreachable"},
            {"status": "origin_unreachable"},
        ]

        finalized_record = ProbeMeasurementRecord(
            id=1,
            measurement_id="m-001",
            xboard_node_id=12345,
            correlation_id="corr-001",
            control_plane_result={},
            final_status="confirmed_blocked_by_gfw",
            reason="海外可达且国内多探针连续失败",
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
            finished_at="2026-03-24T00:00:10Z",
        )
        mock_probe_measurement_repo.finalize_measurement.return_value = finalized_record

        with patch(
            "services.probe_measurement_service.ProbeMeasurementRepo",
            return_value=mock_probe_measurement_repo,
        ):
            service = ProbeMeasurementService(mock_runtime_context)
            result = service.finalize_measurement(
                candidate=sample_candidate,
                measurement_record=measurement_record,
                control_plane_result=sample_probe_result,
                remote_results=remote_results,
            )

        assert result.final_status == "confirmed_blocked_by_gfw"

    def test_finalize_measurement_origin_fault_control_plane_fails(
        self,
        mock_runtime_context,
        mock_probe_measurement_repo,
        sample_candidate,
    ):
        """Should mark as origin_fault when control plane probe fails."""
        measurement_record = ProbeMeasurementRecord(
            id=1,
            measurement_id="m-001",
            xboard_node_id=12345,
            correlation_id="corr-001",
            control_plane_result={},
            final_status="collecting",
            reason=None,
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
            finished_at=None,
        )

        control_plane_result = ProbeResult(
            provider="local_active_probe",
            status="origin_unreachable",
            reason="TCP 连接失败",
            success_region_count=0,
            failed_region_count=1,
        )

        remote_results = [
            {"status": "origin_unreachable"},
            {"status": "origin_unreachable"},
            {"status": "origin_unreachable"},
        ]

        finalized_record = ProbeMeasurementRecord(
            id=1,
            measurement_id="m-001",
            xboard_node_id=12345,
            correlation_id="corr-001",
            control_plane_result={},
            final_status="origin_fault",
            reason="海外控制面探测已失败，更像源站故障",
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
            finished_at="2026-03-24T00:00:10Z",
        )
        mock_probe_measurement_repo.finalize_measurement.return_value = finalized_record

        with patch(
            "services.probe_measurement_service.ProbeMeasurementRepo",
            return_value=mock_probe_measurement_repo,
        ):
            service = ProbeMeasurementService(mock_runtime_context)
            result = service.finalize_measurement(
                candidate=sample_candidate,
                measurement_record=measurement_record,
                control_plane_result=control_plane_result,
                remote_results=remote_results,
            )

        assert result.final_status == "origin_fault"

    def test_finalize_measurement_hysteria2_inconclusive(
        self,
        mock_runtime_context,
        mock_probe_measurement_repo,
        sample_probe_result,
    ):
        """Should mark Hysteria2 as inconclusive when auto-heal is disabled."""
        candidate = MonitorCandidate(
            xboard_node_id=12345,
            node_name="test-node",
            node_type="Hysteria2",
            asset_type="aws",
            domain_name="test.example.com",
            host="test.example.com",
            port="443",
            server_port=443,
            status="online",
            last_healed_at=None,
        )

        measurement_record = ProbeMeasurementRecord(
            id=1,
            measurement_id="m-001",
            xboard_node_id=12345,
            correlation_id="corr-001",
            control_plane_result={},
            final_status="collecting",
            reason=None,
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
            finished_at=None,
        )

        finalized_record = ProbeMeasurementRecord(
            id=1,
            measurement_id="m-001",
            xboard_node_id=12345,
            correlation_id="corr-001",
            control_plane_result={},
            final_status="probe_inconclusive",
            reason="Hysteria2 当前仅支持人工复核，不自动确诊或自愈",
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
            finished_at="2026-03-24T00:00:10Z",
        )
        mock_probe_measurement_repo.finalize_measurement.return_value = finalized_record

        with patch(
            "services.probe_measurement_service.ProbeMeasurementRepo",
            return_value=mock_probe_measurement_repo,
        ):
            service = ProbeMeasurementService(mock_runtime_context)
            result = service.finalize_measurement(
                candidate=candidate,
                measurement_record=measurement_record,
                control_plane_result=sample_probe_result,
                remote_results=[],
            )

        assert result.final_status == "probe_inconclusive"

    def test_finalize_measurement_local_active_probe_mode_healthy(
        self,
        mock_runtime_context,
        mock_probe_measurement_repo,
        sample_candidate,
        sample_probe_result,
    ):
        """Should mark as healthy in local_active_probe mode when control plane succeeds."""
        mock_runtime_context.config.app.sentinel_probe_mode = "local_active_probe"

        measurement_record = ProbeMeasurementRecord(
            id=1,
            measurement_id="m-001",
            xboard_node_id=12345,
            correlation_id="corr-001",
            control_plane_result={},
            final_status="collecting",
            reason=None,
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
            finished_at=None,
        )

        finalized_record = ProbeMeasurementRecord(
            id=1,
            measurement_id="m-001",
            xboard_node_id=12345,
            correlation_id="corr-001",
            control_plane_result={},
            final_status="healthy",
            reason="控制面本地主动探测成功",
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
            finished_at="2026-03-24T00:00:10Z",
        )
        mock_probe_measurement_repo.finalize_measurement.return_value = finalized_record

        with patch(
            "services.probe_measurement_service.ProbeMeasurementRepo",
            return_value=mock_probe_measurement_repo,
        ):
            service = ProbeMeasurementService(mock_runtime_context)
            result = service.finalize_measurement(
                candidate=sample_candidate,
                measurement_record=measurement_record,
                control_plane_result=sample_probe_result,
                remote_results=[],
            )

        assert result.final_status == "healthy"


class TestProbeMeasurementServiceCountRecentFailedCycles:
    """Tests for count_recent_failed_cycles method."""

    def test_count_recent_confirmed_blocked_cycles(
        self, mock_runtime_context, mock_probe_measurement_repo
    ):
        """Should count consecutive confirmed_blocked_by_gfw measurements."""
        mock_probe_measurement_repo.list_recent_measurements_for_node.return_value = [
            ProbeMeasurementRecord(
                id=3,
                measurement_id="m-003",
                xboard_node_id=12345,
                correlation_id="corr-003",
                control_plane_result={},
                final_status="confirmed_blocked_by_gfw",
                reason=None,
                created_at="2026-03-24T00:02:00Z",
                updated_at="2026-03-24T00:02:00Z",
                finished_at="2026-03-24T00:02:10Z",
            ),
            ProbeMeasurementRecord(
                id=2,
                measurement_id="m-002",
                xboard_node_id=12345,
                correlation_id="corr-002",
                control_plane_result={},
                final_status="confirmed_blocked_by_gfw",
                reason=None,
                created_at="2026-03-24T00:01:00Z",
                updated_at="2026-03-24T00:01:00Z",
                finished_at="2026-03-24T00:01:10Z",
            ),
            ProbeMeasurementRecord(
                id=1,
                measurement_id="m-001",
                xboard_node_id=12345,
                correlation_id="corr-001",
                control_plane_result={},
                final_status="healthy",
                reason=None,
                created_at="2026-03-24T00:00:00Z",
                updated_at="2026-03-24T00:00:00Z",
                finished_at="2026-03-24T00:00:10Z",
            ),
        ]

        with patch(
            "services.probe_measurement_service.ProbeMeasurementRepo",
            return_value=mock_probe_measurement_repo,
        ):
            service = ProbeMeasurementService(mock_runtime_context)
            count = service.count_recent_confirmed_blocked_cycles(
                xboard_node_id=12345, limit=10
            )

        assert count == 2

    def test_count_recent_failed_cycles_stops_at_first_non_match(
        self, mock_runtime_context, mock_probe_measurement_repo
    ):
        """Should stop counting when encountering a non-matching status."""
        mock_probe_measurement_repo.list_recent_measurements_for_node.return_value = [
            ProbeMeasurementRecord(
                id=2,
                measurement_id="m-002",
                xboard_node_id=12345,
                correlation_id="corr-002",
                control_plane_result={},
                final_status="origin_fault",
                reason=None,
                created_at="2026-03-24T00:01:00Z",
                updated_at="2026-03-24T00:01:00Z",
                finished_at="2026-03-24T00:01:10Z",
            ),
            ProbeMeasurementRecord(
                id=1,
                measurement_id="m-001",
                xboard_node_id=12345,
                correlation_id="corr-001",
                control_plane_result={},
                final_status="confirmed_blocked_by_gfw",
                reason=None,
                created_at="2026-03-24T00:00:00Z",
                updated_at="2026-03-24T00:00:00Z",
                finished_at="2026-03-24T00:00:10Z",
            ),
        ]

        with patch(
            "services.probe_measurement_service.ProbeMeasurementRepo",
            return_value=mock_probe_measurement_repo,
        ):
            service = ProbeMeasurementService(mock_runtime_context)
            count = service.count_recent_failed_cycles(
                xboard_node_id=12345,
                limit=10,
                status_filter="origin_fault",
            )

        assert count == 1
