"""
Tests for ProbeRegistryService
"""
from unittest.mock import Mock, patch

import pytest

from services.probe_registry_service import (
    ProbeRegistryService,
    ProbeRegistryServiceError,
    ProbeRegistrationResult,
)
from database.probe_models import ProbeRecord, ProbeConfigRecord


class TestProbeRegistryService:
    """Test ProbeRegistryService"""

    @pytest.fixture
    def mock_runtime_context(self):
        """Create a mock runtime context"""
        context = Mock()
        context.logger = Mock()
        context.logger.getChild.return_value = Mock()
        context.config = Mock()
        context.config.app = Mock()
        context.config.app.probe_server_enabled = True
        context.config.app.probe_bootstrap_tokens = ["valid-token-123"]
        context.config.app.probe_heartbeat_timeout_seconds = 300
        context.config.app.probe_poll_interval_seconds = 10
        context.config.app.sentinel_probe_timeout_seconds = 5
        context.config.app.sentinel_probe_result_wait_timeout_seconds = 30
        return context

    @pytest.fixture
    def mock_repo(self):
        """Create a mock ProbeRepo"""
        return Mock()

    @pytest.fixture
    def service(self, mock_runtime_context, mock_repo):
        """Create a ProbeRegistryService instance"""
        with patch("services.probe_registry_service.ProbeRepo", return_value=mock_repo):
            return ProbeRegistryService(mock_runtime_context)

    def test_init(self, mock_runtime_context, mock_repo):
        """Test ProbeRegistryService initialization"""
        with patch("services.probe_registry_service.ProbeRepo", return_value=mock_repo):
            service = ProbeRegistryService(mock_runtime_context)
            assert service._runtime_context == mock_runtime_context
            assert service._repo == mock_repo

    def test_register_probe_new_probe(self, service, mock_repo):
        """Test register_probe creates a new probe"""
        mock_repo.get_probe_by_machine_fingerprint.return_value = None

        created_probe = Mock()
        created_probe.probe_id = "probe-abc123"
        created_probe.probe_name = "test-probe"
        created_probe.auth_token = "token-xyz"
        created_probe.config_version = 1
        mock_repo.create_probe.return_value = created_probe

        config_record = Mock()
        config_record.config_version = 1
        config_record.config = {"poll_interval_seconds": 10}
        mock_repo.get_latest_probe_config.return_value = None
        mock_repo.upsert_probe_config.return_value = config_record

        result = service.register_probe(
            bootstrap_token="valid-token-123",
            probe_name="test-probe",
            machine_fingerprint="fingerprint-123",
            public_ip="1.2.3.4",
            region="us-east-1",
            isp="AWS",
            tags=["tag1", "tag2"],
            capabilities={"http": True},
        )

        assert isinstance(result, ProbeRegistrationResult)
        assert result.probe_id == "probe-abc123"
        assert result.probe_name == "test-probe"
        assert result.auth_token == "token-xyz"
        assert result.config_version == 1
        mock_repo.create_probe.assert_called_once()

    def test_register_probe_existing_probe(self, service, mock_repo):
        """Test register_probe returns existing probe"""
        existing_probe = Mock()
        existing_probe.probe_id = "probe-existing"
        existing_probe.probe_name = "existing-probe"
        existing_probe.auth_token = "existing-token"
        existing_probe.config_version = 2
        mock_repo.get_probe_by_machine_fingerprint.return_value = existing_probe

        config_record = Mock()
        config_record.config_version = 2
        config_record.config = {"poll_interval_seconds": 10}
        mock_repo.get_latest_probe_config.return_value = config_record

        result = service.register_probe(
            bootstrap_token="valid-token-123",
            probe_name="test-probe",
            machine_fingerprint="fingerprint-123",
            public_ip="1.2.3.4",
            region=None,
            isp=None,
            tags=None,
            capabilities=None,
        )

        assert result.probe_id == "probe-existing"
        assert result.probe_name == "existing-probe"
        mock_repo.create_probe.assert_not_called()

    def test_register_probe_server_disabled(self, service):
        """Test register_probe fails when server is disabled"""
        service._runtime_context.config.app.probe_server_enabled = False

        with pytest.raises(ProbeRegistryServiceError, match="probe server is disabled"):
            service.register_probe(
                bootstrap_token="valid-token-123",
                probe_name="test-probe",
                machine_fingerprint="fingerprint-123",
                public_ip=None,
                region=None,
                isp=None,
                tags=None,
                capabilities=None,
            )

    def test_register_probe_invalid_token(self, service):
        """Test register_probe fails with invalid bootstrap token"""
        with pytest.raises(ProbeRegistryServiceError, match="invalid probe bootstrap token"):
            service.register_probe(
                bootstrap_token="invalid-token",
                probe_name="test-probe",
                machine_fingerprint="fingerprint-123",
                public_ip=None,
                region=None,
                isp=None,
                tags=None,
                capabilities=None,
            )

    def test_register_probe_empty_name(self, service):
        """Test register_probe fails with empty probe name"""
        with pytest.raises(ValueError, match="probe_name must not be empty"):
            service.register_probe(
                bootstrap_token="valid-token-123",
                probe_name="   ",
                machine_fingerprint="fingerprint-123",
                public_ip=None,
                region=None,
                isp=None,
                tags=None,
                capabilities=None,
            )

    def test_register_probe_empty_fingerprint(self, service):
        """Test register_probe fails with empty machine fingerprint"""
        with pytest.raises(ValueError, match="machine_fingerprint must not be empty"):
            service.register_probe(
                bootstrap_token="valid-token-123",
                probe_name="test-probe",
                machine_fingerprint="   ",
                public_ip=None,
                region=None,
                isp=None,
                tags=None,
                capabilities=None,
            )

    def test_authenticate_probe_success(self, service, mock_repo):
        """Test authenticate_probe succeeds with valid credentials"""
        probe_record = Mock()
        probe_record.probe_id = "probe-123"
        probe_record.auth_token = "valid-token"
        probe_record.status = "active"
        mock_repo.get_probe_by_probe_id.return_value = probe_record

        result = service.authenticate_probe(probe_id="probe-123", auth_token="valid-token")

        assert result == probe_record

    def test_authenticate_probe_server_disabled(self, service):
        """Test authenticate_probe fails when server is disabled"""
        service._runtime_context.config.app.probe_server_enabled = False

        with pytest.raises(ProbeRegistryServiceError, match="probe server is disabled"):
            service.authenticate_probe(probe_id="probe-123", auth_token="token")

    def test_authenticate_probe_invalid_token(self, service, mock_repo):
        """Test authenticate_probe fails with invalid token"""
        probe_record = Mock()
        probe_record.auth_token = "correct-token"
        mock_repo.get_probe_by_probe_id.return_value = probe_record

        with pytest.raises(ProbeRegistryServiceError, match="invalid probe token"):
            service.authenticate_probe(probe_id="probe-123", auth_token="wrong-token")

    def test_authenticate_probe_disabled_probe(self, service, mock_repo):
        """Test authenticate_probe fails for disabled probe"""
        probe_record = Mock()
        probe_record.auth_token = "valid-token"
        probe_record.status = "disabled"
        mock_repo.get_probe_by_probe_id.return_value = probe_record

        with pytest.raises(ProbeRegistryServiceError, match="probe is disabled"):
            service.authenticate_probe(probe_id="probe-123", auth_token="valid-token")

    def test_record_heartbeat(self, service, mock_repo):
        """Test record_heartbeat updates probe status"""
        probe_record = Mock()
        probe_record.probe_id = "probe-123"
        probe_record.auth_token = "valid-token"
        probe_record.status = "active"
        probe_record.config_version = 1

        updated_probe = Mock()
        updated_probe.probe_id = "probe-123"
        updated_probe.config_version = 2

        mock_repo.get_probe_by_probe_id.side_effect = [probe_record, updated_probe]

        result_probe, config_version = service.record_heartbeat(
            probe_id="probe-123",
            auth_token="valid-token",
            public_ip="1.2.3.4",
            agent_version="1.0.0",
            capabilities={"http": True},
            runtime_metrics={"cpu": 50},
        )

        assert result_probe == updated_probe
        assert config_version == 2
        mock_repo.record_heartbeat.assert_called_once()

    def test_get_probe_config_existing(self, service, mock_repo):
        """Test get_probe_config returns existing config"""
        probe_record = Mock()
        probe_record.probe_id = "probe-123"
        probe_record.auth_token = "valid-token"
        probe_record.status = "active"
        probe_record.config_version = 1
        mock_repo.get_probe_by_probe_id.return_value = probe_record

        config_record = Mock()
        config_record.config_version = 1
        config_record.config = {"poll_interval_seconds": 10}
        mock_repo.get_latest_probe_config.return_value = config_record

        result = service.get_probe_config(probe_id="probe-123", auth_token="valid-token")

        assert result == config_record

    def test_get_probe_config_create_default(self, service, mock_repo):
        """Test get_probe_config creates default config if none exists"""
        probe_record = Mock()
        probe_record.probe_id = "probe-123"
        probe_record.auth_token = "valid-token"
        probe_record.status = "active"
        probe_record.config_version = 1
        mock_repo.get_probe_by_probe_id.return_value = probe_record

        mock_repo.get_latest_probe_config.return_value = None

        new_config = Mock()
        new_config.config_version = 1
        new_config.config = {"poll_interval_seconds": 10}
        mock_repo.upsert_probe_config.return_value = new_config

        result = service.get_probe_config(probe_id="probe-123", auth_token="valid-token")

        assert result == new_config
        mock_repo.upsert_probe_config.assert_called_once()

    def test_list_probes(self, service, mock_repo):
        """Test list_probes returns all probes"""
        mock_probes = [Mock(), Mock(), Mock()]
        mock_repo.list_probes.return_value = mock_probes

        result = service.list_probes()

        assert len(result) == 3
        mock_repo.mark_stale_probes_offline.assert_called_once_with(timeout_seconds=300)
        mock_repo.list_probes.assert_called_once_with(include_inactive=True)

    def test_ensure_probe_config_existing(self, service, mock_repo):
        """Test _ensure_probe_config returns existing config"""
        config_record = Mock()
        config_record.config_version = 1
        mock_repo.get_latest_probe_config.return_value = config_record

        result = service._ensure_probe_config("probe-123", 1)

        assert result == config_record
        mock_repo.upsert_probe_config.assert_not_called()

    def test_ensure_probe_config_create_new(self, service, mock_repo):
        """Test _ensure_probe_config creates new config"""
        mock_repo.get_latest_probe_config.return_value = None

        new_config = Mock()
        new_config.config_version = 1
        mock_repo.upsert_probe_config.return_value = new_config

        result = service._ensure_probe_config("probe-123", 1)

        assert result == new_config
        mock_repo.upsert_probe_config.assert_called_once()

    def test_build_default_probe_config(self, service):
        """Test _build_default_probe_config returns correct config"""
        config = service._build_default_probe_config()

        assert config["poll_interval_seconds"] == 10
        assert config["probe_timeout_seconds"] == 5
        assert config["result_wait_timeout_seconds"] == 30
        assert config["allow_http_probe"] is True
        assert config["allow_tls_probe"] is True
        assert config["allow_udp_probe"] is False
