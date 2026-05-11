from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from database.ready_callback_repo import ReadyCallbackRecord, ReadyCallbackRepo
from services.ready_callback_service import (
    READY_CALLBACK_PATH,
    ReadyCallbackRegistration,
    ReadyCallbackService,
    ReadyCallbackServiceError,
)
from services.runtime_service import RuntimeContext


class TestReadyCallbackService(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_runtime = MagicMock(spec=RuntimeContext)
        self.mock_runtime.logger = MagicMock()
        self.mock_runtime.logger.getChild.return_value = MagicMock()
        self.mock_runtime.correlation_id = "test-corr-id"
        self.mock_runtime.daemon_ipv6 = None
        mock_config = MagicMock()
        mock_config.app.phone_home_base_url = "http://10.0.0.1:8080"
        mock_config.app.phone_home_ready_timeout_seconds = 300
        mock_config.app.phone_home_poll_interval_seconds = 5
        self.mock_runtime.config = mock_config
        self.service = ReadyCallbackService(self.mock_runtime)
        self.service._repo = MagicMock(spec=ReadyCallbackRepo)

    def test_register_callback_success(self) -> None:
        mock_record = ReadyCallbackRecord(
            id=1,
            task_id=100,
            xboard_node_id=200,
            correlation_id="corr-123",
            callback_token="test-token-abc",
            status="pending",
            payload=None,
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:00+00:00",
            received_at=None,
            completed_at=None,
        )
        self.service._repo.create_callback.return_value = mock_record

        result = self.service.register_callback(
            task_id=100,
            xboard_node_id=200,
            correlation_id="corr-123",
        )

        self.assertIsInstance(result, ReadyCallbackRegistration)
        self.assertEqual(result.task_id, 100)
        self.assertEqual(result.xboard_node_id, 200)
        self.assertEqual(result.callback_token, "test-token-abc")
        self.assertEqual(result.callback_url, f"http://10.0.0.1:8080{READY_CALLBACK_PATH}")
        self.service._repo.create_callback.assert_called_once()

    def test_register_callback_with_ipv6(self) -> None:
        mock_runtime = MagicMock(spec=RuntimeContext)
        mock_runtime.logger = MagicMock()
        mock_runtime.logger.getChild.return_value = MagicMock()
        mock_runtime.correlation_id = "test-corr-id"
        mock_runtime.daemon_ipv6 = "2001:db8::1"
        mock_config = MagicMock()
        mock_config.app.phone_home_base_url = "http://192.168.1.1:8080"
        mock_config.app.phone_home_ready_timeout_seconds = 300
        mock_config.app.phone_home_poll_interval_seconds = 5
        mock_runtime.config = mock_config
        service = ReadyCallbackService(mock_runtime)
        service._repo = MagicMock(spec=ReadyCallbackRepo)

        mock_record = ReadyCallbackRecord(
            id=1,
            task_id=100,
            xboard_node_id=200,
            correlation_id="corr-123",
            callback_token="test-token",
            status="pending",
            payload=None,
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:00+00:00",
            received_at=None,
            completed_at=None,
        )
        service._repo.create_callback.return_value = mock_record

        result = service.register_callback(
            task_id=100,
            xboard_node_id=200,
            correlation_id="corr-123",
        )

        self.assertEqual(result.callback_url, f"http://[2001:db8::1]:8080{READY_CALLBACK_PATH}")

    def test_register_callback_ipv6_no_replacement_for_domain(self) -> None:
        mock_runtime = MagicMock(spec=RuntimeContext)
        mock_runtime.logger = MagicMock()
        mock_runtime.logger.getChild.return_value = MagicMock()
        mock_runtime.correlation_id = "test-corr-id"
        mock_runtime.daemon_ipv6 = "2001:db8::1"
        mock_config = MagicMock()
        mock_config.app.phone_home_base_url = "http://example.com:8080"
        mock_config.app.phone_home_ready_timeout_seconds = 300
        mock_config.app.phone_home_poll_interval_seconds = 5
        mock_runtime.config = mock_config
        service = ReadyCallbackService(mock_runtime)
        service._repo = MagicMock(spec=ReadyCallbackRepo)

        mock_record = ReadyCallbackRecord(
            id=1,
            task_id=100,
            xboard_node_id=200,
            correlation_id="corr-123",
            callback_token="test-token",
            status="pending",
            payload=None,
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:00+00:00",
            received_at=None,
            completed_at=None,
        )
        service._repo.create_callback.return_value = mock_record

        result = service.register_callback(
            task_id=100,
            xboard_node_id=200,
            correlation_id="corr-123",
        )

        self.assertEqual(result.callback_url, f"http://example.com:8080{READY_CALLBACK_PATH}")

    def test_build_callback_url_missing_base_url(self) -> None:
        self.mock_runtime.config.app.phone_home_base_url = None

        with self.assertRaises(ReadyCallbackServiceError) as ctx:
            self.service._build_callback_url()

        self.assertIn("phone_home_base_url is required", str(ctx.exception))

    def test_build_callback_url_empty_base_url(self) -> None:
        self.mock_runtime.config.app.phone_home_base_url = "   "

        with self.assertRaises(ReadyCallbackServiceError) as ctx:
            self.service._build_callback_url()

        self.assertIn("phone_home_base_url is required", str(ctx.exception))

    def test_build_callback_url_trailing_slash(self) -> None:
        mock_runtime = MagicMock(spec=RuntimeContext)
        mock_runtime.logger = MagicMock()
        mock_runtime.logger.getChild.return_value = MagicMock()
        mock_runtime.correlation_id = "test-corr-id"
        mock_runtime.daemon_ipv6 = None
        mock_config = MagicMock()
        mock_config.app.phone_home_base_url = "http://10.0.0.1:8080/"
        mock_config.app.phone_home_ready_timeout_seconds = 300
        mock_config.app.phone_home_poll_interval_seconds = 5
        mock_runtime.config = mock_config
        service = ReadyCallbackService(mock_runtime)
        service._repo = MagicMock(spec=ReadyCallbackRepo)

        mock_record = ReadyCallbackRecord(
            id=1,
            task_id=100,
            xboard_node_id=200,
            correlation_id="corr-123",
            callback_token="test-token",
            status="pending",
            payload=None,
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:00+00:00",
            received_at=None,
            completed_at=None,
        )
        service._repo.create_callback.return_value = mock_record

        result = service.register_callback(
            task_id=100,
            xboard_node_id=200,
            correlation_id="corr-123",
        )

        self.assertEqual(result.callback_url, f"http://10.0.0.1:8080{READY_CALLBACK_PATH}")

    def test_wait_for_ready_callback_success(self) -> None:
        mock_record = ReadyCallbackRecord(
            id=1,
            task_id=100,
            xboard_node_id=200,
            correlation_id="corr-123",
            callback_token="test-token",
            status="received",
            payload={"status": "ready"},
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:01:00+00:00",
            received_at="2026-05-11T10:01:00+00:00",
            completed_at=None,
        )
        self.service._repo.wait_until_received.return_value = mock_record

        result = self.service.wait_for_ready_callback(task_id=100)

        self.assertEqual(result.task_id, 100)
        self.assertEqual(result.status, "received")
        self.service._repo.wait_until_received.assert_called_once_with(
            task_id=100,
            timeout_seconds=300,
            poll_interval_seconds=5,
        )

    def test_mark_callback_completed_success(self) -> None:
        mock_record = ReadyCallbackRecord(
            id=1,
            task_id=100,
            xboard_node_id=200,
            correlation_id="corr-123",
            callback_token="test-token",
            status="completed",
            payload={"status": "ready"},
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:02:00+00:00",
            received_at="2026-05-11T10:01:00+00:00",
            completed_at="2026-05-11T10:02:00+00:00",
        )
        self.service._repo.mark_completed.return_value = mock_record

        result = self.service.mark_callback_completed(task_id=100)

        self.assertEqual(result.status, "completed")
        self.service._repo.mark_completed.assert_called_once_with(task_id=100)

    @patch("services.ready_callback_service.set_correlation_id")
    @patch("services.ready_callback_service.set_event_type")
    def test_record_ready_callback_success(
        self,
        mock_set_event_type: MagicMock,
        mock_set_correlation_id: MagicMock,
    ) -> None:
        callback_record = ReadyCallbackRecord(
            id=1,
            task_id=100,
            xboard_node_id=200,
            correlation_id="callback-corr-id",
            callback_token="test-token",
            status="pending",
            payload=None,
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:00+00:00",
            received_at=None,
            completed_at=None,
        )
        updated_record = ReadyCallbackRecord(
            id=1,
            task_id=100,
            xboard_node_id=200,
            correlation_id="callback-corr-id",
            callback_token="test-token",
            status="received",
            payload={"xboard_node_id": 200, "status": "ready"},
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:01:00+00:00",
            received_at="2026-05-11T10:01:00+00:00",
            completed_at=None,
        )
        self.service._repo.get_by_token.return_value = callback_record
        self.service._repo.mark_received.return_value = updated_record

        result = self.service.record_ready_callback(
            callback_token="test-token",
            payload={"xboard_node_id": 200, "status": "ready"},
        )

        self.assertEqual(result.status, "received")
        self.assertEqual(result.payload["status"], "ready")
        mock_set_correlation_id.assert_any_call("callback-corr-id")
        mock_set_correlation_id.assert_any_call("test-corr-id")
        mock_set_event_type.assert_any_call("ready_callback_recorded")
        mock_set_event_type.assert_any_call("general")

    @patch("services.ready_callback_service.set_correlation_id")
    @patch("services.ready_callback_service.set_event_type")
    def test_record_ready_callback_already_completed(
        self,
        mock_set_event_type: MagicMock,
        mock_set_correlation_id: MagicMock,
    ) -> None:
        callback_record = ReadyCallbackRecord(
            id=1,
            task_id=100,
            xboard_node_id=200,
            correlation_id="callback-corr-id",
            callback_token="test-token",
            status="completed",
            payload={"status": "ready"},
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:02:00+00:00",
            received_at="2026-05-11T10:01:00+00:00",
            completed_at="2026-05-11T10:02:00+00:00",
        )
        self.service._repo.get_by_token.return_value = callback_record

        result = self.service.record_ready_callback(
            callback_token="test-token",
            payload={"status": "ready"},
        )

        self.assertEqual(result.status, "completed")
        self.service._repo.mark_received.assert_not_called()

    @patch("services.ready_callback_service.set_correlation_id")
    def test_record_ready_callback_mismatched_xboard_node_id(
        self,
        mock_set_correlation_id: MagicMock,
    ) -> None:
        callback_record = ReadyCallbackRecord(
            id=1,
            task_id=100,
            xboard_node_id=200,
            correlation_id="callback-corr-id",
            callback_token="test-token",
            status="pending",
            payload=None,
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:00+00:00",
            received_at=None,
            completed_at=None,
        )
        self.service._repo.get_by_token.return_value = callback_record

        with self.assertRaises(ReadyCallbackServiceError) as ctx:
            self.service.record_ready_callback(
                callback_token="test-token",
                payload={"xboard_node_id": 999, "status": "ready"},
            )

        self.assertIn("xboard_node_id does not match", str(ctx.exception))

    @patch("services.ready_callback_service.set_correlation_id")
    @patch("services.ready_callback_service.set_event_type")
    def test_record_ready_callback_none_payload(
        self,
        mock_set_event_type: MagicMock,
        mock_set_correlation_id: MagicMock,
    ) -> None:
        callback_record = ReadyCallbackRecord(
            id=1,
            task_id=100,
            xboard_node_id=200,
            correlation_id="callback-corr-id",
            callback_token="test-token",
            status="pending",
            payload=None,
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:00+00:00",
            received_at=None,
            completed_at=None,
        )
        updated_record = ReadyCallbackRecord(
            id=1,
            task_id=100,
            xboard_node_id=200,
            correlation_id="callback-corr-id",
            callback_token="test-token",
            status="received",
            payload=None,
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:01:00+00:00",
            received_at="2026-05-11T10:01:00+00:00",
            completed_at=None,
        )
        self.service._repo.get_by_token.return_value = callback_record
        self.service._repo.mark_received.return_value = updated_record

        result = self.service.record_ready_callback(
            callback_token="test-token",
            payload=None,
        )

        self.assertEqual(result.status, "received")
        self.assertIsNone(result.payload)

    @patch("services.ready_callback_service.set_correlation_id")
    @patch("services.ready_callback_service.set_event_type")
    def test_record_ready_callback_non_dict_payload(
        self,
        mock_set_event_type: MagicMock,
        mock_set_correlation_id: MagicMock,
    ) -> None:
        callback_record = ReadyCallbackRecord(
            id=1,
            task_id=100,
            xboard_node_id=200,
            correlation_id="callback-corr-id",
            callback_token="test-token",
            status="pending",
            payload=None,
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:00:00+00:00",
            received_at=None,
            completed_at=None,
        )
        updated_record = ReadyCallbackRecord(
            id=1,
            task_id=100,
            xboard_node_id=200,
            correlation_id="callback-corr-id",
            callback_token="test-token",
            status="received",
            payload="string payload",
            created_at="2026-05-11T10:00:00+00:00",
            updated_at="2026-05-11T10:01:00+00:00",
            received_at="2026-05-11T10:01:00+00:00",
            completed_at=None,
        )
        self.service._repo.get_by_token.return_value = callback_record
        self.service._repo.mark_received.return_value = updated_record

        result = self.service.record_ready_callback(
            callback_token="test-token",
            payload="string payload",
        )

        self.assertEqual(result.status, "received")
        self.assertEqual(result.payload, "string payload")


if __name__ == "__main__":
    unittest.main()
