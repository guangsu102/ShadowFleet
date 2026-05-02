"""Integration tests: verify SQLite schema completeness and table structure.

This file validates that all tables defined in sqlite_connection.py
are correctly present in the in-memory fixture used by all integration tests.
"""

from __future__ import annotations

import sqlite3



def _get_table_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def _get_table_indexes(cursor: sqlite3.Cursor, table_name: str) -> list[str]:
    cursor.execute(f"PRAGMA index_list({table_name})")
    return [row[1] for row in cursor.fetchall()]


# All tables expected to exist, in dependency order (no forward FK references).
ALL_TABLES = [
    "schema_migrations",
    "fleet_nodes",
    "fleet_node_events",
    "fleet_operation_locks",
    "fleet_assets",
    "fleet_asset_protocols",
    "fleet_asset_allocations",
    "fleet_asset_events",
    "fleet_asset_port_allocations",
    "fleet_provisioning_tasks",
    "fleet_manual_operation_tasks",
    "fleet_ready_callbacks",
    "fleet_monitor_cycles",
    "fleet_monitor_detections",
    "fleet_probes",
    "fleet_probe_configs",
    "fleet_probe_heartbeats",
    "fleet_probe_commands",
    "fleet_probe_measurements",
    "fleet_probe_measurement_results",
]


class TestSqliteSchemaCompleteness:
    """Verify all required tables exist in the test fixture."""

    def test_all_tables_exist_in_in_memory_fixture(self, in_memory_sqlite_db) -> None:
        """All 15 tables should exist in the in_memory_sqlite_db fixture."""
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        actual_tables = {row[0] for row in cursor.fetchall()} - {"sqlite_sequence"}
        assert actual_tables == set(ALL_TABLES), (
            f"Missing tables: {set(ALL_TABLES) - actual_tables}; "
            f"Extra: {actual_tables - set(ALL_TABLES)}"
        )

    def test_all_tables_exist_in_full_schema_fixture(self, full_schema_sqlite_db) -> None:
        """All 15 tables should exist in the full_schema_sqlite_db fixture."""
        cursor = full_schema_sqlite_db.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        actual_tables = {row[0] for row in cursor.fetchall()} - {"sqlite_sequence"}
        assert actual_tables == set(ALL_TABLES), (
            f"Missing tables: {set(ALL_TABLES) - actual_tables}; "
            f"Extra: {actual_tables - set(ALL_TABLES)}"
        )


class TestFleetNodesSchema:
    """Schema validation for fleet_nodes."""

    def test_required_columns(self, in_memory_sqlite_db) -> None:
        cols = _get_table_columns(in_memory_sqlite_db.cursor(), "fleet_nodes")
        required = {
            "id", "xboard_node_id", "node_name", "node_type", "status",
            "aws_account_id", "aws_region", "aws_instance_id",
            "aws_subnet_id", "aws_security_group_id", "cloudflare_record_id",
            "domain_name", "ipv6_address", "is_deleted",
            "created_at", "updated_at", "online_at", "last_healed_at",
        }
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_xboard_node_id_is_unique(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_nodes'")
        ddl = cursor.fetchone()[0]
        assert "UNIQUE" in ddl and "xboard_node_id" in ddl

    def test_status_check_constraint(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_nodes'")
        ddl = cursor.fetchone()[0]
        assert "CHECK" in ddl
        # Valid statuses: provisioning, online, offline, healing, deleting, deleted, failed
        # Use unique xboard_node_id for each row to avoid UNIQUE constraint violation.
        base_id = 99000
        for i, status in enumerate(["online", "failed", "deleted"]):
            in_memory_sqlite_db.execute(
                "INSERT INTO fleet_nodes (xboard_node_id, node_name, node_type, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
                (base_id + i, f"schema-test-node-{i}", "AnyTLS", status),
            )
        in_memory_sqlite_db.rollback()  # don't persist

    def test_indexes_exist(self, in_memory_sqlite_db) -> None:
        indexes = _get_table_indexes(in_memory_sqlite_db.cursor(), "fleet_nodes")
        expected = {"idx_fleet_nodes_status", "idx_fleet_nodes_aws_instance_id",
                    "idx_fleet_nodes_aws_region", "idx_fleet_nodes_domain_name"}
        assert set(indexes).issuperset(expected)


class TestFleetProvisioningTasksSchema:
    """Schema validation for fleet_provisioning_tasks (mirrors real production schema)."""

    def test_required_columns(self, in_memory_sqlite_db) -> None:
        cols = _get_table_columns(in_memory_sqlite_db.cursor(), "fleet_provisioning_tasks")
        required = {
            "id", "task_type", "status", "correlation_id",
            "request_payload_json", "result_payload_json", "last_error",
            "attempt_count", "max_attempts", "locked_by", "locked_at",
            "next_run_at", "created_at", "updated_at",
            "started_at", "finished_at",
        }
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_task_type_check_constraint(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_provisioning_tasks'")
        ddl = cursor.fetchone()[0]
        assert "CHECK" in ddl
        assert "'provision_node'" in ddl

    def test_status_check_constraint(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_provisioning_tasks'")
        ddl = cursor.fetchone()[0]
        # Valid statuses: queued, running, succeeded, failed
        assert "'queued'" in ddl
        assert "'failed'" in ddl

    def test_indexes_exist(self, in_memory_sqlite_db) -> None:
        indexes = _get_table_indexes(in_memory_sqlite_db.cursor(), "fleet_provisioning_tasks")
        assert "idx_fleet_provisioning_tasks_status_next_run_at" in indexes
        assert "idx_fleet_provisioning_tasks_correlation_id" in indexes


class TestFleetOperationLocksSchema:
    """Schema validation for fleet_operation_locks."""

    def test_lock_key_is_unique(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_operation_locks'")
        ddl = cursor.fetchone()[0]
        assert "UNIQUE" in ddl and "lock_key" in ddl

    def test_expires_at_index_exists(self, in_memory_sqlite_db) -> None:
        indexes = _get_table_indexes(in_memory_sqlite_db.cursor(), "fleet_operation_locks")
        assert "idx_fleet_operation_locks_expires_at" in indexes


class TestFleetAssetsSchema:
    """Schema validation for fleet_assets."""

    def test_required_columns(self, in_memory_sqlite_db) -> None:
        cols = _get_table_columns(in_memory_sqlite_db.cursor(), "fleet_assets")
        required = {
            "id", "asset_type", "asset_name", "status",
            "region", "aws_account_id", "ssh_host",
            "default_instance_type", "default_vcpu",
            "created_at", "updated_at",
        }
        assert required.issubset(cols)

    def test_asset_type_check_constraint(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_assets'")
        ddl = cursor.fetchone()[0]
        assert "'aws'" in ddl
        assert "'self_hosted'" in ddl


class TestFleetProbesSchema:
    """Schema validation for fleet_probes and related tables."""

    def test_probe_probe_id_unique(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_probes'")
        ddl = cursor.fetchone()[0]
        assert "probe_id" in ddl and "UNIQUE" in ddl

    def test_probe_auth_token_unique(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_probes'")
        ddl = cursor.fetchone()[0]
        assert "auth_token" in ddl and "UNIQUE" in ddl

    def test_probe_commands_command_id_unique(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_probe_commands'")
        ddl = cursor.fetchone()[0]
        assert "command_id" in ddl and "UNIQUE" in ddl

    def test_probe_measurements_measurement_id_unique(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_probe_measurements'")
        ddl = cursor.fetchone()[0]
        assert "measurement_id" in ddl and "UNIQUE" in ddl

    def test_probe_measurement_results_fk(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_probe_measurement_results'")
        ddl = cursor.fetchone()[0]
        assert "FOREIGN KEY" in ddl
        assert "measurement_id" in ddl
        assert "probe_id" in ddl


class TestFleetReadyCallbacksSchema:
    """Schema validation for fleet_ready_callbacks."""

    def test_callback_token_unique(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_ready_callbacks'")
        ddl = cursor.fetchone()[0]
        assert "callback_token" in ddl and "UNIQUE" in ddl

    def test_task_id_unique(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_ready_callbacks'")
        ddl = cursor.fetchone()[0]
        assert "task_id" in ddl and "UNIQUE" in ddl

    def test_xboard_node_id_unique(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_ready_callbacks'")
        ddl = cursor.fetchone()[0]
        assert "xboard_node_id" in ddl and "UNIQUE" in ddl


class TestFleetManualOperationTasksSchema:
    """Schema validation for fleet_manual_operation_tasks."""

    def test_required_columns(self, in_memory_sqlite_db) -> None:
        cols = _get_table_columns(in_memory_sqlite_db.cursor(), "fleet_manual_operation_tasks")
        required = {
            "id", "task_type", "status", "correlation_id",
            "operator_name", "xboard_node_id", "request_payload_json",
            "attempt_count", "next_run_at", "created_at", "updated_at",
        }
        assert required.issubset(cols), f"Missing: {required - cols}"

    def test_task_type_check(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_manual_operation_tasks'")
        ddl = cursor.fetchone()[0]
        assert "'force_heal'" in ddl
        assert "'decommission_node'" in ddl


class TestSchemaForeignKeys:
    """Verify critical foreign key relationships."""

    def test_fleet_node_events_has_fk_to_fleet_nodes(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_node_events'")
        ddl = cursor.fetchone()[0]
        assert "FOREIGN KEY" in ddl
        assert "node_id" in ddl

    def test_fleet_operation_locks_has_fk_to_fleet_nodes(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_operation_locks'")
        ddl = cursor.fetchone()[0]
        assert "FOREIGN KEY" in ddl

    def test_fleet_ready_callbacks_has_fk_to_provisioning_tasks(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_ready_callbacks'")
        ddl = cursor.fetchone()[0]
        assert "fleet_provisioning_tasks" in ddl

    def test_fleet_monitor_detections_has_fk_to_cycles(self, in_memory_sqlite_db) -> None:
        cursor = in_memory_sqlite_db.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_monitor_detections'")
        ddl = cursor.fetchone()[0]
        assert "fleet_monitor_cycles" in ddl
