from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from database.provisioning_task_repo import ProvisioningTaskRecord
from services.provisioning_models import ProvisionRequest, ProvisionResult
from services.provisioning_task_service import (
    ProvisioningTaskRecoveryResult,
    ProvisioningTaskService,
    ProvisioningTaskServiceError,
    ProvisioningTaskSubmitResult,
)
from services.runtime_service import RuntimeContext


class TestProvisioningTaskService(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_runtime = MagicMock(spec=RuntimeContext)
        self.mock_runtime.logger = MagicMock()
        self.mock_runtime.logger.getChild.return_value = MagicMock()
        self.mock_runtime.correlation_id = "test-corr-id"
        mock_config = MagicMock()
        mock_config.app.max_retries = 2
        mock_config.app.retry_backoff_seconds = 10
        self.mock_runtime.config = mock_config
        self.service = ProvisioningTaskService(self.mock_runtime)
        self.service._task_repo = MagicMock()
        self.service._state_repo = MagicMock()

    @patch("services.provisioning_task_service.generate_correlation_id")
    @patch("services.provisioning_task_service.set_correlation_id")
    @patch("services.provisioning_task_service.set_event_type")
    def test_submit_provision_task_success(
        self,
        mock_set_event_type: MagicMock,
        mock_set_correlation_id: MagicMock,
        mock_gen_corr_id: MagicMock,
    ) -> None:
        mock_gen_corr_id.return_value = "new-corr-123"
        self.service._state_repo.get_node_by_node_name.return_value = None
        self.service._task_repo.create_task.return_value = 42

        request = ProvisionRequest(
            protocol_type="vless",
            node_name="test-node",
            port="443",
            server_port=443,
            rate=Decimal("1.0"),
            asset_type="aws",
            region="us-east-1",
        )
        result = self.service.submit_provision_task(request)

        self.assertIsInstance(result, ProvisioningTaskSubmitResult)
        self.assertEqual(result.task_id, 42)
        self.assertEqual(result.correlation_id, "new-corr-123")
        self.assertEqual(result.status, "queued")
        self.service._task_repo.create_task.assert_called_once()

    def test_submit_provision_task_node_name_exists(self) -> None:
        mock_node = MagicMock()
        mock_node.xboard_node_id = 100
        mock_node.status = "running"
        self.service._state_repo.get_node_by_node_name.return_value = mock_node

        request = ProvisionRequest(
            protocol_type="vless",
            node_name="existing-node",
            port="443",
            server_port=443,
            rate=Decimal("1.0"),
        )

        with self.assertRaises(ProvisioningTaskServiceError) as ctx:
            self.service.submit_provision_task(request)

        self.assertIn("already exists", str(ctx.exception))

    def test_get_task_by_id(self) -> None:
        mock_task = ProvisioningTaskRecord(
            id=1,
            task_type="provision_node",
            correlation_id="corr-1",
            status="queued",
            request_payload={"protocol_type": "vless"},
            result_payload=None,
            last_error=None,
            attempt_count=0,
            max_attempts=3,
            locked_by=None,
            locked_at=None,
            next_run_at="2026-05-11T10:00:00+00:00",
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:00+00:00",
            started_at=None,
            finished_at=None,
        )
        self.service._task_repo.get_task_by_id.return_value = mock_task

        result = self.service.get_task_by_id(task_id=1)

        self.assertEqual(result.id, 1)
        self.service._task_repo.get_task_by_id.assert_called_once_with(1)

    @patch("services.provisioning_task_service.generate_correlation_id")
    @patch("services.provisioning_task_service.set_correlation_id")
    @patch("services.provisioning_task_service.set_event_type")
    def test_retry_failed_task_success(
        self,
        mock_set_event_type: MagicMock,
        mock_set_correlation_id: MagicMock,
        mock_gen_corr_id: MagicMock,
    ) -> None:
        mock_gen_corr_id.return_value = "retry-corr-123"
        mock_task = ProvisioningTaskRecord(
            id=1,
            task_type="provision_node",
            correlation_id="corr-1",
            status="failed",
            request_payload={"protocol_type": "vless"},
            result_payload=None,
            last_error="Test error",
            attempt_count=3,
            max_attempts=3,
            locked_by=None,
            locked_at=None,
            next_run_at="2026-05-11T10:00:00+00:00",
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:01:00+00:00",
            started_at="2026-05-11T10:00:00+00:00",
            finished_at="2026-05-11T10:01:00+00:00",
        )
        reset_task = ProvisioningTaskRecord(
            id=1,
            task_type="provision_node",
            correlation_id="corr-1",
            status="queued",
            request_payload={"protocol_type": "vless"},
            result_payload=None,
            last_error=None,
            attempt_count=0,
            max_attempts=3,
            locked_by=None,
            locked_at=None,
            next_run_at="2026-05-11T10:02:00+00:00",
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:02:00+00:00",
            started_at=None,
            finished_at=None,
        )
        self.service._task_repo.get_task_by_id.return_value = mock_task
        self.service._task_repo.reset_for_retry.return_value = reset_task

        result = self.service.retry_failed_task(task_id=1)

        self.assertEqual(result.status, "queued")
        self.service._task_repo.reset_for_retry.assert_called_once_with(1)

    def test_retry_failed_task_invalid_status(self) -> None:
        mock_task = ProvisioningTaskRecord(
            id=1,
            task_type="provision_node",
            correlation_id="corr-1",
            status="running",
            request_payload={"protocol_type": "vless"},
            result_payload=None,
            last_error=None,
            attempt_count=1,
            max_attempts=3,
            locked_by="worker-1",
            locked_at="2026-05-11T10:00:00+00:00",
            next_run_at="2026-05-11T10:00:00+00:00",
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:00+00:00",
            started_at="2026-05-11T10:00:00+00:00",
            finished_at=None,
        )
        self.service._task_repo.get_task_by_id.return_value = mock_task

        with self.assertRaises(ProvisioningTaskServiceError) as ctx:
            self.service.retry_failed_task(task_id=1)

        self.assertIn("only failed or succeeded tasks can be retried", str(ctx.exception))

    @patch("services.provisioning_task_service.set_event_type")
    def test_delete_task_success(self, mock_set_event_type: MagicMock) -> None:
        mock_task = ProvisioningTaskRecord(
            id=1,
            task_type="provision_node",
            correlation_id="corr-1",
            status="failed",
            request_payload={"protocol_type": "vless"},
            result_payload=None,
            last_error="Test error",
            attempt_count=3,
            max_attempts=3,
            locked_by=None,
            locked_at=None,
            next_run_at="2026-05-11T10:00:00+00:00",
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:01:00+00:00",
            started_at="2026-05-11T10:00:00+00:00",
            finished_at="2026-05-11T10:01:00+00:00",
        )
        self.service._task_repo.get_task_by_id.return_value = mock_task

        self.service.delete_task(task_id=1)

        self.service._task_repo.delete_task.assert_called_once_with(1)

    def test_delete_task_running_not_allowed(self) -> None:
        mock_task = ProvisioningTaskRecord(
            id=1,
            task_type="provision_node",
            correlation_id="corr-1",
            status="running",
            request_payload={"protocol_type": "vless"},
            result_payload=None,
            last_error=None,
            attempt_count=1,
            max_attempts=3,
            locked_by="worker-1",
            locked_at="2026-05-11T10:00:00+00:00",
            next_run_at="2026-05-11T10:00:00+00:00",
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:00+00:00",
            started_at="2026-05-11T10:00:00+00:00",
            finished_at=None,
        )
        self.service._task_repo.get_task_by_id.return_value = mock_task

        with self.assertRaises(ProvisioningTaskServiceError) as ctx:
            self.service.delete_task(task_id=1)

        self.assertIn("running and cannot be deleted", str(ctx.exception))

    def test_list_recent_tasks(self) -> None:
        mock_tasks = [
            ProvisioningTaskRecord(
                id=1,
                task_type="provision_node",
                correlation_id="corr-1",
                status="succeeded",
                request_payload={"protocol_type": "vless"},
                result_payload={"xboard_node_id": 100},
                last_error=None,
                attempt_count=1,
                max_attempts=3,
                locked_by=None,
                locked_at=None,
                next_run_at="2026-05-11T10:00:00+00:00",
                created_at="2026-05-11T10:00:00+00:00",
                updated_at="2026-05-11T10:01:00+00:00",
                started_at="2026-05-11T10:00:00+00:00",
                finished_at="2026-05-11T10:01:00+00:00",
            )
        ]
        self.service._task_repo.list_recent_tasks.return_value = mock_tasks

        result = self.service.list_recent_tasks(limit=10)

        self.assertEqual(len(result), 1)
        self.service._task_repo.list_recent_tasks.assert_called_once_with(limit=10)

    def test_get_task_stats(self) -> None:
        mock_stats = {"queued": 5, "running": 2, "succeeded": 10, "failed": 1}
        self.service._task_repo.get_task_stats.return_value = mock_stats

        result = self.service.get_task_stats()

        self.assertEqual(result["queued"], 5)
        self.assertEqual(result["running"], 2)

    @patch("services.provisioning_task_service.set_correlation_id")
    @patch("services.provisioning_task_service.set_event_type")
    def test_recover_stale_running_tasks_requeue(
        self,
        mock_set_event_type: MagicMock,
        mock_set_correlation_id: MagicMock,
    ) -> None:
        stale_task = ProvisioningTaskRecord(
            id=1,
            task_type="provision_node",
            correlation_id="corr-1",
            status="running",
            request_payload={"protocol_type": "vless"},
            result_payload=None,
            last_error=None,
            attempt_count=1,
            max_attempts=3,
            locked_by="worker-1",
            locked_at="2026-05-11T09:00:00+00:00",
            next_run_at="2026-05-11T09:00:00+00:00",
            created_at="2026-05-11T09:00:00+00:00",
            updated_at="2026-05-11T09:00:00+00:00",
            started_at="2026-05-11T09:00:00+00:00",
            finished_at=None,
        )
        self.service._task_repo.list_stale_running_tasks.return_value = [stale_task]

        result = self.service.recover_stale_running_tasks(
            worker_id="watchdog-1",
            running_timeout_seconds=3600,
            retry_after_seconds=60,
        )

        self.assertIsInstance(result, ProvisioningTaskRecoveryResult)
        self.assertEqual(result.scanned_task_count, 1)
        self.assertEqual(result.requeued_task_count, 1)
        self.assertEqual(result.failed_task_count, 0)
        self.service._task_repo.mark_task_for_retry.assert_called_once()

    @patch("services.provisioning_task_service.set_correlation_id")
    @patch("services.provisioning_task_service.set_event_type")
    def test_recover_stale_running_tasks_fail_max_attempts(
        self,
        mock_set_event_type: MagicMock,
        mock_set_correlation_id: MagicMock,
    ) -> None:
        stale_task = ProvisioningTaskRecord(
            id=1,
            task_type="provision_node",
            correlation_id="corr-1",
            status="running",
            request_payload={"protocol_type": "vless"},
            result_payload=None,
            last_error=None,
            attempt_count=3,
            max_attempts=3,
            locked_by="worker-1",
            locked_at="2026-05-11T09:00:00+00:00",
            next_run_at="2026-05-11T09:00:00+00:00",
            created_at="2026-05-11T09:00:00+00:00",
            updated_at="2026-05-11T09:00:00+00:00",
            started_at="2026-05-11T09:00:00+00:00",
            finished_at=None,
        )
        self.service._task_repo.list_stale_running_tasks.return_value = [stale_task]

        result = self.service.recover_stale_running_tasks(
            worker_id="watchdog-1",
            running_timeout_seconds=3600,
            retry_after_seconds=60,
        )

        self.assertEqual(result.scanned_task_count, 1)
        self.assertEqual(result.requeued_task_count, 0)
        self.assertEqual(result.failed_task_count, 1)
        self.service._task_repo.mark_task_failed.assert_called_once()

    def test_recover_stale_running_tasks_no_stale_tasks(self) -> None:
        self.service._task_repo.list_stale_running_tasks.return_value = []

        result = self.service.recover_stale_running_tasks(
            worker_id="watchdog-1",
            running_timeout_seconds=3600,
            retry_after_seconds=60,
        )

        self.assertEqual(result.scanned_task_count, 0)
        self.assertEqual(result.requeued_task_count, 0)
        self.assertEqual(result.failed_task_count, 0)

    def test_recover_stale_running_tasks_invalid_worker_id(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.service.recover_stale_running_tasks(
                worker_id="",
                running_timeout_seconds=3600,
                retry_after_seconds=60,
            )

        self.assertIn("worker_id must not be empty", str(ctx.exception))

    def test_recover_stale_running_tasks_invalid_timeout(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.service.recover_stale_running_tasks(
                worker_id="watchdog-1",
                running_timeout_seconds=0,
                retry_after_seconds=60,
            )

        self.assertIn("running_timeout_seconds must be greater than 0", str(ctx.exception))

    def test_recover_stale_running_tasks_invalid_retry_after(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.service.recover_stale_running_tasks(
                worker_id="watchdog-1",
                running_timeout_seconds=3600,
                retry_after_seconds=-1,
            )

        self.assertIn("retry_after_seconds must be greater than 0", str(ctx.exception))

    @patch("services.provisioning_task_service.replace")
    @patch("services.provisioning_task_service.ProvisionerService")
    @patch("services.provisioning_task_service.set_correlation_id")
    @patch("services.provisioning_task_service.set_event_type")
    def test_process_next_task_success(
        self,
        mock_set_event_type: MagicMock,
        mock_set_correlation_id: MagicMock,
        mock_provisioner_cls: MagicMock,
        mock_replace: MagicMock,
    ) -> None:
        mock_task = ProvisioningTaskRecord(
            id=1,
            task_type="provision_node",
            correlation_id="task-corr-id",
            status="running",
            request_payload={
                "protocol_type": "vless",
                "node_name": "test-node",
                "port": "443",
                "server_port": 443,
                "rate": "1.0",
            },
            result_payload=None,
            last_error=None,
            attempt_count=1,
            max_attempts=3,
            locked_by="worker-1",
            locked_at="2026-05-11T10:00:00+00:00",
            next_run_at="2026-05-11T10:00:00+00:00",
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:00+00:00",
            started_at="2026-05-11T10:00:00+00:00",
            finished_at=None,
        )
        completed_task = ProvisioningTaskRecord(
            id=1,
            task_type="provision_node",
            correlation_id="task-corr-id",
            status="succeeded",
            request_payload={
                "protocol_type": "vless",
                "node_name": "test-node",
                "port": "443",
                "server_port": 443,
                "rate": "1.0",
            },
            result_payload={"xboard_node_id": 100},
            last_error=None,
            attempt_count=1,
            max_attempts=3,
            locked_by=None,
            locked_at=None,
            next_run_at="2026-05-11T10:00:00+00:00",
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:01:00+00:00",
            started_at="2026-05-11T10:00:00+00:00",
            finished_at="2026-05-11T10:01:00+00:00",
        )
        mock_provisioner = MagicMock()
        mock_result = ProvisionResult(
            local_node_id=1,
            xboard_node_id=100,
            asset_id=1,
            asset_type="aws",
            protocol_type="vless",
            node_name="test-node",
            status="running",
            aws_account_id="123456789012",
            region="us-east-1",
            instance_id="i-123",
            network_interface_id="eni-123",
            ipv6_address="2001:db8::1",
            domain_name="test.example.com",
            cloudflare_record_id="cf-123",
        )
        mock_provisioner.provision_node.return_value = mock_result
        mock_provisioner_cls.return_value = mock_provisioner

        # Mock replace to return the mock_runtime with updated correlation_id
        mock_replace.side_effect = lambda obj, **kwargs: obj

        self.service._task_repo.claim_next_task.return_value = mock_task
        self.service._task_repo.get_task_by_id.return_value = completed_task

        result = self.service.process_next_task(worker_id="worker-1")

        self.assertIsNotNone(result)
        self.assertEqual(result.status, "succeeded")
        self.service._task_repo.mark_task_succeeded.assert_called_once()

    def test_process_next_task_no_task_available(self) -> None:
        self.service._task_repo.claim_next_task.return_value = None

        result = self.service.process_next_task(worker_id="worker-1")

        self.assertIsNone(result)

    def test_build_retry_delay_seconds(self) -> None:
        delay1 = self.service._build_retry_delay_seconds(attempt_count=1)
        delay2 = self.service._build_retry_delay_seconds(attempt_count=2)
        delay3 = self.service._build_retry_delay_seconds(attempt_count=3)

        self.assertGreaterEqual(delay1, 10)
        self.assertLess(delay1, 20)
        self.assertGreaterEqual(delay2, 20)
        self.assertLess(delay2, 40)
        self.assertGreaterEqual(delay3, 40)
        self.assertLess(delay3, 80)

    def test_format_error_message_with_message(self) -> None:
        error = RuntimeError("Test error message")
        result = self.service._format_error_message(error)
        self.assertEqual(result, "Test error message")

    def test_format_error_message_without_message(self) -> None:
        error = RuntimeError()
        result = self.service._format_error_message(error)
        self.assertEqual(result, "RuntimeError")

    def test_serialize_provision_request(self) -> None:
        request = ProvisionRequest(
            protocol_type="vless",
            node_name="test-node",
            port="443",
            server_port=443,
            rate=Decimal("1.5"),
            asset_type="aws",
            region="us-east-1",
        )

        result = self.service._serialize_provision_request(request)

        self.assertEqual(result["protocol_type"], "vless")
        self.assertEqual(result["node_name"], "test-node")
        self.assertEqual(result["rate"], "1.5")

    def test_deserialize_provision_request(self) -> None:
        payload = {
            "protocol_type": "vless",
            "node_name": "test-node",
            "port": "443",
            "server_port": 443,
            "rate": "1.5",
        }

        result = self.service._deserialize_provision_request(payload)

        self.assertEqual(result.protocol_type, "vless")
        self.assertEqual(result.node_name, "test-node")
        self.assertEqual(result.rate, Decimal("1.5"))

    def test_deserialize_provision_request_invalid_payload(self) -> None:
        payload = {"invalid": "data"}

        with self.assertRaises(ProvisioningTaskServiceError) as ctx:
            self.service._deserialize_provision_request(payload)

        self.assertIn("invalid and cannot be deserialized", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
