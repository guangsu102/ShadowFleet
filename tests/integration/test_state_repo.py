"""Integration tests for database.state_repo module."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from database.state_models import (
    FleetNodeCreateRequest,
    FleetNodeEventCreateRequest,
    FleetNodeNotFoundError,
    FleetOperationLockRequest,
)
from database.state_repo import StateRepo


def create_mock_runtime_context(sqlite_conn) -> MagicMock:
    """Create a mock RuntimeContext with in-memory SQLite."""
    mock_context = MagicMock()
    mock_context.logger = MagicMock(spec=logging.Logger)
    mock_context.logger.getChild.return_value = mock_context.logger
    mock_context.correlation_id = "test-correlation-id"

    mock_sqlite_manager = MagicMock()
    mock_sqlite_manager.connection.return_value.__enter__ = MagicMock(return_value=sqlite_conn)
    mock_sqlite_manager.connection.return_value.__exit__ = MagicMock(return_value=False)
    mock_context.sqlite_manager = mock_sqlite_manager

    return mock_context


class TestStateRepoCreateNode:
    """Tests for StateRepo.create_node method."""

    def test_create_node_returns_id(self, in_memory_sqlite_db) -> None:
        """create_node should return the new node's ID."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = StateRepo(runtime_context)

        request = FleetNodeCreateRequest(
            xboard_node_id=1001,
            node_name="test-node",
            node_type="AnyTLS",
            status="provisioning",
        )

        node_id = repo.create_node(request)
        assert isinstance(node_id, int)
        assert node_id > 0

    def test_create_node_inserts_record(self, in_memory_sqlite_db) -> None:
        """create_node should insert a record into the database."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = StateRepo(runtime_context)

        request = FleetNodeCreateRequest(
            xboard_node_id=1002,
            node_name="test-node-2",
            node_type="Trojan",
            aws_account_id="acc-123",
            aws_region="ap-northeast-1",
        )

        node_id = repo.create_node(request)

        cursor = in_memory_sqlite_db.execute(
            "SELECT * FROM fleet_nodes WHERE id = ?", (node_id,)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["xboard_node_id"] == 1002
        assert row["node_name"] == "test-node-2"
        assert row["aws_account_id"] == "acc-123"

    def test_create_node_duplicate_xboard_id_raises(self, in_memory_sqlite_db) -> None:
        """Duplicate xboard_node_id should raise StateRepoError."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = StateRepo(runtime_context)

        request = FleetNodeCreateRequest(
            xboard_node_id=1003,
            node_name="test-node",
            node_type="AnyTLS",
        )

        repo.create_node(request)

        from database.state_models import StateRepoError
        with pytest.raises(StateRepoError):
            repo.create_node(request)

    def test_create_node_with_all_fields(self, in_memory_sqlite_db) -> None:
        """create_node should store all provided fields."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = StateRepo(runtime_context)

        request = FleetNodeCreateRequest(
            xboard_node_id=1004,
            node_name="full-node",
            node_type="vless",
            status="online",
            status_reason="ready",
            aws_account_id="acc-456",
            aws_region="us-east-1",
            aws_instance_id="i-123456",
            aws_subnet_id="subnet-123",
            aws_security_group_id="sg-123",
            cloudflare_record_id="cf-record-123",
            domain_name="sf-1004.example.com",
            ipv4_address="10.0.1.100",
            ipv6_address="2600:1f14:804::1",
        )

        node_id = repo.create_node(request)

        cursor = in_memory_sqlite_db.execute(
            "SELECT * FROM fleet_nodes WHERE id = ?", (node_id,)
        )
        row = cursor.fetchone()
        assert row["aws_instance_id"] == "i-123456"
        assert row["ipv6_address"] == "2600:1f14:804::1"
        assert row["domain_name"] == "sf-1004.example.com"


class TestStateRepoGetNode:
    """Tests for StateRepo.get_node_by_xboard_node_id method."""

    def test_get_existing_node(self, in_memory_sqlite_db) -> None:
        """Should return FleetNodeRecord for existing node."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = StateRepo(runtime_context)

        request = FleetNodeCreateRequest(
            xboard_node_id=2001,
            node_name="get-test-node",
            node_type="AnyTLS",
        )
        created_id = repo.create_node(request)

        result = repo.get_node_by_xboard_node_id(2001)
        assert result is not None
        assert result.id == created_id
        assert result.xboard_node_id == 2001
        assert result.node_name == "get-test-node"

    def test_get_nonexistent_node(self, in_memory_sqlite_db) -> None:
        """Should return None for non-existent node."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = StateRepo(runtime_context)

        result = repo.get_node_by_xboard_node_id(99999)
        assert result is None


class TestStateRepoUpdateNodeStatus:
    """Tests for StateRepo.update_node_status method."""

    def test_update_status_to_online(self, in_memory_sqlite_db) -> None:
        """update_node_status should change status."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = StateRepo(runtime_context)

        request = FleetNodeCreateRequest(
            xboard_node_id=3001,
            node_name="status-test",
            node_type="Trojan",
            status="provisioning",
        )
        repo.create_node(request)

        repo.update_node_status(3001, "online", status_reason="ready")

        node = repo.get_node_by_xboard_node_id(3001)
        assert node is not None
        assert node.status == "online"

    def test_update_nonexistent_node_raises(self, in_memory_sqlite_db) -> None:
        """Updating non-existent node should raise."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = StateRepo(runtime_context)

        with pytest.raises(FleetNodeNotFoundError):
            repo.update_node_status(99999, "online")


class TestStateRepoOperationLock:
    """Tests for StateRepo operation lock methods."""

    def test_acquire_lock_succeeds(self, in_memory_sqlite_db) -> None:
        """acquire_operation_lock should succeed when lock is available."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = StateRepo(runtime_context)

        lock_request = FleetOperationLockRequest(
            lock_key="test-lock",
            operation_type="healing",
            correlation_id="corr-123",
            expires_in_seconds=60,
            node_id=1,
        )

        result = repo.acquire_operation_lock(lock_request)
        assert result is True

    def test_acquire_duplicate_lock_fails(self, in_memory_sqlite_db) -> None:
        """acquire_operation_lock should fail when lock is already held."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = StateRepo(runtime_context)

        lock_request = FleetOperationLockRequest(
            lock_key="test-lock-2",
            operation_type="healing",
            correlation_id="corr-456",
            expires_in_seconds=60,
            node_id=1,
        )

        repo.acquire_operation_lock(lock_request)
        result = repo.acquire_operation_lock(lock_request)
        assert result is False

    def test_release_lock(self, in_memory_sqlite_db) -> None:
        """release_operation_lock should remove the lock."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = StateRepo(runtime_context)

        lock_request = FleetOperationLockRequest(
            lock_key="test-lock-3",
            operation_type="healing",
            correlation_id="corr-789",
            expires_in_seconds=60,
            node_id=1,
        )

        repo.acquire_operation_lock(lock_request)
        repo.release_operation_lock("test-lock-3")

        result = repo.acquire_operation_lock(lock_request)
        assert result is True

    def test_expired_lock_can_be_reacquired(self, in_memory_sqlite_db) -> None:
        """After lock expiration, same lock should be acquirable."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = StateRepo(runtime_context)

        # First acquire a lock
        lock_request = FleetOperationLockRequest(
            lock_key="test-lock-4",
            operation_type="healing",
            correlation_id="corr-first",
            expires_in_seconds=60,
            node_id=1,
        )

        result1 = repo.acquire_operation_lock(lock_request)
        assert result1 is True

        # Try to acquire the same lock - should fail
        result2 = repo.acquire_operation_lock(lock_request)
        assert result2 is False

        # Release the lock
        repo.release_operation_lock("test-lock-4")

        # Now should be able to acquire again
        result3 = repo.acquire_operation_lock(lock_request)
        assert result3 is True


class TestStateRepoEvents:
    """Tests for StateRepo event logging methods."""

    def test_create_event(self, in_memory_sqlite_db) -> None:
        """create_event should insert event record."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = StateRepo(runtime_context)

        node_request = FleetNodeCreateRequest(
            xboard_node_id=4001,
            node_name="event-test",
            node_type="AnyTLS",
        )
        node_id = repo.create_node(node_request)

        event_request = FleetNodeEventCreateRequest(
            node_id=node_id,
            xboard_node_id=4001,
            event_type="test_event",
            correlation_id="event-corr-123",
            from_status="provisioning",
            to_status="online",
            message="Node went online",
        )

        event_id = repo.create_event(event_request)
        assert isinstance(event_id, int)

        cursor = in_memory_sqlite_db.execute(
            "SELECT * FROM fleet_node_events WHERE id = ?", (event_id,)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["event_type"] == "test_event"
        assert row["correlation_id"] == "event-corr-123"


class TestStateRepoDeleteNode:
    """Tests for StateRepo soft delete methods."""

    def test_delete_node_soft_deletes(self, in_memory_sqlite_db) -> None:
        """delete_node should soft-delete (mark as deleted)."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = StateRepo(runtime_context)

        request = FleetNodeCreateRequest(
            xboard_node_id=5001,
            node_name="delete-test",
            node_type="vless",
        )
        repo.create_node(request)

        # Use update_node_status with "deleted" status to soft delete
        repo.update_node_status(5001, "deleted")

        # Soft deleted nodes should have is_deleted=True
        node = repo.get_node_by_xboard_node_id(5001)
        assert node is not None
        assert node.status == "deleted"
        assert node.is_deleted is True
        assert node.deleted_at is not None
