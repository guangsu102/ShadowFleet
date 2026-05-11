"""
Tests for XboardSyncService
"""
from unittest.mock import MagicMock, patch

import pytest

from services.xboard_sync_service import XboardSyncService


@pytest.fixture
def mock_runtime_context():
    """Create a mock runtime context"""
    context = MagicMock()
    context.logger = MagicMock()
    context.logger.getChild.return_value = MagicMock()
    return context


@pytest.fixture
def service(mock_runtime_context):
    """Create XboardSyncService instance"""
    with patch('services.xboard_sync_service.StateRepo'), \
         patch('services.xboard_sync_service.XboardSentinelClient'):
        return XboardSyncService(mock_runtime_context)


class TestXboardSyncService:
    """Tests for XboardSyncService"""

    def test_init(self, mock_runtime_context):
        """Test service initialization"""
        with patch('services.xboard_sync_service.StateRepo') as mock_state_repo, \
             patch('services.xboard_sync_service.XboardSentinelClient') as mock_sentinel:
            service = XboardSyncService(mock_runtime_context)

            assert service._runtime_context == mock_runtime_context
            mock_runtime_context.logger.getChild.assert_called_once_with("services.xboard_sync_service")
            mock_state_repo.assert_called_once_with(mock_runtime_context)
            mock_sentinel.assert_called_once_with(mock_runtime_context)

    def test_sync_all_nodes_success(self, service):
        """Test syncing all nodes successfully"""
        # Setup mock server list
        mock_server1 = MagicMock()
        mock_server1.id = 1
        mock_server1.is_online = 1
        mock_server1.show = 1

        mock_server2 = MagicMock()
        mock_server2.id = 2
        mock_server2.is_online = 0
        mock_server2.show = 1

        mock_server_list = MagicMock()
        mock_server_list.servers = [mock_server1, mock_server2]

        service._sentinel_client.get_server_list.return_value = mock_server_list

        # Execute
        success_count, failed_count = service.sync_all_nodes()

        # Verify
        assert success_count == 2
        assert failed_count == 0
        service._sentinel_client.get_server_list.assert_called_once()
        assert service._state_repo.update_node_xboard_status.call_count == 2

    def test_sync_all_nodes_fetch_failure(self, service):
        """Test syncing fails when fetching server list fails"""
        service._sentinel_client.get_server_list.side_effect = Exception("API error")

        # Execute
        success_count, failed_count = service.sync_all_nodes()

        # Verify
        assert success_count == 0
        assert failed_count == 0
        service._state_repo.update_node_xboard_status.assert_not_called()

    def test_sync_all_nodes_partial_failure(self, service):
        """Test syncing with some nodes failing"""
        # Setup mock server list
        mock_server1 = MagicMock()
        mock_server1.id = 1
        mock_server1.is_online = 1
        mock_server1.show = 1

        mock_server2 = MagicMock()
        mock_server2.id = 2
        mock_server2.is_online = 0
        mock_server2.show = 1

        mock_server_list = MagicMock()
        mock_server_list.servers = [mock_server1, mock_server2]

        service._sentinel_client.get_server_list.return_value = mock_server_list

        # Make second sync fail
        def side_effect(server):
            if server.id == 2:
                raise Exception("Sync error")
            service._state_repo.update_node_xboard_status(
                xboard_node_id=server.id,
                xboard_status="online" if server.is_online == 1 else "offline",
                xboard_show=server.show,
                xboard_updated_at=MagicMock()
            )

        service._sync_single_node = MagicMock(side_effect=side_effect)

        # Execute
        success_count, failed_count = service.sync_all_nodes()

        # Verify
        assert success_count == 1
        assert failed_count == 1

    def test_sync_single_node_online(self, service):
        """Test syncing a single online node"""
        mock_server = MagicMock()
        mock_server.id = 123
        mock_server.is_online = 1
        mock_server.show = 1

        # Execute
        service._sync_single_node(mock_server)

        # Verify
        service._state_repo.update_node_xboard_status.assert_called_once()
        call_args = service._state_repo.update_node_xboard_status.call_args
        assert call_args[1]["xboard_node_id"] == 123
        assert call_args[1]["xboard_status"] == "online"
        assert call_args[1]["xboard_show"] == 1

    def test_sync_single_node_offline(self, service):
        """Test syncing a single offline node"""
        mock_server = MagicMock()
        mock_server.id = 456
        mock_server.is_online = 0
        mock_server.show = 1

        # Execute
        service._sync_single_node(mock_server)

        # Verify
        service._state_repo.update_node_xboard_status.assert_called_once()
        call_args = service._state_repo.update_node_xboard_status.call_args
        assert call_args[1]["xboard_node_id"] == 456
        assert call_args[1]["xboard_status"] == "offline"
        assert call_args[1]["xboard_show"] == 1

    def test_sync_single_node_hidden(self, service):
        """Test syncing a hidden node"""
        mock_server = MagicMock()
        mock_server.id = 789
        mock_server.is_online = 1
        mock_server.show = 0

        # Execute
        service._sync_single_node(mock_server)

        # Verify
        service._state_repo.update_node_xboard_status.assert_called_once()
        call_args = service._state_repo.update_node_xboard_status.call_args
        assert call_args[1]["xboard_node_id"] == 789
        assert call_args[1]["xboard_status"] == "hidden"
        assert call_args[1]["xboard_show"] == 0

    def test_sync_all_nodes_empty_list(self, service):
        """Test syncing with empty server list"""
        mock_server_list = MagicMock()
        mock_server_list.servers = []

        service._sentinel_client.get_server_list.return_value = mock_server_list

        # Execute
        success_count, failed_count = service.sync_all_nodes()

        # Verify
        assert success_count == 0
        assert failed_count == 0
        service._state_repo.update_node_xboard_status.assert_not_called()

    def test_sync_all_nodes_large_list(self, service):
        """Test syncing with large server list"""
        # Create 100 mock servers
        mock_servers = []
        for i in range(100):
            mock_server = MagicMock()
            mock_server.id = i
            mock_server.is_online = i % 2  # Alternate online/offline
            mock_server.show = 1
            mock_servers.append(mock_server)

        mock_server_list = MagicMock()
        mock_server_list.servers = mock_servers

        service._sentinel_client.get_server_list.return_value = mock_server_list

        # Execute
        success_count, failed_count = service.sync_all_nodes()

        # Verify
        assert success_count == 100
        assert failed_count == 0
        assert service._state_repo.update_node_xboard_status.call_count == 100

    def test_sync_single_node_updates_timestamp(self, service):
        """Test that sync updates the timestamp"""
        mock_server = MagicMock()
        mock_server.id = 999
        mock_server.is_online = 1
        mock_server.show = 1

        # Execute
        service._sync_single_node(mock_server)

        # Verify timestamp is set
        call_args = service._state_repo.update_node_xboard_status.call_args
        assert "xboard_updated_at" in call_args[1]
        assert call_args[1]["xboard_updated_at"] is not None

    def test_sync_all_nodes_continues_on_error(self, service):
        """Test that sync continues processing after individual node errors"""
        # Setup mock server list
        mock_servers = []
        for i in range(5):
            mock_server = MagicMock()
            mock_server.id = i
            mock_server.is_online = 1
            mock_server.show = 1
            mock_servers.append(mock_server)

        mock_server_list = MagicMock()
        mock_server_list.servers = mock_servers

        service._sentinel_client.get_server_list.return_value = mock_server_list

        # Make nodes 1 and 3 fail
        call_count = [0]
        def side_effect(*args, **kwargs):
            node_id = kwargs.get("xboard_node_id")
            if node_id in [1, 3]:
                raise Exception("Database error")
            call_count[0] += 1

        service._state_repo.update_node_xboard_status.side_effect = side_effect

        # Execute
        success_count, failed_count = service.sync_all_nodes()

        # Verify - should process all 5, with 2 failures
        assert success_count == 3
        assert failed_count == 2
        assert service._state_repo.update_node_xboard_status.call_count == 5

    def test_sync_single_node_status_mapping(self, service):
        """Test correct status mapping for different server states"""
        test_cases = [
            # (is_online, show, expected_status)
            (1, 1, "online"),
            (0, 1, "offline"),
            (1, 0, "hidden"),
            (0, 0, "hidden"),
        ]

        for is_online, show, expected_status in test_cases:
            service._state_repo.update_node_xboard_status.reset_mock()

            mock_server = MagicMock()
            mock_server.id = 1
            mock_server.is_online = is_online
            mock_server.show = show

            service._sync_single_node(mock_server)

            call_args = service._state_repo.update_node_xboard_status.call_args
            assert call_args[1]["xboard_status"] == expected_status, \
                f"Failed for is_online={is_online}, show={show}"
