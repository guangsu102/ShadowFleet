from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.router import health as health_router
from services.orphan_resource_cleaner import CleanupReport
from services.orphan_resource_detector import OrphanOCIInstance, OrphanResourceReport


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(health_router.router)
    runtime = MagicMock()
    app.dependency_overrides[health_router.get_runtime_context] = lambda: runtime
    app.dependency_overrides[health_router.get_current_user] = lambda: None
    app.dependency_overrides[health_router.require_operator] = lambda: None
    return TestClient(app)


def _report() -> OrphanResourceReport:
    return OrphanResourceReport(
        scan_time="2026-08-14T00:00:00Z",
        ec2_instances=[],
        dns_records=[],
        asset_allocations=[],
        xboard_nodes=[],
        total_count=1,
        oci_instances=[
            OrphanOCIInstance(
                instance_id="instance-ocid",
                asset_id=7,
                region="ap-tokyo-1",
                display_name="sf-orphan",
                created_at="2000-01-01T00:00:00Z",
                state="RUNNING",
                tags={"ManagedBy": "ShadowFleet"},
            )
        ],
    )


def test_orphan_health_response_includes_oci_instances() -> None:
    with patch("api.router.health.OrphanResourceDetector") as detector_type:
        detector_type.return_value.scan_all_orphan_resources.return_value = _report()
        response = _client().get("/api/v1/health/orphan-resources")

    assert response.status_code == 200
    assert response.json()["oci_instances"] == [
        {
            "instance_id": "instance-ocid",
            "asset_id": 7,
            "region": "ap-tokyo-1",
            "display_name": "sf-orphan",
            "created_at": "2000-01-01T00:00:00Z",
            "state": "RUNNING",
            "tags": {"ManagedBy": "ShadowFleet"},
        }
    ]


def test_orphan_cleanup_route_forwards_oci_toggle() -> None:
    with patch("api.router.health.OrphanResourceDetector") as detector_type, patch(
        "api.router.health.OrphanResourceCleaner"
    ) as cleaner_type:
        detector_type.return_value.scan_all_orphan_resources.return_value = _report()
        cleaner_type.return_value.cleanup_orphan_resources.return_value = CleanupReport(
            cleanup_time="2026-08-14T00:00:00Z",
            total_attempted=0,
            total_succeeded=0,
            total_failed=0,
            results=[],
        )
        response = _client().post(
            "/api/v1/health/orphan-resources/cleanup",
            json={"cleanup_oci": False, "dry_run": True},
        )

    assert response.status_code == 200
    kwargs = cleaner_type.return_value.cleanup_orphan_resources.call_args.kwargs
    assert kwargs["cleanup_oci"] is False
    assert kwargs["dry_run"] is True
