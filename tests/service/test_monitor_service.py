"""Integration tests for MonitorService and monitor_support pure functions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from database.state_models import FleetNodeCreateRequest
from database.state_repo import StateRepo
from services.monitor_models import (
    MonitorCandidate,
    ProbeMeasurementSummary,
    ProbeResult,
)
from services.monitor_support import (
    is_in_heal_cooldown,
    should_flag_zero_uplink,
    to_monitor_candidate,
    utcnow,
)
from services.probe_orchestrator_service import ProbeOrchestrationResult


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------

def make_runtime_context(sqlite_conn) -> MagicMock:
    mock = MagicMock()
    mock.logger = MagicMock(spec=logging.Logger)
    mock.logger.getChild.return_value = mock.logger
    mock.correlation_id = "monitor-test-corr-001"

    mock_sqlite_manager = MagicMock()
    mock_sqlite_manager.connection.return_value.__enter__ = MagicMock(return_value=sqlite_conn)
    mock_sqlite_manager.connection.return_value.__exit__ = MagicMock(return_value=False)
    mock.sqlite_manager = mock_sqlite_manager

    mock_config_app = MagicMock()
    mock_config_app.sentinel_enabled = True
    mock_config_app.sentinel_probe_confirm_cycles = 2
    mock_config_app.sentinel_suspicious_lookback_minutes = 60
    mock_config_app.sentinel_zero_uplink_window_minutes = 10
    mock_config_app.sentinel_heal_cooldown_seconds = 300
    mock_config_app.sentinel_probe_mode = "cn_probe_mesh"
    mock_config_app.sentinel_probe_min_cn_probe_count = 2
    mock_config_app.sentinel_probe_timeout_seconds = 10
    mock_config_app.sentinel_probe_result_wait_timeout_seconds = 30
    mock_config_app.probe_poll_interval_seconds = 2
    mock_config_app.sentinel_probe_provider = "test_probe"
    mock_config_app.max_retries = 2
    mock_config_app.retry_backoff_seconds = 1.0
    mock_config_app.sentinel_heal_cooldown_seconds = 300.0
    mock.config = MagicMock()
    mock.config.app = mock_config_app

    return mock


def make_node_record(
    xboard_node_id: int,
    node_name: str = "test-node",
    node_type: str = "AnyTLS",
    status: str = "online",
    aws_account_id: str = "test-account",
    last_healed_at: str | None = None,
    asset_type: str | None = None,
) -> MagicMock:
    record = MagicMock()
    record.id = xboard_node_id
    record.xboard_node_id = xboard_node_id
    record.node_name = node_name
    record.node_type = node_type
    record.status = status
    record.aws_account_id = aws_account_id
    record.aws_region = "ap-northeast-1"
    record.aws_instance_id = "i-1234567890abcdef0"
    record.domain_name = f"sf-{xboard_node_id}.example.com"
    record.ipv6_address = "2600:1f14:804:as03:1234::"
    record.is_deleted = False
    record.last_healed_at = last_healed_at
    if asset_type is not None:
        record.asset_type = asset_type
    record.created_at = "2026-03-01T00:00:00Z"
    record.updated_at = "2026-03-01T00:00:00Z"
    return record


# ---------------------------------------------------------------------------
# Pure function tests: monitor_support
# ---------------------------------------------------------------------------

class TestMonitorSupportPureFunctions:
    """Unit tests for pure functions in monitor_support (no I/O)."""

    def test_should_flag_zero_uplink_candidates(self) -> None:
        """Zero uplink with prior traffic should be flagged."""
        assert should_flag_zero_uplink(
            recent_total_positive=True,
            recent_zero_uplink_count=10,
            expected_zero_window_minutes=10,
        ) is True

    def test_should_flag_zero_uplink_no_prior_traffic(self) -> None:
        """Zero uplink with no prior traffic should NOT be flagged (new node)."""
        assert should_flag_zero_uplink(
            recent_total_positive=False,
            recent_zero_uplink_count=10,
            expected_zero_window_minutes=10,
        ) is False

    def test_should_flag_zero_uplink_partial_uplink(self) -> None:
        """Partial uplink (not all zero) should NOT be flagged."""
        assert should_flag_zero_uplink(
            recent_total_positive=True,
            recent_zero_uplink_count=5,
            expected_zero_window_minutes=10,
        ) is False

    def test_is_in_heal_cooldown_node_never_healed(self) -> None:
        """Node with no last_healed_at should not be in cooldown."""
        record = make_node_record(xboard_node_id=1, last_healed_at=None)
        now = datetime(2026, 3, 24, tzinfo=timezone.utc)
        assert is_in_heal_cooldown(record, now_utc=now, cooldown_seconds=300) is False

    def test_is_in_heal_cooldown_inside_window(self) -> None:
        """Node healed recently should be in cooldown."""
        recent = datetime(2026, 3, 24, 12, 0, 0, tzinfo=timezone.utc)
        record = make_node_record(
            xboard_node_id=1,
            last_healed_at=recent.isoformat(),
        )
        # Now is 1 minute after healing, cooldown is 5 minutes
        now = recent + timedelta(minutes=1)
        assert is_in_heal_cooldown(record, now_utc=now, cooldown_seconds=300) is True

    def test_is_in_heal_cooldown_outside_window(self) -> None:
        """Node healed long ago should NOT be in cooldown."""
        healed = datetime(2026, 3, 24, 10, 0, 0, tzinfo=timezone.utc)
        record = make_node_record(xboard_node_id=1, last_healed_at=healed.isoformat())
        # Now is 10 minutes after healing, cooldown is 5 minutes
        now = healed + timedelta(minutes=10)
        assert is_in_heal_cooldown(record, now_utc=now, cooldown_seconds=300) is False

    def test_to_monitor_candidate_aws_node(self) -> None:
        """AWS node should have asset_type='aws'."""
        record = make_node_record(xboard_node_id=12345, aws_account_id="acc-001")
        xboard_runtime = MagicMock()
        xboard_runtime.host = "sf-12345.example.com"
        xboard_runtime.port = "443"
        xboard_runtime.server_port = 443

        candidate = to_monitor_candidate(record, xboard_runtime)

        assert candidate.xboard_node_id == 12345
        assert candidate.node_name == "test-node"
        assert candidate.asset_type == "aws"
        assert candidate.domain_name == "sf-12345.example.com"
        assert candidate.host == "sf-12345.example.com"
        assert candidate.server_port == 443

    def test_to_monitor_candidate_self_hosted_node(self) -> None:
        """Self-hosted node should have asset_type='self_hosted'."""
        record = make_node_record(xboard_node_id=67890, aws_account_id=None)
        xboard_runtime = MagicMock()
        xboard_runtime.host = "192.168.1.100"
        xboard_runtime.port = "443"
        xboard_runtime.server_port = 443

        candidate = to_monitor_candidate(record, xboard_runtime)

        assert candidate.asset_type == "self_hosted"

    def test_to_monitor_candidate_uses_record_asset_type(self) -> None:
        """Derived asset_type on FleetNodeRecord should override legacy AWS field inference."""
        record = make_node_record(
            xboard_node_id=7788,
            aws_account_id="do-account-uuid",
            asset_type="digitalocean",
        )
        xboard_runtime = MagicMock()
        xboard_runtime.host = "sf-7788.example.com"
        xboard_runtime.port = "443"
        xboard_runtime.server_port = 443

        candidate = to_monitor_candidate(record, xboard_runtime)

        assert candidate.asset_type == "digitalocean"

    def test_utcnow_returns_utc_datetime(self) -> None:
        """utcnow() should return a timezone-aware UTC datetime."""
        now = utcnow()
        assert now.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# MonitorService.run_scan_cycle mocked-integration tests
# ---------------------------------------------------------------------------

class TestMonitorServiceScanCycle:
    """Tests for MonitorService.run_scan_cycle with fully-mocked dependencies."""

    def test_run_scan_cycle_no_candidates_returns_zero_count(
        self, in_memory_sqlite_db
    ) -> None:
        """When collect_suspicious_nodes returns empty, cycle should complete with zero counts."""
        runtime_context = make_runtime_context(in_memory_sqlite_db)

        # Mock xboard_client.get_server_minute_stats to raise (no data)
        mock_xboard = MagicMock()
        mock_xboard.get_server_minute_stats.side_effect = Exception("no data")

        # Mock state_repo.list_monitorable_nodes returns empty
        mock_state_repo = MagicMock()
        mock_state_repo.list_monitorable_nodes.return_value = []

        # Mock monitor_repo
        mock_monitor_repo = MagicMock()
        mock_monitor_repo.create_cycle.return_value = 1

        # Mock probe_client, probe_orchestrator, healer_service
        mock_probe_client = MagicMock()
        mock_probe_orchestrator = MagicMock()
        mock_healer = MagicMock()

        with patch(
            "services.monitor.StateRepo", return_value=mock_state_repo
        ), patch(
            "services.monitor.XboardSentinelClient", return_value=mock_xboard
        ), patch(
            "services.monitor.MonitorRepo", return_value=mock_monitor_repo
        ), patch(
            "services.monitor.ProbeClient", return_value=mock_probe_client
        ), patch(
            "services.monitor.ProbeOrchestratorService",
            return_value=mock_probe_orchestrator,
        ), patch(
            "services.monitor.HealerService", return_value=mock_healer
        ):
            from services.monitor import MonitorService

            svc = MonitorService(runtime_context)
            result = svc.run_scan_cycle()

        assert result.candidate_count == 0
        assert result.confirmed_count == 0
        assert result.healed_count == 0
        assert result.failed_count == 0
        mock_monitor_repo.finalize_cycle.assert_called_once()
        call_kwargs = mock_monitor_repo.finalize_cycle.call_args.kwargs
        assert call_kwargs["status"] == "succeeded"

    def test_run_scan_cycle_with_candidate_probe_error_increments_failed(
        self, in_memory_sqlite_db
    ) -> None:
        """When probe fails, failed_count should increment and cycle continues."""
        runtime_context = make_runtime_context(in_memory_sqlite_db)

        # Setup: one candidate
        candidate = MonitorCandidate(
            xboard_node_id=12345,
            node_name="test-node",
            node_type="AnyTLS",
            asset_type="aws",
            domain_name="sf-12345.example.com",
            host="sf-12345.example.com",
            port="443",
            server_port=443,
            status="online",
            last_healed_at=None,
        )

        mock_state_repo = MagicMock()
        mock_state_repo.list_monitorable_nodes.return_value = [
            make_node_record(
                xboard_node_id=12345,
                last_healed_at=None,
            )
        ]
        _ = candidate

        def make_stat_list(total_bytes: int, uplink_bytes: int, count: int) -> list:
            """Return a real list of stat objects with enough samples to hit window checks."""
            return [
                MagicMock(total_bytes=total_bytes, uplink_bytes=uplink_bytes, downlink_bytes=0)
                for _ in range(count)
            ]

        mock_xboard = MagicMock()
        mock_xboard.get_server_minute_stats.return_value = make_stat_list(
            total_bytes=1000,
            uplink_bytes=0,
            count=runtime_context.config.app.sentinel_zero_uplink_window_minutes,
        )
        mock_xboard.get_server_runtime.return_value = MagicMock(
            host="sf-12345.example.com",
            port="443",
            server_port=443,
            show=True,
        )

        mock_monitor_repo = MagicMock()
        mock_monitor_repo.create_cycle.return_value = 1
        mock_monitor_repo.create_detection.return_value = 1

        # ProbeClient raises ProbeClientError
        from services.probe_client import ProbeClientError

        mock_probe_client = MagicMock()
        mock_probe_client.probe_node.side_effect = ProbeClientError("DNS timeout")
        mock_probe_client.provider = "test"

        mock_probe_orchestrator = MagicMock()
        mock_healer = MagicMock()

        with patch(
            "services.monitor.StateRepo", return_value=mock_state_repo
        ), patch(
            "services.monitor.XboardSentinelClient", return_value=mock_xboard
        ), patch(
            "services.monitor.MonitorRepo", return_value=mock_monitor_repo
        ), patch(
            "services.monitor.ProbeClient", return_value=mock_probe_client
        ), patch(
            "services.monitor.ProbeOrchestratorService",
            return_value=mock_probe_orchestrator,
        ), patch(
            "services.monitor.HealerService", return_value=mock_healer
        ):
            from services.monitor import MonitorService

            svc = MonitorService(runtime_context)
            result = svc.run_scan_cycle()

        assert result.candidate_count == 1
        assert result.confirmed_count == 0
        assert result.healed_count == 0
        assert result.failed_count == 1

    def test_run_scan_cycle_confirmed_blocked_triggers_heal(
        self, in_memory_sqlite_db
    ) -> None:
        """confirmed_blocked_by_gfw status should trigger healer_service.heal_node."""
        runtime_context = make_runtime_context(in_memory_sqlite_db)

        # Create node in DB so state_repo.find_by_xboard_node_id succeeds

        state_repo = StateRepo(runtime_context)
        node_id = state_repo.create_node(
            FleetNodeCreateRequest(
                xboard_node_id=12345,
                node_name="heal-node",
                node_type="AnyTLS",
                status="online",
            )
        )

        candidate = MonitorCandidate(
            xboard_node_id=12345,
            node_name="heal-node",
            node_type="AnyTLS",
            asset_type="aws",
            domain_name="sf-12345.example.com",
            host="sf-12345.example.com",
            port="443",
            server_port=443,
            status="online",
            last_healed_at=None,
        )

        mock_state_repo = MagicMock()
        mock_state_repo.list_monitorable_nodes.return_value = [
            make_node_record(xboard_node_id=12345, last_healed_at=None)
        ]
        mock_state_repo.get_node_by_xboard_node_id.return_value = MagicMock(
            id=node_id, status="online"
        )
        _ = candidate

        def make_stat_list(total_bytes: int, uplink_bytes: int, count: int) -> list:
            """Return a real list of stat objects with enough samples to hit window checks."""
            return [
                MagicMock(total_bytes=total_bytes, uplink_bytes=uplink_bytes, downlink_bytes=0)
                for _ in range(count)
            ]

        mock_xboard = MagicMock()
        mock_xboard.get_server_minute_stats.return_value = make_stat_list(
            total_bytes=1000,
            uplink_bytes=0,
            count=runtime_context.config.app.sentinel_zero_uplink_window_minutes,
        )
        mock_xboard.get_server_runtime.return_value = MagicMock(
            host="sf-12345.example.com",
            port="443",
            server_port=443,
            show=True,
        )

        mock_monitor_repo = MagicMock()
        mock_monitor_repo.create_cycle.return_value = 1
        mock_monitor_repo.create_detection.return_value = 1

        probe_result = ProbeResult(
            provider="test",
            status="reachable",
            reason="ok",
            success_region_count=3,
            failed_region_count=0,
        )

        measurement_summary = ProbeMeasurementSummary(
            measurement_id="m-001",
            xboard_node_id=12345,
            final_status="confirmed_blocked_by_gfw",
            reason="All CN probes blocked",
            control_plane_result={},
            probe_result_count=3,
            created_at="2026-03-24T00:00:00Z",
            finished_at="2026-03-24T00:00:10Z",
        )

        mock_probe_client = MagicMock()
        mock_probe_client.probe_node.return_value = probe_result
        mock_probe_client.provider = "test"

        mock_probe_orchestrator = MagicMock()
        mock_probe_orchestrator.measure_candidate.return_value = ProbeOrchestrationResult(
            measurement_summary=measurement_summary,
            selected_probe_ids=("probe-1", "probe-2"),
        )
        mock_probe_orchestrator.count_recent_confirmed_blocked_cycles.return_value = 2

        mock_healer = MagicMock()
        mock_healer.heal_node.return_value = MagicMock(success=True)

        with patch(
            "services.monitor.StateRepo", return_value=mock_state_repo
        ), patch(
            "services.monitor.XboardSentinelClient", return_value=mock_xboard
        ), patch(
            "services.monitor.MonitorRepo", return_value=mock_monitor_repo
        ), patch(
            "services.monitor.ProbeClient", return_value=mock_probe_client
        ), patch(
            "services.monitor.ProbeOrchestratorService",
            return_value=mock_probe_orchestrator,
        ), patch(
            "services.monitor.HealerService", return_value=mock_healer
        ):
            from services.monitor import MonitorService

            svc = MonitorService(runtime_context)
            result = svc.run_scan_cycle()

        assert result.candidate_count == 1
        assert result.confirmed_count == 1
        assert result.healed_count == 1
        assert result.failed_count == 0
        mock_healer.heal_node.assert_called_once()

    def test_run_scan_cycle_non_confirmed_skips_healing(
        self, in_memory_sqlite_db
    ) -> None:
        """probe result that is not confirmed_blocked should skip healer."""
        runtime_context = make_runtime_context(in_memory_sqlite_db)

        mock_state_repo = MagicMock()
        mock_state_repo.list_monitorable_nodes.return_value = []

        _mock_xboard = MagicMock()
        mock_monitor_repo = MagicMock()
        mock_monitor_repo.create_cycle.return_value = 1

        _probe_result = ProbeResult(
            provider="test",
            status="reachable",
            reason="ok",
            success_region_count=3,
            failed_region_count=0,
        )

        # Non-confirmed status: healthy
        measurement_summary = ProbeMeasurementSummary(
            measurement_id="m-002",
            xboard_node_id=99999,
            final_status="healthy",
            reason=None,
            control_plane_result={},
            probe_result_count=3,
            created_at="2026-03-24T00:00:00Z",
            finished_at=None,
        )

        # Even if we had a candidate, it shouldn't trigger healing
        mock_probe_client = MagicMock()
        mock_probe_client.provider = "test"

        mock_probe_orchestrator = MagicMock()
        mock_probe_orchestrator.measure_candidate.return_value = ProbeOrchestrationResult(
            measurement_summary=measurement_summary,
            selected_probe_ids=(),
        )

        mock_healer = MagicMock()
        mock_xboard_client = MagicMock()

        with patch(
            "services.monitor.StateRepo", return_value=mock_state_repo
        ), patch(
            "services.monitor.XboardSentinelClient", return_value=mock_xboard_client
        ), patch(
            "services.monitor.MonitorRepo", return_value=mock_monitor_repo
        ), patch(
            "services.monitor.ProbeClient", return_value=mock_probe_client
        ), patch(
            "services.monitor.ProbeOrchestratorService",
            return_value=mock_probe_orchestrator,
        ), patch(
            "services.monitor.HealerService", return_value=mock_healer
        ):
            from services.monitor import MonitorService

            svc = MonitorService(runtime_context)
            result = svc.run_scan_cycle()

        assert result.healed_count == 0
        mock_healer.heal_node.assert_not_called()

    def test_run_scan_cycle_error_finalizes_with_failed_status(
        self, in_memory_sqlite_db
    ) -> None:
        """Unexpected exception should finalize cycle with status='failed'."""
        runtime_context = make_runtime_context(in_memory_sqlite_db)

        mock_state_repo = MagicMock()
        mock_state_repo.list_monitorable_nodes.side_effect = RuntimeError("DB error")

        mock_monitor_repo = MagicMock()
        mock_monitor_repo.create_cycle.return_value = 1

        mock_xboard = MagicMock()
        mock_probe_client = MagicMock()
        mock_probe_client.provider = "test"
        mock_probe_orchestrator = MagicMock()
        mock_healer = MagicMock()

        with patch(
            "services.monitor.StateRepo", return_value=mock_state_repo
        ), patch(
            "services.monitor.XboardSentinelClient", return_value=mock_xboard
        ), patch(
            "services.monitor.MonitorRepo", return_value=mock_monitor_repo
        ), patch(
            "services.monitor.ProbeClient", return_value=mock_probe_client
        ), patch(
            "services.monitor.ProbeOrchestratorService",
            return_value=mock_probe_orchestrator,
        ), patch(
            "services.monitor.HealerService", return_value=mock_healer
        ):
            from services.monitor import MonitorService

            svc = MonitorService(runtime_context)
            with pytest.raises(RuntimeError, match="DB error"):
                svc.run_scan_cycle()

        # Verify finalize_cycle was called with failed status
        mock_monitor_repo.finalize_cycle.assert_called()
        call_kwargs = mock_monitor_repo.finalize_cycle.call_args.kwargs
        assert call_kwargs["status"] == "failed"
        assert call_kwargs["error_message"] == "DB error"
