from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ProbeStatus = Literal[
    "reachable",
    "dns_failed",
    "origin_unreachable",
    "tls_failed",
    "application_unreachable",
    "probe_inconclusive",
]

ProbeMeasurementStatus = Literal[
    "healthy",
    "origin_fault",
    "suspected_blocked",
    "confirmed_blocked_by_gfw",
    "probe_inconclusive",
]


@dataclass(frozen=True)
class MonitorCandidate:
    xboard_node_id: int
    node_name: str
    node_type: str
    asset_type: str
    domain_name: str | None
    host: str | None
    port: str | None
    server_port: int | None
    status: str
    last_healed_at: str | None


@dataclass(frozen=True)
class XboardSentinelMinuteStat:
    server_id: int
    server_type: str
    uplink_bytes: int
    downlink_bytes: int
    total_bytes: int
    active_user_count: int
    sample_minute: int


@dataclass(frozen=True)
class XboardSentinelNodeRuntime:
    node_id: int
    node_type: str
    host: str
    port: str
    server_port: int
    show: bool


@dataclass(frozen=True)
class ProbeResult:
    provider: str
    status: ProbeStatus
    reason: str
    success_region_count: int
    failed_region_count: int
    failure_stage: str | None = None
    resolved_ip: str | None = None
    latency_ms: int | None = None
    raw_payload: dict[str, object] | None = None


@dataclass(frozen=True)
class MonitorCycleResult:
    cycle_id: int
    candidate_count: int
    confirmed_count: int
    healed_count: int
    failed_count: int


@dataclass(frozen=True)
class ProbeMeasurementSummary:
    measurement_id: str
    xboard_node_id: int
    final_status: ProbeMeasurementStatus
    reason: str | None
    control_plane_result: dict[str, object] | None
    probe_result_count: int
    created_at: str
    finished_at: str | None


class MonitorServiceError(RuntimeError):
    pass
