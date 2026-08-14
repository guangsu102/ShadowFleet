"""pytest global configuration and shared fixtures for ShadowFleet tests."""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generator
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    pass

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture
def mock_runtime_context() -> MagicMock:
    """Create a mock RuntimeContext for testing services."""
    mock = MagicMock()
    mock.correlation_id = "test-correlation-id-12345"
    mock.config = MagicMock()
    mock.logger = MagicMock(spec=logging.Logger)
    mock.logger.name = "test.logger"
    return mock


@pytest.fixture
def in_memory_sqlite_db() -> Generator[sqlite3.Connection, None, None]:
    """Create an in-memory SQLite database matching the real schema (all tables)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # schema_migrations
    cursor.execute("""
        CREATE TABLE schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # fleet_nodes
    cursor.execute("""
        CREATE TABLE fleet_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            xboard_node_id INTEGER NOT NULL UNIQUE,
            node_name TEXT NOT NULL,
            node_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'provisioning'
                CHECK (status IN (
                    'provisioning','online','offline','healing',
                    'deleting','deleted','failed'
                )),
            status_reason TEXT,
            aws_account_id TEXT,
            aws_region TEXT,
            aws_instance_id TEXT,
            aws_subnet_id TEXT,
            aws_security_group_id TEXT,
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
            last_healed_at TEXT,
            xboard_status TEXT,
            xboard_show INTEGER,
            xboard_updated_at TEXT
        )
    """)
    cursor.execute("CREATE INDEX idx_fleet_nodes_status ON fleet_nodes (status)")
    cursor.execute("CREATE INDEX idx_fleet_nodes_aws_instance_id ON fleet_nodes (aws_instance_id)")
    cursor.execute("CREATE INDEX idx_fleet_nodes_aws_region ON fleet_nodes (aws_region)")
    cursor.execute("CREATE INDEX idx_fleet_nodes_domain_name ON fleet_nodes (domain_name)")

    # fleet_node_events
    cursor.execute("""
        CREATE TABLE fleet_node_events (
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
        )
    """)
    cursor.execute("CREATE INDEX idx_fleet_node_events_node_id_created_at ON fleet_node_events (node_id, created_at)")
    cursor.execute("CREATE INDEX idx_fleet_node_events_correlation_id ON fleet_node_events (correlation_id)")

    # fleet_operation_locks
    cursor.execute("""
        CREATE TABLE fleet_operation_locks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lock_key TEXT NOT NULL UNIQUE,
            node_id INTEGER,
            operation_type TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (node_id) REFERENCES fleet_nodes(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("CREATE INDEX idx_fleet_operation_locks_expires_at ON fleet_operation_locks (expires_at)")

    # fleet_assets
    cursor.execute("""
        CREATE TABLE fleet_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_type TEXT NOT NULL CHECK (asset_type IN ('aws', 'azure', 'digitalocean', 'oci', 'vultr', 'self_hosted')),
            asset_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','full','banned','offline','deploying')),
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
            provider_config_json TEXT,
            remarks TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX idx_fleet_assets_asset_type_status ON fleet_assets (asset_type, status)")
    cursor.execute("CREATE INDEX idx_fleet_assets_region ON fleet_assets (region)")
    cursor.execute("CREATE INDEX idx_fleet_assets_aws_account_id ON fleet_assets (aws_account_id)")
    cursor.execute("CREATE INDEX idx_fleet_assets_ssh_host ON fleet_assets (ssh_host)")

    # fleet_asset_protocols
    cursor.execute("""
        CREATE TABLE fleet_asset_protocols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL,
            protocol_type TEXT NOT NULL
                CHECK (protocol_type IN ('AnyTLS','Trojan','vless','vmess','Hysteria2')),
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
        )
    """)
    cursor.execute("CREATE INDEX idx_fleet_asset_protocols_protocol_type_enabled ON fleet_asset_protocols (protocol_type, enabled)")

    # fleet_asset_allocations
    cursor.execute("""
        CREATE TABLE fleet_asset_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL,
            fleet_node_id INTEGER,
            xboard_node_id INTEGER,
            protocol_type TEXT NOT NULL,
            allocation_status TEXT NOT NULL
                CHECK (allocation_status IN ('allocated','released','failed')),
            vcpu_count INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (asset_id) REFERENCES fleet_assets(id) ON DELETE CASCADE,
            FOREIGN KEY (fleet_node_id) REFERENCES fleet_nodes(id) ON DELETE SET NULL
        )
    """)
    cursor.execute("CREATE INDEX idx_fleet_asset_allocations_asset_protocol_status ON fleet_asset_allocations (asset_id, protocol_type, allocation_status)")
    cursor.execute("CREATE INDEX idx_fleet_asset_allocations_xboard_node_id ON fleet_asset_allocations (xboard_node_id)")

    # fleet_asset_events
    cursor.execute("""
        CREATE TABLE fleet_asset_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            message TEXT,
            payload_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (asset_id) REFERENCES fleet_assets(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("CREATE INDEX idx_fleet_asset_events_asset_id_created_at ON fleet_asset_events (asset_id, created_at)")

    # fleet_asset_port_allocations
    cursor.execute("""
        CREATE TABLE fleet_asset_port_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL,
            fleet_node_id INTEGER,
            xboard_node_id INTEGER,
            server_port INTEGER NOT NULL,
            protocol_type TEXT NOT NULL,
            allocation_status TEXT NOT NULL
                CHECK (allocation_status IN ('allocated','released','failed')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (asset_id) REFERENCES fleet_assets(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("CREATE UNIQUE INDEX idx_port_alloc_active ON fleet_asset_port_allocations (asset_id, server_port) WHERE allocation_status = 'allocated'")
    cursor.execute("CREATE INDEX idx_port_allocations_asset_protocol_status ON fleet_asset_port_allocations (asset_id, protocol_type, allocation_status)")

    # fleet_provisioning_tasks
    cursor.execute("""
        CREATE TABLE fleet_provisioning_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT NOT NULL CHECK (task_type IN ('provision_node')),
            status TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued','running','succeeded','failed')),
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
        )
    """)
    cursor.execute("CREATE INDEX idx_fleet_provisioning_tasks_status_next_run_at ON fleet_provisioning_tasks (status, next_run_at)")
    cursor.execute("CREATE INDEX idx_fleet_provisioning_tasks_correlation_id ON fleet_provisioning_tasks (correlation_id)")

    # fleet_manual_operation_tasks
    cursor.execute("""
        CREATE TABLE fleet_manual_operation_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT NOT NULL
                CHECK (task_type IN ('force_heal','decommission_node','reprobe_node','mark_manual_review')),
            status TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued','running','succeeded','failed')),
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
        )
    """)
    cursor.execute("CREATE INDEX idx_fleet_manual_operation_tasks_status_next_run_at ON fleet_manual_operation_tasks (status, next_run_at)")
    cursor.execute("CREATE INDEX idx_fleet_manual_operation_tasks_xboard_node_id ON fleet_manual_operation_tasks (xboard_node_id)")

    # fleet_ready_callbacks
    cursor.execute("""
        CREATE TABLE fleet_ready_callbacks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL UNIQUE,
            xboard_node_id INTEGER NOT NULL UNIQUE,
            correlation_id TEXT NOT NULL,
            callback_token TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL
                CHECK (status IN ('pending','received','completed')),
            payload_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            received_at TEXT,
            completed_at TEXT,
            FOREIGN KEY (task_id) REFERENCES fleet_provisioning_tasks(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("CREATE INDEX idx_fleet_ready_callbacks_token_status ON fleet_ready_callbacks (callback_token, status)")

    # fleet_monitor_cycles
    cursor.execute("""
        CREATE TABLE fleet_monitor_cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            correlation_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('running','succeeded','failed')),
            candidate_count INTEGER NOT NULL DEFAULT 0,
            confirmed_count INTEGER NOT NULL DEFAULT 0,
            healed_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            error_message TEXT
        )
    """)
    cursor.execute("CREATE INDEX idx_fleet_monitor_cycles_started_at ON fleet_monitor_cycles (started_at)")

    # fleet_monitor_detections
    cursor.execute("""
        CREATE TABLE fleet_monitor_detections (
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
        )
    """)
    cursor.execute("CREATE INDEX idx_fleet_monitor_detections_node_created_at ON fleet_monitor_detections (xboard_node_id, created_at)")

    # fleet_probes
    cursor.execute("""
        CREATE TABLE fleet_probes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            probe_id TEXT NOT NULL UNIQUE,
            probe_name TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending','active','disabled','offline','draining')),
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
        )
    """)
    cursor.execute("CREATE INDEX idx_fleet_probes_status_last_seen_at ON fleet_probes (status, last_seen_at)")

    # fleet_probe_configs
    cursor.execute("""
        CREATE TABLE fleet_probe_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            probe_id TEXT NOT NULL,
            config_version INTEGER NOT NULL,
            config_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (probe_id, config_version),
            FOREIGN KEY (probe_id) REFERENCES fleet_probes(probe_id) ON DELETE CASCADE
        )
    """)
    cursor.execute("CREATE INDEX idx_fleet_probe_configs_probe_id_version ON fleet_probe_configs (probe_id, config_version)")

    # fleet_probe_heartbeats
    cursor.execute("""
        CREATE TABLE fleet_probe_heartbeats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            probe_id TEXT NOT NULL,
            public_ip TEXT,
            agent_version TEXT,
            runtime_metrics_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (probe_id) REFERENCES fleet_probes(probe_id) ON DELETE CASCADE
        )
    """)
    cursor.execute("CREATE INDEX idx_fleet_probe_heartbeats_probe_id_created_at ON fleet_probe_heartbeats (probe_id, created_at)")

    # fleet_probe_commands
    cursor.execute("""
        CREATE TABLE fleet_probe_commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command_id TEXT NOT NULL UNIQUE,
            probe_id TEXT NOT NULL,
            command_type TEXT NOT NULL
                CHECK (command_type IN (
                    'run_connectivity_probe','refresh_config','self_check','drain_probe','resume_probe'
                )),
            status TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued','leased','succeeded','failed','cancelled')),
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
        )
    """)
    cursor.execute("CREATE INDEX idx_fleet_probe_commands_probe_status_next_run_at ON fleet_probe_commands (probe_id, status, next_run_at)")
    cursor.execute("CREATE INDEX idx_fleet_probe_commands_correlation_id ON fleet_probe_commands (correlation_id)")

    # fleet_probe_measurements
    cursor.execute("""
        CREATE TABLE fleet_probe_measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            measurement_id TEXT NOT NULL UNIQUE,
            xboard_node_id INTEGER NOT NULL,
            correlation_id TEXT NOT NULL,
            control_plane_result_json TEXT,
            final_status TEXT NOT NULL
                CHECK (final_status IN (
                    'pending','collecting','healthy','origin_fault',
                    'suspected_blocked','confirmed_blocked_by_gfw',
                    'probe_inconclusive','failed'
                )),
            reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            finished_at TEXT
        )
    """)
    cursor.execute("CREATE INDEX idx_fleet_probe_measurements_node_created_at ON fleet_probe_measurements (xboard_node_id, created_at)")

    # fleet_probe_measurement_results
    cursor.execute("""
        CREATE TABLE fleet_probe_measurement_results (
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
        )
    """)
    cursor.execute("CREATE INDEX idx_fleet_probe_measurement_results_measurement_id ON fleet_probe_measurement_results (measurement_id, created_at)")

    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def full_schema_sqlite_db() -> Generator[sqlite3.Connection, None, None]:
    """Create an in-memory SQLite DB using the real schema builder from sqlite_connection.py.

    This fixture uses the actual _build_schema_script() method, ensuring that
    integration tests always run against the real schema.
    """
    from database.sqlite_connection import SqliteConnectionManager

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.executescript(SqliteConnectionManager._build_schema_script())
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def sample_config_dict() -> dict[str, Any]:
    """Create a minimal valid configuration dictionary for testing."""
    return {
        "app": {
            "environment": "test",
            "sqlite_path": ":memory:",
            "sentinel_enabled": False,
        },
        "logging": {
            "level": "DEBUG",
        },
        "telegram": {
            "enabled": False,
        },
        "cloudflare": {
            "enabled": True,
            "api_token": "test_cf_token_12345",
            "zone_id": "test_zone_id_67890",
            "root_domain": "example.com",
            "auto_subdomain_prefix": "sf",
        },
        "aws_proxy": {
            "enabled": False,
        },
        "xboard": {
            "host": "localhost",
            "port": 5432,
            "database": "xboard_test",
            "user": "test_user",
            "password": "test_password",
        },
        "fleet_matrix": {
            "ap-northeast-1": {
                "AnyTLS": {
                    "desired_count": 5,
                    "min_alert_threshold": 2,
                },
                "Trojan": {
                    "desired_count": 3,
                    "min_alert_threshold": 1,
                },
            }
        },
    }


@pytest.fixture
def mock_ec2_client() -> MagicMock:
    """Create a mock EC2Client for testing."""
    mock = MagicMock()
    mock.rotate_instance_ipv6.return_value = ("2600:1f14:804:as03:1234::", "2600:1f14:804:as03:5678::")
    mock.launch_ipv6_instance.return_value = MagicMock(
        instance_id="i-0abcdef1234567890",
        instance_state="running",
        ipv6_addresses=["2600:1f14:804:as03:abcd::"],
        network_interface_id="eni-1234567890abcdef0",
    )
    return mock


@pytest.fixture
def mock_cf_client() -> MagicMock:
    """Create a mock CFClient for testing."""
    mock = MagicMock()
    mock.sync_aaaa_record.return_value = "cloudflare_record_123"
    mock.set_record_proxied.return_value = None
    mock.upsert_dns_record.return_value = "cloudflare_record_456"
    return mock


@pytest.fixture
def mock_xboard_repo() -> MagicMock:
    """Create a mock XboardRepo for testing."""
    mock = MagicMock()
    mock.register_node.return_value = 12345
    mock.mark_node_online.return_value = None
    mock.update_node_host.return_value = None
    mock.delete_node.return_value = None
    return mock


@pytest.fixture
def mock_state_repo() -> MagicMock:
    """Create a mock StateRepo for testing."""
    mock = MagicMock()
    mock.get_node_by_xboard_node_id.return_value = MagicMock(
        id=1,
        xboard_node_id=12345,
        node_name="test-node",
        node_type="AnyTLS",
        status="online",
        ipv6_address="2600:1f14:804:as03:1234::",
        domain_name="sf-12345.example.com",
        aws_account_id="test-aws-account-001",
        aws_region="ap-northeast-1",
        aws_instance_id="i-0abcdef1234567890",
        aws_subnet_id="subnet-1234567890abcdef0",
        cloudflare_record_id="cloudflare_record_123",
    )
    mock.acquire_operation_lock.return_value = True
    mock.create_event.return_value = None
    mock.update_node_status.return_value = None
    mock.update_node_runtime_metadata.return_value = None
    return mock


@pytest.fixture(autouse=True)
def clean_environment() -> Generator[None, None, None]:
    """Clean environment variables before and after each test."""
    original_env = os.environ.copy()

    test_env_keys = [k for k in os.environ.keys() if k.startswith("SHADOWFLEET_")]
    for key in test_env_keys:
        del os.environ[key]

    yield

    os.environ.clear()
    os.environ.update(original_env)
