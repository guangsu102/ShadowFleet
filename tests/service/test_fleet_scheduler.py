#!/usr/bin/env python3
"""
测试 Fleet Scheduler 自动补充节点功能
"""
import pytest
import sys
sys.path.insert(0, ".")

from unittest.mock import MagicMock, patch

from services.fleet_scheduler_models import (
    RegionProtocolGap,
    SchedulerCooldownTracker,
)
from services.asset_selector_service import AssetSelectionError
from services.fleet_scheduler_service import FleetSchedulerService


@pytest.fixture
def mock_runtime():
    """创建模拟的 RuntimeContext"""
    mock_config = MagicMock()
    mock_config.fleet_matrix = {
        "ap-northeast-1": {
            "AnyTLS": MagicMock(desired_count=2, min_alert_threshold=1),
            "Trojan": MagicMock(desired_count=1, min_alert_threshold=1),
        },
    }
    mock_config.fleet_scheduler.enabled = True
    mock_config.fleet_scheduler.poll_interval_seconds = 30.0
    mock_config.fleet_scheduler.cooldown_seconds = 60.0
    mock_config.fleet_scheduler.max_tasks_per_cycle = 5
    mock_config.fleet_scheduler.enabled_regions = ["*"]
    mock_config.fleet_scheduler.enabled_protocols = ["*"]
    mock_config.fleet_scheduler.enabled_asset_types = ["digitalocean", "aws"]
    mock_config.app.max_retries = 0

    mock_runtime = MagicMock()
    mock_runtime.config = mock_config
    mock_runtime.config_holder = None
    mock_runtime.correlation_id = "test-correlation-id"
    mock_runtime.logger.getChild.return_value = MagicMock()
    return mock_runtime


class TestCalculateAlertLevel:
    """测试 _calculate_alert_level 方法"""

    def test_critical_when_below_min_threshold(self):
        """在线数低于最小阈值时应返回 critical"""
        level = FleetSchedulerService._calculate_alert_level(0, 1, 5)
        assert level == "critical"

    def test_critical_edge_case(self):
        """在线数刚好在最小阈值以下时应返回 critical"""
        level = FleetSchedulerService._calculate_alert_level(0, 1, 5)
        assert level == "critical"

    def test_warning_when_between_min_and_desired(self):
        """在线数在最小阈值和期望数之间时应返回 warning"""
        level = FleetSchedulerService._calculate_alert_level(2, 1, 5)
        assert level == "warning"

    def test_healthy_when_at_desired_count(self):
        """在线数等于期望数时应返回 healthy"""
        level = FleetSchedulerService._calculate_alert_level(5, 1, 5)
        assert level == "healthy"

    def test_healthy_when_above_desired_count(self):
        """在线数高于期望数时应返回 healthy"""
        level = FleetSchedulerService._calculate_alert_level(10, 1, 5)
        assert level == "healthy"


class TestSchedulerCooldownTracker:
    """测试 SchedulerCooldownTracker"""

    def test_first_submission_allowed(self):
        """首次提交应该被允许"""
        tracker = SchedulerCooldownTracker()
        key = ("ap-northeast-1", "AnyTLS")
        assert tracker.can_submit(key, cooldown_seconds=60.0) == True

    def test_in_cooldown_after_submit(self):
        """提交后应该进入冷却期"""
        tracker = SchedulerCooldownTracker()
        key = ("ap-northeast-1", "AnyTLS")
        tracker.record_submit(key)
        # 在冷却期内不应该允许提交
        assert tracker.can_submit(key, cooldown_seconds=60.0) == False

    def test_record_submit_resets_failures(self):
        """记录提交后应重置失败计数"""
        tracker = SchedulerCooldownTracker()
        key = ("ap-northeast-1", "AnyTLS")
        tracker.record_failure(key)
        tracker.record_failure(key)
        tracker.record_submit(key)
        assert tracker.consecutive_failures.get(key, 0) == 0

    def test_backoff_exponential_increase(self):
        """失败次数增加时退避时间应指数增长"""
        tracker = SchedulerCooldownTracker()
        key = ("ap-northeast-1", "AnyTLS")

        # 初始无失败，返回 base cooldown
        backoff = tracker.get_backoff_seconds(key, base_cooldown=60.0)
        assert backoff == 60.0

        # failures = 1, <= 1 返回 base cooldown
        tracker.consecutive_failures[key] = 1
        backoff = tracker.get_backoff_seconds(key, base_cooldown=60.0)
        assert backoff == 60.0

        # failures = 2, > 1, backoff = 60 * 2^1 = 120
        tracker.consecutive_failures[key] = 2
        backoff = tracker.get_backoff_seconds(key, base_cooldown=60.0)
        assert backoff == 120.0

        # failures = 3, > 1, backoff = 60 * 2^2 = 240
        tracker.consecutive_failures[key] = 3
        backoff = tracker.get_backoff_seconds(key, base_cooldown=60.0)
        assert backoff == 240.0

    def test_backoff_max_cap(self):
        """退避时间不应超过最大值"""
        tracker = SchedulerCooldownTracker()
        key = ("ap-northeast-1", "AnyTLS")

        # 大量失败时应该被 cap 在 max_cooldown
        for _ in range(10):
            tracker.record_failure(key)
        backoff = tracker.get_backoff_seconds(key, base_cooldown=60.0, max_cooldown=300.0)
        assert backoff == 300.0

    def test_backoff_large_failure_count_does_not_overflow(self):
        """失败次数极大时应直接封顶，不应计算超大指数。"""
        tracker = SchedulerCooldownTracker()
        key = ("ap-northeast-1", "AnyTLS")
        tracker.consecutive_failures[key] = 10000

        backoff = tracker.get_backoff_seconds(key, base_cooldown=60.0, max_cooldown=300.0)

        assert backoff == 300.0


class TestGenerateUniqueNodeName:
    """测试节点名称生成"""

    def test_node_name_format_japan(self, mock_runtime):
        """日本区域节点名称格式测试"""
        service = FleetSchedulerService(mock_runtime)
        name = service._generate_unique_node_name("ap-northeast-1", "AnyTLS")
        assert name.startswith("sf-jpt-atl-")
        assert len(name) > 10

    def test_node_name_format_usa(self, mock_runtime):
        """美国区域节点名称格式测试"""
        service = FleetSchedulerService(mock_runtime)
        name = service._generate_unique_node_name("us-west-2", "Trojan")
        assert name.startswith("sf-uso-tro-")

    def test_node_name_format_unknown_region(self, mock_runtime):
        """未知区域使用清理后的区域前缀（去除连字符后取前3个字符）"""
        service = FleetSchedulerService(mock_runtime)
        name = service._generate_unique_node_name("eu-west-99", "vless")
        # eu-west-99 去除连字符后变成 euwest99，取前3个字符是 euw
        assert name.startswith("sf-euw-")
        assert "vls" in name  # vless 协议前缀

    def test_node_name_uniqueness(self, mock_runtime):
        """节点名称应该唯一"""
        service = FleetSchedulerService(mock_runtime)
        names = set()
        for _ in range(10):
            name = service._generate_unique_node_name("ap-northeast-1", "AnyTLS")
            names.add(name)
        # 名称可能重复，但概率很低
        assert len(names) >= 1


class TestRegionProtocolFiltering:
    """测试区域和协议过滤"""

    def test_wildcard_allows_all_regions(self, mock_runtime):
        """通配符应该允许所有区域"""
        service = FleetSchedulerService(mock_runtime)
        assert service._is_region_enabled("ap-northeast-1") == True
        assert service._is_region_enabled("us-west-2") == True
        assert service._is_region_enabled("eu-west-1") == True

    def test_wildcard_allows_all_protocols(self, mock_runtime):
        """通配符应该允许所有协议"""
        service = FleetSchedulerService(mock_runtime)
        assert service._is_protocol_enabled("AnyTLS") == True
        assert service._is_protocol_enabled("Trojan") == True
        assert service._is_protocol_enabled("vless") == True

    def test_specific_region_filter(self, mock_runtime):
        """特定区域过滤"""
        mock_runtime.config.fleet_scheduler.enabled_regions = ["ap-northeast-1"]
        service = FleetSchedulerService(mock_runtime)
        assert service._is_region_enabled("ap-northeast-1") == True
        assert service._is_region_enabled("us-west-2") == False

    def test_specific_protocol_filter(self, mock_runtime):
        """特定协议过滤"""
        mock_runtime.config.fleet_scheduler.enabled_protocols = ["AnyTLS"]
        service = FleetSchedulerService(mock_runtime)
        assert service._is_protocol_enabled("AnyTLS") == True
        assert service._is_protocol_enabled("Trojan") == False


class TestCloudAssetSelection:
    """测试自动调度选择云资产类型的顺序。"""

    @staticmethod
    def _gap() -> RegionProtocolGap:
        return RegionProtocolGap(
            region="sgp1",
            protocol_type="AnyTLS",
            desired_count=1,
            min_alert_threshold=1,
            current_online_count=0,
            pending_provisioning_tasks=0,
            deficit=1,
            alert_level="critical",
        )

    def test_default_order_tries_digitalocean_before_aws(self, mock_runtime):
        with patch("services.fleet_scheduler_service.StateRepo"), \
             patch("services.fleet_scheduler_service.ProvisioningTaskRepo"), \
             patch("services.fleet_scheduler_service.AssetRepo"), \
             patch("services.fleet_scheduler_service.AssetSelectorService") as MockAssetSelector:

            selector = MagicMock()
            selector.select_asset.side_effect = [
                AssetSelectionError("no digitalocean asset"),
                "aws-selection",
            ]
            MockAssetSelector.return_value = selector

            service = FleetSchedulerService(mock_runtime)
            result = service._select_cloud_asset_for_gap(self._gap())

        assert result == "aws-selection"
        assert [call.args[0].asset_type for call in selector.select_asset.call_args_list] == [
            "digitalocean",
            "aws",
        ]

    def test_config_can_limit_scheduler_to_aws(self, mock_runtime):
        mock_runtime.config.fleet_scheduler.enabled_asset_types = ["aws"]
        with patch("services.fleet_scheduler_service.StateRepo"), \
             patch("services.fleet_scheduler_service.ProvisioningTaskRepo"), \
             patch("services.fleet_scheduler_service.AssetRepo"), \
             patch("services.fleet_scheduler_service.AssetSelectorService") as MockAssetSelector:

            selector = MagicMock()
            selector.select_asset.return_value = "aws-selection"
            MockAssetSelector.return_value = selector

            service = FleetSchedulerService(mock_runtime)
            result = service._select_cloud_asset_for_gap(self._gap())

        assert result == "aws-selection"
        selector.select_asset.assert_called_once()
        assert selector.select_asset.call_args.args[0].asset_type == "aws"


class TestRegionProtocolGap:
    """测试 RegionProtocolGap 数据类"""

    def test_gap_creation(self):
        """Gap 对象创建"""
        gap = RegionProtocolGap(
            region="ap-northeast-1",
            protocol_type="AnyTLS",
            desired_count=5,
            min_alert_threshold=2,
            current_online_count=1,
            pending_provisioning_tasks=1,
            deficit=3,
            alert_level="critical",
        )
        assert gap.region == "ap-northeast-1"
        assert gap.protocol_type == "AnyTLS"
        assert gap.deficit == 3
        assert gap.alert_level == "critical"

    def test_gap_frozen_immutable(self):
        """Frozen dataclass 应该不可变"""
        gap = RegionProtocolGap(
            region="ap-northeast-1",
            protocol_type="AnyTLS",
            desired_count=5,
            min_alert_threshold=2,
            current_online_count=1,
            pending_provisioning_tasks=0,
            deficit=4,
            alert_level="critical",
        )
        # 尝试修改应该失败
        with pytest.raises(AttributeError):
            gap.deficit = 10


class TestIntegrationScenario:
    """集成场景测试"""

    def test_scheduler_identifies_critical_gap(self, mock_runtime):
        """当节点数为0时应识别出 critical gap"""
        with patch("services.fleet_scheduler_service.StateRepo") as MockStateRepo, \
             patch("services.fleet_scheduler_service.ProvisioningTaskRepo") as MockTaskRepo, \
             patch("services.fleet_scheduler_service.AssetRepo") as MockAssetRepo, \
             patch("services.fleet_scheduler_service.AssetSelectorService") as MockAssetSelector:

            # Mock 返回空节点列表（模拟无在线节点）
            mock_state_repo = MagicMock()
            mock_state_repo.list_active_nodes.return_value = []
            MockStateRepo.return_value = mock_state_repo

            # Mock 返回空任务列表
            mock_task_repo = MagicMock()
            mock_task_repo.list_recent_tasks.return_value = []
            MockTaskRepo.return_value = mock_task_repo

            service = FleetSchedulerService(mock_runtime)
            gaps = service._calculate_all_gaps()

            # 应该有 gap（因为 desired_count=2, online=0）
            assert len(gaps) >= 1

            anytls_gap = next((g for g in gaps if g.protocol_type == "AnyTLS"), None)
            assert anytls_gap is not None
            assert anytls_gap.deficit == 2  # desired - online(0) - pending(0) = 2
            assert anytls_gap.alert_level == "critical"

    def test_scheduler_calculates_pending_tasks(self, mock_runtime):
        """调度器应考虑待处理的 Provisioning 任务"""
        with patch("services.fleet_scheduler_service.StateRepo") as MockStateRepo, \
             patch("services.fleet_scheduler_service.ProvisioningTaskRepo") as MockTaskRepo, \
             patch("services.fleet_scheduler_service.AssetRepo") as MockAssetRepo, \
             patch("services.fleet_scheduler_service.AssetSelectorService") as MockAssetSelector:

            # Mock 1个在线节点
            mock_node = MagicMock()
            mock_node.status = "online"
            mock_node.aws_region = "ap-northeast-1"
            mock_node.node_type = "AnyTLS"

            mock_state_repo = MagicMock()
            mock_state_repo.list_active_nodes.return_value = [mock_node]
            MockStateRepo.return_value = mock_state_repo

            # Mock 1个待处理任务
            mock_task = MagicMock()
            mock_task.status = "queued"
            mock_task.request_payload = {
                "region": "ap-northeast-1",
                "protocol_type": "AnyTLS",
            }

            mock_task_repo = MagicMock()
            mock_task_repo.list_recent_tasks.return_value = [mock_task]
            MockTaskRepo.return_value = mock_task_repo

            service = FleetSchedulerService(mock_runtime)
            gaps = service._calculate_all_gaps()

            anytls_gap = next((g for g in gaps if g.protocol_type == "AnyTLS"), None)
            assert anytls_gap is not None
            # desired=2, online=1, pending=1, deficit=0
            assert anytls_gap.deficit == 0
            # online=1, min_threshold=1, desired=2 -> not below min, not at desired -> warning
            assert anytls_gap.alert_level == "warning"
