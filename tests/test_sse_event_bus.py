from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from services.sse_event_bus import EventBus, EventType, SSEEvent, get_event_bus


class TestSSEEvent(unittest.TestCase):
    def test_to_json(self) -> None:
        event = SSEEvent(
            event_type=EventType.TASK_CREATED,
            data={"task_id": 123, "status": "queued"},
            correlation_id="corr-123",
        )

        json_str = event.to_json()

        self.assertIn('"event_type": "task:created"', json_str)
        self.assertIn('"correlation_id": "corr-123"', json_str)
        self.assertIn('"task_id": 123', json_str)
        self.assertIn('"status": "queued"', json_str)
        self.assertIn('"timestamp":', json_str)

    def test_to_json_empty_correlation_id(self) -> None:
        event = SSEEvent(
            event_type=EventType.NODE_STATUS_CHANGED,
            data={"node_id": 456},
        )

        json_str = event.to_json()

        self.assertIn('"correlation_id": ""', json_str)

    def test_to_sse(self) -> None:
        event = SSEEvent(
            event_type=EventType.SNAPSHOT_UPDATED,
            data={"snapshot_id": 789},
            correlation_id="corr-456",
        )

        sse_str = event.to_sse()

        self.assertTrue(sse_str.startswith("event: snapshot:updated\n"))
        self.assertTrue(sse_str.startswith("event: snapshot:updated\ndata: "))
        self.assertTrue(sse_str.endswith("\n\n"))
        self.assertIn('"event_type": "snapshot:updated"', sse_str)
        self.assertIn('"snapshot_id": 789', sse_str)

    def test_to_sse_format(self) -> None:
        event = SSEEvent(
            event_type=EventType.TASK_STATUS_CHANGED,
            data={"task_id": 1, "old_status": "queued", "new_status": "running"},
            correlation_id="corr-789",
        )

        sse_str = event.to_sse()

        lines = sse_str.split("\n")
        self.assertEqual(lines[0], "event: task:status_changed")
        self.assertTrue(lines[1].startswith("data: "))
        self.assertEqual(lines[2], "")
        self.assertEqual(lines[3], "")

    def test_event_type_enum_values(self) -> None:
        self.assertEqual(EventType.TASK_CREATED.value, "task:created")
        self.assertEqual(EventType.TASK_STATUS_CHANGED.value, "task:status_changed")
        self.assertEqual(EventType.NODE_STATUS_CHANGED.value, "node:status_changed")
        self.assertEqual(EventType.SNAPSHOT_UPDATED.value, "snapshot:updated")


class TestEventBus(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        EventBus._instance = None

    def tearDown(self) -> None:
        EventBus._instance = None

    def test_get_instance_singleton(self) -> None:
        bus1 = EventBus.get_instance()
        bus2 = EventBus.get_instance()
        self.assertIs(bus1, bus2)

    def test_initialization(self) -> None:
        bus = EventBus()
        self.assertTrue(hasattr(bus, "_queue"))
        self.assertTrue(hasattr(bus, "_logger"))
        self.assertTrue(hasattr(bus, "_initialized"))

    async def test_publish_event_success(self) -> None:
        bus = EventBus()
        event = SSEEvent(
            event_type=EventType.TASK_CREATED,
            data={"task_id": 1},
            correlation_id="corr-1",
        )

        await bus.publish(event)

        queue = bus.subscribe()
        published_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        self.assertEqual(published_event.event_type, EventType.TASK_CREATED)
        self.assertEqual(published_event.data["task_id"], 1)
        self.assertEqual(published_event.correlation_id, "corr-1")

    async def test_publish_multiple_events(self) -> None:
        bus = EventBus()
        events = [
            SSEEvent(event_type=EventType.TASK_CREATED, data={"task_id": i}, correlation_id=f"corr-{i}")
            for i in range(5)
        ]

        for event in events:
            await bus.publish(event)

        queue = bus.subscribe()
        for i in range(5):
            published_event = await asyncio.wait_for(queue.get(), timeout=1.0)
            self.assertEqual(published_event.data["task_id"], i)

    async def test_subscribe_returns_queue(self) -> None:
        bus = EventBus()
        queue = bus.subscribe()

        self.assertIsInstance(queue, asyncio.Queue)

    async def test_queue_full_drops_event(self) -> None:
        bus = EventBus()
        queue = bus.subscribe()

        for i in range(1000):
            event = SSEEvent(
                event_type=EventType.TASK_CREATED,
                data={"task_id": i},
            )
            await bus.publish(event)

        extra_event = SSEEvent(
            event_type=EventType.TASK_CREATED,
            data={"task_id": 9999},
        )

        with patch.object(bus._logger, "warning") as mock_warning:
            await bus.publish(extra_event)
            mock_warning.assert_called_once()
            self.assertIn("queue full", mock_warning.call_args[0][0].lower())

    async def test_multiple_subscribers_share_queue(self) -> None:
        bus = EventBus()
        queue1 = bus.subscribe()
        queue2 = bus.subscribe()

        self.assertIs(queue1, queue2)

    async def test_publish_different_event_types(self) -> None:
        bus = EventBus()
        events = [
            SSEEvent(event_type=EventType.TASK_CREATED, data={"id": 1}),
            SSEEvent(event_type=EventType.TASK_STATUS_CHANGED, data={"id": 2}),
            SSEEvent(event_type=EventType.NODE_STATUS_CHANGED, data={"id": 3}),
            SSEEvent(event_type=EventType.SNAPSHOT_UPDATED, data={"id": 4}),
        ]

        for event in events:
            await bus.publish(event)

        queue = bus.subscribe()
        for i, expected_type in enumerate(
            [
                EventType.TASK_CREATED,
                EventType.TASK_STATUS_CHANGED,
                EventType.NODE_STATUS_CHANGED,
                EventType.SNAPSHOT_UPDATED,
            ]
        ):
            published_event = await asyncio.wait_for(queue.get(), timeout=1.0)
            self.assertEqual(published_event.event_type, expected_type)
            self.assertEqual(published_event.data["id"], i + 1)

    async def test_publish_with_complex_data(self) -> None:
        bus = EventBus()
        complex_data = {
            "task_id": 123,
            "nested": {"key": "value", "list": [1, 2, 3]},
            "unicode": "测试数据",
        }
        event = SSEEvent(
            event_type=EventType.TASK_CREATED,
            data=complex_data,
            correlation_id="corr-complex",
        )

        await bus.publish(event)

        queue = bus.subscribe()
        published_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        self.assertEqual(published_event.data["nested"]["key"], "value")
        self.assertEqual(published_event.data["unicode"], "测试数据")

    def test_get_event_bus_function(self) -> None:
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        self.assertIs(bus1, bus2)
        self.assertIsInstance(bus1, EventBus)

    async def test_queue_maxsize_1000(self) -> None:
        bus = EventBus()
        queue = bus.subscribe()
        self.assertEqual(queue.maxsize, 1000)

    async def test_publish_empty_data(self) -> None:
        bus = EventBus()
        event = SSEEvent(
            event_type=EventType.TASK_CREATED,
            data={},
            correlation_id="corr-empty",
        )

        await bus.publish(event)

        queue = bus.subscribe()
        published_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        self.assertEqual(published_event.data, {})


if __name__ == "__main__":
    unittest.main()
