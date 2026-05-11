from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from database.state_repo import FleetNodeRecord
from services.manual_operation_models import (
    ManualOperationRequest,
    ManualOperationSubmitResult,
    ManualOperationTaskRecord,
)
from services.manual_operation_service import ManualOperationService
from services.runtime_service import RuntimeContext


class TestManualOperationService(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_runtime = MagicMock(spec=RuntimeContext)
        self.mock_runtime.logger = MagicMock()
        self.mock_runtime.logger.getChild.return_value = MagicMock()
        self.mock_runtime.correlation_id = "test-corr-id"
        self.mock_runtime.db_pool = MagicMock()
        mock_config = MagicMock()
        mock_config.app.max_retries = 2
        mock_config.app.retry_backoff_seconds = 10
        mock_config.app.sentinel_heal_cooldown_seconds = 300
        self.mock_runtime.config = mock_config
        self.service = ManualOperationService(self.mock_runtime)
        self.service._task_repo = MagicMock()
        self.service._state_repo = MagicMock()
        self.service._asset_repo = MagicMock()
        self.service._xboard_repo = MagicMock()
        self.service._probe_client = MagicMock()
        self.service._node_registry = MagicMock()
        self.service._healer_service = MagicMock()

    @patch("services.manual_operation_service.generate_correlation_id")
    @patch("services.manual_operation_service.set_correlation_id")
    @patch("services.manual_operation_service.set_event_type")
    def test_submit_task_force_heal_success(
        self,
        mock_set_event_type: MagicMock,
        mock_set_correlation_id: MagicMock,
        mock_gen_corr_id: MagicMock,
    ) -> None:
        mock_gen_corr_id.return_value = "new-corr-123"
        mock_node = FleetNodeRecord(
            id=1,
            xboard_node_id=100,
            node_name="test-node",
            node_type="vless",
            status="running",
            status_reason=None,
            aws_account_id="123456789012",
            aws_region="us-east-1",
            aws_instance_id="i-123",
            aws_subnet_id=None,
            aws_security_group_id=None,
            cloudflare_record_id=None,
            domain_name="test.example.com",
            ipv4_address=None,
            ipv6_address="2001:db8::1",
            last_known_host=None,
            last_error=None,
            is_deleted=False,
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:00+00:00",
            online_at=None,
            offline_at=None,
            deleted_at=None,
            last_healed_at=None,
            xboard_status=None,
            xboard_show=None,
            xboard_updated_at=None,
        )
        self.service._state_repo.get_node_by_xboard_node_id.return_value = mock_node
        self.service._task_repo.has_pending_task.return_value = False
        self.service._task_repo.create_task.return_value = 42

        request = ManualOperationRequest(
            task_type="force_heal",
            xboard_node_id=100,
            operator_name="admin",
            reason="test reason",
            force_strategy="replace_ip",
        )
        result = self.service.submit_task(request)

        self.assertIsInstance(result, ManualOperationSubmitResult)
        self.assertEqual(result.task_id, 42)
        self.assertEqual(result.correlation_id, "new-corr-123")
        self.assertEqual(result.status, "queued")
        self.service._task_repo.create_task.assert_called_once()

    def test_submit_task_node_not_found(self) -> None:
        self.service._state_repo.get_node_by_xboard_node_id.return_value = None

        request = ManualOperationRequest(
            task_type="force_heal",
            xboard_node_id=999,
        )

        with self.assertRaises(ValueError) as ctx:
            self.service.submit_task(request)

        self.assertIn("节点不存在", str(ctx.exception))

    def test_submit_task_invalid_xboard_node_id(self) -> None:
        request = ManualOperationRequest(
            task_type="force_heal",
            xboard_node_id=0,
        )

        with self.assertRaises(ValueError) as ctx:
            self.service.submit_task(request)

        self.assertIn("节点 ID 必须大于 0", str(ctx.exception))

    def test_submit_task_pending_task_exists(self) -> None:
        mock_node = FleetNodeRecord(
            id=1,
            xboard_node_id=100,
            node_name="test-node",
            node_type="vless",
            status="running",
            status_reason=None,
            aws_account_id="123456789012",
            aws_region="us-east-1",
            aws_instance_id="i-123",
            aws_subnet_id=None,
            aws_security_group_id=None,
            cloudflare_record_id=None,
            domain_name="test.example.com",
            ipv4_address=None,
            ipv6_address="2001:db8::1",
            last_known_host=None,
            last_error=None,
            is_deleted=False,
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:00+00:00",
            online_at=None,
            offline_at=None,
            deleted_at=None,
            last_healed_at=None,
            xboard_status=None,
            xboard_show=None,
            xboard_updated_at=None,
        )
        self.service._state_repo.get_node_by_xboard_node_id.return_value = mock_node
        self.service._task_repo.has_pending_task.return_value = True

        request = ManualOperationRequest(
            task_type="force_heal",
            xboard_node_id=100,
        )

        with self.assertRaises(ValueError) as ctx:
            self.service.submit_task(request)

        self.assertIn("已有同类型人工任务", str(ctx.exception))

    @patch("services.manual_operation_service.is_in_heal_cooldown")
    def test_submit_task_force_heal_in_cooldown(self, mock_cooldown: MagicMock) -> None:
        mock_node = FleetNodeRecord(
            id=1,
            xboard_node_id=100,
            node_name="test-node",
            node_type="vless",
            status="running",
            status_reason=None,
            aws_account_id="123456789012",
            aws_region="us-east-1",
            aws_instance_id="i-123",
            aws_subnet_id=None,
            aws_security_group_id=None,
            cloudflare_record_id=None,
            domain_name="test.example.com",
            ipv4_address=None,
            ipv6_address="2001:db8::1",
            last_known_host=None,
            last_error=None,
            is_deleted=False,
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:00+00:00",
            online_at=None,
            offline_at=None,
            deleted_at=None,
            last_healed_at="2026-05-11T10:00:00+00:00",
            xboard_status=None,
            xboard_show=None,
            xboard_updated_at=None,
        )
        self.service._state_repo.get_node_by_xboard_node_id.return_value = mock_node
        self.service._task_repo.has_pending_task.return_value = False
        mock_cooldown.return_value = True

        request = ManualOperationRequest(
            task_type="force_heal",
            xboard_node_id=100,
        )

        with self.assertRaises(ValueError) as ctx:
            self.service.submit_task(request)

        self.assertIn("自愈冷却期", str(ctx.exception))

    def test_validate_task_support_unsupported_task_type(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.service._validate_task_support(
                request=ManualOperationRequest(
                    task_type="force_heal",  # type: ignore[arg-type]
                    xboard_node_id=100,
                ),
                node_type="invalid_type",
                is_aws=True,
            )

        self.assertIn("不支持", str(ctx.exception))

    def test_validate_task_support_aws_unsupported_protocol(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.service._validate_task_support(
                request=ManualOperationRequest(
                    task_type="force_heal",
                    xboard_node_id=100,
                ),
                node_type="http",
                is_aws=True,
            )

        self.assertIn("AWS 节点协议不支持", str(ctx.exception))

    def test_validate_task_support_self_hosted_unsupported_protocol(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.service._validate_task_support(
                request=ManualOperationRequest(
                    task_type="force_heal",
                    xboard_node_id=100,
                ),
                node_type="invalid",
                is_aws=False,
            )

        self.assertIn("自建节点协议不支持", str(ctx.exception))

    def test_validate_task_support_reprobe_always_allowed(self) -> None:
        self.service._validate_task_support(
            request=ManualOperationRequest(
                task_type="reprobe_node",
                xboard_node_id=100,
            ),
            node_type="any_type",
            is_aws=True,
        )

    def test_validate_task_support_decommission_always_allowed(self) -> None:
        self.service._validate_task_support(
            request=ManualOperationRequest(
                task_type="decommission_node",
                xboard_node_id=100,
            ),
            node_type="any_type",
            is_aws=False,
        )

    def test_list_recent_tasks(self) -> None:
        mock_tasks = [
            ManualOperationTaskRecord(
                id=1,
                task_type="force_heal",
                status="succeeded",
                correlation_id="corr-1",
                operator_name="admin",
                xboard_node_id=100,
                request_payload={"reason": "test"},
                result_payload={"success": True},
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
        self.assertEqual(result[0].id, 1)
        self.service._task_repo.list_recent_tasks.assert_called_once_with(limit=10)

    @patch("services.manual_operation_service.set_correlation_id")
    @patch("services.manual_operation_service.set_event_type")
    def test_process_next_task_success(
        self,
        mock_set_event_type: MagicMock,
        mock_set_correlation_id: MagicMock,
    ) -> None:
        mock_task = ManualOperationTaskRecord(
            id=1,
            task_type="reprobe_node",
            status="running",
            correlation_id="task-corr-id",
            operator_name="admin",
            xboard_node_id=100,
            request_payload={"reason": "test"},
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
        completed_task = ManualOperationTaskRecord(
            id=1,
            task_type="reprobe_node",
            status="succeeded",
            correlation_id="task-corr-id",
            operator_name="admin",
            xboard_node_id=100,
            request_payload={"reason": "test"},
            result_payload={"success": True},
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
        self.service._task_repo.claim_next_task.return_value = mock_task
        self.service._task_repo.get_task_by_id.return_value = completed_task
        self.service._execute_task = MagicMock(return_value={"success": True})

        result = self.service.process_next_task(worker_id="worker-1")

        self.assertIsNotNone(result)
        self.assertEqual(result.status, "succeeded")
        self.service._task_repo.mark_task_succeeded.assert_called_once()

    def test_process_next_task_no_task_available(self) -> None:
        self.service._task_repo.claim_next_task.return_value = None

        result = self.service.process_next_task(worker_id="worker-1")

        self.assertIsNone(result)

    @patch("services.manual_operation_service.set_correlation_id")
    @patch("services.manual_operation_service.set_event_type")
    def test_process_next_task_failure_with_retries(
        self,
        mock_set_event_type: MagicMock,
        mock_set_correlation_id: MagicMock,
    ) -> None:
        mock_task = ManualOperationTaskRecord(
            id=1,
            task_type="force_heal",
            status="running",
            correlation_id="task-corr-id",
            operator_name="admin",
            xboard_node_id=100,
            request_payload={"reason": "test"},
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
        retry_task = ManualOperationTaskRecord(
            id=1,
            task_type="force_heal",
            status="queued",
            correlation_id="task-corr-id",
            operator_name="admin",
            xboard_node_id=100,
            request_payload={"reason": "test"},
            result_payload=None,
            last_error="Test error",
            attempt_count=1,
            max_attempts=3,
            locked_by=None,
            locked_at=None,
            next_run_at="2026-05-11T10:00:10+00:00",
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:01+00:00",
            started_at="2026-05-11T10:00:00+00:00",
            finished_at=None,
        )
        self.service._task_repo.claim_next_task.return_value = mock_task
        self.service._task_repo.get_task_by_id.return_value = retry_task
        self.service._execute_task = MagicMock(side_effect=RuntimeError("Test error"))

        result = self.service.process_next_task(worker_id="worker-1")

        self.assertIsNotNone(result)
        self.assertEqual(result.status, "queued")
        self.service._task_repo.mark_task_for_retry.assert_called_once()

    @patch("services.manual_operation_service.set_correlation_id")
    @patch("services.manual_operation_service.set_event_type")
    def test_process_next_task_failure_max_attempts(
        self,
        mock_set_event_type: MagicMock,
        mock_set_correlation_id: MagicMock,
    ) -> None:
        mock_task = ManualOperationTaskRecord(
            id=1,
            task_type="force_heal",
            status="running",
            correlation_id="task-corr-id",
            operator_name="admin",
            xboard_node_id=100,
            request_payload={"reason": "test"},
            result_payload=None,
            last_error=None,
            attempt_count=3,
            max_attempts=3,
            locked_by="worker-1",
            locked_at="2026-05-11T10:00:00+00:00",
            next_run_at="2026-05-11T10:00:00+00:00",
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:00+00:00",
            started_at="2026-05-11T10:00:00+00:00",
            finished_at=None,
        )
        failed_task = ManualOperationTaskRecord(
            id=1,
            task_type="force_heal",
            status="failed",
            correlation_id="task-corr-id",
            operator_name="admin",
            xboard_node_id=100,
            request_payload={"reason": "test"},
            result_payload=None,
            last_error="Test error",
            attempt_count=3,
            max_attempts=3,
            locked_by=None,
            locked_at=None,
            next_run_at="2026-05-11T10:00:00+00:00",
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:01+00:00",
            started_at="2026-05-11T10:00:00+00:00",
            finished_at="2026-05-11T10:00:01+00:00",
        )
        self.service._task_repo.claim_next_task.return_value = mock_task
        self.service._task_repo.get_task_by_id.return_value = failed_task
        self.service._execute_task = MagicMock(side_effect=RuntimeError("Test error"))

        result = self.service.process_next_task(worker_id="worker-1")

        self.assertIsNotNone(result)
        self.assertEqual(result.status, "failed")
        self.service._task_repo.mark_task_failed.assert_called_once()

    def test_normalize_optional_text_none(self) -> None:
        result = self.service._normalize_optional_text(None)
        self.assertIsNone(result)

    def test_normalize_optional_text_empty(self) -> None:
        result = self.service._normalize_optional_text("   ")
        self.assertIsNone(result)

    def test_normalize_optional_text_valid(self) -> None:
        result = self.service._normalize_optional_text("  test value  ")
        self.assertEqual(result, "test value")

    def test_to_optional_text_none(self) -> None:
        result = self.service._to_optional_text(None)
        self.assertIsNone(result)

    def test_to_optional_text_empty(self) -> None:
        result = self.service._to_optional_text("   ")
        self.assertIsNone(result)

    def test_to_optional_text_valid(self) -> None:
        result = self.service._to_optional_text("  test  ")
        self.assertEqual(result, "test")

    def test_to_optional_text_number(self) -> None:
        result = self.service._to_optional_text(123)
        self.assertEqual(result, "123")


if __name__ == "__main__":
    unittest.main()
