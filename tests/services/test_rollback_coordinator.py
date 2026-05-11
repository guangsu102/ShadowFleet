"""
Tests for RollbackCoordinator
"""
from unittest.mock import MagicMock

import pytest

from services.rollback_coordinator import (
    RollbackAction,
    RollbackCoordinator,
    RollbackPriority,
    RollbackReport,
    RollbackResult,
    create_rollback_coordinator,
)


@pytest.fixture
def mock_logger():
    """Create a mock logger"""
    return MagicMock()


@pytest.fixture
def coordinator(mock_logger):
    """Create RollbackCoordinator instance"""
    return RollbackCoordinator(mock_logger)


class TestRollbackPriority:
    """Tests for RollbackPriority enum"""

    def test_priority_values(self):
        """Test priority values are ordered correctly"""
        assert RollbackPriority.CRITICAL.value == 1
        assert RollbackPriority.HIGH.value == 2
        assert RollbackPriority.MEDIUM.value == 3
        assert RollbackPriority.LOW.value == 4

    def test_priority_ordering(self):
        """Test priorities can be compared"""
        assert RollbackPriority.CRITICAL.value < RollbackPriority.HIGH.value
        assert RollbackPriority.HIGH.value < RollbackPriority.MEDIUM.value
        assert RollbackPriority.MEDIUM.value < RollbackPriority.LOW.value


class TestRollbackAction:
    """Tests for RollbackAction dataclass"""

    def test_rollback_action_creation(self):
        """Test creating a rollback action"""
        action_fn = lambda: None
        action = RollbackAction(
            name="test_action",
            action=action_fn,
            priority=RollbackPriority.HIGH,
            resource_type="instance",
            resource_id="i-123",
            allow_failure=False
        )

        assert action.name == "test_action"
        assert action.action == action_fn
        assert action.priority == RollbackPriority.HIGH
        assert action.resource_type == "instance"
        assert action.resource_id == "i-123"
        assert action.allow_failure is False

    def test_rollback_action_defaults(self):
        """Test rollback action default values"""
        action_fn = lambda: None
        action = RollbackAction(
            name="test",
            action=action_fn,
            priority=RollbackPriority.LOW,
            resource_type="test"
        )

        assert action.resource_id is None
        assert action.allow_failure is False


class TestRollbackResult:
    """Tests for RollbackResult dataclass"""

    def test_rollback_result_success(self):
        """Test creating a successful rollback result"""
        result = RollbackResult(
            action_name="delete_instance",
            resource_type="instance",
            resource_id="i-123",
            success=True
        )

        assert result.action_name == "delete_instance"
        assert result.resource_type == "instance"
        assert result.resource_id == "i-123"
        assert result.success is True
        assert result.error_message is None

    def test_rollback_result_failure(self):
        """Test creating a failed rollback result"""
        result = RollbackResult(
            action_name="delete_instance",
            resource_type="instance",
            resource_id="i-123",
            success=False,
            error_message="Instance not found"
        )

        assert result.success is False
        assert result.error_message == "Instance not found"


class TestRollbackReport:
    """Tests for RollbackReport dataclass"""

    def test_rollback_report_creation(self):
        """Test creating a rollback report"""
        results = [
            RollbackResult("action1", "type1", "id1", True),
            RollbackResult("action2", "type2", "id2", False, "error")
        ]
        critical = [results[1]]

        report = RollbackReport(
            total_actions=2,
            succeeded=1,
            failed=1,
            skipped=0,
            results=results,
            critical_failures=critical
        )

        assert report.total_actions == 2
        assert report.succeeded == 1
        assert report.failed == 1
        assert report.skipped == 0
        assert len(report.results) == 2
        assert len(report.critical_failures) == 1


class TestRollbackCoordinator:
    """Tests for RollbackCoordinator"""

    def test_init(self, mock_logger):
        """Test coordinator initialization"""
        coordinator = RollbackCoordinator(mock_logger)
        assert coordinator._logger == mock_logger
        assert coordinator._actions == []

    def test_register_action(self, coordinator):
        """Test registering a rollback action"""
        action_fn = MagicMock()

        coordinator.register_action(
            name="test_action",
            action=action_fn,
            priority=RollbackPriority.HIGH,
            resource_type="instance",
            resource_id="i-123"
        )

        assert len(coordinator._actions) == 1
        assert coordinator._actions[0].name == "test_action"
        assert coordinator._actions[0].priority == RollbackPriority.HIGH

    def test_register_multiple_actions(self, coordinator):
        """Test registering multiple actions"""
        action1 = MagicMock()
        action2 = MagicMock()

        coordinator.register_action("action1", action1, RollbackPriority.HIGH, "type1")
        coordinator.register_action("action2", action2, RollbackPriority.LOW, "type2")

        assert len(coordinator._actions) == 2

    def test_execute_rollback_no_actions(self, coordinator):
        """Test executing rollback with no actions"""
        report = coordinator.execute_rollback()

        assert report.total_actions == 0
        assert report.succeeded == 0
        assert report.failed == 0
        assert report.skipped == 0
        assert len(report.results) == 0
        assert len(report.critical_failures) == 0

    def test_execute_rollback_single_success(self, coordinator):
        """Test executing single successful rollback"""
        action_fn = MagicMock()
        coordinator.register_action("test", action_fn, RollbackPriority.HIGH, "instance")

        report = coordinator.execute_rollback()

        assert report.total_actions == 1
        assert report.succeeded == 1
        assert report.failed == 0
        assert report.skipped == 0
        action_fn.assert_called_once()

    def test_execute_rollback_single_failure(self, coordinator):
        """Test executing single failed rollback"""
        action_fn = MagicMock(side_effect=RuntimeError("Test error"))
        coordinator.register_action("test", action_fn, RollbackPriority.HIGH, "instance")

        report = coordinator.execute_rollback()

        assert report.total_actions == 1
        assert report.succeeded == 0
        assert report.failed == 1
        assert len(report.critical_failures) == 1
        assert report.results[0].error_message == "Test error"

    def test_execute_rollback_priority_order(self, coordinator):
        """Test rollback actions execute in priority order"""
        execution_order = []

        def make_action(name):
            def action():
                execution_order.append(name)
            return action

        coordinator.register_action("low", make_action("low"), RollbackPriority.LOW, "type")
        coordinator.register_action("critical", make_action("critical"), RollbackPriority.CRITICAL, "type")
        coordinator.register_action("high", make_action("high"), RollbackPriority.HIGH, "type")
        coordinator.register_action("medium", make_action("medium"), RollbackPriority.MEDIUM, "type")

        coordinator.execute_rollback()

        assert execution_order == ["critical", "high", "medium", "low"]

    def test_execute_rollback_mixed_results(self, coordinator):
        """Test rollback with mixed success and failure"""
        success_action = MagicMock()
        failure_action = MagicMock(side_effect=RuntimeError("Failed"))

        coordinator.register_action("success", success_action, RollbackPriority.HIGH, "type1")
        coordinator.register_action("failure", failure_action, RollbackPriority.HIGH, "type2")

        report = coordinator.execute_rollback()

        assert report.total_actions == 2
        assert report.succeeded == 1
        assert report.failed == 1
        assert len(report.critical_failures) == 1

    def test_execute_rollback_allow_failure(self, coordinator):
        """Test rollback with allowed failures"""
        failure_action = MagicMock(side_effect=RuntimeError("Failed"))

        coordinator.register_action(
            "failure",
            failure_action,
            RollbackPriority.HIGH,
            "type",
            allow_failure=True
        )

        report = coordinator.execute_rollback()

        assert report.total_actions == 1
        assert report.succeeded == 0
        assert report.failed == 1
        assert len(report.critical_failures) == 0  # Not critical because allow_failure=True

    def test_execute_rollback_continue_on_failure(self, coordinator):
        """Test rollback continues after failure when continue_on_failure=True"""
        action1 = MagicMock(side_effect=RuntimeError("Failed"))
        action2 = MagicMock()

        coordinator.register_action("action1", action1, RollbackPriority.HIGH, "type1")
        coordinator.register_action("action2", action2, RollbackPriority.LOW, "type2")

        report = coordinator.execute_rollback(continue_on_failure=True)

        assert report.total_actions == 2
        assert report.succeeded == 1
        assert report.failed == 1
        action1.assert_called_once()
        action2.assert_called_once()

    def test_execute_rollback_stop_on_critical_failure(self, coordinator):
        """Test rollback stops on critical failure when continue_on_failure=False"""
        action1 = MagicMock(side_effect=RuntimeError("Critical failure"))
        action2 = MagicMock()

        coordinator.register_action("action1", action1, RollbackPriority.HIGH, "type1", allow_failure=False)
        coordinator.register_action("action2", action2, RollbackPriority.LOW, "type2")

        report = coordinator.execute_rollback(continue_on_failure=False)

        assert report.total_actions == 2
        assert report.succeeded == 0
        assert report.failed == 1
        assert report.skipped == 1
        action1.assert_called_once()
        action2.assert_not_called()

    def test_execute_rollback_continue_on_allowed_failure(self, coordinator):
        """Test rollback continues on allowed failure even when continue_on_failure=False"""
        action1 = MagicMock(side_effect=RuntimeError("Allowed failure"))
        action2 = MagicMock()

        coordinator.register_action("action1", action1, RollbackPriority.HIGH, "type1", allow_failure=True)
        coordinator.register_action("action2", action2, RollbackPriority.LOW, "type2")

        report = coordinator.execute_rollback(continue_on_failure=False)

        assert report.total_actions == 2
        assert report.succeeded == 1
        assert report.failed == 1
        assert report.skipped == 0
        action1.assert_called_once()
        action2.assert_called_once()

    def test_clear(self, coordinator):
        """Test clearing all actions"""
        action_fn = MagicMock()
        coordinator.register_action("test", action_fn, RollbackPriority.HIGH, "type")

        assert len(coordinator._actions) == 1

        coordinator.clear()

        assert len(coordinator._actions) == 0

    def test_execute_rollback_with_resource_ids(self, coordinator):
        """Test rollback actions with resource IDs"""
        action_fn = MagicMock()
        coordinator.register_action(
            "delete_instance",
            action_fn,
            RollbackPriority.HIGH,
            "instance",
            resource_id="i-123456"
        )

        report = coordinator.execute_rollback()

        assert report.results[0].resource_id == "i-123456"

    def test_execute_rollback_multiple_priorities(self, coordinator):
        """Test rollback with multiple actions at different priorities"""
        execution_order = []

        def make_action(name):
            def action():
                execution_order.append(name)
            return action

        # Register in random order
        coordinator.register_action("medium1", make_action("medium1"), RollbackPriority.MEDIUM, "type")
        coordinator.register_action("critical1", make_action("critical1"), RollbackPriority.CRITICAL, "type")
        coordinator.register_action("low1", make_action("low1"), RollbackPriority.LOW, "type")
        coordinator.register_action("high1", make_action("high1"), RollbackPriority.HIGH, "type")
        coordinator.register_action("critical2", make_action("critical2"), RollbackPriority.CRITICAL, "type")
        coordinator.register_action("high2", make_action("high2"), RollbackPriority.HIGH, "type")

        report = coordinator.execute_rollback()

        # Critical actions first, then high, then medium, then low
        assert execution_order[:2] == ["critical1", "critical2"] or execution_order[:2] == ["critical2", "critical1"]
        assert execution_order[2:4] == ["high1", "high2"] or execution_order[2:4] == ["high2", "high1"]
        assert execution_order[4] == "medium1"
        assert execution_order[5] == "low1"
        assert report.succeeded == 6

    def test_execute_rollback_exception_details(self, coordinator):
        """Test rollback captures exception details"""
        action_fn = MagicMock(side_effect=ValueError("Invalid value"))
        coordinator.register_action("test", action_fn, RollbackPriority.HIGH, "type")

        report = coordinator.execute_rollback()

        assert report.results[0].error_message == "Invalid value"

    def test_multiple_execute_rollback_calls(self, coordinator):
        """Test executing rollback multiple times"""
        action_fn = MagicMock()
        coordinator.register_action("test", action_fn, RollbackPriority.HIGH, "type")

        report1 = coordinator.execute_rollback()
        report2 = coordinator.execute_rollback()

        # Actions should be executed twice
        assert action_fn.call_count == 2
        assert report1.succeeded == 1
        assert report2.succeeded == 1


class TestCreateRollbackCoordinator:
    """Tests for create_rollback_coordinator factory function"""

    def test_create_rollback_coordinator(self, mock_logger):
        """Test creating coordinator via factory function"""
        coordinator = create_rollback_coordinator(mock_logger)

        assert isinstance(coordinator, RollbackCoordinator)
        assert coordinator._logger == mock_logger
