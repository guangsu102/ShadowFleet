from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING, Iterator

from utils.logger import set_event_type

if TYPE_CHECKING:
    from services.runtime_service import RuntimeContext


FLEET_NODE_STATUSES = (
    "provisioning",
    "online",
    "offline",
    "healing",
    "deleting",
    "deleted",
    "failed",
)
FLEET_ASSET_TYPES = ("aws", "self_hosted")
FLEET_ASSET_STATUSES = ("active", "full", "banned", "offline", "deploying")
FLEET_PROTOCOL_TYPES = ("AnyTLS", "Trojan", "vless", "vmess", "Hysteria2")
FLEET_ALLOCATION_STATUSES = ("allocated", "released", "failed")
FLEET_TASK_TYPES = ("provision_node",)
FLEET_TASK_STATUSES = ("queued", "running", "succeeded", "failed")
FLEET_MANUAL_TASK_TYPES = (
    "force_heal",
    "decommission_node",
    "reprobe_node",
    "mark_manual_review",
)
FLEET_MANUAL_TASK_STATUSES = ("queued", "running", "succeeded", "failed")
FLEET_READY_CALLBACK_STATUSES = ("pending", "received", "completed")
FLEET_MONITOR_CYCLE_STATUSES = ("running", "succeeded", "failed")
FLEET_PROBE_STATUSES = ("pending", "active", "disabled", "offline", "draining")
FLEET_PROBE_COMMAND_TYPES = (
    "run_connectivity_probe",
    "refresh_config",
    "self_check",
    "drain_probe",
    "resume_probe",
)
FLEET_PROBE_COMMAND_STATUSES = ("queued", "leased", "succeeded", "failed", "cancelled")
FLEET_PROBE_MEASUREMENT_STATUSES = (
    "pending",
    "collecting",
    "healthy",
    "origin_fault",
    "suspected_blocked",
    "confirmed_blocked_by_gfw",
    "probe_inconclusive",
    "failed",
)


class SqliteConnectionManager:
    def __init__(self, runtime_context: RuntimeContext) -> None:
        self._runtime_context = runtime_context
        self._logger = runtime_context.logger.getChild("database.sqlite")
        self._database_path = self._resolve_database_path()
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize_schema()

    @property
    def database_path(self) -> Path:
        return self._database_path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            set_event_type("sqlite_transaction_failed")
            self._logger.exception("SQLite transaction failed and was rolled back")
            raise
        finally:
            connection.close()

    def initialize_schema(self) -> None:
        with self.connection() as connection:
            connection.executescript(self._build_schema_script())
            self._run_migrations(connection)

        set_event_type("sqlite_schema_initialized")
        self._logger.info("Initialized SQLite schema at %s", self._database_path)

    def _run_migrations(self, connection: sqlite3.Connection) -> None:
        """Apply incremental schema migrations for existing databases."""
        migrations: list[tuple[str, str]] = [
            ("add_cpu_cores_memory_gb", """
                ALTER TABLE fleet_assets ADD COLUMN cpu_cores INTEGER;
                ALTER TABLE fleet_assets ADD COLUMN memory_gb REAL;
            """),
            ("add_account_total_vcpu", """
                ALTER TABLE fleet_assets ADD COLUMN account_total_vcpu INTEGER;
            """),
            ("add_auth_users", """
                CREATE TABLE IF NOT EXISTS auth_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    hashed_password TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'viewer'
                        CHECK (role IN ('admin', 'operator', 'viewer')),
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_users_username
                    ON auth_users (username COLLATE NOCASE);
            """),
            ("add_sse_events", """
                CREATE TABLE IF NOT EXISTS sse_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    correlation_id TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_sse_events_created
                    ON sse_events (created_at DESC);
            """),
            ("cleanup_duplicate_nodes_and_unique_index", """
                -- This migration:
                -- 1. Removes duplicate xboard_node_id entries (keeps highest id)
                -- 2. Creates a partial UNIQUE index on xboard_node_id for active nodes
                --
                -- Step 1: Check if index already exists
                -- (migration is idempotent - safe to run multiple times)

                -- Step 2: Cleanup duplicates only if index doesn't exist yet
                DELETE FROM fleet_nodes
                WHERE is_deleted = 0
                  AND id NOT IN (
                      SELECT MAX(id)
                      FROM fleet_nodes
                      WHERE is_deleted = 0
                      GROUP BY xboard_node_id
                  );

                -- Step 3: Create unique index on xboard_node_id for non-deleted nodes
                CREATE UNIQUE INDEX IF NOT EXISTS idx_fleet_nodes_xboard_node_id_active
                    ON fleet_nodes (xboard_node_id)
                    WHERE is_deleted = 0;
            """),
        ]
        applied = connection.execute(
            "SELECT name FROM schema_migrations"
        ).fetchall()
        applied_names = {row["name"] for row in applied}
        for name, sql in migrations:
            if name in applied_names:
                continue
            for stmt in sql.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    try:
                        connection.execute(stmt)
                    except sqlite3.OperationalError:
                        pass
            connection.execute("INSERT INTO schema_migrations (name) VALUES (?)", (name,))
        connection.commit()

    def _resolve_database_path(self) -> Path:
        sqlite_path = Path(self._runtime_context.config.app.sqlite_path)
        if sqlite_path.is_absolute():
            return sqlite_path
        return Path.cwd() / sqlite_path

    @staticmethod
    def _build_schema_script() -> str:
        status_list = ", ".join(f"'{status}'" for status in FLEET_NODE_STATUSES)
        asset_type_list = ", ".join(f"'{asset_type}'" for asset_type in FLEET_ASSET_TYPES)
        asset_status_list = ", ".join(f"'{status}'" for status in FLEET_ASSET_STATUSES)
        protocol_type_list = ", ".join(f"'{protocol}'" for protocol in FLEET_PROTOCOL_TYPES)
        allocation_status_list = ", ".join(
            f"'{status}'" for status in FLEET_ALLOCATION_STATUSES
        )
        task_type_list = ", ".join(f"'{task_type}'" for task_type in FLEET_TASK_TYPES)
        task_status_list = ", ".join(f"'{status}'" for status in FLEET_TASK_STATUSES)
        manual_task_type_list = ", ".join(f"'{task_type}'" for task_type in FLEET_MANUAL_TASK_TYPES)
        manual_task_status_list = ", ".join(
            f"'{status}'" for status in FLEET_MANUAL_TASK_STATUSES
        )
        ready_callback_status_list = ", ".join(
            f"'{status}'" for status in FLEET_READY_CALLBACK_STATUSES
        )
        monitor_cycle_status_list = ", ".join(
            f"'{status}'" for status in FLEET_MONITOR_CYCLE_STATUSES
        )
        probe_status_list = ", ".join(f"'{status}'" for status in FLEET_PROBE_STATUSES)
        probe_command_type_list = ", ".join(
            f"'{command_type}'" for command_type in FLEET_PROBE_COMMAND_TYPES
        )
        probe_command_status_list = ", ".join(
            f"'{status}'" for status in FLEET_PROBE_COMMAND_STATUSES
        )
        probe_measurement_status_list = ", ".join(
            f"'{status}'" for status in FLEET_PROBE_MEASUREMENT_STATUSES
        )
        return f"""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS fleet_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            xboard_node_id INTEGER NOT NULL UNIQUE,
            node_name TEXT NOT NULL,
            node_type TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ({status_list})),
            status_reason TEXT,
            aws_account_id TEXT,
            aws_region TEXT,
            aws_instance_id TEXT,
            aws_subnet_id TEXT,
            aws_security_group_id TEXT,
            instance_type TEXT,
            cloudflare_record_id TEXT,
            domain_name TEXT,
            ipv4_address TEXT,
            ipv6_address TEXT,
            last_known_host TEXT,
            last_error TEXT,
            is_deleted INTEGER NOT NULL DEFAULT 0 CHECK (is_deleted IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            online_at TEXT,
            offline_at TEXT,
            deleted_at TEXT,
            last_healed_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_fleet_nodes_status
        ON fleet_nodes (status);

        CREATE INDEX IF NOT EXISTS idx_fleet_nodes_aws_instance_id
        ON fleet_nodes (aws_instance_id);

        CREATE INDEX IF NOT EXISTS idx_fleet_nodes_aws_region
        ON fleet_nodes (aws_region);

        CREATE INDEX IF NOT EXISTS idx_fleet_nodes_domain_name
        ON fleet_nodes (domain_name);

        CREATE TABLE IF NOT EXISTS fleet_node_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id INTEGER NOT NULL,
            xboard_node_id INTEGER,
            event_type TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT,
            correlation_id TEXT NOT NULL,
            message TEXT,
            payload_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (node_id) REFERENCES fleet_nodes(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_fleet_node_events_node_id_created_at
        ON fleet_node_events (node_id, created_at);

        CREATE INDEX IF NOT EXISTS idx_fleet_node_events_correlation_id
        ON fleet_node_events (correlation_id);

        CREATE INDEX IF NOT EXISTS idx_fleet_node_events_event_type_created_at
        ON fleet_node_events (event_type, created_at);

        CREATE TABLE IF NOT EXISTS fleet_operation_locks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lock_key TEXT NOT NULL UNIQUE,
            node_id INTEGER,
            operation_type TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (node_id) REFERENCES fleet_nodes(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_fleet_operation_locks_expires_at
        ON fleet_operation_locks (expires_at);

        CREATE TABLE IF NOT EXISTS fleet_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_type TEXT NOT NULL CHECK (asset_type IN ({asset_type_list})),
            asset_name TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ({asset_status_list})),
            region TEXT,
            aws_account_id TEXT,
            aws_access_key TEXT,
            aws_secret_key TEXT,
            ssh_host TEXT,
            ssh_port INTEGER,
            ssh_username TEXT,
            ssh_password TEXT,
            ssh_private_key TEXT,
            default_instance_type TEXT,
            default_vcpu INTEGER,
            account_total_vcpu INTEGER,
            default_architecture TEXT,
            cpu_cores INTEGER,
            memory_gb REAL,
            remarks TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_fleet_assets_asset_type_status
        ON fleet_assets (asset_type, status);

        CREATE INDEX IF NOT EXISTS idx_fleet_assets_region
        ON fleet_assets (region);

        CREATE INDEX IF NOT EXISTS idx_fleet_assets_aws_account_id
        ON fleet_assets (aws_account_id);

        CREATE INDEX IF NOT EXISTS idx_fleet_assets_ssh_host
        ON fleet_assets (ssh_host);

        CREATE TABLE IF NOT EXISTS fleet_asset_protocols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL,
            protocol_type TEXT NOT NULL CHECK (protocol_type IN ({protocol_type_list})),
            enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
            target_count INTEGER NOT NULL DEFAULT 0,
            max_count INTEGER NOT NULL DEFAULT 0,
            priority INTEGER NOT NULL DEFAULT 100,
            allow_cdn_proxy INTEGER NOT NULL DEFAULT 0 CHECK (allow_cdn_proxy IN (0, 1)),
            instance_type TEXT,
            vcpu INTEGER,
            architecture TEXT,
            ami_id TEXT,
            subnet_id TEXT,
            security_group_id TEXT,
            requires_domain INTEGER NOT NULL DEFAULT 0 CHECK (requires_domain IN (0, 1)),
            requires_dns_record INTEGER NOT NULL DEFAULT 0 CHECK (requires_dns_record IN (0, 1)),
            supports_cdn_proxy INTEGER NOT NULL DEFAULT 0 CHECK (supports_cdn_proxy IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (asset_id, protocol_type),
            FOREIGN KEY (asset_id) REFERENCES fleet_assets(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_fleet_asset_protocols_protocol_type_enabled
        ON fleet_asset_protocols (protocol_type, enabled);

        CREATE INDEX IF NOT EXISTS idx_fleet_asset_protocols_priority
        ON fleet_asset_protocols (priority);

        CREATE TABLE IF NOT EXISTS fleet_asset_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL,
            fleet_node_id INTEGER,
            xboard_node_id INTEGER,
            protocol_type TEXT NOT NULL CHECK (protocol_type IN ({protocol_type_list})),
            allocation_status TEXT NOT NULL CHECK (allocation_status IN ({allocation_status_list})),
            vcpu_count INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (asset_id) REFERENCES fleet_assets(id) ON DELETE CASCADE,
            FOREIGN KEY (fleet_node_id) REFERENCES fleet_nodes(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_fleet_asset_allocations_asset_protocol_status
        ON fleet_asset_allocations (asset_id, protocol_type, allocation_status);

        CREATE INDEX IF NOT EXISTS idx_fleet_asset_allocations_xboard_node_id
        ON fleet_asset_allocations (xboard_node_id);

        CREATE TABLE IF NOT EXISTS fleet_asset_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            message TEXT,
            payload_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (asset_id) REFERENCES fleet_assets(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_fleet_asset_events_asset_id_created_at
        ON fleet_asset_events (asset_id, created_at);

        CREATE INDEX IF NOT EXISTS idx_fleet_asset_events_correlation_id
        ON fleet_asset_events (correlation_id);

        CREATE TABLE IF NOT EXISTS fleet_asset_port_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL,
            fleet_node_id INTEGER,
            xboard_node_id INTEGER,
            server_port INTEGER NOT NULL,
            protocol_type TEXT NOT NULL,
            allocation_status TEXT NOT NULL CHECK (allocation_status IN ({allocation_status_list})),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (asset_id) REFERENCES fleet_assets(id) ON DELETE CASCADE
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_port_alloc_active
        ON fleet_asset_port_allocations (asset_id, server_port)
        WHERE allocation_status = 'allocated';

        CREATE INDEX IF NOT EXISTS idx_port_allocations_asset_protocol_status
        ON fleet_asset_port_allocations (asset_id, protocol_type, allocation_status);

        CREATE TABLE IF NOT EXISTS fleet_provisioning_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT NOT NULL CHECK (task_type IN ({task_type_list})),
            status TEXT NOT NULL CHECK (status IN ({task_status_list})),
            correlation_id TEXT NOT NULL,
            request_payload_json TEXT NOT NULL,
            result_payload_json TEXT,
            last_error TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 1,
            locked_by TEXT,
            locked_at TEXT,
            next_run_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_fleet_provisioning_tasks_status_next_run_at
        ON fleet_provisioning_tasks (status, next_run_at);

        CREATE INDEX IF NOT EXISTS idx_fleet_provisioning_tasks_correlation_id
        ON fleet_provisioning_tasks (correlation_id);

        CREATE INDEX IF NOT EXISTS idx_fleet_provisioning_tasks_created_at
        ON fleet_provisioning_tasks (created_at);

        CREATE TABLE IF NOT EXISTS fleet_manual_operation_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT NOT NULL CHECK (task_type IN ({manual_task_type_list})),
            status TEXT NOT NULL CHECK (status IN ({manual_task_status_list})),
            correlation_id TEXT NOT NULL,
            operator_name TEXT,
            xboard_node_id INTEGER NOT NULL,
            request_payload_json TEXT NOT NULL,
            result_payload_json TEXT,
            last_error TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 1,
            locked_by TEXT,
            locked_at TEXT,
            next_run_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_fleet_manual_operation_tasks_status_next_run_at
        ON fleet_manual_operation_tasks (status, next_run_at);

        CREATE INDEX IF NOT EXISTS idx_fleet_manual_operation_tasks_xboard_node_id
        ON fleet_manual_operation_tasks (xboard_node_id);

        CREATE INDEX IF NOT EXISTS idx_fleet_manual_operation_tasks_created_at
        ON fleet_manual_operation_tasks (created_at);

        CREATE TABLE IF NOT EXISTS fleet_ready_callbacks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL UNIQUE,
            xboard_node_id INTEGER NOT NULL UNIQUE,
            correlation_id TEXT NOT NULL,
            callback_token TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL CHECK (status IN ({ready_callback_status_list})),
            payload_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            received_at TEXT,
            completed_at TEXT,
            FOREIGN KEY (task_id) REFERENCES fleet_provisioning_tasks(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_fleet_ready_callbacks_token_status
        ON fleet_ready_callbacks (callback_token, status);

        CREATE INDEX IF NOT EXISTS idx_fleet_ready_callbacks_task_status
        ON fleet_ready_callbacks (task_id, status);

        CREATE TABLE IF NOT EXISTS fleet_monitor_cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            correlation_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ({monitor_cycle_status_list})),
            candidate_count INTEGER NOT NULL DEFAULT 0,
            confirmed_count INTEGER NOT NULL DEFAULT 0,
            healed_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            error_message TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_fleet_monitor_cycles_started_at
        ON fleet_monitor_cycles (started_at);

        CREATE INDEX IF NOT EXISTS idx_fleet_monitor_cycles_correlation_id
        ON fleet_monitor_cycles (correlation_id);

        CREATE TABLE IF NOT EXISTS fleet_monitor_detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id INTEGER NOT NULL,
            xboard_node_id INTEGER NOT NULL,
            detection_type TEXT NOT NULL,
            detection_status TEXT NOT NULL,
            reason TEXT,
            probe_provider TEXT,
            payload_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (cycle_id) REFERENCES fleet_monitor_cycles(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_fleet_monitor_detections_node_created_at
        ON fleet_monitor_detections (xboard_node_id, created_at);

        CREATE INDEX IF NOT EXISTS idx_fleet_monitor_detections_cycle_id
        ON fleet_monitor_detections (cycle_id);

        CREATE TABLE IF NOT EXISTS fleet_probes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            probe_id TEXT NOT NULL UNIQUE,
            probe_name TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ({probe_status_list})),
            auth_token TEXT NOT NULL UNIQUE,
            machine_fingerprint TEXT NOT NULL,
            public_ip TEXT,
            region TEXT,
            isp TEXT,
            tags_json TEXT NOT NULL,
            capabilities_json TEXT NOT NULL,
            config_version INTEGER NOT NULL DEFAULT 1,
            last_seen_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_fleet_probes_status_last_seen_at
        ON fleet_probes (status, last_seen_at);

        CREATE TABLE IF NOT EXISTS fleet_probe_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            probe_id TEXT NOT NULL,
            config_version INTEGER NOT NULL,
            config_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (probe_id, config_version),
            FOREIGN KEY (probe_id) REFERENCES fleet_probes(probe_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_fleet_probe_configs_probe_id_version
        ON fleet_probe_configs (probe_id, config_version);

        CREATE TABLE IF NOT EXISTS fleet_probe_heartbeats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            probe_id TEXT NOT NULL,
            public_ip TEXT,
            agent_version TEXT,
            runtime_metrics_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (probe_id) REFERENCES fleet_probes(probe_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_fleet_probe_heartbeats_probe_id_created_at
        ON fleet_probe_heartbeats (probe_id, created_at);

        CREATE TABLE IF NOT EXISTS fleet_probe_commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command_id TEXT NOT NULL UNIQUE,
            probe_id TEXT NOT NULL,
            command_type TEXT NOT NULL CHECK (command_type IN ({probe_command_type_list})),
            status TEXT NOT NULL CHECK (status IN ({probe_command_status_list})),
            correlation_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            result_json TEXT,
            last_error TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 1,
            leased_by TEXT,
            leased_at TEXT,
            next_run_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            finished_at TEXT,
            FOREIGN KEY (probe_id) REFERENCES fleet_probes(probe_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_fleet_probe_commands_probe_status_next_run_at
        ON fleet_probe_commands (probe_id, status, next_run_at);

        CREATE INDEX IF NOT EXISTS idx_fleet_probe_commands_correlation_id
        ON fleet_probe_commands (correlation_id);

        CREATE TABLE IF NOT EXISTS fleet_probe_measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            measurement_id TEXT NOT NULL UNIQUE,
            xboard_node_id INTEGER NOT NULL,
            correlation_id TEXT NOT NULL,
            control_plane_result_json TEXT,
            final_status TEXT NOT NULL CHECK (final_status IN ({probe_measurement_status_list})),
            reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            finished_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_fleet_probe_measurements_node_created_at
        ON fleet_probe_measurements (xboard_node_id, created_at);

        CREATE INDEX IF NOT EXISTS idx_fleet_probe_measurements_correlation_id
        ON fleet_probe_measurements (correlation_id);

        CREATE TABLE IF NOT EXISTS fleet_probe_measurement_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            measurement_id TEXT NOT NULL,
            probe_id TEXT NOT NULL,
            probe_status TEXT NOT NULL,
            failure_stage TEXT,
            resolved_ip TEXT,
            latency_ms INTEGER,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (measurement_id) REFERENCES fleet_probe_measurements(measurement_id) ON DELETE CASCADE,
            FOREIGN KEY (probe_id) REFERENCES fleet_probes(probe_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_fleet_probe_measurement_results_measurement_id
        ON fleet_probe_measurement_results (measurement_id, created_at);
        """
