from __future__ import annotations

import requests

from probe_agent.models import AgentCommand, AgentRegistration


class ProbeAgentClient:
    def __init__(self, *, control_plane_url: str, timeout_seconds: int) -> None:
        self._control_plane_url = control_plane_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def register(
        self,
        *,
        bootstrap_token: str,
        probe_name: str,
        machine_fingerprint: str,
        public_ip: str | None,
        region: str | None,
        isp: str | None,
        tags: list[str],
        capabilities: dict[str, object],
    ) -> AgentRegistration:
        response = requests.post(
            f"{self._control_plane_url}/probe/register",
            json={
                "bootstrap_token": bootstrap_token,
                "probe_name": probe_name,
                "machine_fingerprint": machine_fingerprint,
                "public_ip": public_ip,
                "region": region,
                "isp": isp,
                "tags": tags,
                "capabilities": capabilities,
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Probe register response must be a JSON object")
        return AgentRegistration(
            probe_id=str(payload["probe_id"]),
            probe_name=str(payload["probe_name"]),
            auth_token=str(payload["auth_token"]),
            config_version=int(payload["config_version"]),
            config=dict(payload.get("config", {})),
        )

    def heartbeat(
        self,
        *,
        probe_id: str,
        auth_token: str,
        public_ip: str | None,
        agent_version: str,
        capabilities: dict[str, object],
        runtime_metrics: dict[str, object],
    ) -> dict[str, object]:
        response = requests.post(
            f"{self._control_plane_url}/probe/heartbeat",
            json={
                "probe_id": probe_id,
                "auth_token": auth_token,
                "public_ip": public_ip,
                "agent_version": agent_version,
                "capabilities": capabilities,
                "runtime_metrics": runtime_metrics,
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Probe heartbeat response must be a JSON object")
        return payload

    def poll(
        self,
        *,
        probe_id: str,
        auth_token: str,
        lease_owner: str,
        max_commands: int,
    ) -> list[AgentCommand]:
        response = requests.post(
            f"{self._control_plane_url}/probe/poll",
            json={
                "probe_id": probe_id,
                "auth_token": auth_token,
                "lease_owner": lease_owner,
                "max_commands": max_commands,
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Probe poll response must be a JSON object")
        commands = payload.get("commands", [])
        if not isinstance(commands, list):
            raise RuntimeError("Probe poll response commands must be a JSON array")
        return [
            AgentCommand(
                command_id=str(command["command_id"]),
                command_type=str(command["command_type"]),
                correlation_id=str(command["correlation_id"]),
                payload=dict(command.get("payload", {})),
            )
            for command in commands
            if isinstance(command, dict)
        ]

    def submit_result(
        self,
        *,
        probe_id: str,
        auth_token: str,
        command_id: str,
        status: str,
        result_payload: dict[str, object] | None,
        last_error: str | None,
    ) -> None:
        response = requests.post(
            f"{self._control_plane_url}/probe/result",
            json={
                "probe_id": probe_id,
                "auth_token": auth_token,
                "command_id": command_id,
                "status": status,
                "result_payload": result_payload,
                "last_error": last_error,
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()

    def get_config(self, *, probe_id: str, auth_token: str) -> dict[str, object]:
        response = requests.get(
            f"{self._control_plane_url}/probe/config",
            params={
                "probe_id": probe_id,
                "auth_token": auth_token,
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Probe config response must be a JSON object")
        return payload
