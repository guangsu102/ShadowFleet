from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ManualTaskType = Literal[
    "force_heal",
    "decommission_node",
    "reprobe_node",
    "mark_manual_review",
]
ManualTaskStatus = Literal["queued", "running", "succeeded", "failed"]
ManualForceStrategy = Literal[
    "aws_ipv6_rotate",
    "azure_ipv6_rotate",
    "digitalocean_instance_replace",
    "kamatera_instance_replace",
    "vultr_instance_replace",
    "oci_ipv6_rotate",
    "cloudflare_enable_proxy",
]


@dataclass(frozen=True)
class ManualOperationRequest:
    task_type: ManualTaskType
    xboard_node_id: int
    operator_name: str | None = None
    reason: str | None = None
    force_strategy: ManualForceStrategy | None = None


@dataclass(frozen=True)
class ManualOperationSubmitResult:
    task_id: int
    correlation_id: str
    status: str


@dataclass(frozen=True)
class ManualOperationTaskRecord:
    id: int
    task_type: ManualTaskType
    status: ManualTaskStatus
    correlation_id: str
    operator_name: str | None
    xboard_node_id: int
    request_payload: dict[str, object]
    result_payload: dict[str, object] | None
    last_error: str | None
    attempt_count: int
    max_attempts: int
    locked_by: str | None
    locked_at: str | None
    next_run_at: str
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
