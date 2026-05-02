"""Integration tests for database.provisioning_task_repo module."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from database.provisioning_task_repo import (
    JsonValue,
    ProvisioningTaskCreateRequest,
    ProvisioningTaskNotFoundError,
    ProvisioningTaskRepo,
)
from services.provisioning_models import ProvisionRequest


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

    # ProvisioningTaskService reads these from config.app
    mock_config_app = MagicMock()
    mock_config_app.max_retries = 2
    mock_config_app.retry_backoff_seconds = 1.0
    mock_config_app.request_timeout_seconds = 10
    mock_config_app.sentinel_enabled = False
    mock_config_app.dashboard_require_password = False
    mock_config_app.sqlite_path = ":memory:"
    mock_context.config = MagicMock()
    mock_context.config.app = mock_config_app

    return mock_context


def make_request_payload(**overrides: Any) -> dict[str, JsonValue]:
    defaults: dict[str, JsonValue] = {
        "protocol_type": "AnyTLS",
        "node_name": "test-node",
        "port": "443",
        "server_port": 443,
        "rate": "100",
        "asset_type": "aws",
        "region": "us-east-1",
        "domain_name": None,
        "require_cdn_proxy": False,
        "code": None,
        "parent_id": None,
        "group_ids": None,
        "route_ids": None,
        "tags": None,
        "protocol_settings": None,
        "show": True,
        "sort": None,
        "rate_time_enable": False,
        "rate_time_ranges": None,
        "status_reason": None,
    }
    defaults.update(overrides)
    return defaults


class TestProvisioningTaskRepoCreate:
    """Tests for ProvisioningTaskRepo.create_task method."""

    def test_create_task_returns_id(self, in_memory_sqlite_db) -> None:
        """create_task should return the new task's ID as an integer."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        request = ProvisioningTaskCreateRequest(
            correlation_id="corr-create-001",
            request_payload=make_request_payload(),
        )

        task_id = repo.create_task(request)
        assert isinstance(task_id, int)
        assert task_id > 0

    def test_create_task_inserts_queued_record(self, in_memory_sqlite_db) -> None:
        """Created task should have status='queued' in SQLite."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        request = ProvisioningTaskCreateRequest(
            correlation_id="corr-create-002",
            request_payload=make_request_payload(node_name="queued-node"),
        )
        task_id = repo.create_task(request)

        record = repo.get_task_by_id(task_id)
        assert record.status == "queued"
        assert record.task_type == "provision_node"
        assert record.correlation_id == "corr-create-002"
        assert record.attempt_count == 0

    def test_create_task_stores_payload_json(self, in_memory_sqlite_db) -> None:
        """The request payload should be stored as JSON."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        payload = make_request_payload(protocol_type="Trojan", region="ap-northeast-1")
        request = ProvisioningTaskCreateRequest(
            correlation_id="corr-create-003",
            request_payload=payload,
        )
        task_id = repo.create_task(request)

        record = repo.get_task_by_id(task_id)
        assert record.request_payload["protocol_type"] == "Trojan"
        assert record.request_payload["region"] == "ap-northeast-1"

    def test_create_task_with_custom_max_attempts(self, in_memory_sqlite_db) -> None:
        """Custom max_attempts should be respected."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        request = ProvisioningTaskCreateRequest(
            correlation_id="corr-create-004",
            request_payload=make_request_payload(),
            max_attempts=5,
        )
        task_id = repo.create_task(request)

        record = repo.get_task_by_id(task_id)
        assert record.max_attempts == 5

    def test_create_task_empty_correlation_id_raises(self, in_memory_sqlite_db) -> None:
        """Empty correlation_id should raise ValueError."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        with pytest.raises(ValueError, match="correlation_id"):
            repo.create_task(
                ProvisioningTaskCreateRequest(
                    correlation_id="",
                    request_payload=make_request_payload(),
                )
            )

    def test_create_task_zero_max_attempts_raises(self, in_memory_sqlite_db) -> None:
        """max_attempts <= 0 should raise ValueError."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        with pytest.raises(ValueError, match="max_attempts"):
            repo.create_task(
                ProvisioningTaskCreateRequest(
                    correlation_id="corr-005",
                    request_payload=make_request_payload(),
                    max_attempts=0,
                )
            )


class TestProvisioningTaskRepoGetAndList:
    """Tests for get and list methods."""

    def setup_method(self) -> None:
        self._created_ids: list[int] = []

    def _create_task(
        self,
        repo: ProvisioningTaskRepo,
        correlation_id: str,
        status: str = "queued",
        node_name: str = "test-node",
    ) -> int:
        request = ProvisioningTaskCreateRequest(
            correlation_id=correlation_id,
            request_payload=make_request_payload(node_name=node_name),
        )
        task_id = repo.create_task(request)
        self._created_ids.append(task_id)
        return task_id

    def test_get_task_by_id_returns_record(self, in_memory_sqlite_db) -> None:
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)
        task_id = self._create_task(repo, "corr-get-001")

        record = repo.get_task_by_id(task_id)
        assert record.id == task_id
        assert record.correlation_id == "corr-get-001"

    def test_get_task_by_id_not_found_raises(self, in_memory_sqlite_db) -> None:
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        with pytest.raises(ProvisioningTaskNotFoundError, match="not found"):
            repo.get_task_by_id(99999)

    def test_list_recent_tasks_returns_multiple(self, in_memory_sqlite_db) -> None:
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)
        for i in range(5):
            self._create_task(repo, f"corr-list-{i:03d}", node_name=f"node-{i}")

        records = repo.list_recent_tasks(limit=3)
        assert len(records) == 3
        # Most recent first
        assert records[0].correlation_id == "corr-list-004"
        assert records[1].correlation_id == "corr-list-003"
        assert records[2].correlation_id == "corr-list-002"

    def test_list_recent_tasks_zero_limit_raises(self, in_memory_sqlite_db) -> None:
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        with pytest.raises(ValueError, match="limit"):
            repo.list_recent_tasks(limit=0)


class TestProvisioningTaskClaim:
    """Tests for claim_next_task (worker picks up queued task)."""

    def test_claim_next_task_returns_record(self, in_memory_sqlite_db) -> None:
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        # Create a queued task
        request = ProvisioningTaskCreateRequest(
            correlation_id="corr-claim-001",
            request_payload=make_request_payload(node_name="claim-node"),
        )
        task_id = repo.create_task(request)

        # Claim it
        record = repo.claim_next_task(worker_id="worker-1")
        assert record is not None
        assert record.id == task_id
        assert record.status == "running"
        assert record.locked_by == "worker-1"
        assert record.attempt_count == 1

    def test_claim_next_task_empty_worker_id_raises(self, in_memory_sqlite_db) -> None:
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        with pytest.raises(ValueError, match="worker_id"):
            repo.claim_next_task(worker_id="")

    def test_claim_next_task_no_queued_tasks_returns_none(self, in_memory_sqlite_db) -> None:
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        # No tasks created
        result = repo.claim_next_task(worker_id="worker-1")
        assert result is None

    def test_claim_next_task_concurrent_claim_race_returns_none(
        self, in_memory_sqlite_db
    ) -> None:
        """Simulate a race: second worker tries to claim the same task."""
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        request = ProvisioningTaskCreateRequest(
            correlation_id="corr-claim-race",
            request_payload=make_request_payload(),
        )
        task_id = repo.create_task(request)

        # First worker claims
        record1 = repo.claim_next_task(worker_id="worker-1")
        assert record1 is not None
        _task_id = task_id

        # Second worker should get None (task is now 'running', not 'queued')
        record2 = repo.claim_next_task(worker_id="worker-2")
        assert record2 is None


class TestProvisioningTaskStateTransitions:
    """Tests for mark_task_succeeded / mark_task_failed / mark_task_for_retry."""

    def test_mark_task_succeeded(self, in_memory_sqlite_db) -> None:
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        request = ProvisioningTaskCreateRequest(
            correlation_id="corr-state-001",
            request_payload=make_request_payload(),
        )
        task_id = repo.create_task(request)
        repo.claim_next_task(worker_id="worker-1")

        result_payload = {"local_node_id": 1, "xboard_node_id": 12345}
        repo.mark_task_succeeded(task_id=task_id, result_payload=result_payload)

        record = repo.get_task_by_id(task_id)
        assert record.status == "succeeded"
        assert record.result_payload == result_payload
        assert record.finished_at is not None

    def test_mark_task_failed(self, in_memory_sqlite_db) -> None:
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        request = ProvisioningTaskCreateRequest(
            correlation_id="corr-state-002",
            request_payload=make_request_payload(),
        )
        task_id = repo.create_task(request)
        repo.claim_next_task(worker_id="worker-1")

        repo.mark_task_failed(task_id=task_id, error_message="AWS API timeout")

        record = repo.get_task_by_id(task_id)
        assert record.status == "failed"
        assert record.last_error == "AWS API timeout"
        assert record.finished_at is not None

    def test_mark_task_failed_empty_error_raises(self, in_memory_sqlite_db) -> None:
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        request = ProvisioningTaskCreateRequest(
            correlation_id="corr-state-003",
            request_payload=make_request_payload(),
        )
        task_id = repo.create_task(request)

        with pytest.raises(ValueError, match="error_message"):
            repo.mark_task_failed(task_id=task_id, error_message="")

    def test_mark_task_for_retry(self, in_memory_sqlite_db) -> None:
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        request = ProvisioningTaskCreateRequest(
            correlation_id="corr-retry-001",
            request_payload=make_request_payload(),
            max_attempts=3,
        )
        task_id = repo.create_task(request)
        repo.claim_next_task(worker_id="worker-1")

        repo.mark_task_for_retry(
            task_id=task_id,
            error_message="Transient error",
            retry_after_seconds=30.0,
        )

        record = repo.get_task_by_id(task_id)
        assert record.status == "queued"
        assert record.last_error == "Transient error"
        assert record.attempt_count == 1
        assert record.locked_by is None  # lock released

    def test_mark_task_for_retry_invalid_retry_seconds_raises(self, in_memory_sqlite_db) -> None:
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        request = ProvisioningTaskCreateRequest(
            correlation_id="corr-retry-002",
            request_payload=make_request_payload(),
        )
        task_id = repo.create_task(request)

        with pytest.raises(ValueError, match="retry_after_seconds"):
            repo.mark_task_for_retry(task_id=task_id, error_message="err", retry_after_seconds=0)


class TestProvisioningTaskStaleRecovery:
    """Tests for recover_stale_running_tasks (watchdog)."""

    def test_recover_stale_running_tasks_no_stale_tasks(self, in_memory_sqlite_db) -> None:
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        request = ProvisioningTaskCreateRequest(
            correlation_id="corr-stale-001",
            request_payload=make_request_payload(),
        )
        repo.create_task(request)

        from services.provisioning_task_service import (
            ProvisioningTaskService,
        )

        svc = ProvisioningTaskService(runtime_context)
        result = svc.recover_stale_running_tasks(
            worker_id="watchdog",
            running_timeout_seconds=60.0,
            retry_after_seconds=30.0,
        )
        assert result.scanned_task_count == 0
        assert result.requeued_task_count == 0
        assert result.failed_task_count == 0

    def _insert_stale_task(
        self,
        sqlite_conn,
        correlation_id: str,
        max_attempts: int,
        locked_by: str,
        locked_at_seconds_ago: float,
    ) -> int:
        """Insert a task directly in 'running' state with a past locked_at (simulates a crashed worker)."""
        from datetime import datetime, timedelta, timezone

        locked_at = datetime.now(timezone.utc) - timedelta(seconds=locked_at_seconds_ago)
        cursor = sqlite_conn.execute(
            """
            INSERT INTO fleet_provisioning_tasks (
                task_type, status, correlation_id,
                request_payload_json, result_payload_json, last_error,
                attempt_count, max_attempts,
                locked_by, locked_at,
                next_run_at, created_at, updated_at,
                started_at, finished_at
            )
            VALUES (
                'provision_node', 'running', ?,
                '{}', NULL, NULL,
                1, ?,
                ?, ?,
                ?, ?, ?,
                ?, NULL
            )
            """,
            (
                correlation_id,
                max_attempts,
                locked_by,
                locked_at.isoformat(),
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                locked_at.isoformat(),
            ),
        )
        sqlite_conn.commit()
        return int(cursor.lastrowid)

    def test_recover_stale_running_tasks_requeues_when_attempts_remaining(
        self, in_memory_sqlite_db
    ) -> None:
        """A task at attempt 1 of 3, held by a crashed worker, should be requeued."""
        task_id = self._insert_stale_task(
            sqlite_conn=in_memory_sqlite_db,
            correlation_id="corr-stale-002",
            max_attempts=3,
            locked_by="crashed-worker",
            locked_at_seconds_ago=3600,  # locked 1 hour ago
        )

        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        from services.provisioning_task_service import ProvisioningTaskService

        svc = ProvisioningTaskService(runtime_context)
        result = svc.recover_stale_running_tasks(
            worker_id="watchdog",
            running_timeout_seconds=60.0,  # anything > 0 picks up this 1h-old lock
            retry_after_seconds=60.0,
        )
        assert result.scanned_task_count == 1
        assert result.requeued_task_count == 1
        assert result.failed_task_count == 0

        from database.provisioning_task_repo import ProvisioningTaskRepo

        repo = ProvisioningTaskRepo(runtime_context)
        record = repo.get_task_by_id(task_id)
        assert record.status == "queued"

    def test_recover_stale_running_tasks_fails_when_max_attempts_exceeded(
        self, in_memory_sqlite_db
    ) -> None:
        """A task at max_attempts=1 (attempt 1/1), held by a crashed worker, should be marked failed."""
        task_id = self._insert_stale_task(
            sqlite_conn=in_memory_sqlite_db,
            correlation_id="corr-stale-003",
            max_attempts=1,
            locked_by="crashed-worker",
            locked_at_seconds_ago=3600,
        )

        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        from services.provisioning_task_service import ProvisioningTaskService

        svc = ProvisioningTaskService(runtime_context)
        result = svc.recover_stale_running_tasks(
            worker_id="watchdog",
            running_timeout_seconds=60.0,
            retry_after_seconds=30.0,
        )
        assert result.scanned_task_count == 1
        assert result.requeued_task_count == 0
        assert result.failed_task_count == 1

        from database.provisioning_task_repo import ProvisioningTaskRepo

        repo = ProvisioningTaskRepo(runtime_context)
        record = repo.get_task_by_id(task_id)
        assert record.status == "failed"


class TestProvisioningTaskLifecycleIntegration:
    """End-to-end lifecycle: submit -> claim -> succeed / fail."""

    def test_full_lifecycle_submit_claim_succeed(self, in_memory_sqlite_db) -> None:
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        from services.provisioning_task_service import (
            ProvisioningTaskService,
        )

        svc = ProvisioningTaskService(runtime_context)

        # Submit
        submit_result = svc.submit_provision_task(
            ProvisionRequest(
                protocol_type="Trojan",
                node_name="lifecycle-node",
                port="443",
                server_port=443,
                rate=Decimal("100"),
            )
        )
        assert submit_result.status == "queued"
        assert submit_result.task_id > 0

        # Verify in DB
        record = repo.get_task_by_id(submit_result.task_id)
        assert record.status == "queued"
        assert record.correlation_id == submit_result.correlation_id
        assert record.request_payload["node_name"] == "lifecycle-node"
        assert record.request_payload["protocol_type"] == "Trojan"

    def test_submit_provision_task_returns_submit_result(self, in_memory_sqlite_db) -> None:
        runtime_context = create_mock_runtime_context(in_memory_sqlite_db)
        from services.provisioning_task_service import ProvisioningTaskService

        svc = ProvisioningTaskService(runtime_context)

        result = svc.submit_provision_task(
            ProvisionRequest(
                protocol_type="AnyTLS",
                node_name="submit-result-node",
                port="443",
                server_port=443,
                rate=Decimal("100"),
            )
        )
        assert result.task_id > 0
        assert result.status == "queued"
        assert len(result.correlation_id) == 36  # UUID format
