#!/usr/bin/env python3
"""
测试账号弃尸后的自动补充功能
"""
import pytest
import sys
sys.path.insert(0, ".")

from unittest.mock import MagicMock, patch

from services.account_abandonment_service import AccountAbandonmentService


@pytest.fixture
def mock_runtime():
    """创建模拟的 RuntimeContext"""
    mock_config = MagicMock()
    mock_config.fleet_matrix = {
        "ap-northeast-1": {
            "AnyTLS": MagicMock(desired_count=2, min_alert_threshold=1),
        },
    }
    mock_config.fleet_scheduler.enabled = True
    mock_config.fleet_scheduler.poll_interval_seconds = 30.0
    mock_config.fleet_scheduler.cooldown_seconds = 60.0
    mock_config.fleet_scheduler.max_tasks_per_cycle = 5
    mock_config.fleet_scheduler.enabled_regions = ["*"]
    mock_config.fleet_scheduler.enabled_protocols = ["*"]
    mock_config.app.max_retries = 0

    mock_runtime = MagicMock()
    mock_runtime.config = mock_config
    mock_runtime.correlation_id = "test-correlation-id"
    mock_logger = MagicMock()
    mock_runtime.logger.getChild.return_value = mock_logger
    return mock_runtime


@pytest.fixture
def mock_repos():
    """创建模拟的 repository"""
    asset_repo = MagicMock()
    state_repo = MagicMock()
    node_registry = MagicMock()

    # Mock 资产数据
    mock_asset = MagicMock()
    mock_asset.id = 1
    mock_asset.region = "ap-northeast-1"
    mock_asset.aws_account_id = "123456789012"
    asset_repo.list_assets_by_aws_account_id.return_value = [mock_asset]

    # Mock 节点数据
    mock_node = MagicMock()
    mock_node.id = 1
    mock_node.xboard_node_id = 100
    mock_node.node_type = "AnyTLS"
    mock_node.status = "online"
    state_repo.list_nodes_by_aws_account_id.return_value = [mock_node]

    return asset_repo, state_repo, node_registry


class TestEmergencyReplenishment:
    """测试紧急补充逻辑"""

    def test_trigger_replenishment_when_enabled(self, mock_runtime, mock_repos):
        """当调度器启用时应触发紧急补充"""
        asset_repo, state_repo, node_registry = mock_repos

        with patch("services.account_abandonment_service.AssetRepo", return_value=asset_repo), \
             patch("services.account_abandonment_service.StateRepo", return_value=state_repo), \
             patch("services.account_abandonment_service.NodeRegistryService", return_value=node_registry), \
             patch("services.account_abandonment_service.FleetSchedulerService") as MockScheduler:

            # Mock 调度器
            mock_scheduler_instance = MagicMock()
            mock_scheduler_instance.fill_gap_for_region_protocol.return_value = [1, 2]
            MockScheduler.return_value = mock_scheduler_instance

            service = AccountAbandonmentService(mock_runtime)

            # 执行弃尸
            result = service.abandon_account(
                aws_account_id="123456789012",
                error_code="AuthFailure",
                error_message="Account banned",
                source_xboard_node_id=100,
            )

            # 验证调度器被调用
            mock_scheduler_instance.fill_gap_for_region_protocol.assert_called()
            assert result.deleted_node_count == 1
            assert result.asset_count == 1

    def test_skip_replenishment_when_disabled(self, mock_runtime, mock_repos):
        """当调度器禁用时应跳过紧急补充"""
        mock_runtime.config.fleet_scheduler.enabled = False
        asset_repo, state_repo, node_registry = mock_repos

        with patch("services.account_abandonment_service.AssetRepo", return_value=asset_repo), \
             patch("services.account_abandonment_service.StateRepo", return_value=state_repo), \
             patch("services.account_abandonment_service.NodeRegistryService", return_value=node_registry), \
             patch("services.account_abandonment_service.FleetSchedulerService") as MockScheduler:

            service = AccountAbandonmentService(mock_runtime)

            # 执行弃尸
            result = service.abandon_account(
                aws_account_id="123456789012",
                error_code="AuthFailure",
                error_message="Account banned",
                source_xboard_node_id=100,
            )

            # 验证调度器没有被调用
            MockScheduler.return_value.fill_gap_for_region_protocol.assert_not_called()
            assert result.deleted_node_count == 1

    def test_replenishment_with_multiple_nodes(self, mock_runtime, mock_repos):
        """有多个节点时应补充对应数量"""
        asset_repo, state_repo, node_registry = mock_repos

        # 添加更多节点
        mock_node2 = MagicMock()
        mock_node2.id = 2
        mock_node2.xboard_node_id = 101
        mock_node2.node_type = "Trojan"
        mock_node2.status = "online"
        state_repo.list_nodes_by_aws_account_id.return_value = [
            MagicMock(id=1, xboard_node_id=100, node_type="AnyTLS"),
            MagicMock(id=2, xboard_node_id=101, node_type="Trojan"),
        ]

        with patch("services.account_abandonment_service.AssetRepo", return_value=asset_repo), \
             patch("services.account_abandonment_service.StateRepo", return_value=state_repo), \
             patch("services.account_abandonment_service.NodeRegistryService", return_value=node_registry), \
             patch("services.account_abandonment_service.FleetSchedulerService") as MockScheduler:

            mock_scheduler_instance = MagicMock()
            mock_scheduler_instance.fill_gap_for_region_protocol.return_value = [1]
            MockScheduler.return_value = mock_scheduler_instance

            service = AccountAbandonmentService(mock_runtime)

            result = service.abandon_account(
                aws_account_id="123456789012",
                error_code="AuthFailure",
                error_message="Account banned",
                source_xboard_node_id=100,
            )

            # 应为 AnyTLS 和 Trojan 各调用一次
            assert mock_scheduler_instance.fill_gap_for_region_protocol.call_count == 2
            assert result.deleted_node_count == 2

    def test_replenishment_reason_includes_delete_count(self, mock_runtime, mock_repos):
        """补充原因应包含删除的节点数量"""
        asset_repo, state_repo, node_registry = mock_repos

        with patch("services.account_abandonment_service.AssetRepo", return_value=asset_repo), \
             patch("services.account_abandonment_service.StateRepo", return_value=state_repo), \
             patch("services.account_abandonment_service.NodeRegistryService", return_value=node_registry), \
             patch("services.account_abandonment_service.FleetSchedulerService") as MockScheduler:

            mock_scheduler_instance = MagicMock()
            mock_scheduler_instance.fill_gap_for_region_protocol.return_value = [1]
            MockScheduler.return_value = mock_scheduler_instance

            service = AccountAbandonmentService(mock_runtime)

            result = service.abandon_account(
                aws_account_id="123456789012",
                error_code="AuthFailure",
                error_message="Account banned",
                source_xboard_node_id=100,
            )

            # 验证 fill_gap 被调用时的 reason 参数
            call_args = mock_scheduler_instance.fill_gap_for_region_protocol.call_args
            reason = call_args.kwargs.get("reason", call_args[1].get("reason", ""))
            assert "abandonment_replenishment:1" in reason


class TestReplenishmentLogic:
    """测试补充逻辑"""

    def test_fill_gap_for_region_protocol_returns_task_ids(self):
        """fill_gap_for_region_protocol 应返回任务 ID 列表"""
        from unittest.mock import MagicMock, patch

        mock_runtime = MagicMock()
        mock_runtime.config.fleet_matrix = {
            "ap-northeast-1": {
                "AnyTLS": MagicMock(desired_count=5, min_alert_threshold=2),
            },
        }
        mock_runtime.config.fleet_scheduler.enabled = True
        mock_runtime.config.fleet_scheduler.cooldown_seconds = 60.0
        mock_runtime.logger.getChild.return_value = MagicMock()

        with patch("services.fleet_scheduler_service.StateRepo") as MockStateRepo, \
             patch("services.fleet_scheduler_service.ProvisioningTaskRepo") as MockTaskRepo, \
             patch("services.fleet_scheduler_service.AssetRepo") as MockAssetRepo, \
             patch("services.fleet_scheduler_service.AssetSelectorService") as MockAssetSelector:

            mock_state_repo = MagicMock()
            mock_state_repo.list_active_nodes.return_value = []
            MockStateRepo.return_value = mock_state_repo

            mock_task_repo = MagicMock()
            mock_task_repo.list_recent_tasks.return_value = []
            mock_task_repo.create_task.return_value = 999
            MockTaskRepo.return_value = mock_task_repo

            mock_asset_selector = MagicMock()
            mock_asset_selector.select_asset.return_value = MagicMock()
            MockAssetSelector.return_value = mock_asset_selector

            from services.fleet_scheduler_service import FleetSchedulerService

            service = FleetSchedulerService(mock_runtime)
            task_ids = service.fill_gap_for_region_protocol(
                region="ap-northeast-1",
                protocol_type="AnyTLS",
                count=1,
                reason="test",
            )

            # 应返回创建的任务 ID
            assert task_ids == [999]
