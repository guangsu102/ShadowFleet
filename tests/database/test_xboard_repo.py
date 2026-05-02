"""Integration tests for XboardRepo (PostgreSQL operations layer).

All tests mock the real DB pool and execute_with_backoff to isolate
the repository logic without needing a live PostgreSQL connection.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from database.xboard_repo import (
    MAX_NODE_NAME_LENGTH,
    XboardNodeCreateRequest,
    XboardNodeNotFoundError,
    XboardRepo,
    XboardRepoError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_runtime_context() -> MagicMock:
    """Create a minimal RuntimeContext mock for XboardRepo."""
    mock = MagicMock()
    mock.logger = MagicMock(spec=logging.Logger)
    mock.logger.getChild.return_value = mock.logger
    mock.correlation_id = "xboard-test-001"

    mock_config_app = MagicMock()
    mock_config_app.max_retries = 0
    mock_config_app.retry_backoff_seconds = 0.001
    mock.config = MagicMock()
    mock.config.app = mock_config_app

    mock_db_pool = MagicMock()
    mock.db_pool = mock_db_pool

    return mock


def _patch_backoff() -> MagicMock:
    """
    Replace execute_with_backoff so it directly calls the inner func
    without sleeping or retrying.
    """
    return patch(
        "database.xboard_repo.execute_with_backoff",
        side_effect=lambda **kw: kw["func"](),
    )


# ---------------------------------------------------------------------------
# Tests: Input Validation
# ---------------------------------------------------------------------------

class TestXboardRepoValidation:
    """Tests for _validate_create_request static method."""

    def test_valid_request_does_not_raise(self) -> None:
        request = XboardNodeCreateRequest(
            node_type="AnyTLS",
            name="test-node",
            host="sf-1.example.com",
            port="443",
            server_port=443,
            rate=Decimal("1.0"),
        )
        XboardRepo._validate_create_request(request)  # should not raise

    def test_empty_node_type_raises(self) -> None:
        request = XboardNodeCreateRequest(
            node_type="", name="n", host="h", port="80", server_port=80, rate=Decimal("1")
        )
        with pytest.raises(ValueError, match="node_type"):
            XboardRepo._validate_create_request(request)

    def test_whitespace_node_type_raises(self) -> None:
        request = XboardNodeCreateRequest(
            node_type="  ", name="n", host="h", port="80", server_port=80, rate=Decimal("1")
        )
        with pytest.raises(ValueError, match="node_type"):
            XboardRepo._validate_create_request(request)

    def test_empty_name_raises(self) -> None:
        request = XboardNodeCreateRequest(
            node_type="AnyTLS", name="", host="h", port="80", server_port=80, rate=Decimal("1")
        )
        with pytest.raises(ValueError, match="name"):
            XboardRepo._validate_create_request(request)

    def test_empty_host_raises(self) -> None:
        request = XboardNodeCreateRequest(
            node_type="AnyTLS", name="n", host="", port="80", server_port=80, rate=Decimal("1")
        )
        with pytest.raises(ValueError, match="host"):
            XboardRepo._validate_create_request(request)

    def test_empty_port_raises(self) -> None:
        request = XboardNodeCreateRequest(
            node_type="AnyTLS", name="n", host="h", port="", server_port=80, rate=Decimal("1")
        )
        with pytest.raises(ValueError, match="port"):
            XboardRepo._validate_create_request(request)

    def test_zero_server_port_raises(self) -> None:
        request = XboardNodeCreateRequest(
            node_type="AnyTLS", name="n", host="h", port="80", server_port=0, rate=Decimal("1")
        )
        with pytest.raises(ValueError, match="server_port"):
            XboardRepo._validate_create_request(request)

    def test_negative_server_port_raises(self) -> None:
        request = XboardNodeCreateRequest(
            node_type="AnyTLS", name="n", host="h", port="80", server_port=-1, rate=Decimal("1")
        )
        with pytest.raises(ValueError, match="server_port"):
            XboardRepo._validate_create_request(request)

    def test_zero_rate_raises(self) -> None:
        request = XboardNodeCreateRequest(
            node_type="AnyTLS", name="n", host="h", port="80", server_port=80, rate=Decimal("0")
        )
        with pytest.raises(ValueError, match="rate"):
            XboardRepo._validate_create_request(request)

    def test_negative_rate_raises(self) -> None:
        request = XboardNodeCreateRequest(
            node_type="AnyTLS", name="n", host="h", port="80", server_port=80, rate=Decimal("-1")
        )
        with pytest.raises(ValueError, match="rate"):
            XboardRepo._validate_create_request(request)


# ---------------------------------------------------------------------------
# Tests: register_node
# ---------------------------------------------------------------------------

class TestXboardRepoRegisterNode:
    """Tests for register_node()."""

    def test_register_node_returns_id_from_returning(
        self,
    ) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.fetchone.return_value = (42,)
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff():
            repo = XboardRepo(ctx)
            node_id = repo.register_node(
                XboardNodeCreateRequest(
                    node_type="AnyTLS",
                    name="register-test",
                    host="sf-1.example.com",
                    port="443",
                    server_port=443,
                    rate=Decimal("1.0"),
                )
            )

        assert node_id == 42
        mock_cursor.execute.assert_called_once()

    def test_register_node_raises_when_no_id_returned(
        self,
    ) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff(), pytest.raises(XboardRepoError, match="no id"):
            repo = XboardRepo(ctx)
            repo.register_node(
                XboardNodeCreateRequest(
                    node_type="AnyTLS",
                    name="no-id-test",
                    host="h",
                    port="80",
                    server_port=80,
                    rate=Decimal("1"),
                )
            )


# ---------------------------------------------------------------------------
# Tests: delete_node
# ---------------------------------------------------------------------------

class TestXboardRepoDeleteNode:
    """Tests for delete_node()."""

    def test_delete_node_succeeds_for_existing_node(
        self,
    ) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.rowcount = 1
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff():
            repo = XboardRepo(ctx)
            repo.delete_node(node_id=999)

        mock_cursor.execute.assert_called_once()
        _, params = mock_cursor.execute.call_args[0]
        assert params == 999

    def test_delete_node_raises_not_found(
        self,
    ) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.rowcount = 0
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff(), pytest.raises(XboardNodeNotFoundError):
            repo = XboardRepo(ctx)
            repo.delete_node(node_id=404)


# ---------------------------------------------------------------------------
# Tests: update_node_host
# ---------------------------------------------------------------------------

class TestXboardRepoUpdateNodeHost:
    """Tests for update_node_host()."""

    def test_update_node_host_succeeds(
        self,
    ) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.rowcount = 1
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff():
            repo = XboardRepo(ctx)
            repo.update_node_host(node_id=55, host="  new-host.example.com  ")

        mock_cursor.execute.assert_called_once()
        _, params = mock_cursor.execute.call_args[0]
        # host should be stripped
        assert params[0] == "new-host.example.com"

    def test_update_node_host_empty_host_raises(
        self,
    ) -> None:
        ctx = _make_runtime_context()
        with _patch_backoff():
            repo = XboardRepo(ctx)
            with pytest.raises(ValueError, match="host"):
                repo.update_node_host(node_id=1, host="   ")

    def test_update_node_host_not_found(
        self,
    ) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.rowcount = 0
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff(), pytest.raises(XboardNodeNotFoundError):
            repo = XboardRepo(ctx)
            repo.update_node_host(node_id=404, host="h.example.com")


# ---------------------------------------------------------------------------
# Tests: get_node_runtime
# ---------------------------------------------------------------------------

class TestXboardRepoGetNodeRuntime:
    """Tests for get_node_runtime()."""

    def test_get_node_runtime_returns_record(
        self,
    ) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.fetchone.return_value = (42, "AnyTLS", "sf-42.example.com", "443", 443, True)
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff():
            repo = XboardRepo(ctx)
            record = repo.get_node_runtime(node_id=42)

        assert record.node_id == 42
        assert record.node_type == "AnyTLS"
        assert record.host == "sf-42.example.com"
        assert record.port == "443"
        assert record.server_port == 443
        assert record.show is True

        _, params = mock_cursor.execute.call_args[0]
        assert params == 42

    def test_get_node_runtime_not_found(
        self,
    ) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff(), pytest.raises(XboardNodeNotFoundError):
            repo = XboardRepo(ctx)
            repo.get_node_runtime(node_id=9999)  # valid id but not found in DB

    def test_get_node_runtime_zero_id_raises(
        self,
    ) -> None:
        ctx = _make_runtime_context()
        with _patch_backoff():
            repo = XboardRepo(ctx)
            with pytest.raises(ValueError, match="greater than 0"):
                repo.get_node_runtime(node_id=0)


# ---------------------------------------------------------------------------
# Tests: list_server_minute_stats
# ---------------------------------------------------------------------------

class TestXboardRepoListServerMinuteStats:
    """Tests for list_server_minute_stats()."""

    def test_list_server_minute_stats_returns_records(
        self,
    ) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.fetchall.return_value = [
            (100, "AnyTLS", 1024, 2048, 3072, 5, 1700000000),
            (100, "AnyTLS", 0, 100, 100, 0, 1700000001),
            (100, "AnyTLS", 0, 0, 0, 0, 1700000002),
        ]
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff():
            repo = XboardRepo(ctx)
            records = repo.list_server_minute_stats(
                server_id=100, server_type="AnyTLS", since_minute=1700000000
            )

        assert len(records) == 3
        assert records[0].uplink_bytes == 1024
        assert records[0].downlink_bytes == 2048
        assert records[0].total_bytes == 3072
        assert records[0].active_user_count == 5
        assert records[1].uplink_bytes == 0
        assert records[2].total_bytes == 0

    def test_list_server_minute_stats_empty_when_no_rows(
        self,
    ) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff():
            repo = XboardRepo(ctx)
            records = repo.list_server_minute_stats(
                server_id=999, server_type="AnyTLS", since_minute=1700000000
            )

        assert records == []

    def test_list_server_minute_stats_zero_server_id_raises(
        self,
    ) -> None:
        ctx = _make_runtime_context()
        with _patch_backoff():
            repo = XboardRepo(ctx)
            with pytest.raises(ValueError, match="server_id"):
                repo.list_server_minute_stats(
                    server_id=0, server_type="AnyTLS", since_minute=1700000000
                )

    def test_list_server_minute_stats_empty_server_type_raises(
        self,
    ) -> None:
        ctx = _make_runtime_context()
        with _patch_backoff():
            repo = XboardRepo(ctx)
            with pytest.raises(ValueError, match="server_type"):
                repo.list_server_minute_stats(
                    server_id=1, server_type="", since_minute=1700000000
                )


# ---------------------------------------------------------------------------
# Tests: mark_node_online / mark_node_offline
# ---------------------------------------------------------------------------

class TestXboardRepoNodeVisibility:
    """Tests for mark_node_online() and mark_node_offline()."""

    def test_mark_node_online_calls_update_with_visible_true(
        self,
    ) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.rowcount = 1
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff():
            repo = XboardRepo(ctx)
            repo.mark_node_online(node_id=7)

        mock_cursor.execute.assert_called_once()
        _, params = mock_cursor.execute.call_args[0]
        assert params[0] is True  # visible=True

    def test_mark_node_offline_calls_update_with_visible_false(
        self,
    ) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.rowcount = 1
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff():
            repo = XboardRepo(ctx)
            repo.mark_node_offline(node_id=8)

        mock_cursor.execute.assert_called_once()
        _, params = mock_cursor.execute.call_args[0]
        assert params[0] is False  # visible=False

    def test_mark_node_online_not_found_raises(
        self,
    ) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.rowcount = 0
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff(), pytest.raises(XboardNodeNotFoundError):
            repo = XboardRepo(ctx)
            repo.mark_node_online(node_id=404)


# ---------------------------------------------------------------------------
# Tests: ShadowFleet sf- isolation
# ---------------------------------------------------------------------------

class TestXboardRepoEnforceSfName:
    """Tests for _enforce_sf_name()."""

    def test_enforce_sf_name_adds_prefix_when_missing(self) -> None:
        assert XboardRepo._enforce_sf_name("my-node") == "sf-my-node"

    def test_enforce_sf_name_preserves_existing_prefix(self) -> None:
        assert XboardRepo._enforce_sf_name("sf-my-node") == "sf-my-node"

    def test_enforce_sf_name_truncates_long_name(self) -> None:
        long_name = "a" * 80
        result = XboardRepo._enforce_sf_name(long_name)
        assert result == "sf-" + "a" * (MAX_NODE_NAME_LENGTH - 3)
        assert len(result) == MAX_NODE_NAME_LENGTH

    def test_enforce_sf_name_truncates_long_name_already_prefixed(self) -> None:
        long_name = "sf-" + "b" * 80
        result = XboardRepo._enforce_sf_name(long_name)
        assert len(result) == MAX_NODE_NAME_LENGTH


class TestXboardRepoRegisterNodeSfPrefix:
    """Tests that register_node enforces sf- prefix on name."""

    def test_register_node_injects_sf_prefix_into_sql(
        self,
    ) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff():
            repo = XboardRepo(ctx)
            repo.register_node(
                XboardNodeCreateRequest(
                    node_type="AnyTLS",
                    name="xboard-panel-node",
                    host="h.example.com",
                    port="443",
                    server_port=443,
                    rate=Decimal("1.0"),
                )
            )

        mock_cursor.execute.assert_called_once()
        _, params = mock_cursor.execute.call_args[0]
        assert params[5] == "sf-xboard-panel-node"  # name is 6th positional param

    def test_register_node_does_not_double_prefix(
        self,
    ) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.fetchone.return_value = (2,)
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff():
            repo = XboardRepo(ctx)
            repo.register_node(
                XboardNodeCreateRequest(
                    node_type="Trojan",
                    name="sf-existing-node",
                    host="h2.example.com",
                    port="443",
                    server_port=443,
                    rate=Decimal("1.0"),
                )
            )

        _, params = mock_cursor.execute.call_args[0]
        assert params[5] == "sf-existing-node"


class TestXboardRepoSfGuard:
    """Tests that UPDATE/DELETE operations include sf-% name guard."""

    def test_delete_node_sql_contains_sf_guard(self) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.rowcount = 1
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff():
            repo = XboardRepo(ctx)
            repo.delete_node(node_id=5)

        call_args = mock_cursor.execute.call_args[0]
        sql = call_args[0]
        assert "name LIKE 'sf-%'" in sql

    def test_update_node_host_sql_contains_sf_guard(self) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.rowcount = 1
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff():
            repo = XboardRepo(ctx)
            repo.update_node_host(node_id=6, host="new.example.com")

        call_args = mock_cursor.execute.call_args[0]
        sql = call_args[0]
        assert "name LIKE 'sf-%'" in sql

    def test_get_node_runtime_sql_contains_sf_guard(self) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.fetchone.return_value = (7, "AnyTLS", "h.example.com", "443", 443, True)
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff():
            repo = XboardRepo(ctx)
            repo.get_node_runtime(node_id=7)

        call_args = mock_cursor.execute.call_args[0]
        sql = call_args[0]
        assert "name LIKE 'sf-%'" in sql

    def test_mark_node_online_sql_contains_sf_guard(self) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.rowcount = 1
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff():
            repo = XboardRepo(ctx)
            repo.mark_node_online(node_id=9)

        call_args = mock_cursor.execute.call_args[0]
        sql = call_args[0]
        assert "name LIKE 'sf-%'" in sql

    def test_mark_node_offline_sql_contains_sf_guard(self) -> None:
        ctx = _make_runtime_context()

        mock_cursor = MagicMock()
        mock_cursor.execute = MagicMock()
        mock_cursor.rowcount = 1
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        ctx.db_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        ctx.db_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with _patch_backoff():
            repo = XboardRepo(ctx)
            repo.mark_node_offline(node_id=10)

        call_args = mock_cursor.execute.call_args[0]
        sql = call_args[0]
        assert "name LIKE 'sf-%'" in sql
