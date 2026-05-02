from __future__ import annotations

from dataclasses import dataclass, field
import os


@dataclass(frozen=True)
class ProbeAgentConfig:
    control_plane_url: str
    bootstrap_token: str
    probe_name: str
    machine_fingerprint: str
    region: str | None = None
    isp: str | None = None
    tags: list[str] = field(default_factory=list)
    poll_interval_seconds: float = 5.0
    heartbeat_interval_seconds: float = 15.0
    probe_timeout_seconds: int = 10


def load_probe_agent_config() -> ProbeAgentConfig:
    control_plane_url = os.getenv("SHADOWFLEET_PROBE_CONTROL_PLANE_URL", "").strip()
    bootstrap_token = os.getenv("SHADOWFLEET_PROBE_BOOTSTRAP_TOKEN", "").strip()
    probe_name = os.getenv("SHADOWFLEET_PROBE_NAME", "").strip()
    machine_fingerprint = os.getenv("SHADOWFLEET_PROBE_MACHINE_FINGERPRINT", "").strip()
    region = _optional_env("SHADOWFLEET_PROBE_REGION")
    isp = _optional_env("SHADOWFLEET_PROBE_ISP")
    tags = [
        item.strip()
        for item in os.getenv("SHADOWFLEET_PROBE_TAGS", "").split(",")
        if item.strip()
    ]
    poll_interval_seconds = float(os.getenv("SHADOWFLEET_PROBE_POLL_INTERVAL_SECONDS", "5.0"))
    heartbeat_interval_seconds = float(
        os.getenv("SHADOWFLEET_PROBE_HEARTBEAT_INTERVAL_SECONDS", "15.0")
    )
    probe_timeout_seconds = int(os.getenv("SHADOWFLEET_PROBE_TIMEOUT_SECONDS", "10"))
    if not control_plane_url:
        raise ValueError("SHADOWFLEET_PROBE_CONTROL_PLANE_URL is required")
    if not bootstrap_token:
        raise ValueError("SHADOWFLEET_PROBE_BOOTSTRAP_TOKEN is required")
    if not probe_name:
        raise ValueError("SHADOWFLEET_PROBE_NAME is required")
    if not machine_fingerprint:
        raise ValueError("SHADOWFLEET_PROBE_MACHINE_FINGERPRINT is required")
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be greater than 0")
    if heartbeat_interval_seconds <= 0:
        raise ValueError("heartbeat_interval_seconds must be greater than 0")
    if probe_timeout_seconds <= 0:
        raise ValueError("probe_timeout_seconds must be greater than 0")
    return ProbeAgentConfig(
        control_plane_url=control_plane_url.rstrip("/"),
        bootstrap_token=bootstrap_token,
        probe_name=probe_name,
        machine_fingerprint=machine_fingerprint,
        region=region,
        isp=isp,
        tags=tags,
        poll_interval_seconds=poll_interval_seconds,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        probe_timeout_seconds=probe_timeout_seconds,
    )


def _optional_env(key: str) -> str | None:
    value = os.getenv(key)
    if value is None:
        return None
    normalized_value = value.strip()
    return normalized_value or None
