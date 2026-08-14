from __future__ import annotations

from unittest.mock import MagicMock, patch

from infrastructure.digitalocean import DigitalOceanClient


def _runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.logger.getChild.return_value = MagicMock()
    runtime.config.app.request_timeout_seconds = 30
    runtime.config.app.max_retries = 0
    runtime.config.app.retry_backoff_seconds = 0.01
    return runtime


def test_list_droplets_follows_all_pages() -> None:
    client = DigitalOceanClient(_runtime(), api_token="dop_v1_test")
    with patch.object(
        client,
        "_request",
        side_effect=[
            {
                "droplets": [{"id": 1}],
                "links": {"pages": {"next": "https://api.example/droplets?page=2"}},
            },
            {"droplets": [{"id": 2}], "links": {"pages": {}}},
        ],
    ) as request:
        droplets = client.list_droplets(tag_name="shadowfleet")

    assert [droplet["id"] for droplet in droplets] == [1, 2]
    assert request.call_args_list[0].kwargs["params"] == {
        "tag_name": "shadowfleet",
        "page": 1,
        "per_page": 200,
    }
    assert request.call_args_list[1].kwargs["params"]["page"] == 2


def test_create_snapshot_waits_for_action_and_snapshot_visibility() -> None:
    client = DigitalOceanClient(_runtime(), api_token="dop_v1_test")
    with patch.object(
        client,
        "_request",
        return_value={"action": {"id": 91}},
    ) as request, patch.object(
        client,
        "wait_for_action_completed",
    ) as wait_for_action, patch.object(
        client,
        "list_snapshots",
        return_value=[
            {"id": "snapshot-1", "name": "heal-snapshot", "resource_id": 1001}
        ],
    ):
        snapshot = client.create_droplet_snapshot(
            1001,
            "heal-snapshot",
            poll_interval_seconds=0,
        )

    assert snapshot["id"] == "snapshot-1"
    assert request.call_args.kwargs["payload"] == {
        "type": "snapshot",
        "name": "heal-snapshot",
    }
    wait_for_action.assert_called_once_with(
        91,
        timeout_seconds=1800,
        poll_interval_seconds=0,
    )


def test_delete_droplet_and_snapshot_accept_missing_resources() -> None:
    client = DigitalOceanClient(_runtime(), api_token="dop_v1_test")
    with patch.object(client, "_request") as request:
        client.delete_droplet("missing-droplet")
        client.delete_snapshot("missing-snapshot")

    assert request.call_args_list[0].kwargs["expected_status"] == {204, 404}
    assert request.call_args_list[1].kwargs["expected_status"] == {204, 404}
