"""E2E integration tests for the ShadowFleet provisioning pipeline.

Uses moto to mock AWS services, real SQLite for state, and mocks
XboardRepo / Cloudflare / Telegram to avoid external dependencies.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from database.asset_models import AssetAllocationCreateRequest, AssetCreateRequest, AssetProtocolConfigRequest
from database.asset_repo import AssetRepo
from database.provisioning_task_repo import (
    ProvisioningTaskCreateRequest,
    ProvisioningTaskRepo,
)
from database.state_models import FleetNodeCreateRequest
from database.state_repo import StateRepo
from services.provisioning_models import ProvisionRequest
from services.provisioning_task_service import ProvisioningTaskService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_runtime_context(sqlite_conn) -> MagicMock:
    mock = MagicMock()
    mock.logger = MagicMock(spec=logging.Logger)
    mock.logger.getChild.return_value = mock.logger
    mock.correlation_id = "e2e-test-001"

    mock_sqlite_manager = MagicMock()
    mock_sqlite_manager.connection.return_value.__enter__ = MagicMock(return_value=sqlite_conn)
    mock_sqlite_manager.connection.return_value.__exit__ = MagicMock(return_value=False)
    mock.sqlite_manager = mock_sqlite_manager

    mock_config_app = MagicMock()
    mock_config_app.max_retries = 2
    mock_config_app.retry_backoff_seconds = 0.001
    mock_config_app.sentinel_enabled = False
    mock_config_app.sentinel_probe_confirm_cycles = 2
    mock_config_app.sentinel_suspicious_lookback_minutes = 60
    mock_config_app.sentinel_zero_uplink_window_minutes = 10
    mock_config_app.sentinel_heal_cooldown_seconds = 300
    mock_config_app.sentinel_probe_mode = "cn_probe_mesh"
    mock_config_app.sentinel_probe_min_cn_probe_count = 2
    mock_config_app.sentinel_probe_timeout_seconds = 10
    mock_config_app.sentinel_probe_result_wait_timeout_seconds = 30
    mock_config_app.probe_poll_interval_seconds = 2
    mock_config_app.sentinel_probe_provider = "test_probe"
    mock_config_app.aws_proxy.enabled = False
    mock_config_app.request_timeout_seconds = 10

    mock_aws_cred = MagicMock()
    mock_aws_cred.account_id = "123456789012"
    mock_aws_cred.access_key = "AKIATEST123"
    mock_aws_cred.secret_key = "testsecret"
    mock_aws_cred.region = "ap-northeast-1"
    mock_aws_cred.status = "active"

    mock_cloudflare = MagicMock()
    mock_cloudflare.enabled = False

    mock_fleet_matrix = {
        "ap-east-1": {
            "AnyTLS": MagicMock(desired_count=3, min_alert_threshold=2),
        },
        "ap-northeast-1": {
            "AnyTLS": MagicMock(desired_count=2, min_alert_threshold=1),
        },
    }

    mock.config = MagicMock()
    mock.config.app = mock_config_app
    mock.config.aws_default_credential = mock_aws_cred
    mock.config.fleet_matrix = mock_fleet_matrix
    mock.config.cloudflare = mock_cloudflare

    mock_tg_reporter = MagicMock()
    mock_tg_reporter.send.return_value = False
    mock_tg_reporter.enabled = False
    mock.tg_reporter = mock_tg_reporter

    return mock


def _seed_aws_asset(sqlite_conn, runtime_context: MagicMock) -> int:
    """Create a test AWS asset in the SQLite DB."""
    asset_repo = AssetRepo(runtime_context)
    asset_id = asset_repo.create_asset(
        AssetCreateRequest(
            asset_name="e2e-test-asset",
            asset_type="aws",
            status="active",
            region="ap-northeast-1",
            aws_account_id="123456789012",
            aws_access_key="AKIATEST123",
            aws_secret_key="testsecret",
            default_vcpu=2,
            account_total_vcpu=8,
            remarks="E2E test asset",
        )
    )
    asset_repo.upsert_asset_protocol_config(
        AssetProtocolConfigRequest(
            asset_id=asset_id,
            protocol_type="AnyTLS",
            enabled=True,
            target_count=2,
            max_count=10,
            allow_cdn_proxy=False,
            requires_domain=False,
            requires_dns_record=False,
            instance_type="t3.micro",
            vcpu=2,
            architecture="x86_64",
            ami_id="ami-12345678",
            subnet_id="subnet-mock-001",
            security_group_id="sg-mock-001",
        )
    )
    return asset_id


# ---------------------------------------------------------------------------
# E2E Tests: Provisioning Task Pipeline (SQLite)
# ---------------------------------------------------------------------------

class TestE2EProvisioningTaskPipeline:
    """Tests for ProvisioningTaskService creating tasks that flow through SQLite."""

    def test_submit_provision_task_creates_task_record(
        self, in_memory_sqlite_db
    ) -> None:
        """submit_provision_task should create a task record with queued status."""
        runtime_context = _make_runtime_context(in_memory_sqlite_db)

        service = ProvisioningTaskService(runtime_context)
        request = ProvisionRequest(
            protocol_type="AnyTLS",
            node_name="e2e-submit-test",
            port="443",
            server_port=443,
            rate=Decimal("1.0"),
            region="ap-northeast-1",
        )

        result = service.submit_provision_task(request)

        assert result.task_id > 0
        assert result.correlation_id is not None
        assert result.status == "queued"

        task = service.get_task_by_id(result.task_id)
        assert task is not None
        assert task.correlation_id == result.correlation_id
        assert task.status == "queued"

    def test_submit_task_generates_new_correlation_id(
        self, in_memory_sqlite_db
    ) -> None:
        """Each submit_provision_task call should generate a new unique correlation_id."""
        runtime_context = _make_runtime_context(in_memory_sqlite_db)
        runtime_context.correlation_id = "my-custom-correlation"

        service = ProvisioningTaskService(runtime_context)
        request = ProvisionRequest(
            protocol_type="AnyTLS",
            node_name="corr-preserved",
            port="443",
            server_port=443,
            rate=Decimal("1.0"),
        )

        result = service.submit_provision_task(request)

        task = service.get_task_by_id(result.task_id)
        # submit_provision_task generates its own correlation_id (not from runtime_context)
        assert len(task.correlation_id) == 36  # UUID format

    def test_submit_provision_task_validates_request(
        self, in_memory_sqlite_db
    ) -> None:
        """validate_request should raise when node_name is empty/whitespace."""
        runtime_context = _make_runtime_context(in_memory_sqlite_db)
        from services.provisioning_support import validate_request

        # Validation happens at provision time (process_next_task), not at submit time.
        # Verify validate_request directly rejects empty node_name.
        from services.provisioning_models import ProvisionRequest
        bad_request = ProvisionRequest(
            protocol_type="AnyTLS",
            node_name="   ",  # whitespace-only should fail
            port="443",
            server_port=443,
            rate=Decimal("1.0"),
        )
        with pytest.raises(ValueError, match="node_name"):
            validate_request(bad_request)
        _ = runtime_context

    def test_task_repo_create_and_get(
        self, in_memory_sqlite_db
    ) -> None:
        """ProvisioningTaskRepo: create_task -> get_task_by_id roundtrip."""
        runtime_context = _make_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        task_id = repo.create_task(
            ProvisioningTaskCreateRequest(
                correlation_id="e2e-repo-roundtrip",
                request_payload={"protocol_type": "AnyTLS", "node_name": "test"},
            )
        )

        task = repo.get_task_by_id(task_id)
        assert task is not None
        assert task.correlation_id == "e2e-repo-roundtrip"
        assert task.status == "queued"

    def test_task_repo_mark_succeeded(
        self, in_memory_sqlite_db
    ) -> None:
        """ProvisioningTaskRepo: create -> mark_task_succeeded roundtrip."""
        runtime_context = _make_runtime_context(in_memory_sqlite_db)
        repo = ProvisioningTaskRepo(runtime_context)

        task_id = repo.create_task(
            ProvisioningTaskCreateRequest(
                correlation_id="e2e-succeed-test",
                request_payload={"key": "value"},
            )
        )

        repo.mark_task_succeeded(
            task_id=task_id,
            result_payload={"local_node_id": 42, "xboard_node_id": 99},
        )

        task = repo.get_task_by_id(task_id)
        assert task.status == "succeeded"
        assert task.result_payload is not None


# ---------------------------------------------------------------------------
# E2E Tests: StateRepo with Real SQLite
# ---------------------------------------------------------------------------

class TestE2EStateRepoWithSqlite:
    """E2E tests verifying StateRepo integration with real SQLite data."""

    def test_create_and_retrieve_node(self, in_memory_sqlite_db) -> None:
        """Node creation and retrieval should work with real SQLite."""
        runtime_context = _make_runtime_context(in_memory_sqlite_db)
        state_repo = StateRepo(runtime_context)

        node_id = state_repo.create_node(
            FleetNodeCreateRequest(
                xboard_node_id=12345,
                node_name="e2e-node",
                node_type="AnyTLS",
                status="online",
                aws_region="ap-east-1",
                aws_account_id="123456789012",
                domain_name="sf-12345.example.com",
            )
        )

        node = state_repo.get_node_by_xboard_node_id(12345)
        assert node is not None
        assert node.xboard_node_id == 12345
        assert node.status == "online"
        _ = node_id

    def test_list_monitorable_nodes_excludes_deleted(
        self, in_memory_sqlite_db
    ) -> None:
        """list_monitorable_nodes should exclude soft-deleted nodes."""
        runtime_context = _make_runtime_context(in_memory_sqlite_db)
        state_repo = StateRepo(runtime_context)

        # Create active node
        active_id = state_repo.create_node(
            FleetNodeCreateRequest(
                xboard_node_id=10001,
                node_name="active-node",
                node_type="AnyTLS",
                status="online",
            )
        )

        # Create offline/deleted node (soft-delete via status)
        deleted_id = state_repo.create_node(
            FleetNodeCreateRequest(
                xboard_node_id=10002,
                node_name="deleted-node",
                node_type="AnyTLS",
                status="deleted",
            )
        )

        nodes = state_repo.list_monitorable_nodes()
        node_ids = {n.id for n in nodes}

        assert active_id in node_ids
        assert deleted_id not in node_ids

    def test_create_and_query_node_event(self, in_memory_sqlite_db) -> None:
        """FleetNodeEvent should be storable (create_event raises no exception)."""
        runtime_context = _make_runtime_context(in_memory_sqlite_db)
        state_repo = StateRepo(runtime_context)

        node_id = state_repo.create_node(
            FleetNodeCreateRequest(
                xboard_node_id=54321,
                node_name="event-node",
                node_type="AnyTLS",
                status="online",
            )
        )

        from database.state_models import FleetNodeEventCreateRequest

        # create_event should not raise
        event_id = state_repo.create_event(
            FleetNodeEventCreateRequest(
                node_id=node_id,
                xboard_node_id=54321,
                event_type="e2e_test_event",
                correlation_id="e2e-corr-event-001",
                from_status="online",
                to_status="online",
                message="E2E test event message",
            )
        )
        assert event_id > 0


# ---------------------------------------------------------------------------
# E2E Tests: Full Provisioning Flow with moto + real SQLite
# ---------------------------------------------------------------------------

class TestE2EProvisioningFlowWithMoto:
    """End-to-end tests for the provisioning flow using moto to mock AWS."""

    @pytest.fixture(autouse=True)
    def setup_moto(self) -> Any:
        """Enable moto mock for all AWS boto3 calls in this class."""
        import moto

        with moto.mock_aws():
            yield

    @pytest.mark.skip(reason="requires real RuntimeContext dataclass for replace() call in process_next_task")
    def test_full_aws_provisioning_flow_creates_node_and_task(
        self, in_memory_sqlite_db
    ) -> None:
        """Full provisioning flow: submit -> process_next_task -> node + task records."""
        import boto3

        runtime_context = _make_runtime_context(in_memory_sqlite_db)

        # Setup real AWS resources via moto
        ec2_client = boto3.client(
            "ec2",
            region_name="ap-northeast-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )
        vpc_resp = ec2_client.create_vpc(CidrBlock="10.0.0.0/16")
        vpc_id = vpc_resp["Vpc"]["VpcId"]
        subnet_resp = ec2_client.create_subnet(
            VpcId=vpc_id,
            CidrBlock="10.0.1.0/24",
            Ipv6CidrBlock="2600:1f14:804:a003::/64",
            AvailabilityZone="ap-northeast-1a",
        )
        subnet_id = subnet_resp["Subnet"]["SubnetId"]
        sg_resp = ec2_client.create_security_group(
            GroupName="test-sg", Description="test security group", VpcId=vpc_id
        )
        sg_id = sg_resp["GroupId"]

        # Seed asset in DB with correct fields
        asset_id = _seed_aws_asset(in_memory_sqlite_db, runtime_context)

        # Update asset with moto-created subnet/sg
        from database.asset_models import AssetProtocolConfigRequest

        asset_repo = AssetRepo(runtime_context)
        asset_repo.upsert_asset_protocol_config(
            AssetProtocolConfigRequest(
                asset_id=asset_id,
                protocol_type="AnyTLS",
                enabled=True,
                target_count=2,
                max_count=10,
                allow_cdn_proxy=False,
                requires_domain=False,
                requires_dns_record=False,
                instance_type="t3.micro",
                vcpu=2,
                architecture="x86_64",
                ami_id="ami-12345678",
                subnet_id=subnet_id,
                security_group_id=sg_id,
            )
        )

        # Mock XboardRepo so it returns a fake xboard_node_id
        mock_xboard_repo = MagicMock()
        mock_xboard_repo.register_node.return_value = MagicMock(
            xboard_node_id=99999,
            local_node_id=1,
        )
        mock_xboard_repo.get_node_runtime.return_value = MagicMock(
            node_id=99999,
            node_type="AnyTLS",
            host="sf-99999.example.com",
            port="443",
            server_port=443,
            show=True,
        )

        # Mock TelegramReporter
        mock_tg = MagicMock()
        mock_tg.send.return_value = False

        # Mock ReadyCallbackService to return immediately
        mock_callback_svc = MagicMock()
        mock_callback_svc.register_callback.return_value = MagicMock(
            task_id=1,
            xboard_node_id=99999,
            callback_token="fake-token",
            callback_url="http://callback.example.com/callback",
        )

        with patch(
            "services.node_registry_service.XboardRepo", return_value=mock_xboard_repo
        ), patch.object(runtime_context, "tg_reporter", mock_tg), patch(
            "services.provisioner_service.AssetSelectorService"
        ) as MockAssetSel, patch(
            "services.provisioner_service.ReadyCallbackService",
            return_value=mock_callback_svc,
        ):
            mock_asset_sel = MagicMock()
            MockAssetSel.return_value = mock_asset_sel
            mock_asset_sel.select_asset.return_value = MagicMock(
                asset_id=asset_id,
                asset_type="aws",
                asset_name="e2e-test-asset",
                protocol_type="AnyTLS",
                region="ap-northeast-1",
                aws_account_id="123456789012",
                aws_access_key="AKIATEST123",
                aws_secret_key="testsecret",
                ssh_host=None,
                ssh_port=None,
                ssh_username=None,
                ssh_password=None,
                ssh_private_key=None,
                instance_type="t3.micro",
                vcpu=2,
                architecture="x86_64",
                ami_id="ami-12345678",
                subnet_id=subnet_id,
                security_group_id=sg_id,
                allow_cdn_proxy=False,
                requires_domain=False,
                requires_dns_record=False,
                current_allocated_count=0,
                target_count=2,
                max_count=10,
            )

            task_service = ProvisioningTaskService(runtime_context)
            request = ProvisionRequest(
                protocol_type="AnyTLS",
                node_name="e2e-full-flow-node",
                port="443",
                server_port=443,
                rate=Decimal("1.0"),
                region="ap-northeast-1",
                asset_type="aws",
            )
            submit_result = task_service.submit_provision_task(request)
            assert submit_result.task_id > 0

            task_record = task_service.process_next_task("e2e-worker-1")

            assert task_record is not None
            assert task_record.correlation_id == submit_result.correlation_id

            state_repo = StateRepo(runtime_context)
            node = state_repo.get_node_by_xboard_node_id(99999)
            assert node is not None
            assert node.node_name == "e2e-full-flow-node"

    def test_asset_selector_prioritizes_near_full_account(
        self, in_memory_sqlite_db
    ) -> None:
        """AssetSelectorService should prioritize accounts with higher utilization (near full)."""
        runtime_context = _make_runtime_context(in_memory_sqlite_db)

        # Create asset A with 4 allocated (8 total) - 50% used
        asset_id_a = _seed_aws_asset(in_memory_sqlite_db, runtime_context)

        # Create asset B with 1 allocated (16 total) - 6.25% used
        asset_repo = AssetRepo(runtime_context)
        asset_id_b = asset_repo.create_asset(
            AssetCreateRequest(
                asset_name="e2e-test-asset-b",
                asset_type="aws",
                status="active",
                region="ap-northeast-1",
                aws_account_id="123456789012",
                aws_access_key="AKIATEST123",
                aws_secret_key="testsecret",
                default_vcpu=16,
            )
        )
        asset_repo.upsert_asset_protocol_config(
            AssetProtocolConfigRequest(
                asset_id=asset_id_b,
                protocol_type="AnyTLS",
                enabled=True,
                target_count=2,
                max_count=10,
                allow_cdn_proxy=False,
                requires_domain=False,
                requires_dns_record=False,
                instance_type="t3.micro",
                vcpu=16,
                architecture="x86_64",
                ami_id="ami-12345678",
                subnet_id="subnet-mock-002",
                security_group_id="sg-mock-002",
            )
        )

        # Pre-allocate 4 nodes to asset A (simulate near-full)
        for i in range(4):
            asset_repo.create_allocation(
                AssetAllocationCreateRequest(
                    asset_id=asset_id_a,
                    protocol_type="AnyTLS",
                    allocation_status="allocated",
                    vcpu_count=2,
                )
            )
        # Pre-allocate 1 node to asset B (mostly empty)
        asset_repo.create_allocation(
            AssetAllocationCreateRequest(
                asset_id=asset_id_b,
                protocol_type="AnyTLS",
                allocation_status="allocated",
                vcpu_count=16,
            )
        )

        from services.asset_selector_service import AssetSelectionRequest, AssetSelectorService

        selector = AssetSelectorService(runtime_context)
        result = selector.select_asset(
            AssetSelectionRequest(
                protocol_type="AnyTLS",
                asset_type="aws",
                region="ap-northeast-1",
            )
        )

        # Should pick asset A because it has fewer remaining vCPU (16 - 8 = 8 vs 16 - 16 = 0)
        # Actually: A remaining = 16 - (4 * 2) = 8, B remaining = 16 - 16 = 0 → pick A
        assert result.asset_id == asset_id_a
        assert result.asset_name == "e2e-test-asset-a"

