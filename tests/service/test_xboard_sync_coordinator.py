"""
Unit tests for XboardSyncCoordinator
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch, call

import pytest

from services.xboard_sync_coordinator import XboardSyncCoordinator


@pytest.fixture
def mock_ctx() -> MagicMock:
    """Create a mock RuntimeContext."""
    ctx = MagicMock()
    ctx.correlation_id = "test-correlation-123"
    ctx.logger = MagicMock()
    ctx.config = MagicMock()
    return ctx


@pytest.fixture
def coordinator(mock_ctx: MagicMock) -> XboardSyncCoordinator:
    """Create an XboardSyncCoordinator instance."""
    with patch("services.xboard_sync_coordinator.XboardRepo"), \
         patch("services.xboard_sync_coordinator.StateRepo"), \
         patch("services.xboard_sync_coordinator.SyncMonitorService"), \
         patch("services.xboard_sync_coordinator.SyncCoordinatorMonitor"):
        return XboardSyncCoordinator(mock_ctx)


class TestXboardSyncCoordinator:
    """Test XboardSyncCoordinator service."""

    def test_initialization(self, coordinator: XboardSyncCoordinator) -> None:
        """Test coordinator initializes correctly."""
        assert coordinator is not None

    def test_atomic_sync_context_success(self, coordinator: XboardSyncCoordinator) -> None:
        """Test atomic sync context with successful operations."""
        with coordinator.atomic_sync_context() as register_rollback:
            # Simulate successful operations
            register_rollback("test_operation", lambda: None)

        # Should complete without raising

    def test_atomic_sync_context_failure_triggers_rollback(
        self, coordinator: XboardSyncCoordinator
    ) -> None:
        """Test atomic sync context triggers rollback on failure."""
        rollback_called = False

        def rollback_fn():
            nonlocal rollback_called
            rollback_called = True

        with pytest.raises(ValueError):
            with coordinator.atomic_sync_context() as register_rollback:
                register_rollback("test_operation", rollback_fn)
                raise ValueError("Operation failed")

        assert rollback_called

    def test_atomic_sync_context_multiple_rollbacks(
        self, coordinator: XboardSyncCoordinator
    ) -> None:
        """Test atomic sync context executes multiple rollbacks in reverse order."""
        rollback_order = []

        def rollback_1():
            rollback_order.append(1)

        def rollback_2():
            rollback_order.append(2)

        with pytest.raises(ValueError):
            with coordinator.atomic_sync_context() as register_rollback:
                register_rollback("operation_1", rollback_1)
                register_rollback("operation_2", rollback_2)
                raise ValueError("Operation failed")

        # Should rollback in reverse order
        assert rollback_order == [2, 1]

    def test_atomic_sync_context_rollback_failure_logged(
        self, coordinator: XboardSyncCoordinator
    ) -> None:
        """Test that rollback failures are logged but don't stop other rollbacks."""
        rollback_2_called = False

        def rollback_1():
            raise RuntimeError("Rollback 1 failed")

        def rollback_2():
            nonlocal rollback_2_called
            rollback_2_called = True

        with pytest.raises(ValueError):
            with coordinator.atomic_sync_context() as register_rollback:
                register_rollback("operation_1", rollback_1)
                register_rollback("operation_2", rollback_2)
                raise ValueError("Operation failed")

        # Rollback 2 should still be called even if rollback 1 failed
        assert rollback_2_called

    def test_sync_node_registration_success(
        self, coordinator: XboardSyncCoordinator
    ) -> None:
        """Test successful node registration sync."""
        xboard_node_id = 12345
        local_node_id = 1

        def create_local_node():
            return local_node_id

        with patch.object(coordinator, "_get_sqlite_write_lock"):
            result = coordinator.sync_node_registration(
                xboard_node_id=xboard_node_id,
                local_node_create_fn=create_local_node,
            )

        assert result == local_node_id

    def test_sync_node_registration_integrity_error(
        self, coordinator: XboardSyncCoordinator
    ) -> None:
        """Test node registration sync handles integrity errors."""
        xboard_node_id = 12345

        def create_local_node():
            raise sqlite3.IntegrityError("UNIQUE constraint failed")

        with patch.object(coordinator, "_get_sqlite_write_lock"):
            with pytest.raises(sqlite3.IntegrityError):
                coordinator.sync_node_registration(
                    xboard_node_id=xboard_node_id,
                    local_node_create_fn=create_local_node,
                )

    def test_sync_node_status_change_success(
        self, coordinator: XboardSyncCoordinator
    ) -> None:
        """Test successful node status change sync."""
        xboard_node_id = 12345
        xboard_called = False
        sqlite_called = False

        def xboard_op():
            nonlocal xboard_called
            xboard_called = True

        def sqlite_op():
            nonlocal sqlite_called
            sqlite_called = True

        def rollback_op():
            pass

        with patch.object(coordinator, "_get_sqlite_write_lock"), \
             patch.object(coordinator._sync_monitor, "record_sync_operation_start", return_value="op-123"), \
             patch.object(coordinator._sync_monitor, "record_sync_operation_complete"):
            coordinator.sync_node_status_change(
                xboard_node_id=xboard_node_id,
                xboard_operation=xboard_op,
                sqlite_operation=sqlite_op,
                rollback_xboard_operation=rollback_op,
                operation_name="test_operation",
            )

        assert xboard_called
        assert sqlite_called

    def test_sync_node_status_change_xboard_failure(
        self, coordinator: XboardSyncCoordinator
    ) -> None:
        """Test node status change sync handles Xboard failures."""
        from database.xboard_repo import XboardRepoError

        xboard_node_id = 12345

        def xboard_op():
            raise XboardRepoError("Xboard operation failed")

        def sqlite_op():
            pass

        def rollback_op():
            pass

        with patch.object(coordinator._sync_monitor, "record_sync_operation_start", return_value="op-123"), \
             patch.object(coordinator._sync_monitor, "record_sync_operation_complete"):
            with pytest.raises(XboardRepoError):
                coordinator.sync_node_status_change(
                    xboard_node_id=xboard_node_id,
                    xboard_operation=xboard_op,
                    sqlite_operation=sqlite_op,
                    rollback_xboard_operation=rollback_op,
                    operation_name="test_operation",
                )

    def test_sync_node_status_change_sqlite_failure_triggers_rollback(
        self, coordinator: XboardSyncCoordinator
    ) -> None:
        """Test that SQLite failure triggers Xboard rollback."""
        xboard_node_id = 12345
        rollback_called = False

        def xboard_op():
            pass

        def sqlite_op():
            raise RuntimeError("SQLite operation failed")

        def rollback_op():
            nonlocal rollback_called
            rollback_called = True

        with patch.object(coordinator, "_get_sqlite_write_lock"), \
             patch.object(coordinator._sync_monitor, "record_sync_operation_start", return_value="op-123"), \
             patch.object(coordinator._sync_monitor, "record_sync_operation_complete"):
            with pytest.raises(RuntimeError):
                coordinator.sync_node_status_change(
                    xboard_node_id=xboard_node_id,
                    xboard_operation=xboard_op,
                    sqlite_operation=sqlite_op,
                    rollback_xboard_operation=rollback_op,
                    operation_name="test_operation",
                )

        assert rollback_called

    def test_sync_node_status_change_rollback_failure_logged(
        self, coordinator: XboardSyncCoordinator
    ) -> None:
        """Test that rollback failures are logged."""
        xboard_node_id = 12345

        def xboard_op():
            pass

        def sqlite_op():
            raise RuntimeError("SQLite operation failed")

        def rollback_op():
            raise RuntimeError("Rollback failed")

        with patch.object(coordinator, "_get_sqlite_write_lock"), \
             patch.object(coordinator._sync_monitor, "record_sync_operation_start", return_value="op-123"), \
             patch.object(coordinator._sync_monitor, "record_sync_operation_complete"):
            with pytest.raises(RuntimeError, match="SQLite operation failed"):
                coordinator.sync_node_status_change(
                    xboard_node_id=xboard_node_id,
                    xboard_operation=xboard_op,
                    sqlite_operation=sqlite_op,
                    rollback_xboard_operation=rollback_op,
                    operation_name="test_operation",
                )

        # Should log the rollback failure
        coordinator._logger.exception.assert_called()

    def test_get_sqlite_write_lock_success(
        self, coordinator: XboardSyncCoordinator
    ) -> None:
        """Test getting SQLite write lock."""
        mock_connection = MagicMock()

        with patch("services.xboard_sync_coordinator.sqlite3.connect", return_value=mock_connection):
            with coordinator._get_sqlite_write_lock() as conn:
                assert conn == mock_connection

            # Should commit on success
            mock_connection.commit.assert_called_once()
            mock_connection.close.assert_called_once()

    def test_get_sqlite_write_lock_failure_rollback(
        self, coordinator: XboardSyncCoordinator
    ) -> None:
        """Test that write lock failure triggers rollback."""
        mock_connection = MagicMock()

        with patch("services.xboard_sync_coordinator.sqlite3.connect", return_value=mock_connection):
            with pytest.raises(RuntimeError):
                with coordinator._get_sqlite_write_lock():
                    raise RuntimeError("Operation failed")

            # Should rollback on failure
            mock_connection.rollback.assert_called_once()
            mock_connection.close.assert_called_once()

    def test_sync_monitor_integration(
        self, coordinator: XboardSyncCoordinator
    ) -> None:
        """Test integration with sync monitor service."""
        xboard_node_id = 12345

        def xboard_op():
            pass

        def sqlite_op():
            pass

        def rollback_op():
            pass

        with patch.object(coordinator, "_get_sqlite_write_lock"), \
             patch.object(coordinator._sync_monitor, "record_sync_operation_start", return_value="op-123") as mock_start, \
             patch.object(coordinator._sync_monitor, "record_sync_operation_complete") as mock_complete:
            coordinator.sync_node_status_change(
                xboard_node_id=xboard_node_id,
                xboard_operation=xboard_op,
                sqlite_operation=sqlite_op,
                rollback_xboard_operation=rollback_op,
                operation_name="test_operation",
            )

        # Should record operation start and completion
        mock_start.assert_called_once()
        assert mock_complete.call_count == 2  # Once after Xboard, once after SQLite
