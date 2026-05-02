from __future__ import annotations

import platform
import socket
from dataclasses import dataclass

import psutil


@dataclass(frozen=True, slots=True)
class ProcessResourceInfo:
    cpu_percent: float
    memory_rss_mb: float
    num_threads: int
    open_files_count: int
    virtual_memory_mb: float
    memory_percent: float


@dataclass(frozen=True, slots=True)
class SystemInfo:
    hostname: str
    os_name: str
    cpu_percent: float
    memory_percent: float
    disk_percent: float


@dataclass(frozen=True, slots=True)
class NetworkConnectionSummary:
    status: str
    count: int


class SystemInfoService:
    def get_process_resource_info(self) -> ProcessResourceInfo:
        process = psutil.Process()
        mem_info = process.memory_info()
        return ProcessResourceInfo(
            cpu_percent=process.cpu_percent(interval=0.1),
            memory_rss_mb=mem_info.rss / 1024 / 1024,
            num_threads=process.num_threads(),
            open_files_count=len(process.open_files()),
            virtual_memory_mb=mem_info.vms / 1024 / 1024,
            memory_percent=process.memory_percent(),
        )

    def get_system_info(self) -> SystemInfo:
        return SystemInfo(
            hostname=socket.gethostname(),
            os_name=platform.system(),
            cpu_percent=psutil.cpu_percent(interval=0.1),
            memory_percent=psutil.virtual_memory().percent,
            disk_percent=psutil.disk_usage("/").percent,
        )

    def get_network_connection_summary(self) -> list[NetworkConnectionSummary]:
        connections = psutil.net_connections()
        counter: dict[str, int] = {}
        for conn in connections:
            status = conn.status or "UNKNOWN"
            counter[status] = counter.get(status, 0) + 1
        return [
            NetworkConnectionSummary(status=status, count=count)
            for status, count in sorted(counter.items(), key=lambda x: x[1], reverse=True)
        ]
