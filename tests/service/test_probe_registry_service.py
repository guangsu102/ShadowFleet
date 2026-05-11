"""Unit tests for ProbeRegistryService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from database.probe_models import ProbeConfigRecord, ProbeRecord
from services.probe_registry_service import (
    ProbeRegistryService,
    ProbeRegistryServiceError,
)


@pytest.fixture
def mock_runtime_context():
    """Create a mock RuntimeContext for testing."""
    mock = MagicMock()
    mock.correlation_id = "test-correlation-id"
    mock.logger = MagicMock()
    mock.logger.getChild.return_value = mock.logger
    mock.config = MagicMock()
    mock.config.app = MagicMock()
    mock.config.app.probe_server_enabled = True
    mock.config.app.probe_bootstrap_tokens = ["bootstrap-token-123", "bootstrap-token-456"]
    mock.config.app.probe_poll_interval_seconds = 5
    mock.config.app.sentinel_probe_timeout_seconds = 10
    mock.config.app.sentinel_probe_result_wait_timeout_seconds = 30
    mock.config.app.probe_heartbeat_timeout_seconds = 300
    return mock


@pytest.fixture
def mock_probe_repo():
    """Create a mock ProbeRepo."""
    return MagicMock()


class TestProbeRegistryServiceRegisterProbe:
    """Tests for register_probe method."""

    def test_register_probe_new_probe_success(
        self, mock_runtime_context, mock_probe_repo
    ):
        """Should register a new probe successfully."""
        mock_probe_repo.get_probe_by_machine_fingerprint.return_value = None
        mock_probe_repo.create_probe.return_value = ProbeRecord(
            id=1,
            probe_id="probe-abc123",
            probe_name="CN-Beijing-1",
            status="pending",
            auth_token="auth-token-xyz",
            machine_fingerprint="fp-machine-001",
            public_ip="1.2.3.4",
            region="cn-north-1",
            isp="China Telecom",
            tags=["production"],
            capabilities={"http": True, "tls": True},
            config_version=1,
            last_seen_at=None,
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
        )
        mock_probe_repo.get_latest_probe_config.return_value = None
        mock_probe_repo.upsert_probe_config.return_value = ProbeConfigRecord(
            id=1,
            probe_id="probe-abc123",
            config_version=1,
            config={
                "poll_interval_seconds": 5,
                "probe_timeout_seconds": 10,
            },
            created_at="2026-03-24T00:00:00Z",
        )

        with patch(
            "services.probe_registry_service.ProbeRepo",
            return_value=mock_probe_repo,
        ):
            service = ProbeRegistryService(mock_runtime_context)
            result = service.register_probe(
                bootstrap_token="bootstrap-token-123",
                probe_name="CN-Beijing-1",
                machine_fingerprint="fp-machine-001",
                public_ip="1.2.3.4",
                region="cn-north-1",
                isp="China Telecom",
                tags=["production"],
                capabilities={"http": True, "tls": True},
            )

        assert result.probe_id == "probe-abc123"
        assert result.probe_name == "CN-Beijing-1"
        assert result.auth_token == "auth-token-xyz"
        assert result.config_version == 1
        mock_probe_repo.create_probe.assert_called_once()

    def test_register_probe_existing_probe_returns_existing(
        self, mock_runtime_context, mock_probe_repo
    ):
        """Should return existing probe when machine fingerprint matches."""
        existing_probe = ProbeRecord(
            id=1,
            probe_id="probe-existing",
            probe_name="CN-Beijing-1",
            status="active",
            auth_token="existing-token",
            machine_fingerprint="fp-machine-001",
            public_ip="1.2.3.4",
            region="cn-north-1",
            isp="China Telecom",
            tags=[],
            capabilities={},
            config_version=1,
            last_seen_at="2026-03-24T00:00:00Z",
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
        )
        mock_probe_repo.get_probe_by_machine_fingerprint.return_value = existing_probe
        mock_probe_repo.get_latest_probe_config.return_value = ProbeConfigRecord(
            id=1,
            probe_id="probe-existing",
            config_version=1,
            config={"poll_interval_seconds": 5},
            created_at="2026-03-24T00:00:00Z",
        )

        with patch(
            "services.probe_registry_service.ProbeRepo",
            return_value=mock_probe_repo,
        ):
            service = ProbeRegistryService(mock_runtime_context)
            result = service.register_probe(
                bootstrap_token="bootstrap-token-123",
                probe_name="CN-Beijing-1",
                machine_fingerprint="fp-machine-001",
                public_ip="1.2.3.4",
                region="cn-north-1",
                isp="China Telecom",
                tags=None,
                capabilities=None,
            )

        assert result.probe_id == "probe-existing"
        assert result.auth_token == "existing-token"
        mock_probe_repo.create_probe.assert_not_called()

    def test_register_probe_invalid_bootstrap_token_raises_error(
        self, mock_runtime_context, mock_probe_repo
    ):
        """Should raise error when bootstrap token is invalid."""
        with patch(
            "services.probe_registry_service.ProbeRepo",
            return_value=mock_probe_repo,
        ):
            service = ProbeRegistryService(mock_runtime_context)
            with pytest.raises(
                ProbeRegistryServiceError, match="invalid probe bootstrap token"
            ):
                service.register_probe(
                    bootstrap_token="invalid-token",
                    probe_name="CN-Beijing-1",
                    machine_fingerprint="fp-machine-001",
                    public_ip="1.2.3.4",
                    region="cn-north-1",
                    isp="China Telecom",
                    tags=None,
                    capabilities=None,
                )

    def test_register_probe_server_disabled_raises_error(
        self, mock_runtime_context, mock_probe_repo
    ):
        """Should raise error when probe server is disabled."""
        mock_runtime_context.config.app.probe_server_enabled = False

        with patch(
            "services.probe_registry_service.ProbeRepo",
            return_value=mock_probe_repo,
        ):
            service = ProbeRegistryService(mock_runtime_context)
            with pytest.raises(
                ProbeRegistryServiceError,
                match="probe server is disabled by configuration",
            ):
                service.register_probe(
                    bootstrap_token="bootstrap-token-123",
                    probe_name="CN-Beijing-1",
                    machine_fingerprint="fp-machine-001",
                    public_ip="1.2.3.4",
                    region="cn-north-1",
                    isp="China Telecom",
                    tags=None,
                    capabilities=None,
                )

    def test_register_probe_empty_probe_name_raises_error(
        self, mock_runtime_context, mock_probe_repo
    ):
        """Should raise error when probe_name is empty."""
        with patch(
            "services.probe_registry_service.ProbeRepo",
            return_value=mock_probe_repo,
        ):
            service = ProbeRegistryService(mock_runtime_context)
            with pytest.raises(ValueError, match="probe_name must not be empty"):
                service.register_probe(
                    bootstrap_token="bootstrap-token-123",
                    probe_name="   ",
                    machine_fingerprint="fp-machine-001",
                    public_ip="1.2.3.4",
                    region="cn-north-1",
                    isp="China Telecom",
                    tags=None,
                    capabilities=None,
                )

    def test_register_probe_empty_machine_fingerprint_raises_error(
        self, mock_runtime_context, mock_probe_repo
    ):
        """Should raise error when machine_fingerprint is empty."""
        with patch(
            "services.probe_registry_service.ProbeRepo",
            return_value=mock_probe_repo,
        ):
            service = ProbeRegistryService(mock_runtime_context)
            with pytest.raises(ValueError, match="machine_fingerprint must not be empty"):
                service.register_probe(
                    bootstrap_token="bootstrap-token-123",
                    probe_name="CN-Beijing-1",
                    machine_fingerprint="",
                    public_ip="1.2.3.4",
                    region="cn-north-1",
                    isp="China Telecom",
                    tags=None,
                    capabilities=None,
                )


class TestProbeRegistryServiceAuthenticateProbe:
    """Tests for authenticate_probe method."""

    def test_authenticate_probe_success(self, mock_runtime_context, mock_probe_repo):
        """Should authenticate probe successfully with valid credentials."""
        probe_record = ProbeRecord(
            id=1,
            probe_id="probe-001",
            probe_name="CN-Beijing-1",
            status="active",
            auth_token="valid-token",
            machine_fingerprint="fp-001",
            public_ip="1.2.3.4",
            region="cn-north-1",
            isp="China Telecom",
            tags=[],
            capabilities={},
            config_version=1,
            last_seen_at="2026-03-24T00:00:00Z",
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
        )
        mock_probe_repo.get_probe_by_probe_id.return_value = probe_record

        with patch(
            "services.probe_registry_service.ProbeRepo",
            return_value=mock_probe_repo,
        ):
            service = ProbeRegistryService(mock_runtime_context)
            result = service.authenticate_probe(
                probe_id="probe-001", auth_token="valid-token"
            )

        assert result.probe_id == "probe-001"
        assert result.status == "active"

    def test_authenticate_probe_invalid_token_raises_error(
        self, mock_runtime_context, mock_probe_repo
    ):
        """Should raise error when auth token is invalid."""
        probe_record = ProbeRecord(
            id=1,
            probe_id="probe-001",
            probe_name="CN-Beijing-1",
            status="active",
            auth_token="valid-token",
            machine_fingerprint="fp-001",
            public_ip="1.2.3.4",
            region="cn-north-1",
            isp="China Telecom",
            tags=[],
            capabilities={},
            config_version=1,
            last_seen_at="2026-03-24T00:00:00Z",
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
        )
        mock_probe_repo.get_probe_by_probe_id.return_value = probe_record

        with patch(
            "services.probe_registry_service.ProbeRepo",
            return_value=mock_probe_repo,
        ):
            service = ProbeRegistryService(mock_runtime_context)
            with pytest.raises(ProbeRegistryServiceError, match="invalid probe token"):
                service.authenticate_probe(
                    probe_id="probe-001", auth_token="invalid-token"
                )

    def test_authenticate_probe_disabled_probe_raises_error(
        self, mock_runtime_context, mock_probe_repo
    ):
        """Should raise error when probe is disabled."""
        probe_record = ProbeRecord(
            id=1,
            probe_id="probe-001",
            probe_name="CN-Beijing-1",
            status="disabled",
            auth_token="valid-token",
            machine_fingerprint="fp-001",
            public_ip="1.2.3.4",
            region="cn-north-1",
            isp="China Telecom",
            tags=[],
            capabilities={},
            config_version=1,
            last_seen_at="2026-03-24T00:00:00Z",
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
        )
        mock_probe_repo.get_probe_by_probe_id.return_value = probe_record

        with patch(
            "services.probe_registry_service.ProbeRepo",
            return_value=mock_probe_repo,
        ):
            service = ProbeRegistryService(mock_runtime_context)
            with pytest.raises(ProbeRegistryServiceError, match="probe is disabled"):
                service.authenticate_probe(
                    probe_id="probe-001", auth_token="valid-token"
                )


class TestProbeRegistryServiceRecordHeartbeat:
    """Tests for record_heartbeat method."""

    def test_record_heartbeat_success(self, mock_runtime_context, mock_probe_repo):
        """Should record heartbeat and return updated probe."""
        probe_record = ProbeRecord(
            id=1,
            probe_id="probe-001",
            probe_name="CN-Beijing-1",
            status="active",
            auth_token="valid-token",
            machine_fingerprint="fp-001",
            public_ip="1.2.3.4",
            region="cn-north-1",
            isp="China Telecom",
            tags=[],
            capabilities={},
            config_version=1,
            last_seen_at="2026-03-24T00:00:00Z",
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
        )
        updated_probe = ProbeRecord(
            id=1,
            probe_id="probe-001",
            probe_name="CN-Beijing-1",
            status="active",
            auth_token="valid-token",
            machine_fingerprint="fp-001",
            public_ip="1.2.3.5",
            region="cn-north-1",
            isp="China Telecom",
            tags=[],
            capabilities={},
            config_version=1,
            last_seen_at="2026-03-24T00:01:00Z",
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:01:00Z",
        )
        mock_probe_repo.get_probe_by_probe_id.side_effect = [probe_record, updated_probe]

        with patch(
            "services.probe_registry_service.ProbeRepo",
            return_value=mock_probe_repo,
        ):
            service = ProbeRegistryService(mock_runtime_context)
            result_probe, config_version = service.record_heartbeat(
                probe_id="probe-001",
                auth_token="valid-token",
                public_ip="1.2.3.5",
                agent_version="1.0.0",
                capabilities={"http": True},
                runtime_metrics={"cpu": 50},
            )

        assert result_probe.public_ip == "1.2.3.5"
        assert config_version == 1
        mock_probe_repo.record_heartbeat.assert_called_once()


class TestProbeRegistryServiceGetProbeConfig:
    """Tests for get_probe_config method."""

    def test_get_probe_config_existing_config(
        self, mock_runtime_context, mock_probe_repo
    ):
        """Should return existing probe config."""
        probe_record = ProbeRecord(
            id=1,
            probe_id="probe-001",
            probe_name="CN-Beijing-1",
            status="active",
            auth_token="valid-token",
            machine_fingerprint="fp-001",
            public_ip="1.2.3.4",
            region="cn-north-1",
            isp="China Telecom",
            tags=[],
            capabilities={},
            config_version=1,
            last_seen_at="2026-03-24T00:00:00Z",
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
        )
        config_record = ProbeConfigRecord(
            id=1,
            probe_id="probe-001",
            config_version=1,
            config={
                "poll_interval_seconds": 5,
                "probe_timeout_seconds": 10,
            },
            created_at="2026-03-24T00:00:00Z",
        )
        mock_probe_repo.get_probe_by_probe_id.return_value = probe_record
        mock_probe_repo.get_latest_probe_config.return_value = config_record

        with patch(
            "services.probe_registry_service.ProbeRepo",
            return_value=mock_probe_repo,
        ):
            service = ProbeRegistryService(mock_runtime_context)
            result = service.get_probe_config(
                probe_id="probe-001", auth_token="valid-token"
            )

        assert result.config_version == 1
        assert result.config["poll_interval_seconds"] == 5

    def test_get_probe_config_creates_default_when_missing(
        self, mock_runtime_context, mock_probe_repo
    ):
        """Should create default config when none exists."""
        probe_record = ProbeRecord(
            id=1,
            probe_id="probe-001",
            probe_name="CN-Beijing-1",
            status="active",
            auth_token="valid-token",
            machine_fingerprint="fp-001",
            public_ip="1.2.3.4",
            region="cn-north-1",
            isp="China Telecom",
            tags=[],
            capabilities={},
            config_version=1,
            last_seen_at="2026-03-24T00:00:00Z",
            created_at="2026-03-24T00:00:00Z",
            updated_at="2026-03-24T00:00:00Z",
        )
        default_config = ProbeConfigRecord(
            id=1,
            probe_id="probe-001",
            config_version=1,
            config={
                "poll_interval_seconds": 5,
                "probe_timeout_seconds": 10,
                "result_wait_timeout_seconds": 30,
                "allow_http_probe": True,
                "allow_tls_probe": True,
                "allow_udp_probe": False,
            },
            created_at="2026-03-24T00:00:00Z",
        )
        mock_probe_repo.get_probe_by_probe_id.return_value = probe_record
        mock_probe_repo.get_latest_probe_config.return_value = None
        mock_probe_repo.upsert_probe_config.return_value = default_config

        with patch(
            "services.probe_registry_service.ProbeRepo",
            return_value=mock_probe_repo,
        ):
            service = ProbeRegistryService(mock_runtime_context)
            result = service.get_probe_config(
                probe_id="probe-001", auth_token="valid-token"
            )

        assert result.config["allow_http_probe"] is True
        assert result.config["allow_udp_probe"] is False
        mock_probe_repo.upsert_probe_config.assert_called_once()


class TestProbeRegistryServiceListProbes:
    """Tests for list_probes method."""

    def test_list_probes_marks_stale_probes_offline(
        self, mock_runtime_context, mock_probe_repo
    ):
        """Should mark stale probes as offline before listing."""
        mock_probe_repo.list_probes.return_value = [
            ProbeRecord(
                id=1,
                probe_id="probe-001",
                probe_name="CN-Beijing-1",
                status="active",
                auth_token="token-001",
                machine_fingerprint="fp-001",
                public_ip="1.2.3.4",
                region="cn-north-1",
                isp="China Telecom",
                tags=[],
                capabilities={},
                config_version=1,
                last_seen_at="2026-03-24T00:00:00Z",
                created_at="2026-03-24T00:00:00Z",
                updated_at="2026-03-24T00:00:00Z",
            ),
        ]

        with patch(
            "services.probe_registry_service.ProbeRepo",
            return_value=mock_probe_repo,
        ):
            service = ProbeRegistryService(mock_runtime_context)
            probes = service.list_probes()

        assert len(probes) == 1
        mock_probe_repo.mark_stale_probes_offline.assert_called_once_with(
            timeout_seconds=300
        )
