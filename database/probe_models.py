from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]

ProbeStatus = Literal["pending", "active", "disabled", "offline", "draining"]
ProbeCommandType = Literal[
    "run_connectivity_probe",
    "refresh_config",
    "self_check",
    "drain_probe",
    "resume_probe",
]
ProbeCommandStatus = Literal["queued", "leased", "succeeded", "failed", "cancelled"]
ProbeMeasurementStatus = Literal[
    "pending",
    "collecting",
    "healthy",
    "origin_fault",
    "suspected_blocked",
    "confirmed_blocked_by_gfw",
    "probe_inconclusive",
    "failed",
]


@dataclass(frozen=True)
class ProbeCreateRequest:
    probe_id: str
    probe_name: str
    auth_token: str
    machine_fingerprint: str
    public_ip: str | None = None
    region: str | None = None
    isp: str | None = None
    status: ProbeStatus = "active"
    tags: list[str] | None = None
    capabilities: dict[str, JsonValue] | None = None
    config_version: int = 1


@dataclass(frozen=True)
class ProbeRecord:
    id: int
    probe_id: str
    probe_name: str
    status: ProbeStatus
    auth_token: str
    machine_fingerprint: str
    public_ip: str | None
    region: str | None
    isp: str | None
    tags: list[str]
    capabilities: dict[str, JsonValue]
    config_version: int
    last_seen_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ProbeConfigUpsertRequest:
    probe_id: str
    config_version: int
    config: dict[str, JsonValue]


@dataclass(frozen=True)
class ProbeConfigRecord:
    id: int
    probe_id: str
    config_version: int
    config: dict[str, JsonValue]
    created_at: str


@dataclass(frozen=True)
class ProbeHeartbeatRecord:
    id: int
    probe_id: str
    public_ip: str | None
    agent_version: str | None
    runtime_metrics: dict[str, JsonValue] | None
    created_at: str


@dataclass(frozen=True)
class ProbeCommandCreateRequest:
    probe_id: str
    command_type: ProbeCommandType
    payload: dict[str, JsonValue]
    correlation_id: str
    max_attempts: int = 1


@dataclass(frozen=True)
class ProbeCommandRecord:
    id: int
    command_id: str
    probe_id: str
    command_type: ProbeCommandType
    status: ProbeCommandStatus
    correlation_id: str
    payload: dict[str, JsonValue]
    result: dict[str, JsonValue] | None
    last_error: str | None
    attempt_count: int
    max_attempts: int
    leased_by: str | None
    leased_at: str | None
    next_run_at: str
    created_at: str
    updated_at: str
    finished_at: str | None


@dataclass(frozen=True)
class ProbeMeasurementCreateRequest:
    measurement_id: str
    xboard_node_id: int
    correlation_id: str
    final_status: ProbeMeasurementStatus = "pending"
    reason: str | None = None
    control_plane_result: dict[str, JsonValue] | None = None


@dataclass(frozen=True)
class ProbeMeasurementRecord:
    id: int
    measurement_id: str
    xboard_node_id: int
    correlation_id: str
    final_status: ProbeMeasurementStatus
    reason: str | None
    control_plane_result: dict[str, JsonValue] | None
    created_at: str
    updated_at: str
    finished_at: str | None


@dataclass(frozen=True)
class ProbeMeasurementResultCreateRequest:
    measurement_id: str
    probe_id: str
    probe_status: str
    result: dict[str, JsonValue]
    failure_stage: str | None = None
    resolved_ip: str | None = None
    latency_ms: int | None = None


@dataclass(frozen=True)
class ProbeMeasurementResultRecord:
    id: int
    measurement_id: str
    probe_id: str
    probe_status: str
    failure_stage: str | None
    resolved_ip: str | None
    latency_ms: int | None
    result: dict[str, JsonValue]
    created_at: str
