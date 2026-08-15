from __future__ import annotations

import sqlite3
from collections import defaultdict

from database.monitor_repo import MonitorRepo
from database.probe_repo import ProbeRepo
from database.probe_measurement_repo import ProbeMeasurementRepo
from services.dashboard_models import (
    AssetHealthRow,
    DashboardOverview,
    DashboardSnapshot,
    FleetNodeDashboardRow,
    MonitorCycleSummary,
    NodeEventRow,
    ProbeHealthRow,
    ProbeMeasurementRow,
    RegionProtocolHealthRow,
)
from services.runtime_service import RuntimeContext


class DashboardService:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        sqlite_manager = runtime_context.sqlite_manager
        if sqlite_manager is None:
            raise ValueError("RuntimeContext.sqlite_manager is required for DashboardService")
        self._runtime_context = runtime_context
        self._sqlite_manager = sqlite_manager
        self._monitor_repo = MonitorRepo(runtime_context)
        self._probe_repo = ProbeRepo(runtime_context)
        self._probe_measurement_repo = ProbeMeasurementRepo(runtime_context)

    def build_snapshot(self) -> DashboardSnapshot:
        node_rows = self._list_node_rows()
        asset_rows = self._list_asset_rows()
        probe_rows = self._list_probe_rows()
        probe_measurement_rows = self._list_probe_measurement_rows()
        overview = self._build_overview(
            node_rows=node_rows,
            asset_rows=asset_rows,
            probe_rows=probe_rows,
        )
        region_protocol_rows = self._build_region_protocol_rows(node_rows=node_rows)
        latest_monitor_cycle = self._build_latest_monitor_cycle()
        return DashboardSnapshot(
            overview=overview,
            region_protocol_rows=tuple(region_protocol_rows),
            asset_rows=tuple(asset_rows),
            node_rows=tuple(node_rows),
            latest_monitor_cycle=latest_monitor_cycle,
            probe_rows=tuple(probe_rows),
            probe_measurement_rows=tuple(probe_measurement_rows),
        )

    def list_recent_node_events(self, xboard_node_id: int, limit: int = 10) -> list[NodeEventRow]:
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    event_type,
                    from_status,
                    to_status,
                    message,
                    correlation_id,
                    created_at
                FROM fleet_node_events
                WHERE xboard_node_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (xboard_node_id, limit),
            ).fetchall()
        return [
            NodeEventRow(
                event_id=int(row["id"]),
                event_type=str(row["event_type"]),
                from_status=row["from_status"],
                to_status=row["to_status"],
                message=row["message"],
                correlation_id=str(row["correlation_id"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def _build_overview(
        self,
        *,
        node_rows: list[FleetNodeDashboardRow],
        asset_rows: list[AssetHealthRow],
        probe_rows: list[ProbeHealthRow],
    ) -> DashboardOverview:
        expected_node_count = 0
        for region_config in self._runtime_context.config.fleet_matrix.values():
            for protocol_config in region_config.values():
                expected_node_count += protocol_config.desired_count

        online_node_count = sum(1 for row in node_rows if row.status == "online")
        healing_node_count = sum(1 for row in node_rows if row.status == "healing")
        offline_or_failed_node_count = sum(
            1 for row in node_rows if row.status in {"offline", "failed", "deleting", "deleted"}
        )
        monthly_healing_count = sum(
            1
            for row in node_rows
            if row.last_healed_at is not None and row.last_healed_at[:7] == self._current_utc_month()
        )
        total_asset_count = len(asset_rows)
        active_asset_count = sum(1 for row in asset_rows if row.status == "active")
        full_asset_count = sum(1 for row in asset_rows if row.status == "full")
        banned_asset_count = sum(1 for row in asset_rows if row.status == "banned")
        deploying_asset_count = sum(1 for row in asset_rows if row.status == "deploying")
        offline_asset_count = sum(1 for row in asset_rows if row.status == "offline")
        aws_rows = [row for row in asset_rows if row.asset_type == "aws"]
        allocated_aws_node_count = sum(row.allocated_count for row in aws_rows)
        target_aws_capacity = sum(row.target_count for row in aws_rows)
        max_aws_capacity = sum(row.max_count for row in aws_rows)
        overall_survival_rate = 0.0
        if expected_node_count > 0:
            overall_survival_rate = online_node_count / expected_node_count
        aws_capacity_utilization_rate = 0.0
        if max_aws_capacity > 0:
            aws_capacity_utilization_rate = allocated_aws_node_count / max_aws_capacity
        total_probe_count = len(probe_rows)
        active_probe_count = sum(1 for row in probe_rows if row.status == "active")
        offline_probe_count = sum(1 for row in probe_rows if row.status == "offline")
        disabled_probe_count = sum(1 for row in probe_rows if row.status == "disabled")

        return DashboardOverview(
            expected_node_count=expected_node_count,
            total_node_count=len(node_rows),
            online_node_count=online_node_count,
            healing_node_count=healing_node_count,
            offline_or_failed_node_count=offline_or_failed_node_count,
            overall_survival_rate=overall_survival_rate,
            monthly_healing_count=monthly_healing_count,
            total_asset_count=total_asset_count,
            active_asset_count=active_asset_count,
            full_asset_count=full_asset_count,
            banned_asset_count=banned_asset_count,
            deploying_asset_count=deploying_asset_count,
            offline_asset_count=offline_asset_count,
            aws_asset_count=len(aws_rows),
            active_aws_asset_count=sum(1 for row in aws_rows if row.status == "active"),
            full_aws_asset_count=sum(1 for row in aws_rows if row.status == "full"),
            banned_aws_asset_count=sum(1 for row in aws_rows if row.status == "banned"),
            allocated_aws_node_count=allocated_aws_node_count,
            target_aws_capacity=target_aws_capacity,
            max_aws_capacity=max_aws_capacity,
            aws_capacity_utilization_rate=aws_capacity_utilization_rate,
            total_probe_count=total_probe_count,
            active_probe_count=active_probe_count,
            offline_probe_count=offline_probe_count,
            disabled_probe_count=disabled_probe_count,
        )

    def _build_region_protocol_rows(
        self,
        *,
        node_rows: list[FleetNodeDashboardRow],
    ) -> list[RegionProtocolHealthRow]:
        online_counts: dict[tuple[str, str], int] = defaultdict(int)
        total_counts: dict[tuple[str, str], int] = defaultdict(int)
        for row in node_rows:
            region = row.region or "unassigned"
            key = (region, row.protocol_type)
            total_counts[key] += 1
            if row.status == "online":
                online_counts[key] += 1

        rows: list[RegionProtocolHealthRow] = []
        for region, protocol_map in self._runtime_context.config.fleet_matrix.items():
            for protocol_type, protocol_config in protocol_map.items():
                key = (region, protocol_type)
                desired_count = protocol_config.desired_count
                online_count = online_counts.get(key, 0)
                total_count = total_counts.get(key, 0)
                gap_count = max(desired_count - online_count, 0)
                survival_rate = 0.0 if desired_count == 0 else online_count / desired_count
                alert_level = "healthy"
                if online_count < protocol_config.min_alert_threshold:
                    alert_level = "critical"
                elif online_count < desired_count:
                    alert_level = "warning"
                rows.append(
                    RegionProtocolHealthRow(
                        region=region,
                        protocol_type=protocol_type,
                        desired_count=desired_count,
                        min_alert_threshold=protocol_config.min_alert_threshold,
                        online_count=online_count,
                        total_count=total_count,
                        gap_count=gap_count,
                        survival_rate=survival_rate,
                        alert_level=alert_level,
                    )
                )
        return rows

    def _build_latest_monitor_cycle(self) -> MonitorCycleSummary | None:
        latest_cycle = self._monitor_repo.get_latest_cycle()
        if latest_cycle is None:
            return None
        return MonitorCycleSummary(
            cycle_id=latest_cycle.id,
            status=latest_cycle.status,
            candidate_count=latest_cycle.candidate_count,
            confirmed_count=latest_cycle.confirmed_count,
            healed_count=latest_cycle.healed_count,
            failed_count=latest_cycle.failed_count,
            started_at=latest_cycle.started_at,
            finished_at=latest_cycle.finished_at,
            error_message=latest_cycle.error_message,
        )

    def _list_node_rows(self) -> list[FleetNodeDashboardRow]:
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    n.xboard_node_id,
                    n.node_name,
                    n.node_type,
                    COALESCE(
                        (
                            SELECT a.asset_type
                            FROM fleet_asset_allocations AS alloc
                            JOIN fleet_assets AS a ON a.id = alloc.asset_id
                            WHERE alloc.xboard_node_id = n.xboard_node_id
                            ORDER BY alloc.id DESC
                            LIMIT 1
                        ),
                        CASE
                            WHEN n.aws_account_id IS NULL THEN 'self_hosted'
                            WHEN lower(trim(n.aws_account_id)) = 'digitalocean'
              OR lower(trim(n.aws_account_id)) LIKE 'digitalocean:%' THEN 'digitalocean'
            WHEN lower(trim(n.aws_account_id)) = 'vultr'
                              OR lower(trim(n.aws_account_id)) LIKE 'vultr:%' THEN 'vultr'
                            WHEN lower(trim(n.aws_account_id)) = 'azure'
                              OR lower(trim(n.aws_account_id)) LIKE 'azure:%' THEN 'azure'
                            WHEN lower(trim(n.aws_account_id)) = 'gcp'
                              OR lower(trim(n.aws_account_id)) LIKE 'gcp:%' THEN 'gcp'
                            WHEN lower(trim(n.aws_account_id)) = 'kamatera'
                              OR lower(trim(n.aws_account_id)) LIKE 'kamatera:%' THEN 'kamatera'
                            WHEN lower(trim(n.aws_account_id)) = 'oci'
                              OR lower(trim(n.aws_account_id)) LIKE 'oci:%' THEN 'oci'
                            ELSE 'aws'
                        END
                    ) AS asset_type,
                    n.aws_region,
                    n.status,
                    n.aws_instance_id,
                    n.domain_name,
                    n.ipv6_address,
                    n.aws_account_id,
                    n.last_healed_at,
                    n.updated_at,
                    n.last_error,
                    n.xboard_status,
                    n.xboard_show,
                    n.xboard_updated_at
                FROM fleet_nodes AS n
                WHERE n.is_deleted = 0
                ORDER BY n.updated_at DESC, n.id DESC
                """
            ).fetchall()
        return [self._map_node_row(row) for row in rows]

    def _list_asset_rows(self) -> list[AssetHealthRow]:
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    a.id,
                    a.asset_name,
                    a.asset_type,
                    a.region,
                    a.status,
                    a.aws_account_id,
                    a.account_total_vcpu,
                    a.remarks,
                    a.updated_at,
                    a.cpu_cores,
                    a.memory_gb,
                    COALESCE(protocol_summary.target_count, 0) AS target_count,
                    COALESCE(protocol_summary.max_count, 0) AS max_count,
                    COALESCE(protocol_summary.supported_protocols, '') AS supported_protocols,
                    COALESCE(allocation_summary.allocated_count, 0) AS allocated_count
                FROM fleet_assets AS a
                LEFT JOIN (
                    SELECT
                        asset_id,
                        SUM(target_count) AS target_count,
                        SUM(max_count) AS max_count,
                        GROUP_CONCAT(DISTINCT protocol_type) AS supported_protocols
                    FROM fleet_asset_protocols
                    WHERE enabled = 1
                    GROUP BY asset_id
                ) AS protocol_summary
                    ON protocol_summary.asset_id = a.id
                LEFT JOIN (
                    SELECT
                        asset_id,
                        COUNT(*) AS allocated_count
                    FROM fleet_asset_allocations
                    WHERE allocation_status = 'allocated'
                    GROUP BY asset_id
                ) AS allocation_summary
                    ON allocation_summary.asset_id = a.id
                ORDER BY a.updated_at DESC, a.id DESC
                """
            ).fetchall()
        return [self._map_asset_row(row) for row in rows]

    @staticmethod
    def _map_node_row(row: sqlite3.Row) -> FleetNodeDashboardRow:
        return FleetNodeDashboardRow(
            xboard_node_id=int(row["xboard_node_id"]),
            node_name=str(row["node_name"]),
            protocol_type=str(row["node_type"]),
            asset_type=str(row["asset_type"]),
            region=row["aws_region"],
            status=str(row["status"]),
            instance_id=row["aws_instance_id"],
            domain_name=row["domain_name"],
            ipv6_address=row["ipv6_address"],
            aws_account_id=row["aws_account_id"],
            last_healed_at=row["last_healed_at"],
            updated_at=str(row["updated_at"]),
            last_error=row["last_error"],
            xboard_status=row["xboard_status"],
            xboard_show=row["xboard_show"],
            xboard_updated_at=row["xboard_updated_at"],
        )

    @staticmethod
    def _map_asset_row(row: sqlite3.Row) -> AssetHealthRow:
        supported_protocols = ()
        if row["supported_protocols"]:
            supported_protocols = tuple(sorted(str(row["supported_protocols"]).split(",")))
        return AssetHealthRow(
            asset_id=int(row["id"]),
            asset_name=str(row["asset_name"]),
            asset_type=str(row["asset_type"]),
            region=row["region"],
            status=str(row["status"]),
            aws_account_id=row["aws_account_id"],
            account_total_vcpu=row["account_total_vcpu"],
            allocated_count=int(row["allocated_count"]),
            target_count=int(row["target_count"]),
            max_count=int(row["max_count"]),
            supported_protocols=supported_protocols,
            cpu_cores=row["cpu_cores"],
            memory_gb=row["memory_gb"],
            remarks=row["remarks"],
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _current_utc_month() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).strftime("%Y-%m")

    def _list_probe_rows(self) -> list[ProbeHealthRow]:
        self._probe_repo.mark_stale_probes_offline(
            timeout_seconds=self._runtime_context.config.app.probe_heartbeat_timeout_seconds
        )
        probe_records = self._probe_repo.list_probes(include_inactive=True)
        return [
            ProbeHealthRow(
                probe_id=record.probe_id,
                probe_name=record.probe_name,
                status=record.status,
                public_ip=record.public_ip,
                region=record.region,
                isp=record.isp,
                tags=tuple(record.tags),
                config_version=record.config_version,
                last_seen_at=record.last_seen_at,
                updated_at=record.updated_at,
            )
            for record in probe_records
        ]

    def _list_probe_measurement_rows(self) -> list[ProbeMeasurementRow]:
        measurement_records = self._probe_measurement_repo.list_recent_measurements(limit=20)
        return [
            ProbeMeasurementRow(
                measurement_id=record.measurement_id,
                xboard_node_id=record.xboard_node_id,
                final_status=record.final_status,
                reason=record.reason,
                created_at=record.created_at,
                finished_at=record.finished_at,
            )
            for record in measurement_records
        ]
