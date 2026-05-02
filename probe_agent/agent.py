from __future__ import annotations

import hashlib
import socket
import time
import uuid

from probe_agent.client import ProbeAgentClient
from probe_agent.config import load_probe_agent_config
from probe_agent.executor import ProbeCommandExecutor
from probe_agent.logger import configure_logging

AGENT_VERSION = "0.1.0"


def main() -> None:
    logger = configure_logging()
    config = load_probe_agent_config()
    client = ProbeAgentClient(
        control_plane_url=config.control_plane_url,
        timeout_seconds=config.probe_timeout_seconds,
    )
    executor = ProbeCommandExecutor(timeout_seconds=config.probe_timeout_seconds)

    public_ip = _resolve_public_ip()
    machine_fingerprint = _resolve_machine_fingerprint(config.machine_fingerprint)

    registration = client.register(
        bootstrap_token=config.bootstrap_token,
        probe_name=config.probe_name,
        machine_fingerprint=machine_fingerprint,
        public_ip=public_ip,
        region=config.region,
        isp=config.isp,
        tags=config.tags,
        capabilities=_build_capabilities(),
    )
    logger.info("Probe registered probe_id=%s probe_name=%s", registration.probe_id, registration.probe_name)
    current_config_version = registration.config_version

    last_heartbeat_at = 0.0
    while True:
        current_monotonic = time.monotonic()
        if current_monotonic - last_heartbeat_at >= config.heartbeat_interval_seconds:
            heartbeat_response = client.heartbeat(
                probe_id=registration.probe_id,
                auth_token=registration.auth_token,
                public_ip=public_ip,
                agent_version=AGENT_VERSION,
                capabilities=_build_capabilities(),
                runtime_metrics={"hostname": socket.gethostname(), "fingerprint": machine_fingerprint},
            )
            last_heartbeat_at = current_monotonic
            logger.info(
                "Heartbeat acknowledged probe_id=%s status=%s config_version=%s",
                registration.probe_id,
                heartbeat_response.get("status"),
                heartbeat_response.get("config_version"),
            )
            response_config_version = int(heartbeat_response.get("config_version", current_config_version))
            if response_config_version != current_config_version:
                config_response = client.get_config(
                    probe_id=registration.probe_id,
                    auth_token=registration.auth_token,
                )
                current_config_version = int(
                    config_response.get("config_version", response_config_version)
                )
                logger.info(
                    "Fetched updated config probe_id=%s config_version=%s",
                    registration.probe_id,
                    current_config_version,
                )

        commands = client.poll(
            probe_id=registration.probe_id,
            auth_token=registration.auth_token,
            lease_owner=socket.gethostname(),
            max_commands=5,
        )
        if not commands:
            time.sleep(config.poll_interval_seconds)
            continue

        for command in commands:
            try:
                result_payload = executor.execute(command.command_type, command.payload)
                client.submit_result(
                    probe_id=registration.probe_id,
                    auth_token=registration.auth_token,
                    command_id=command.command_id,
                    status="succeeded",
                    result_payload=result_payload,
                    last_error=None,
                )
                logger.info(
                    "Command succeeded command_id=%s command_type=%s",
                    command.command_id,
                    command.command_type,
                )
            except Exception as exc:
                client.submit_result(
                    probe_id=registration.probe_id,
                    auth_token=registration.auth_token,
                    command_id=command.command_id,
                    status="failed",
                    result_payload=None,
                    last_error=str(exc),
                )
                logger.exception(
                    "Command failed command_id=%s command_type=%s",
                    command.command_id,
                    command.command_type,
                )


def _build_capabilities() -> dict[str, object]:
    return {
        "supports_dns": True,
        "supports_tcp": True,
        "supports_tls": True,
        "supports_http": True,
        "supports_udp": False,
        "supports_ipv6": True,
        "supports_sni": True,
    }


def _resolve_public_ip() -> str | None:
    """Resolve the machine's public IPv4 address via external service."""
    import requests as _requests
    try:
        response = _requests.get("https://api.ipify.org", timeout=5)
        if response.status_code == 200:
            return response.text.strip()
    except Exception:
        pass
    return None


def _resolve_machine_fingerprint(seed: str) -> str:
    """Derive a stable machine fingerprint from the config seed, hostname, and MAC address."""
    mac_hex = format(uuid.getnode(), "012x")[-12:]
    raw = f"{seed}|{socket.gethostname()}|{mac_hex}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


if __name__ == "__main__":
    main()
