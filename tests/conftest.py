"""pytest global configuration and shared fixtures for ShadowFleet tests."""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generator
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    pass

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture
def mock_runtime_context() -> MagicMock:
    """Create a mock RuntimeContext for testing services."""
    mock = MagicMock()
    mock.correlation_id = "test-correlation-id-12345"
    mock.config = MagicMock()
    mock.logger = MagicMock(spec=logging.Logger)
    mock.logger.name = "test.logger"
    return mock


def _create_in_memory_schema_db() -> sqlite3.Connection:
    from database.sqlite_connection import SqliteConnectionManager

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SqliteConnectionManager._build_schema_script())
    manager = object.__new__(SqliteConnectionManager)
    manager._run_migrations(connection)
    connection.commit()
    return connection


@pytest.fixture
def in_memory_sqlite_db() -> Generator[sqlite3.Connection, None, None]:
    """Create an in-memory database from the production SQLite schema."""
    connection = _create_in_memory_schema_db()
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def full_schema_sqlite_db() -> Generator[sqlite3.Connection, None, None]:
    """Create an integration database from the production SQLite schema."""
    connection = _create_in_memory_schema_db()
    try:
        yield connection
    finally:
        connection.close()

@pytest.fixture
def sample_config_dict() -> dict[str, Any]:
    """Create a minimal valid configuration dictionary for testing."""
    return {
        "app": {
            "environment": "test",
            "sqlite_path": ":memory:",
            "sentinel_enabled": False,
        },
        "logging": {
            "level": "DEBUG",
        },
        "telegram": {
            "enabled": False,
        },
        "cloudflare": {
            "enabled": True,
            "api_token": "test_cf_token_12345",
            "zone_id": "test_zone_id_67890",
            "root_domain": "example.com",
            "auto_subdomain_prefix": "sf",
        },
        "aws_proxy": {
            "enabled": False,
        },
        "xboard": {
            "host": "localhost",
            "port": 5432,
            "database": "xboard_test",
            "user": "test_user",
            "password": "test_password",
        },
        "fleet_matrix": {
            "ap-northeast-1": {
                "AnyTLS": {
                    "desired_count": 5,
                    "min_alert_threshold": 2,
                },
                "Trojan": {
                    "desired_count": 3,
                    "min_alert_threshold": 1,
                },
            }
        },
    }


@pytest.fixture
def mock_ec2_client() -> MagicMock:
    """Create a mock EC2Client for testing."""
    mock = MagicMock()
    mock.rotate_instance_ipv6.return_value = ("2600:1f14:804:as03:1234::", "2600:1f14:804:as03:5678::")
    mock.launch_ipv6_instance.return_value = MagicMock(
        instance_id="i-0abcdef1234567890",
        instance_state="running",
        ipv6_addresses=["2600:1f14:804:as03:abcd::"],
        network_interface_id="eni-1234567890abcdef0",
    )
    return mock


@pytest.fixture
def mock_cf_client() -> MagicMock:
    """Create a mock CFClient for testing."""
    mock = MagicMock()
    mock.sync_aaaa_record.return_value = "cloudflare_record_123"
    mock.set_record_proxied.return_value = None
    mock.upsert_dns_record.return_value = "cloudflare_record_456"
    return mock


@pytest.fixture
def mock_xboard_repo() -> MagicMock:
    """Create a mock XboardRepo for testing."""
    mock = MagicMock()
    mock.register_node.return_value = 12345
    mock.mark_node_online.return_value = None
    mock.update_node_host.return_value = None
    mock.delete_node.return_value = None
    return mock


@pytest.fixture
def mock_state_repo() -> MagicMock:
    """Create a mock StateRepo for testing."""
    mock = MagicMock()
    mock.get_node_by_xboard_node_id.return_value = MagicMock(
        id=1,
        xboard_node_id=12345,
        node_name="test-node",
        node_type="AnyTLS",
        status="online",
        ipv6_address="2600:1f14:804:as03:1234::",
        domain_name="sf-12345.example.com",
        aws_account_id="test-aws-account-001",
        aws_region="ap-northeast-1",
        aws_instance_id="i-0abcdef1234567890",
        aws_subnet_id="subnet-1234567890abcdef0",
        cloudflare_record_id="cloudflare_record_123",
    )
    mock.acquire_operation_lock.return_value = True
    mock.create_event.return_value = None
    mock.update_node_status.return_value = None
    mock.update_node_runtime_metadata.return_value = None
    return mock


@pytest.fixture(autouse=True)
def clean_environment() -> Generator[None, None, None]:
    """Clean environment variables before and after each test."""
    original_env = os.environ.copy()

    test_env_keys = [k for k in os.environ.keys() if k.startswith("SHADOWFLEET_")]
    for key in test_env_keys:
        del os.environ[key]

    yield

    os.environ.clear()
    os.environ.update(original_env)
