"""Integration tests for DashboardService."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from database.state_models import FleetNodeCreateRequest
from database.state_repo import FleetNodeEventCreateRequest, StateRepo


def _make_runtime_context(sqlite_conn) -> MagicMock:
    mock = MagicMock()
    mock.logger = MagicMock(spec=logging.Logger)
    mock.logger.getChild.return_value = mock.logger
    mock.correlation_id = "dashboard-test-001"

    mock_sqlite_manager = MagicMock()
    mock_sqlite_manager.connection.return_value.__enter__ = MagicMock(return_value=sqlite_conn)
    mock_sqlite_manager.connection.return_value.__exit__ = MagicMock(return_value=False)
    mock.sqlite_manager = mock_sqlite_manager

    # fleet_matrix config for _build_region_protocol_rows
    mock_fleet_matrix = {
        "ap-east-1": {
            "AnyTLS": MagicMock(desired_count=3, min_alert_threshold=2),
            "Shadowsocks": MagicMock(desired_count=2, min_alert_threshold=1),
        },
        "us-east-1": {
            "AnyTLS": MagicMock(desired_count=2, min_alert_threshold=1),
        },
    }
    mock_config_app = MagicMock()
    mock_config_app.probe_heartbeat_timeout_seconds = 60
    mock_config_app.sentinel_probe_provider = "test"

    mock.config = MagicMock()
    mock.config.fleet_matrix = mock_fleet_matrix
    mock.config.app = mock_config_app

    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDashboardServiceListRecentNodeEvents:
    """Tests for list_recent_node_events()."""

    def test_list_recent_node_events_returns_events(
        self, in_memory_sqlite_db
    ) -> None:
        runtime_context = _make_runtime_context(in_memory_sqlite_db)
        state_repo = StateRepo(runtime_context)
        node_id = state_repo.create_node(
            FleetNodeCreateRequest(
                xboard_node_id=111,
                node_name="event-node",
                node_type="AnyTLS",
                status="online",
            )
        )

        # Create a few events
        for i in range(3):
            state_repo.create_event(
                FleetNodeEventCreateRequest(
                    node_id=node_id,
                    xboard_node_id=111,
                    event_type=f"test_event_{i}",
                    correlation_id=f"corr-{i}",
                    from_status="online",
                    to_status="online",
                    message=f"Message {i}",
                )
            )

        # Patch probe_repo and monitor_repo so DashboardService can init
        mock_probe_repo = MagicMock()
        mock_probe_repo.list_probes.return_value = []
        mock_probe_repo.list_recent_measurements.return_value = []

        mock_monitor_repo = MagicMock()
        mock_monitor_repo.get_latest_cycle.return_value = None

        with patch(
            "services.dashboard_service.ProbeRepo", return_value=mock_probe_repo
        ), patch(
            "services.dashboard_service.MonitorRepo", return_value=mock_monitor_repo
        ):
            from services.dashboard_service import DashboardService

            svc = DashboardService(runtime_context)
            events = svc.list_recent_node_events(xboard_node_id=111, limit=10)

        assert len(events) == 3
        assert events[0].event_type == "test_event_2"  # DESC order
        assert events[0].message == "Message 2"

    def test_list_recent_node_events_respects_limit(
        self, in_memory_sqlite_db
    ) -> None:
        runtime_context = _make_runtime_context(in_memory_sqlite_db)
        state_repo = StateRepo(runtime_context)
        node_id = state_repo.create_node(
            FleetNodeCreateRequest(
                xboard_node_id=222,
                node_name="limit-test-node",
                node_type="AnyTLS",
                status="online",
            )
        )

        for i in range(5):
            state_repo.create_event(
                FleetNodeEventCreateRequest(
                    node_id=node_id,
                    xboard_node_id=222,
                    event_type=f"event_{i}",
                    correlation_id=f"corr-{i}",
                    from_status="online",
                    to_status="online",
                    message=f"Msg {i}",
                )
            )

        mock_probe_repo = MagicMock()
        mock_probe_repo.list_probes.return_value = []
        mock_probe_repo.list_recent_measurements.return_value = []
        mock_monitor_repo = MagicMock()
        mock_monitor_repo.get_latest_cycle.return_value = None

        with patch(
            "services.dashboard_service.ProbeRepo", return_value=mock_probe_repo
        ), patch(
            "services.dashboard_service.MonitorRepo", return_value=mock_monitor_repo
        ):
            from services.dashboard_service import DashboardService

            svc = DashboardService(runtime_context)
            events = svc.list_recent_node_events(xboard_node_id=222, limit=2)

        assert len(events) == 2


class TestDashboardServiceBuildSnapshot:
    """Tests for build_snapshot() and its sub-methods."""

    def test_build_overview_counts_online_nodes(
        self, in_memory_sqlite_db
    ) -> None:
        runtime_context = _make_runtime_context(in_memory_sqlite_db)
        state_repo = StateRepo(runtime_context)

        # Create nodes with different statuses
        state_repo.create_node(
            FleetNodeCreateRequest(xboard_node_id=1, node_name="n1", node_type="AnyTLS", status="online")
        )
        state_repo.create_node(
            FleetNodeCreateRequest(xboard_node_id=2, node_name="n2", node_type="AnyTLS", status="online")
        )
        state_repo.create_node(
            FleetNodeCreateRequest(xboard_node_id=3, node_name="n3", node_type="AnyTLS", status="healing")
        )
        state_repo.create_node(
            FleetNodeCreateRequest(xboard_node_id=4, node_name="n4", node_type="AnyTLS", status="offline")
        )
        state_repo.create_node(
            FleetNodeCreateRequest(xboard_node_id=5, node_name="n5", node_type="AnyTLS", status="failed")
        )

        mock_probe_repo = MagicMock()
        mock_probe_repo.list_probes.return_value = []
        mock_probe_repo.list_recent_measurements.return_value = []
        mock_monitor_repo = MagicMock()
        mock_monitor_repo.get_latest_cycle.return_value = None

        with patch(
            "services.dashboard_service.ProbeRepo", return_value=mock_probe_repo
        ), patch(
            "services.dashboard_service.MonitorRepo", return_value=mock_monitor_repo
        ):
            from services.dashboard_service import DashboardService

            svc = DashboardService(runtime_context)
            snapshot = svc.build_snapshot()

        assert snapshot.overview.total_node_count == 5
        assert snapshot.overview.online_node_count == 2
        assert snapshot.overview.healing_node_count == 1
        assert snapshot.overview.offline_or_failed_node_count == 2

    def test_node_rows_use_allocated_asset_type(
        self, in_memory_sqlite_db
    ) -> None:
        runtime_context = _make_runtime_context(in_memory_sqlite_db)
        state_repo = StateRepo(runtime_context)
        fleet_node_id = state_repo.create_node(
            FleetNodeCreateRequest(
                xboard_node_id=9090,
                node_name="do-node",
                node_type="AnyTLS",
                status="online",
                aws_account_id="do-account-uuid",
                aws_region="sgp1",
                aws_instance_id="do-droplet-9090",
            )
        )
        timestamp = "2026-03-23T10:00:00Z"
        cursor = in_memory_sqlite_db.execute(
            """
            INSERT INTO fleet_assets (
                asset_type, asset_name, status, region, aws_account_id,
                aws_access_key, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "digitalocean",
                "do-sgp1",
                "active",
                "sgp1",
                "do-account-uuid",
                "dop_v1_test",
                timestamp,
                timestamp,
            ),
        )
        asset_id = int(cursor.lastrowid)
        in_memory_sqlite_db.execute(
            """
            INSERT INTO fleet_asset_allocations (
                asset_id, fleet_node_id, xboard_node_id, protocol_type,
                allocation_status, vcpu_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (asset_id, fleet_node_id, 9090, "AnyTLS", "allocated", 2, timestamp, timestamp),
        )
        in_memory_sqlite_db.commit()

        mock_probe_repo = MagicMock()
        mock_probe_repo.list_probes.return_value = []
        mock_probe_repo.list_recent_measurements.return_value = []
        mock_monitor_repo = MagicMock()
        mock_monitor_repo.get_latest_cycle.return_value = None

        with patch(
            "services.dashboard_service.ProbeRepo", return_value=mock_probe_repo
        ), patch(
            "services.dashboard_service.MonitorRepo", return_value=mock_monitor_repo
        ):
            from services.dashboard_service import DashboardService

            svc = DashboardService(runtime_context)
            snapshot = svc.build_snapshot()

        node_row = next(row for row in snapshot.node_rows if row.xboard_node_id == 9090)
        assert node_row.asset_type == "digitalocean"

    def test_node_rows_derive_vultr_type_without_allocation(
        self, in_memory_sqlite_db
    ) -> None:
        runtime_context = _make_runtime_context(in_memory_sqlite_db)
        state_repo = StateRepo(runtime_context)
        state_repo.create_node(
            FleetNodeCreateRequest(
                xboard_node_id=9091,
                node_name="vultr-node",
                node_type="AnyTLS",
                status="provisioning",
                aws_account_id="vultr:token-fingerprint",
                aws_region="sgp",
                aws_instance_id="vultr-instance-9091",
            )
        )

        mock_probe_repo = MagicMock()
        mock_probe_repo.list_probes.return_value = []
        mock_probe_repo.list_recent_measurements.return_value = []
        mock_monitor_repo = MagicMock()
        mock_monitor_repo.get_latest_cycle.return_value = None

        with patch(
            "services.dashboard_service.ProbeRepo", return_value=mock_probe_repo
        ), patch(
            "services.dashboard_service.MonitorRepo", return_value=mock_monitor_repo
        ):
            from services.dashboard_service import DashboardService

            snapshot = DashboardService(runtime_context).build_snapshot()

        node_row = next(row for row in snapshot.node_rows if row.xboard_node_id == 9091)
        assert node_row.asset_type == "vultr"

    def test_node_rows_derive_azure_type_without_allocation(
        self, in_memory_sqlite_db
    ) -> None:
        runtime_context = _make_runtime_context(in_memory_sqlite_db)
        state_repo = StateRepo(runtime_context)
        state_repo.create_node(
            FleetNodeCreateRequest(
                xboard_node_id=9092,
                node_name="azure-node",
                node_type="Trojan",
                status="provisioning",
                aws_account_id="azure:subscription-id",
                aws_region="japaneast",
                aws_instance_id="/subscriptions/subscription-id/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/node",
            )
        )

        mock_probe_repo = MagicMock()
        mock_probe_repo.list_probes.return_value = []
        mock_probe_repo.list_recent_measurements.return_value = []
        mock_monitor_repo = MagicMock()
        mock_monitor_repo.get_latest_cycle.return_value = None

        with patch(
            "services.dashboard_service.ProbeRepo", return_value=mock_probe_repo
        ), patch(
            "services.dashboard_service.MonitorRepo", return_value=mock_monitor_repo
        ):
            from services.dashboard_service import DashboardService

            snapshot = DashboardService(runtime_context).build_snapshot()

        node_row = next(row for row in snapshot.node_rows if row.xboard_node_id == 9092)
        assert node_row.asset_type == "azure"

    def test_build_overview_survival_rate(self, in_memory_sqlite_db) -> None:
        runtime_context = _make_runtime_context(in_memory_sqlite_db)
        state_repo = StateRepo(runtime_context)

        # Create 3 nodes, 1 online => 1/3 survival rate
        for i in range(3):
            status = "online" if i == 0 else "offline"
            state_repo.create_node(
                FleetNodeCreateRequest(
                    xboard_node_id=10 + i,
                    node_name=f"surv-{i}",
                    node_type="AnyTLS",
                    status=status,
                )
            )

        mock_probe_repo = MagicMock()
        mock_probe_repo.list_probes.return_value = []
        mock_probe_repo.list_recent_measurements.return_value = []
        mock_monitor_repo = MagicMock()
        mock_monitor_repo.get_latest_cycle.return_value = None

        with patch(
            "services.dashboard_service.ProbeRepo", return_value=mock_probe_repo
        ), patch(
            "services.dashboard_service.MonitorRepo", return_value=mock_monitor_repo
        ):
            from services.dashboard_service import DashboardService

            svc = DashboardService(runtime_context)
            snapshot = svc.build_snapshot()

        # fleet_matrix from _make_runtime_context: ap-east-1/AnyTLS=3, Shadowsocks=2, us-east-1/AnyTLS=2 => 7 total
        assert snapshot.overview.overall_survival_rate == pytest.approx(1 / 7)

    def test_build_region_protocol_rows_healthy_alert_level(
        self, in_memory_sqlite_db
    ) -> None:
        runtime_context = _make_runtime_context(in_memory_sqlite_db)
        state_repo = StateRepo(runtime_context)

        # Create nodes matching desired count for ap-east-1 / AnyTLS
        # desired_count=3, min_alert_threshold=2
        for i in range(3):
            state_repo.create_node(
                FleetNodeCreateRequest(
                    xboard_node_id=100 + i,
                    node_name=f"proto-{i}",
                    node_type="AnyTLS",
                    status="online",
                    aws_region="ap-east-1",
                )
            )

        mock_probe_repo = MagicMock()
        mock_probe_repo.list_probes.return_value = []
        mock_probe_repo.list_recent_measurements.return_value = []
        mock_monitor_repo = MagicMock()
        mock_monitor_repo.get_latest_cycle.return_value = None

        with patch(
            "services.dashboard_service.ProbeRepo", return_value=mock_probe_repo
        ), patch(
            "services.dashboard_service.MonitorRepo", return_value=mock_monitor_repo
        ):
            from services.dashboard_service import DashboardService

            svc = DashboardService(runtime_context)
            snapshot = svc.build_snapshot()

        region_rows = {
            (r.region, r.protocol_type): r
            for r in snapshot.region_protocol_rows
        }
        ap_anytls = region_rows[("ap-east-1", "AnyTLS")]
        assert ap_anytls.alert_level == "healthy"
        assert ap_anytls.online_count == 3
        assert ap_anytls.survival_rate == 1.0
        assert ap_anytls.gap_count == 0

    def test_build_region_protocol_rows_critical_alert_level(
        self, in_memory_sqlite_db
    ) -> None:
        runtime_context = _make_runtime_context(in_memory_sqlite_db)
        state_repo = StateRepo(runtime_context)

        # Create only 1 node for ap-east-1/AnyTLS (threshold=2, so critical)
        state_repo.create_node(
            FleetNodeCreateRequest(
                xboard_node_id=200,
                node_name="low-node",
                node_type="AnyTLS",
                status="online",
                aws_region="ap-east-1",
            )
        )

        mock_probe_repo = MagicMock()
        mock_probe_repo.list_probes.return_value = []
        mock_probe_repo.list_recent_measurements.return_value = []
        mock_monitor_repo = MagicMock()
        mock_monitor_repo.get_latest_cycle.return_value = None

        with patch(
            "services.dashboard_service.ProbeRepo", return_value=mock_probe_repo
        ), patch(
            "services.dashboard_service.MonitorRepo", return_value=mock_monitor_repo
        ):
            from services.dashboard_service import DashboardService

            svc = DashboardService(runtime_context)
            snapshot = svc.build_snapshot()

        region_rows = {
            (r.region, r.protocol_type): r
            for r in snapshot.region_protocol_rows
        }
        ap_anytls = region_rows[("ap-east-1", "AnyTLS")]
        assert ap_anytls.alert_level == "critical"
        assert ap_anytls.online_count == 1
        assert ap_anytls.gap_count == 2

    def test_build_region_protocol_rows_warning_alert_level(
        self, in_memory_sqlite_db
    ) -> None:
        runtime_context = _make_runtime_context(in_memory_sqlite_db)
        state_repo = StateRepo(runtime_context)

        # 2 nodes online for ap-east-1/AnyTLS (>=threshold=2 but <desired=3 => warning)
        for i in range(2):
            state_repo.create_node(
                FleetNodeCreateRequest(
                    xboard_node_id=300 + i,
                    node_name=f"warn-{i}",
                    node_type="AnyTLS",
                    status="online",
                    aws_region="ap-east-1",
                )
            )

        mock_probe_repo = MagicMock()
        mock_probe_repo.list_probes.return_value = []
        mock_probe_repo.list_recent_measurements.return_value = []
        mock_monitor_repo = MagicMock()
        mock_monitor_repo.get_latest_cycle.return_value = None

        with patch(
            "services.dashboard_service.ProbeRepo", return_value=mock_probe_repo
        ), patch(
            "services.dashboard_service.MonitorRepo", return_value=mock_monitor_repo
        ):
            from services.dashboard_service import DashboardService

            svc = DashboardService(runtime_context)
            snapshot = svc.build_snapshot()

        region_rows = {
            (r.region, r.protocol_type): r
            for r in snapshot.region_protocol_rows
        }
        ap_anytls = region_rows[("ap-east-1", "AnyTLS")]
        assert ap_anytls.alert_level == "warning"
        assert ap_anytls.gap_count == 1

    def test_build_latest_monitor_cycle_returns_cycle(
        self, in_memory_sqlite_db
    ) -> None:
        runtime_context = _make_runtime_context(in_memory_sqlite_db)

        # Seed a real monitor cycle via MonitorRepo
        from database.monitor_repo import MonitorRepo

        monitor_repo = MonitorRepo(runtime_context)
        cycle_id = monitor_repo.create_cycle("test-corr-001")
        monitor_repo.finalize_cycle(
            cycle_id=cycle_id,
            status="succeeded",
            candidate_count=5,
            confirmed_count=2,
            healed_count=2,
            failed_count=1,
        )

        mock_probe_repo = MagicMock()
        mock_probe_repo.list_probes.return_value = []
        mock_probe_repo.list_recent_measurements.return_value = []

        with patch(
            "services.dashboard_service.ProbeRepo", return_value=mock_probe_repo
        ):
            from services.dashboard_service import DashboardService

            svc = DashboardService(runtime_context)
            snapshot = svc.build_snapshot()

        assert snapshot.latest_monitor_cycle is not None
        assert snapshot.latest_monitor_cycle.candidate_count == 5
        assert snapshot.latest_monitor_cycle.healed_count == 2
        assert snapshot.latest_monitor_cycle.status == "succeeded"

    def test_build_latest_monitor_cycle_returns_none_when_empty(
        self, in_memory_sqlite_db
    ) -> None:
        runtime_context = _make_runtime_context(in_memory_sqlite_db)

        mock_probe_repo = MagicMock()
        mock_probe_repo.list_probes.return_value = []
        mock_probe_repo.list_recent_measurements.return_value = []
        mock_monitor_repo = MagicMock()
        mock_monitor_repo.get_latest_cycle.return_value = None

        with patch(
            "services.dashboard_service.ProbeRepo", return_value=mock_probe_repo
        ), patch(
            "services.dashboard_service.MonitorRepo", return_value=mock_monitor_repo
        ):
            from services.dashboard_service import DashboardService

            svc = DashboardService(runtime_context)
            snapshot = svc.build_snapshot()

        assert snapshot.latest_monitor_cycle is None
