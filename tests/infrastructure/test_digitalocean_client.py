from __future__ import annotations

from unittest.mock import MagicMock

from infrastructure.digitalocean.client import (
    DigitalOceanClient,
    DigitalOceanDropletLaunchRequest,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.content = b"{}" if payload is not None else b""
        self.text = ""

    def json(self) -> dict:
        return self._payload


def _runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.logger.getChild.return_value = MagicMock()
    runtime.config.app.request_timeout_seconds = 30
    runtime.config.app.max_retries = 0
    runtime.config.app.retry_backoff_seconds = 0.01
    return runtime


def test_launch_droplet_maps_public_networks() -> None:
    client = DigitalOceanClient(runtime_context=_runtime(), api_token="dop_v1_test")
    responses = [
        FakeResponse(202, {"droplet": {"id": 123, "name": "sf-do"}}),
        FakeResponse(
            200,
            {
                "droplet": {
                    "id": 123,
                    "name": "sf-do",
                    "status": "active",
                    "size_slug": "s-2vcpu-2gb",
                    "image": {"slug": "ubuntu-24-04-x64"},
                    "networks": {
                        "v4": [{"type": "public", "ip_address": "203.0.113.10"}],
                        "v6": [{"type": "public", "ip_address": "2001:db8::10"}],
                    },
                }
            },
        ),
    ]

    client._session.request = MagicMock(side_effect=responses)

    result = client.launch_droplet(
        DigitalOceanDropletLaunchRequest(
            name="sf-do",
            region="sgp1",
            size="s-2vcpu-2gb",
            image="ubuntu-24-04-x64",
            user_data="#!/bin/sh\ntrue\n",
            ssh_keys=("fingerprint-1",),
            vpc_uuid="vpc-123",
            tags=("shadowfleet",),
        ),
        wait_timeout_seconds=1,
        poll_interval_seconds=0,
    )

    assert result.instance_id == "123"
    assert result.ipv4_address == "203.0.113.10"
    assert result.ipv6_addresses == ("2001:db8::10",)
    assert result.subnet_id == "vpc-123"

    create_call = client._session.request.call_args_list[0]
    assert create_call.kwargs["json"]["user_data"] == "#!/bin/sh\ntrue\n"
    assert create_call.kwargs["json"]["ssh_keys"] == ["fingerprint-1"]
