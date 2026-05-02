from __future__ import annotations

from typing import TYPE_CHECKING

from database.asset_models import (
    AllocationStatus,
    AssetAllocationCreateRequest,
    AssetCreateRequest,
    AssetEventCreateRequest,
    AssetNotFoundError,
    AssetProtocolConfigRecord,
    AssetProtocolConfigRequest,
    AssetRecord,
    AssetRepoError,
    AssetSelectionCandidate,
    AssetType,
    PortAllocationCreateRequest,
    PortAllocationRecord,
    ProtocolType,
)
from database.asset_repo_helpers import (
    build_protocol_defaults,
    map_asset_protocol_config_record,
    map_asset_protocol_config_record_from_join,
    map_asset_record,
    map_port_allocation_record,
    to_json_text,
    utcnow_iso,
    validate_asset_request,
    validate_protocol_config_request,
)

from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext

class AssetRepo:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        sqlite_manager = runtime_context.sqlite_manager
        if sqlite_manager is None:
            raise ValueError("RuntimeContext.sqlite_manager is required for AssetRepo")

        self._sqlite_manager = sqlite_manager
        self._logger = runtime_context.logger.getChild("database.asset_repo")

    def create_asset(self, request: AssetCreateRequest) -> int:
        validate_asset_request(request)
        timestamp = utcnow_iso()
        sql = """
            INSERT INTO fleet_assets (
                asset_type,
                asset_name,
                status,
                region,
                aws_account_id,
                aws_access_key,
                aws_secret_key,
                ssh_host,
                ssh_port,
                ssh_username,
                ssh_password,
                ssh_private_key,
                default_instance_type,
                default_vcpu,
                account_total_vcpu,
                default_architecture,
                cpu_cores,
                memory_gb,
                remarks,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        parameters = (
            request.asset_type,
            request.asset_name.strip(),
            request.status,
            request.region.strip() if request.region else None,
            request.aws_account_id.strip() if request.aws_account_id else None,
            request.aws_access_key.strip() if request.aws_access_key else None,
            request.aws_secret_key.strip() if request.aws_secret_key else None,
            request.ssh_host.strip() if request.ssh_host else None,
            request.ssh_port,
            request.ssh_username.strip() if request.ssh_username else None,
            request.ssh_password,
            request.ssh_private_key,
            request.default_instance_type.strip() if request.default_instance_type else None,
            request.default_vcpu,
            request.account_total_vcpu,
            request.default_architecture.strip() if request.default_architecture else None,
            request.cpu_cores,
            request.memory_gb,
            request.remarks,
            timestamp,
            timestamp,
        )
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(sql, parameters)
            asset_id = int(cursor.lastrowid)

        set_event_type("sqlite_asset_created")
        self._logger.info("Created asset id=%s type=%s", asset_id, request.asset_type)
        return asset_id

    def upsert_asset_protocol_config(self, request: AssetProtocolConfigRequest) -> int:
        asset = self.get_asset_by_id(request.asset_id)
        validate_protocol_config_request(asset=asset, request=request)
        protocol_defaults = build_protocol_defaults(request.protocol_type)
        requires_domain = (
            protocol_defaults["requires_domain"]
            if request.requires_domain is None
            else request.requires_domain
        )
        requires_dns_record = (
            protocol_defaults["requires_dns_record"]
            if request.requires_dns_record is None
            else request.requires_dns_record
        )
        supports_cdn_proxy = (
            protocol_defaults["supports_cdn_proxy"]
            if request.supports_cdn_proxy is None
            else request.supports_cdn_proxy
        )
        timestamp = utcnow_iso()
        sql = """
            INSERT INTO fleet_asset_protocols (
                asset_id,
                protocol_type,
                enabled,
                target_count,
                max_count,
                priority,
                allow_cdn_proxy,
                instance_type,
                vcpu,
                architecture,
                ami_id,
                subnet_id,
                security_group_id,
                requires_domain,
                requires_dns_record,
                supports_cdn_proxy,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(asset_id, protocol_type) DO UPDATE SET
                enabled = excluded.enabled,
                target_count = excluded.target_count,
                max_count = excluded.max_count,
                priority = excluded.priority,
                allow_cdn_proxy = excluded.allow_cdn_proxy,
                instance_type = excluded.instance_type,
                vcpu = excluded.vcpu,
                architecture = excluded.architecture,
                ami_id = excluded.ami_id,
                subnet_id = excluded.subnet_id,
                security_group_id = excluded.security_group_id,
                requires_domain = excluded.requires_domain,
                requires_dns_record = excluded.requires_dns_record,
                supports_cdn_proxy = excluded.supports_cdn_proxy,
                updated_at = excluded.updated_at
        """
        parameters = (
            request.asset_id,
            request.protocol_type,
            int(request.enabled),
            request.target_count,
            request.max_count,
            request.priority,
            int(request.allow_cdn_proxy),
            request.instance_type.strip() if request.instance_type else None,
            request.vcpu,
            request.architecture.strip() if request.architecture else None,
            request.ami_id.strip() if request.ami_id else None,
            request.subnet_id.strip() if request.subnet_id else None,
            request.security_group_id.strip() if request.security_group_id else None,
            int(requires_domain),
            int(requires_dns_record),
            int(supports_cdn_proxy),
            timestamp,
            timestamp,
        )
        with self._sqlite_manager.connection() as connection:
            connection.execute(sql, parameters)
            row = connection.execute(
                """
                SELECT id
                FROM fleet_asset_protocols
                WHERE asset_id = ? AND protocol_type = ?
                """,
                (request.asset_id, request.protocol_type),
            ).fetchone()
        if row is None:
            raise AssetRepoError("Failed to load upserted asset protocol config")

        protocol_config_id = int(row["id"])
        set_event_type("sqlite_asset_protocol_upserted")
        self._logger.info("Upserted asset protocol config id=%s asset_id=%s protocol=%s", protocol_config_id, request.asset_id, request.protocol_type)
        return protocol_config_id

    def get_asset_by_id(self, asset_id: int) -> AssetRecord:
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                "SELECT * FROM fleet_assets WHERE id = ?",
                (asset_id,),
            ).fetchone()
        if row is None:
            raise AssetNotFoundError(f"Asset not found: asset_id={asset_id}")
        return map_asset_record(row)

    def list_assets_by_aws_account_id(self, aws_account_id: str) -> list[AssetRecord]:
        if not aws_account_id or not aws_account_id.strip():
            raise ValueError("aws_account_id must not be empty")
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM fleet_assets
                WHERE aws_account_id = ?
                ORDER BY id ASC
                """,
                (aws_account_id.strip(),),
            ).fetchall()
        return [map_asset_record(row) for row in rows]

    def list_assets_by_status(self, status: str) -> list[AssetRecord]:
        """List all assets with the given status."""
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM fleet_assets
                WHERE status = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (status,),
            ).fetchall()
        return [map_asset_record(row) for row in rows]

    def get_asset_protocol_config(
        self,
        asset_id: int,
        protocol_type: ProtocolType,
    ) -> AssetProtocolConfigRecord:
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM fleet_asset_protocols
                WHERE asset_id = ? AND protocol_type = ?
                """,
                (asset_id, protocol_type),
            ).fetchone()
        if row is None:
            raise AssetNotFoundError(f"Asset protocol config not found: asset_id={asset_id} protocol={protocol_type}")
        return map_asset_protocol_config_record(row)

    def list_selection_candidates(
        self,
        protocol_type: ProtocolType,
        asset_type: AssetType | None = None,
        region: str | None = None,
        require_cdn_proxy: bool = False,
    ) -> list[AssetSelectionCandidate]:
        conditions = [
            "a.status = 'active'",
            "p.enabled = 1",
            "p.protocol_type = ?",
        ]
        parameters: list[object] = [protocol_type]
        if asset_type is not None:
            conditions.append("a.asset_type = ?")
            parameters.append(asset_type)
        if region is not None:
            conditions.append("a.region = ?")
            parameters.append(region.strip())
        if require_cdn_proxy:
            conditions.append("p.allow_cdn_proxy = 1")
            conditions.append("p.supports_cdn_proxy = 1")

        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT
                a.*,
                p.id AS protocol_config_id,
                p.protocol_type,
                p.enabled,
                p.target_count,
                p.max_count,
                p.priority,
                p.allow_cdn_proxy,
                p.instance_type,
                p.vcpu,
                p.architecture,
                p.ami_id,
                p.subnet_id,
                p.security_group_id,
                p.requires_domain,
                p.requires_dns_record,
                p.supports_cdn_proxy,
                p.created_at AS protocol_created_at,
                p.updated_at AS protocol_updated_at,
                COALESCE(SUM(CASE WHEN faa.allocation_status = 'allocated' THEN 1 ELSE 0 END), 0)
                    AS current_allocated_count,
                COALESCE(SUM(CASE WHEN faa.allocation_status = 'allocated' THEN faa.vcpu_count ELSE 0 END), 0)
                    AS current_allocated_vcpu
            FROM fleet_assets AS a
            INNER JOIN fleet_asset_protocols AS p
                ON p.asset_id = a.id
            LEFT JOIN fleet_asset_allocations AS faa
                ON faa.asset_id = a.id
                AND faa.protocol_type = p.protocol_type
            WHERE {where_clause}
            GROUP BY
                a.id,
                p.id
            ORDER BY
                p.priority ASC,
                (a.account_total_vcpu - COALESCE(SUM(CASE WHEN faa.allocation_status = 'allocated' THEN faa.vcpu_count ELSE 0 END), 0)) ASC,
                a.id ASC
        """
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(sql, tuple(parameters)).fetchall()

        candidates: list[AssetSelectionCandidate] = []
        for row in rows:
            current_allocated_count = int(row["current_allocated_count"])
            current_allocated_vcpu = int(row["current_allocated_vcpu"])
            max_count = int(row["max_count"])
            if max_count > 0 and current_allocated_count >= max_count:
                continue
            candidates.append(
                AssetSelectionCandidate(
                    asset=map_asset_record(row),
                    protocol_config=map_asset_protocol_config_record_from_join(row),
                    current_allocated_count=current_allocated_count,
                    current_allocated_vcpu=current_allocated_vcpu,
                )
            )
        return candidates

    def create_allocation(self, request: AssetAllocationCreateRequest) -> int:
        timestamp = utcnow_iso()
        sql = """
            INSERT INTO fleet_asset_allocations (
                asset_id,
                fleet_node_id,
                xboard_node_id,
                protocol_type,
                allocation_status,
                vcpu_count,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        parameters = (
            request.asset_id,
            request.fleet_node_id,
            request.xboard_node_id,
            request.protocol_type,
            request.allocation_status,
            request.vcpu_count,
            timestamp,
            timestamp,
        )
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(sql, parameters)
            allocation_id = int(cursor.lastrowid)

        set_event_type("sqlite_asset_allocation_created")
        self._logger.info("Created asset allocation id=%s asset_id=%s protocol=%s vcpu=%s", allocation_id, request.asset_id, request.protocol_type, request.vcpu_count)
        return allocation_id

    def release_allocation_by_xboard_node_id(
        self,
        xboard_node_id: int,
        allocation_status: AllocationStatus = "released",
    ) -> None:
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE fleet_asset_allocations
                SET allocation_status = ?, updated_at = ?
                WHERE xboard_node_id = ? AND allocation_status = 'allocated'
                """,
                (allocation_status, utcnow_iso(), xboard_node_id),
            )
            if cursor.rowcount == 0:
                raise AssetNotFoundError(
                    f"Active allocation not found for xboard_node_id={xboard_node_id}"
                )

        set_event_type("sqlite_asset_allocation_released")
        self._logger.info("Released asset allocation for xboard_node_id=%s", xboard_node_id)

    def update_asset_status(self, asset_id: int, status: str) -> None:
        if not status or not status.strip():
            raise ValueError("status must not be empty")
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE fleet_assets
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status.strip(), utcnow_iso(), asset_id),
            )
            if cursor.rowcount == 0:
                raise AssetNotFoundError(f"Asset not found: asset_id={asset_id}")

        set_event_type("sqlite_asset_status_updated")
        self._logger.info("Updated asset status asset_id=%s status=%s", asset_id, status.strip())

    def update_asset_hardware(self, asset_id: int, cpu_cores: int, memory_gb: float) -> None:
        """Update CPU cores and memory for an asset (self-hosted only)."""
        self.get_asset_by_id(asset_id)  # validate asset exists
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE fleet_assets
                SET cpu_cores = ?, memory_gb = ?, updated_at = ?
                WHERE id = ?
                """,
                (cpu_cores, memory_gb, utcnow_iso(), asset_id),
            )
            if cursor.rowcount == 0:
                raise AssetNotFoundError(f"Asset not found: asset_id={asset_id}")

        self._logger.info(
            "Updated asset hardware asset_id=%s cpu_cores=%s memory_gb=%s",
            asset_id,
            cpu_cores,
            memory_gb,
        )

    def create_asset_event(self, request: AssetEventCreateRequest) -> int:
        if not request.event_type or not request.event_type.strip():
            raise ValueError("event_type must not be empty")
        if not request.correlation_id or not request.correlation_id.strip():
            raise ValueError("correlation_id must not be empty")

        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO fleet_asset_events (
                    asset_id,
                    event_type,
                    correlation_id,
                    message,
                    payload_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    request.asset_id,
                    request.event_type.strip(),
                    request.correlation_id.strip(),
                    request.message,
                    to_json_text(request.payload),
                    utcnow_iso(),
                ),
            )
            event_id = int(cursor.lastrowid)

        set_event_type("sqlite_asset_event_created")
        self._logger.info("Created asset event id=%s asset_id=%s type=%s", event_id, request.asset_id, request.event_type)
        return event_id

    def get_active_allocations_count(self, asset_id: int) -> int:
        """Return count of allocations with status 'allocated' for the given asset."""
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM fleet_asset_allocations
                WHERE asset_id = ? AND allocation_status = 'allocated'
                """,
                (asset_id,),
            ).fetchone()
        return int(row["cnt"]) if row else 0

    def delete_asset(self, asset_id: int) -> None:
        """Delete an asset and all its related records (cascade)."""
        self.get_asset_by_id(asset_id)  # raises AssetNotFoundError if not found

        with self._sqlite_manager.connection() as connection:
            connection.execute(
                "DELETE FROM fleet_asset_port_allocations WHERE asset_id = ?",
                (asset_id,),
            )
            connection.execute(
                "DELETE FROM fleet_asset_allocations WHERE asset_id = ?",
                (asset_id,),
            )
            connection.execute(
                "DELETE FROM fleet_asset_protocols WHERE asset_id = ?",
                (asset_id,),
            )
            connection.execute(
                "DELETE FROM fleet_asset_events WHERE asset_id = ?",
                (asset_id,),
            )
            cursor = connection.execute(
                "DELETE FROM fleet_assets WHERE id = ?",
                (asset_id,),
            )
            if cursor.rowcount == 0:
                raise AssetNotFoundError(f"Asset not found: asset_id={asset_id}")

        set_event_type("sqlite_asset_deleted")
        self._logger.info("Deleted asset and cascade records asset_id=%s", asset_id)

    def create_port_allocation(self, request: PortAllocationCreateRequest) -> int:
        """Allocate a server_port on a self-hosted asset. Raises if port already active."""
        timestamp = utcnow_iso()
        existing = self._find_active_port_allocation(request.asset_id, request.server_port)
        if existing is not None:
            raise AssetRepoError(
                f"Port {request.server_port} is already in use on asset_id={request.asset_id} "
                f"(xboard_node_id={existing.xboard_node_id}). Choose a different port."
            )
        sql = """
            INSERT INTO fleet_asset_port_allocations (
                asset_id,
                fleet_node_id,
                xboard_node_id,
                server_port,
                protocol_type,
                allocation_status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        parameters = (
            request.asset_id,
            request.fleet_node_id,
            request.xboard_node_id,
            request.server_port,
            request.protocol_type,
            request.allocation_status,
            timestamp,
            timestamp,
        )
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(sql, parameters)
            allocation_id = int(cursor.lastrowid)

        self._logger.info(
            "Allocated port asset_id=%s port=%s protocol=%s id=%s",
            request.asset_id,
            request.server_port,
            request.protocol_type,
            allocation_id,
        )
        return allocation_id

    def _find_active_port_allocation(
        self,
        asset_id: int,
        server_port: int,
    ) -> PortAllocationRecord | None:
        with self._sqlite_manager.connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM fleet_asset_port_allocations
                WHERE asset_id = ? AND server_port = ? AND allocation_status = 'allocated'
                """,
                (asset_id, server_port),
            ).fetchone()
        if row is None:
            return None
        return map_port_allocation_record(row)

    def list_active_ports_by_asset(self, asset_id: int) -> list[PortAllocationRecord]:
        """Return all active port allocations for an asset (self-hosted only)."""
        with self._sqlite_manager.connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM fleet_asset_port_allocations
                WHERE asset_id = ? AND allocation_status = 'allocated'
                ORDER BY server_port ASC
                """,
                (asset_id,),
            ).fetchall()
        return [map_port_allocation_record(row) for row in rows]

    def allocate_next_free_port(
        self,
        asset_id: int,
        protocol_type: ProtocolType,
        port_range_start: int = 40000,
        port_range_end: int = 60000,
    ) -> int:
        """Find the first free port within the range and allocate it atomically."""
        with self._sqlite_manager.connection() as connection:
            used_rows = connection.execute(
                """
                SELECT server_port
                FROM fleet_asset_port_allocations
                WHERE asset_id = ? AND allocation_status = 'allocated'
                AND server_port BETWEEN ? AND ?
                ORDER BY server_port ASC
                """,
                (asset_id, port_range_start, port_range_end),
            ).fetchall()
        used_ports = {int(row["server_port"]) for row in used_rows}
        candidate = port_range_start
        for candidate in range(port_range_start, port_range_end + 1):
            if candidate not in used_ports:
                break
        else:
            raise AssetRepoError(
                f"No free ports available in range {port_range_start}-{port_range_end} "
                f"for asset_id={asset_id}"
            )
        self.create_port_allocation(
            PortAllocationCreateRequest(
                asset_id=asset_id,
                server_port=candidate,
                protocol_type=protocol_type,
            )
        )
        return candidate

    def release_port_allocation_by_xboard_node_id(self, xboard_node_id: int) -> None:
        """Mark a port allocation as released for the given xboard node."""
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE fleet_asset_port_allocations
                SET allocation_status = 'released', updated_at = ?
                WHERE xboard_node_id = ? AND allocation_status = 'allocated'
                """,
                (utcnow_iso(), xboard_node_id),
            )
            if cursor.rowcount == 0:
                self._logger.warning(
                    "No active port allocation found for xboard_node_id=%s",
                    xboard_node_id,
                )
        set_event_type("sqlite_port_allocation_released")
        self._logger.info("Released port allocation for xboard_node_id=%s", xboard_node_id)

    def release_port_allocation_by_asset_and_port(self, asset_id: int, server_port: int) -> None:
        """Mark a port allocation as released for the given asset and port."""
        with self._sqlite_manager.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE fleet_asset_port_allocations
                SET allocation_status = 'released', updated_at = ?
                WHERE asset_id = ? AND server_port = ? AND allocation_status = 'allocated'
                """,
                (utcnow_iso(), asset_id, server_port),
            )
            if cursor.rowcount == 0:
                self._logger.warning(
                    "No active port allocation found for asset_id=%s port=%s",
                    asset_id,
                    server_port,
                )
        self._logger.info(
            "Released port allocation asset_id=%s port=%s",
            asset_id,
            server_port,
        )

