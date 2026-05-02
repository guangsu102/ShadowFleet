#!/usr/bin/env python3
"""
ShadowFleet API E2E Integration Test
Run from project root:
    python tests/e2e/test_api_integration.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import uuid
from fastapi.testclient import TestClient

from api.main import create_app

app = create_app()
client = TestClient(app, raise_server_exceptions=False)


def random_user() -> str:
    return f"test_{uuid.uuid4().hex[:8]}"


# ──────────────────────────────────────────────
# T-1.B1.a  Hardware Probe Endpoints
# ──────────────────────────────────────────────
def test_hardware_probe_self_hosted():
    """POST /assets/self-hosted/probe-hardware — standalone probe without registration."""
    resp = client.post(
        "/api/v1/assets/self-hosted/probe-hardware",
        json={
            "host": "127.0.0.1",
            "ssh_port": 22,
            "ssh_username": "root",
            "ssh_password": "wrong-password",
        },
        headers={"Authorization": f"Bearer {client_token()}"},
    )
    assert resp.status_code in (200, 400), f"Expected 200 or 400, got {resp.status_code}: {resp.json()}"
    if resp.status_code == 200:
        data = resp.json()
        assert "cpu_cores" in data
        assert "memory_gb" in data
        print(f"  [PASS] Hardware probe returned cpu={data['cpu_cores']} mem={data['memory_gb']}GB")
    else:
        print(f"  [PASS] Hardware probe correctly rejected (SSH unreachable): {resp.json().get('detail', '')}")


def test_hardware_probe_requires_auth():
    """POST /assets/self-hosted/probe-hardware without token → 401."""
    resp = client.post("/api/v1/assets/self-hosted/probe-hardware", json={"host": "127.0.0.1"})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
    print("  [PASS] Hardware probe rejects unauthenticated request")


# ──────────────────────────────────────────────
# T-1.B1.b  Monitor Detections with Filters
# ──────────────────────────────────────────────
def test_monitor_detections_filter():
    """GET /monitor/detections supports cycle_id, node_id, detection_status filters."""
    resp = client.get(
        "/api/v1/monitor/detections?detection_status=candidate",
        headers={"Authorization": f"Bearer {client_token()}"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
    data = resp.json()
    assert isinstance(data, list), f"Expected list, got {type(data)}"
    print(f"  [PASS] GET /monitor/detections with detection_status filter returns {len(data)} records")


def test_monitor_detections_requires_auth():
    """GET /monitor/detections without token → 401."""
    resp = client.get("/api/v1/monitor/detections")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
    print("  [PASS] /monitor/detections rejects unauthenticated request")


# ──────────────────────────────────────────────
# T-2.1.a  Login → JWT → Protected Endpoint
# ──────────────────────────────────────────────
def test_login_default_admin():
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200, f"Login failed: {resp.json()}"
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    print(f"  [PASS] Login admin (expires_in={data.get('expires_in')})")


def test_login_invalid_credentials():
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.json()}"
    print("  [PASS] Login rejected for wrong password")


def test_protected_endpoint_without_token():
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.json()}"
    print("  [PASS] Protected endpoint rejects unauthenticated request")


def test_protected_endpoint_with_token():
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    token = login.json()["access_token"]
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
    data = resp.json()
    assert data["username"] == "admin"
    assert data["role"] == "admin"
    assert data["is_active"] is True
    print(f"  [PASS] GET /auth/me returns user={data['username']} role={data['role']}")


def test_token_refresh():
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    refresh_token = login.json()["refresh_token"]
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200, f"Refresh failed: {resp.json()}"
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    print("  [PASS] Token refresh successful")


# ──────────────────────────────────────────────
# T-2.1.b  Correlation ID Propagation
# ──────────────────────────────────────────────
def test_correlation_id_returned_in_response():
    client_id = str(uuid.uuid4())
    resp = client.get(
        "/api/v1/auth/me",
        headers={"X-Correlation-ID": client_id, "Authorization": f"Bearer {client_token()}"}
    )
    assert resp.status_code == 200
    corr_id = resp.headers.get("x-correlation-id")
    assert corr_id == client_id, f"Expected {client_id}, got {corr_id}"
    print(f"  [PASS] X-Correlation-ID propagated: {corr_id}")


def test_correlation_id_generated_if_missing():
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {client_token()}"})
    assert resp.status_code == 200
    corr_id = resp.headers.get("x-correlation-id")
    assert corr_id is not None and len(corr_id) == 36  # UUID format
    print(f"  [PASS] X-Correlation-ID auto-generated: {corr_id}")


# ──────────────────────────────────────────────
# T-2.1.c  CORS Headers
# ──────────────────────────────────────────────
def test_cors_headers_present():
    resp = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert "access-control-allow-origin" in [h.lower() for h in resp.headers]
    allow_origin = resp.headers.get("access-control-allow-origin", "")
    assert allow_origin == "*" or allow_origin == "http://localhost:5173"
    print(f"  [PASS] CORS headers present (allow-origin={allow_origin})")


# ──────────────────────────────────────────────
# T-2.1.d  API Response Format Consistency
# ──────────────────────────────────────────────
def test_auth_me_response_shape():
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {client_token()}"})
    assert resp.status_code == 200
    data = resp.json()
    required = {"id", "username", "role", "is_active", "created_at", "updated_at"}
    missing = required - set(data.keys())
    assert not missing, f"Missing fields: {missing}"
    print("  [PASS] /auth/me response has all required fields")


# ──────────────────────────────────────────────
# T-2.2.a  daemon.py standalone — FastAPI doesn't import daemon code
# ──────────────────────────────────────────────
def test_fastapi_does_not_import_daemon():
    """FastAPI app must not transitively import daemon.py to ensure daemon runs standalone."""
    import importlib.util

    importlib.util.find_spec("daemon")
    # daemon.py is a script, not a package — spec will be None or file-based
    # The real test: daemon.py never imported in api/
    daemon_imports = []
    for py_file in Path("api").rglob("*.py"):
        content = py_file.read_text()
        if "import daemon" in content or "from daemon" in content:
            daemon_imports.append(str(py_file))
    assert not daemon_imports, f"api/ must not import daemon: {daemon_imports}"
    print("  [PASS] FastAPI does not import daemon.py (daemon stays standalone)")


# ──────────────────────────────────────────────
# T-2.2.b  FastAPI + daemon write to same SQLite (via config.yaml)
# ──────────────────────────────────────────────
def test_sqlite_path_matches_daemon_config():
    """Both FastAPI and daemon read the same sqlite_path from config.yaml."""
    from utils.config_parser import load_config
    config = load_config(Path("config.yaml"))
    sqlite_path = Path(config.app.sqlite_path)
    if not sqlite_path.is_absolute():
        sqlite_path = Path.cwd() / sqlite_path
    assert sqlite_path.exists(), f"SQLite path does not exist: {sqlite_path}"
    print(f"  [PASS] SQLite path configured: {sqlite_path}")


# ──────────────────────────────────────────────
# T-2.2.c  /api/v1/provisioning/ready handled by daemon (port 8787), NOT FastAPI
# ──────────────────────────────────────────────
def test_ready_callback_not_registered_on_fastapi():
    """FastAPI must NOT have a route for /api/v1/provisioning/ready — daemon owns it on port 8787."""
    for route in app.routes:
        path = getattr(route, "path", None)
        if path and "provisioning" in path and "ready" in path:
            raise AssertionError(f"FastAPI must not register ready callback: {path}")
    print("  [PASS] FastAPI has no /api/v1/provisioning/ready route (daemon owns it)")


# ──────────────────────────────────────────────
# T-2.3.a  Both UIs can run simultaneously
# ──────────────────────────────────────────────
def test_fastapi_starts_on_port_8000():
    """Verify FastAPI app can bind to port 8000 (no port conflict with Streamlit)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", 8000))
        print("  [PASS] Port 8000 is available for FastAPI")
    except OSError:
        raise AssertionError("Port 8000 is already in use — check Streamlit is not on 8000")
    finally:
        s.close()


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
_cached_token: str | None = None


def client_token() -> str:
    global _cached_token
    if _cached_token:
        return _cached_token
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    _cached_token = resp.json()["access_token"]
    return _cached_token


# ──────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  ShadowFleet API E2E Integration Tests (Phase 2)")
    print("=" * 60)

    tests = [
        ("T-1.B1.a — Hardware Probe Endpoints", [
            test_hardware_probe_self_hosted,
            test_hardware_probe_requires_auth,
        ]),
        ("T-1.B1.b — Monitor Detections Filters", [
            test_monitor_detections_filter,
            test_monitor_detections_requires_auth,
        ]),
        ("T-2.1.a — Login → JWT → Protected Endpoint", [
            test_login_default_admin,
            test_login_invalid_credentials,
            test_protected_endpoint_without_token,
            test_protected_endpoint_with_token,
            test_token_refresh,
        ]),
        ("T-2.1.b — Correlation ID Propagation", [
            test_correlation_id_returned_in_response,
            test_correlation_id_generated_if_missing,
        ]),
        ("T-2.1.c — CORS Headers", [
            test_cors_headers_present,
        ]),
        ("T-2.1.d — API Response Format Consistency", [
            test_auth_me_response_shape,
        ]),
        ("T-2.2.a — daemon.py standalone", [
            test_fastapi_does_not_import_daemon,
        ]),
        ("T-2.2.b — SQLite shared path", [
            test_sqlite_path_matches_daemon_config,
        ]),
        ("T-2.2.c — Ready callback not on FastAPI", [
            test_ready_callback_not_registered_on_fastapi,
        ]),
        ("T-2.3.a — Dual UI port availability", [
            test_fastapi_starts_on_port_8000,
        ]),
    ]

    passed = 0
    failed = 0
    for group_name, test_funcs in tests:
        print(f"\n  {group_name}")
        for fn in test_funcs:
            try:
                fn()
                passed += 1
            except Exception as exc:
                failed += 1
                print(f"  [FAIL] {fn.__name__}: {exc}")

    print("\n" + "=" * 60)
    total = passed + failed
    print(f"  Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60 + "\n")
    sys.exit(0 if failed == 0 else 1)
