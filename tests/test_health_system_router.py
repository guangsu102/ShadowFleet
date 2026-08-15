from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.router import health as health_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(health_router.router)
    app.dependency_overrides[health_router.get_runtime_context] = lambda: MagicMock()
    app.dependency_overrides[health_router.get_current_user] = lambda: None
    return TestClient(app)


def _health_report() -> SimpleNamespace:
    orphan_report = SimpleNamespace(
        total_count=0,
        ec2_instances=[],
        digitalocean_droplets=[],
        digitalocean_snapshots=[],
        vultr_instances=[],
        kamatera_servers=[],
        oci_instances=[],
        azure_vms=[],
        azure_network_resources=[],
        dns_records=[],
        asset_allocations=[],
        xboard_nodes=[],
    )
    sync_report = SimpleNamespace(
        health_status="healthy",
        total_xboard_nodes=0,
        total_sqlite_nodes=0,
        inconsistency_count=0,
    )
    return SimpleNamespace(
        check_time="2026-08-15T00:00:00Z",
        overall_status="healthy",
        alerts=[],
        orphan_resource_report=orphan_report,
        sync_health_report=sync_report,
    )


def test_system_health_get_never_enables_cleanup_or_repair() -> None:
    with patch("api.router.health.SystemHealthMonitor") as monitor_type:
        monitor_type.return_value.run_health_check.return_value = _health_report()
        response = _client().get(
            "/api/v1/health/system?auto_cleanup=true&auto_repair=true"
        )

    assert response.status_code == 200
    monitor_type.return_value.run_health_check.assert_called_once_with(
        auto_cleanup_orphans=False,
        auto_repair_sync=False,
    )