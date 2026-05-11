"""
Tests for ProbeCommandService
"""
from unittest.mock import Mock, patch

import pytest

from services.probe_command_service import (
    ProbeCommandService,
    ProbeCommandServiceError,
    ProbeCommandSubmitResult,
)
from database.probe_models import ProbeCommandRecord


class TestProbeCommandService:
    """Test ProbeCommandService"""

    @pytest.fixture
    def mock_runtime_context(self):
        """Create a mock runtime context"""
        context = Mock()
        context.logger = Mock()
        context.logger.getChild.return_value = Mock()
        context.config = Mock()
        context.config.app = Mock()
        context.config.app.max_retries = 3
        return context

    @pytest.fixture
    def mock_command_repo(self):
        """Create a mock ProbeCommandRepo"""
        return Mock()

    @pytest.fixture
    def mock_registry_service(self):
        """Create a mock ProbeRegistryService"""
        return Mock()

    @pytest.fixture
    def mock_measurement_service(self):
        """Create a mock ProbeMeasurementService"""
        return Mock()

    @pytest.fixture
    def service(self, mock_runtime_context, mock_command_repo, mock_registry_service, mock_measurement_service):
        """Create a ProbeCommandService instance"""
        with patch("services.probe_command_service.ProbeCommandRepo", return_value=mock_command_repo), \
             patch("services.probe_command_service.ProbeRegistryService", return_value=mock_registry_service), \
             patch("services.probe_command_service.ProbeMeasurementService", return_value=mock_measurement_service):
            return ProbeCommandService(mock_runtime_context)

    def test_init(self, mock_runtime_context, mock_command_repo):
        """Test ProbeCommandService initialization"""
        with patch("services.probe_command_service.ProbeCommandRepo", return_value=mock_command_repo), \
             patch("services.probe_command_service.ProbeRegistryService"), \
             patch("services.probe_command_service.ProbeMeasurementService"):
            service = ProbeCommandService(mock_runtime_context)
            assert service._runtime_context == mock_runtime_context
            assert service._command_repo == mock_command_repo

    def test_enqueue_command(self, service, mock_command_repo):
        """Test enqueue_command creates a command"""
        command_record = Mock()
        command_record.command_id = "cmd-123"
        command_record.status = "pending"
        mock_command_repo.create_command.return_value = command_record

        result = service.enqueue_command(
            probe_id="probe-1",
            command_type="run_connectivity_probe",
            payload={"measurement_id": "m-123"},
            correlation_id="corr-123",
        )

        assert isinstance(result, ProbeCommandSubmitResult)
        assert result.command_id == "cmd-123"
        assert result.status == "pending"
        mock_command_repo.create_command.assert_called_once()
        call_args = mock_command_repo.create_command.call_args[0][0]
        assert call_args.probe_id == "probe-1"
        assert call_args.command_type == "run_connectivity_probe"
        assert call_args.max_attempts == 4

    def test_enqueue_command_custom_max_attempts(self, service, mock_command_repo):
        """Test enqueue_command with custom max_attempts"""
        command_record = Mock()
        command_record.command_id = "cmd-123"
        command_record.status = "pending"
        mock_command_repo.create_command.return_value = command_record

        result = service.enqueue_command(
            probe_id="probe-1",
            command_type="run_connectivity_probe",
            payload={},
            correlation_id="corr-123",
            max_attempts=10,
        )

        call_args = mock_command_repo.create_command.call_args[0][0]
        assert call_args.max_attempts == 10

    def test_poll_commands(self, service, mock_command_repo, mock_registry_service):
        """Test poll_commands returns claimed commands"""
        mock_probe = Mock()
        mock_registry_service.authenticate_probe.return_value = mock_probe

        mock_commands = [Mock(), Mock()]
        mock_command_repo.claim_commands.return_value = mock_commands

        result = service.poll_commands(
            probe_id="probe-1",
            auth_token="token-123",
            lease_owner="worker-1",
            max_commands=5,
        )

        assert len(result) == 2
        mock_registry_service.authenticate_probe.assert_called_once_with(
            probe_id="probe-1",
            auth_token="token-123",
        )
        mock_command_repo.claim_commands.assert_called_once_with(
            probe_id="probe-1",
            lease_owner="worker-1",
            limit=5,
        )

    def test_submit_command_result_succeeded(self, service, mock_command_repo, mock_registry_service, mock_measurement_service):
        """Test submit_command_result with succeeded status"""
        mock_probe = Mock()
        mock_registry_service.authenticate_probe.return_value = mock_probe

        command_record = Mock()
        command_record.command_id = "cmd-123"
        command_record.probe_id = "probe-1"
        command_record.command_type = "run_connectivity_probe"
        mock_command_repo.get_command_by_command_id.return_value = command_record

        updated_record = Mock()
        mock_command_repo.mark_command_succeeded.return_value = updated_record

        result_payload = {
            "measurement_id": "m-123",
            "status": "reachable",
            "latency_ms": 50,
        }

        result = service.submit_command_result(
            probe_id="probe-1",
            auth_token="token-123",
            command_id="cmd-123",
            status="succeeded",
            result_payload=result_payload,
            last_error=None,
        )

        assert result == updated_record
        mock_command_repo.mark_command_succeeded.assert_called_once_with(
            command_id="cmd-123",
            result=result_payload,
        )
        mock_measurement_service.record_remote_result.assert_called_once_with(
            measurement_id="m-123",
            probe_id="probe-1",
            result_payload=result_payload,
        )

    def test_submit_command_result_succeeded_no_measurement(self, service, mock_command_repo, mock_registry_service, mock_measurement_service):
        """Test submit_command_result succeeded without measurement_id"""
        mock_probe = Mock()
        mock_registry_service.authenticate_probe.return_value = mock_probe

        command_record = Mock()
        command_record.command_id = "cmd-123"
        command_record.probe_id = "probe-1"
        command_record.command_type = "run_connectivity_probe"
        mock_command_repo.get_command_by_command_id.return_value = command_record

        updated_record = Mock()
        mock_command_repo.mark_command_succeeded.return_value = updated_record

        result_payload = {
            "status": "reachable",
        }

        result = service.submit_command_result(
            probe_id="probe-1",
            auth_token="token-123",
            command_id="cmd-123",
            status="succeeded",
            result_payload=result_payload,
            last_error=None,
        )

        assert result == updated_record
        mock_measurement_service.record_remote_result.assert_not_called()

    def test_submit_command_result_succeeded_non_probe_command(self, service, mock_command_repo, mock_registry_service, mock_measurement_service):
        """Test submit_command_result succeeded for non-probe command"""
        mock_probe = Mock()
        mock_registry_service.authenticate_probe.return_value = mock_probe

        command_record = Mock()
        command_record.command_id = "cmd-123"
        command_record.probe_id = "probe-1"
        command_record.command_type = "other_command"
        mock_command_repo.get_command_by_command_id.return_value = command_record

        updated_record = Mock()
        mock_command_repo.mark_command_succeeded.return_value = updated_record

        result = service.submit_command_result(
            probe_id="probe-1",
            auth_token="token-123",
            command_id="cmd-123",
            status="succeeded",
            result_payload={"data": "value"},
            last_error=None,
        )

        assert result == updated_record
        mock_measurement_service.record_remote_result.assert_not_called()

    def test_submit_command_result_failed(self, service, mock_command_repo, mock_registry_service):
        """Test submit_command_result with failed status"""
        mock_probe = Mock()
        mock_registry_service.authenticate_probe.return_value = mock_probe

        command_record = Mock()
        command_record.command_id = "cmd-123"
        command_record.probe_id = "probe-1"
        command_record.command_type = "run_connectivity_probe"
        mock_command_repo.get_command_by_command_id.return_value = command_record

        updated_record = Mock()
        mock_command_repo.mark_command_failed.return_value = updated_record

        result = service.submit_command_result(
            probe_id="probe-1",
            auth_token="token-123",
            command_id="cmd-123",
            status="failed",
            result_payload=None,
            last_error="Connection timeout",
        )

        assert result == updated_record
        mock_command_repo.mark_command_failed.assert_called_once_with(
            command_id="cmd-123",
            last_error="Connection timeout",
        )

    def test_submit_command_result_failed_no_error(self, service, mock_command_repo, mock_registry_service):
        """Test submit_command_result failed with no error message"""
        mock_probe = Mock()
        mock_registry_service.authenticate_probe.return_value = mock_probe

        command_record = Mock()
        command_record.command_id = "cmd-123"
        command_record.probe_id = "probe-1"
        mock_command_repo.get_command_by_command_id.return_value = command_record

        updated_record = Mock()
        mock_command_repo.mark_command_failed.return_value = updated_record

        result = service.submit_command_result(
            probe_id="probe-1",
            auth_token="token-123",
            command_id="cmd-123",
            status="failed",
            result_payload=None,
            last_error=None,
        )

        mock_command_repo.mark_command_failed.assert_called_once_with(
            command_id="cmd-123",
            last_error="probe command failed",
        )

    def test_submit_command_result_wrong_probe(self, service, mock_command_repo, mock_registry_service):
        """Test submit_command_result fails when command belongs to different probe"""
        mock_probe = Mock()
        mock_registry_service.authenticate_probe.return_value = mock_probe

        command_record = Mock()
        command_record.command_id = "cmd-123"
        command_record.probe_id = "probe-2"
        mock_command_repo.get_command_by_command_id.return_value = command_record

        with pytest.raises(ProbeCommandServiceError, match="command does not belong to probe"):
            service.submit_command_result(
                probe_id="probe-1",
                auth_token="token-123",
                command_id="cmd-123",
                status="succeeded",
                result_payload={},
                last_error=None,
            )

    def test_list_recent_commands(self, service, mock_command_repo):
        """Test list_recent_commands returns command records"""
        mock_commands = [Mock(), Mock(), Mock()]
        mock_command_repo.list_recent_commands.return_value = mock_commands

        result = service.list_recent_commands(limit=20)

        assert len(result) == 3
        mock_command_repo.list_recent_commands.assert_called_once_with(limit=20)

    def test_list_recent_commands_default_limit(self, service, mock_command_repo):
        """Test list_recent_commands with default limit"""
        mock_commands = [Mock()]
        mock_command_repo.list_recent_commands.return_value = mock_commands

        result = service.list_recent_commands()

        mock_command_repo.list_recent_commands.assert_called_once_with(limit=20)
