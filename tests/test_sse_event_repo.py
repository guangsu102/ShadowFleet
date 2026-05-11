from __future__ import annotations

import json
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from database.sqlite_connection import SqliteConnectionManager
from services.sse_event_repo import SSEEventRepo, SSEStoredEvent


class TestSSEEventRepo(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_db = MagicMock(spec=SqliteConnectionManager)
        self.mock_conn = MagicMock()
        self.mock_db.connection.return_value.__enter__.return_value = self.mock_conn
        self.mock_db.connection.return_value.__exit__.return_value = None
        SSEEventRepo._instance = None
        self.repo = SSEEventRepo(self.mock_db)

    def tearDown(self) -> None:
        SSEEventRepo._instance = None

    def test_get_instance_singleton(self) -> None:
        repo1 = SSEEventRepo.get_instance(self.mock_db)
        repo2 = SSEEventRepo.get_instance(self.mock_db)
        self.assertIs(repo1, repo2)

    def test_write_event_success(self) -> None:
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 42
        self.mock_conn.execute.return_value = mock_cursor

        event_id = self.repo.write(
            event_type="test_event",
            correlation_id="corr-123",
            payload={"key": "value", "number": 123},
        )

        self.assertEqual(event_id, 42)
        self.mock_conn.execute.assert_called_once()
        call_args = self.mock_conn.execute.call_args
        self.assertIn("INSERT INTO sse_events", call_args[0][0])
        self.assertEqual(call_args[0][1][0], "test_event")
        self.assertEqual(call_args[0][1][1], "corr-123")
        payload_json = json.loads(call_args[0][1][2])
        self.assertEqual(payload_json["key"], "value")
        self.assertEqual(payload_json["number"], 123)
        self.mock_conn.commit.assert_called_once()

    def test_write_event_empty_payload(self) -> None:
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 1
        self.mock_conn.execute.return_value = mock_cursor

        event_id = self.repo.write(
            event_type="empty_event",
            correlation_id="corr-456",
            payload={},
        )

        self.assertEqual(event_id, 1)
        call_args = self.mock_conn.execute.call_args
        payload_json = json.loads(call_args[0][1][2])
        self.assertEqual(payload_json, {})

    def test_write_event_complex_payload(self) -> None:
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 99
        self.mock_conn.execute.return_value = mock_cursor

        complex_payload = {
            "nested": {"data": {"value": 123}},
            "list": [1, 2, 3],
            "unicode": "测试数据",
        }
        event_id = self.repo.write(
            event_type="complex_event",
            correlation_id="corr-789",
            payload=complex_payload,
        )

        self.assertEqual(event_id, 99)
        call_args = self.mock_conn.execute.call_args
        payload_json = json.loads(call_args[0][1][2])
        self.assertEqual(payload_json["nested"]["data"]["value"], 123)
        self.assertEqual(payload_json["unicode"], "测试数据")

    def test_poll_since_returns_events(self) -> None:
        mock_rows = [
            {
                "id": 10,
                "event_type": "event1",
                "correlation_id": "corr-1",
                "payload_json": '{"data": "value1"}',
                "created_at": "2026-05-11T10:00:00+00:00",
            },
            {
                "id": 11,
                "event_type": "event2",
                "correlation_id": "corr-2",
                "payload_json": '{"data": "value2"}',
                "created_at": "2026-05-11T10:01:00+00:00",
            },
        ]
        self.mock_conn.execute.return_value.fetchall.return_value = mock_rows

        result = self.repo.poll_since(since_id=5, timeout_seconds=1.0)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].id, 10)
        self.assertEqual(result[0].event_type, "event1")
        self.assertEqual(result[0].correlation_id, "corr-1")
        self.assertEqual(result[0].payload["data"], "value1")
        self.assertEqual(result[1].id, 11)
        self.assertEqual(result[1].event_type, "event2")

    def test_poll_since_empty_result_timeout(self) -> None:
        self.mock_conn.execute.return_value.fetchall.return_value = []

        start = time.monotonic()
        result = self.repo.poll_since(since_id=100, timeout_seconds=0.5)
        elapsed = time.monotonic() - start

        self.assertEqual(len(result), 0)
        self.assertGreaterEqual(elapsed, 0.5)
        self.assertLess(elapsed, 1.0)

    def test_poll_since_returns_immediately_when_events_available(self) -> None:
        mock_rows = [
            {
                "id": 20,
                "event_type": "fast_event",
                "correlation_id": "corr-fast",
                "payload_json": '{"fast": true}',
                "created_at": "2026-05-11T10:00:00+00:00",
            }
        ]
        self.mock_conn.execute.return_value.fetchall.return_value = mock_rows

        start = time.monotonic()
        result = self.repo.poll_since(since_id=15, timeout_seconds=30.0)
        elapsed = time.monotonic() - start

        self.assertEqual(len(result), 1)
        self.assertLess(elapsed, 1.0)

    def test_poll_since_null_correlation_id(self) -> None:
        mock_rows = [
            {
                "id": 30,
                "event_type": "no_corr",
                "correlation_id": None,
                "payload_json": '{"test": true}',
                "created_at": "2026-05-11T10:00:00+00:00",
            }
        ]
        self.mock_conn.execute.return_value.fetchall.return_value = mock_rows

        result = self.repo.poll_since(since_id=25, timeout_seconds=1.0)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].correlation_id, "")

    def test_poll_since_limit_100_events(self) -> None:
        mock_rows = [
            {
                "id": i,
                "event_type": f"event{i}",
                "correlation_id": f"corr-{i}",
                "payload_json": f'{{"id": {i}}}',
                "created_at": "2026-05-11T10:00:00+00:00",
            }
            for i in range(1, 101)
        ]
        self.mock_conn.execute.return_value.fetchall.return_value = mock_rows

        result = self.repo.poll_since(since_id=0, timeout_seconds=1.0)

        self.assertEqual(len(result), 100)
        call_args = self.mock_conn.execute.call_args
        self.assertIn("LIMIT 100", call_args[0][0])

    def test_sse_stored_event_to_sse_line(self) -> None:
        event = SSEStoredEvent(
            id=42,
            event_type="test_event",
            correlation_id="corr-123",
            payload={"key": "value"},
            created_at="2026-05-11T10:00:00+00:00",
        )

        sse_line = event.to_sse_line()

        self.assertIn("data: ", sse_line)
        self.assertTrue(sse_line.endswith("\n\n"))
        data_json = sse_line.replace("data: ", "").strip()
        data = json.loads(data_json)
        self.assertEqual(data["event_type"], "test_event")
        self.assertEqual(data["correlation_id"], "corr-123")
        self.assertEqual(data["event_id"], 42)
        self.assertEqual(data["data"]["key"], "value")
        self.assertEqual(data["timestamp"], "2026-05-11T10:00:00+00:00")

    def test_sse_stored_event_raw_sse_json(self) -> None:
        event = SSEStoredEvent(
            id=99,
            event_type="raw_test",
            correlation_id="corr-raw",
            payload={"test": "data"},
            created_at="2026-05-11T12:00:00+00:00",
        )

        raw_json = event._raw_sse_json()

        data = json.loads(raw_json)
        self.assertEqual(data["event_type"], "raw_test")
        self.assertEqual(data["correlation_id"], "corr-raw")
        self.assertEqual(data["event_id"], 99)
        self.assertEqual(data["data"]["test"], "data")

    def test_poll_since_query_parameters(self) -> None:
        self.mock_conn.execute.return_value.fetchall.return_value = []

        self.repo.poll_since(since_id=42, timeout_seconds=0.1)

        call_args = self.mock_conn.execute.call_args
        self.assertIn("WHERE id > ?", call_args[0][0])
        self.assertIn("ORDER BY id ASC", call_args[0][0])
        self.assertEqual(call_args[0][1], (42,))

    @patch("services.sse_event_repo.time.sleep")
    def test_poll_since_polling_interval(self, mock_sleep: MagicMock) -> None:
        call_count = [0]

        def side_effect(*args: object, **kwargs: object) -> list[dict[str, object]]:
            call_count[0] += 1
            if call_count[0] >= 3:
                return [
                    {
                        "id": 1,
                        "event_type": "delayed",
                        "correlation_id": "corr",
                        "payload_json": "{}",
                        "created_at": "2026-05-11T10:00:00+00:00",
                    }
                ]
            return []

        self.mock_conn.execute.return_value.fetchall.side_effect = side_effect

        result = self.repo.poll_since(since_id=0, timeout_seconds=5.0)

        self.assertEqual(len(result), 1)
        self.assertGreaterEqual(mock_sleep.call_count, 2)
        for call in mock_sleep.call_args_list:
            self.assertEqual(call[0][0], 0.5)


if __name__ == "__main__":
    unittest.main()
