from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentRegistration:
    probe_id: str
    probe_name: str
    auth_token: str
    config_version: int
    config: dict[str, Any]


@dataclass(frozen=True)
class AgentCommand:
    command_id: str
    command_type: str
    correlation_id: str
    payload: dict[str, Any]
