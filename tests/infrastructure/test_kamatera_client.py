from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from infrastructure.kamatera import (
    KamateraClient,
    KamateraClientError,
    KamateraServerLaunchRequest,
)


def _runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.logger.getChild.return_value = MagicMock()
    runtime.config.app.request_timeout_seconds = 30
    runtime.config.app.max_retries = 0
    runtime.config.app.retry_backoff_seconds = 0.01
    return runtime


def _server() -> dict[str, object]:
    return {
        "id": "server-1",
        "name": "sf-node-1",
        "datacenter": "AS",
        "cpu": "2B",
        "ram": 2048,
        "networks": [
            {"network": "wan-as", "ips": ["203.0.113.10", "2001:db8::10"]}
        ],
    }


def test_launch_server_uses_official_json_fields_and_waits_for_command() -> None:
    client = KamateraClient(_runtime(), client_id="client", secret="secret")
    with patch.object(
        client,
        "_request",
        return_value={"password": "generated", "commandIds": ["command-1"]},
    ) as request, patch.object(
        client,
        "wait_for_command",
        return_value={"status": "complete", "log": "Name: sf-node-1\n"},
    ) as wait, patch.object(client, "get_server_by_name", return_value=_server()):
        result = client.launch_server(
            KamateraServerLaunchRequest(
                name="sf-node-1",
                datacenter="AS",
                image="ubuntu_server_24.04_64-bit",
                cpu="2B",
                ram_mb=2048,
                disk_sizes_gb=(20,),
                startup_script="#!/bin/bash\necho ready",
                ssh_public_key="ssh-ed25519 AAAA test",
                tags=("production",),
            ),
            poll_interval_seconds=0,
        )

    payload = request.call_args.kwargs["payload"]
    assert payload["password"] == "__generate__"
    assert payload["passwordValidate"] == "__generate__"
    assert payload["disk"] == "size=20"
    assert payload["network"] == "name=wan,ip=auto"
    assert payload["tag"] == ["shadowfleet", "production"]
    assert payload["script-file"].startswith("#!/bin/bash")
    wait.assert_called_once()
    assert result.instance_id == "server-1"
    assert result.ipv4_address == "203.0.113.10"
    assert result.ipv6_address == "2001:db8::10"


def test_wait_for_command_surfaces_error_log() -> None:
    client = KamateraClient(_runtime(), client_id="client", secret="secret")
    with patch.object(
        client,
        "_request",
        return_value=[{"status": "error", "log": "quota exceeded"}],
    ):
        with pytest.raises(KamateraClientError, match="quota exceeded"):
            client.wait_for_command(
                "command-1",
                timeout_seconds=1,
                poll_interval_seconds=0,
            )


def test_delete_server_is_idempotent_when_api_reports_missing() -> None:
    client = KamateraClient(_runtime(), client_id="client", secret="secret")
    with patch.object(
        client,
        "_request",
        side_effect=KamateraClientError("server not found", status_code=404),
    ):
        client.delete_server("missing")


def test_http_200_embedded_errors_are_rejected() -> None:
    client = KamateraClient(_runtime(), client_id="client", secret="secret")
    response = MagicMock(status_code=200)
    response.json.return_value = {"errors": [{"message": "invalid credentials"}]}
    with patch.object(client._session, "request", return_value=response):
        with pytest.raises(KamateraClientError, match="invalid credentials"):
            client.list_datacenters()
