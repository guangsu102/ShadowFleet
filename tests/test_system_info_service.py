from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.system_info_service import (
    NetworkConnectionSummary,
    ProcessResourceInfo,
    SystemInfo,
    SystemInfoService,
)


class TestSystemInfoService(unittest.TestCase):
    def setUp(self) -> None:
        self.service = SystemInfoService()

    @patch("services.system_info_service.psutil.Process")
    def test_get_process_resource_info_success(self, mock_process_cls: MagicMock) -> None:
        mock_process = MagicMock()
        mock_process_cls.return_value = mock_process
        mock_process.cpu_percent.return_value = 15.5
        mock_mem_info = MagicMock()
        mock_mem_info.rss = 100 * 1024 * 1024
        mock_mem_info.vms = 200 * 1024 * 1024
        mock_process.memory_info.return_value = mock_mem_info
        mock_process.num_threads.return_value = 8
        mock_process.open_files.return_value = [MagicMock(), MagicMock()]
        mock_process.memory_percent.return_value = 2.5

        result = self.service.get_process_resource_info()

        self.assertIsInstance(result, ProcessResourceInfo)
        self.assertEqual(result.cpu_percent, 15.5)
        self.assertAlmostEqual(result.memory_rss_mb, 100.0, places=1)
        self.assertEqual(result.num_threads, 8)
        self.assertEqual(result.open_files_count, 2)
        self.assertAlmostEqual(result.virtual_memory_mb, 200.0, places=1)
        self.assertEqual(result.memory_percent, 2.5)
        mock_process.cpu_percent.assert_called_once_with(interval=0.1)

    @patch("services.system_info_service.psutil.Process")
    def test_get_process_resource_info_zero_memory(self, mock_process_cls: MagicMock) -> None:
        mock_process = MagicMock()
        mock_process_cls.return_value = mock_process
        mock_process.cpu_percent.return_value = 0.0
        mock_mem_info = MagicMock()
        mock_mem_info.rss = 0
        mock_mem_info.vms = 0
        mock_process.memory_info.return_value = mock_mem_info
        mock_process.num_threads.return_value = 1
        mock_process.open_files.return_value = []
        mock_process.memory_percent.return_value = 0.0

        result = self.service.get_process_resource_info()

        self.assertEqual(result.memory_rss_mb, 0.0)
        self.assertEqual(result.virtual_memory_mb, 0.0)
        self.assertEqual(result.open_files_count, 0)

    @patch("services.system_info_service.psutil.Process")
    def test_get_process_resource_info_high_values(self, mock_process_cls: MagicMock) -> None:
        mock_process = MagicMock()
        mock_process_cls.return_value = mock_process
        mock_process.cpu_percent.return_value = 99.9
        mock_mem_info = MagicMock()
        mock_mem_info.rss = 8 * 1024 * 1024 * 1024
        mock_mem_info.vms = 16 * 1024 * 1024 * 1024
        mock_process.memory_info.return_value = mock_mem_info
        mock_process.num_threads.return_value = 256
        mock_process.open_files.return_value = [MagicMock() for _ in range(100)]
        mock_process.memory_percent.return_value = 50.0

        result = self.service.get_process_resource_info()

        self.assertEqual(result.cpu_percent, 99.9)
        self.assertAlmostEqual(result.memory_rss_mb, 8192.0, places=1)
        self.assertEqual(result.num_threads, 256)
        self.assertEqual(result.open_files_count, 100)
        self.assertAlmostEqual(result.virtual_memory_mb, 16384.0, places=1)

    @patch("services.system_info_service.psutil.disk_usage")
    @patch("services.system_info_service.psutil.virtual_memory")
    @patch("services.system_info_service.psutil.cpu_percent")
    @patch("services.system_info_service.platform.system")
    @patch("services.system_info_service.socket.gethostname")
    def test_get_system_info_success(
        self,
        mock_hostname: MagicMock,
        mock_platform: MagicMock,
        mock_cpu: MagicMock,
        mock_mem: MagicMock,
        mock_disk: MagicMock,
    ) -> None:
        mock_hostname.return_value = "test-host"
        mock_platform.return_value = "Linux"
        mock_cpu.return_value = 45.2
        mock_mem_obj = MagicMock()
        mock_mem_obj.percent = 60.5
        mock_mem.return_value = mock_mem_obj
        mock_disk_obj = MagicMock()
        mock_disk_obj.percent = 75.8
        mock_disk.return_value = mock_disk_obj

        result = self.service.get_system_info()

        self.assertIsInstance(result, SystemInfo)
        self.assertEqual(result.hostname, "test-host")
        self.assertEqual(result.os_name, "Linux")
        self.assertEqual(result.cpu_percent, 45.2)
        self.assertEqual(result.memory_percent, 60.5)
        self.assertEqual(result.disk_percent, 75.8)
        mock_cpu.assert_called_once_with(interval=0.1)
        mock_disk.assert_called_once_with("/")

    @patch("services.system_info_service.psutil.disk_usage")
    @patch("services.system_info_service.psutil.virtual_memory")
    @patch("services.system_info_service.psutil.cpu_percent")
    @patch("services.system_info_service.platform.system")
    @patch("services.system_info_service.socket.gethostname")
    def test_get_system_info_windows(
        self,
        mock_hostname: MagicMock,
        mock_platform: MagicMock,
        mock_cpu: MagicMock,
        mock_mem: MagicMock,
        mock_disk: MagicMock,
    ) -> None:
        mock_hostname.return_value = "WIN-PC"
        mock_platform.return_value = "Windows"
        mock_cpu.return_value = 10.0
        mock_mem_obj = MagicMock()
        mock_mem_obj.percent = 30.0
        mock_mem.return_value = mock_mem_obj
        mock_disk_obj = MagicMock()
        mock_disk_obj.percent = 50.0
        mock_disk.return_value = mock_disk_obj

        result = self.service.get_system_info()

        self.assertEqual(result.hostname, "WIN-PC")
        self.assertEqual(result.os_name, "Windows")

    @patch("services.system_info_service.psutil.net_connections")
    def test_get_network_connection_summary_multiple_statuses(self, mock_net_conn: MagicMock) -> None:
        mock_conn1 = MagicMock()
        mock_conn1.status = "ESTABLISHED"
        mock_conn2 = MagicMock()
        mock_conn2.status = "ESTABLISHED"
        mock_conn3 = MagicMock()
        mock_conn3.status = "LISTEN"
        mock_conn4 = MagicMock()
        mock_conn4.status = "TIME_WAIT"
        mock_conn5 = MagicMock()
        mock_conn5.status = "ESTABLISHED"
        mock_net_conn.return_value = [mock_conn1, mock_conn2, mock_conn3, mock_conn4, mock_conn5]

        result = self.service.get_network_connection_summary()

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].status, "ESTABLISHED")
        self.assertEqual(result[0].count, 3)
        self.assertIn(result[1].status, ["LISTEN", "TIME_WAIT"])
        self.assertEqual(result[1].count, 1)

    @patch("services.system_info_service.psutil.net_connections")
    def test_get_network_connection_summary_empty(self, mock_net_conn: MagicMock) -> None:
        mock_net_conn.return_value = []

        result = self.service.get_network_connection_summary()

        self.assertEqual(len(result), 0)

    @patch("services.system_info_service.psutil.net_connections")
    def test_get_network_connection_summary_unknown_status(self, mock_net_conn: MagicMock) -> None:
        mock_conn1 = MagicMock()
        mock_conn1.status = None
        mock_conn2 = MagicMock()
        mock_conn2.status = None
        mock_conn3 = MagicMock()
        mock_conn3.status = "ESTABLISHED"
        mock_net_conn.return_value = [mock_conn1, mock_conn2, mock_conn3]

        result = self.service.get_network_connection_summary()

        self.assertEqual(len(result), 2)
        unknown_entry = next((r for r in result if r.status == "UNKNOWN"), None)
        self.assertIsNotNone(unknown_entry)
        self.assertEqual(unknown_entry.count, 2)

    @patch("services.system_info_service.psutil.net_connections")
    def test_get_network_connection_summary_sorted_by_count(self, mock_net_conn: MagicMock) -> None:
        connections = []
        for _ in range(10):
            conn = MagicMock()
            conn.status = "ESTABLISHED"
            connections.append(conn)
        for _ in range(5):
            conn = MagicMock()
            conn.status = "LISTEN"
            connections.append(conn)
        for _ in range(2):
            conn = MagicMock()
            conn.status = "TIME_WAIT"
            connections.append(conn)
        mock_net_conn.return_value = connections

        result = self.service.get_network_connection_summary()

        self.assertEqual(result[0].status, "ESTABLISHED")
        self.assertEqual(result[0].count, 10)
        self.assertEqual(result[1].status, "LISTEN")
        self.assertEqual(result[1].count, 5)
        self.assertEqual(result[2].status, "TIME_WAIT")
        self.assertEqual(result[2].count, 2)

    def test_process_resource_info_immutable(self) -> None:
        info = ProcessResourceInfo(
            cpu_percent=10.0,
            memory_rss_mb=100.0,
            num_threads=5,
            open_files_count=10,
            virtual_memory_mb=200.0,
            memory_percent=5.0,
        )
        with self.assertRaises(Exception):
            info.cpu_percent = 20.0  # type: ignore[misc]

    def test_system_info_immutable(self) -> None:
        info = SystemInfo(
            hostname="test",
            os_name="Linux",
            cpu_percent=10.0,
            memory_percent=20.0,
            disk_percent=30.0,
        )
        with self.assertRaises(Exception):
            info.hostname = "new-host"  # type: ignore[misc]

    def test_network_connection_summary_immutable(self) -> None:
        summary = NetworkConnectionSummary(status="ESTABLISHED", count=5)
        with self.assertRaises(Exception):
            summary.count = 10  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
